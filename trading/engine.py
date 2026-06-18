"""자동매매 엔진 — 실시간 데이터 → 분석 → 전략 → 주문 실행

파이프라인과 함께 EC2 백그라운드 서비스로 실행.
모든 설정은 DB에서 로드. 종목은 watchlist 기반.

실행: python3 -m trading.engine
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import os
from datetime import datetime, timezone, time as dtime
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from trading.portfolio import PortfolioManager
from trading.strategy import get_strategy, TradeSignal
from trading.safety import TradingSafety

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trading_engine")


MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)


class TradingEngine:
    def __init__(self):
        self._running = False
        self._portfolio: PortfolioManager | None = None
        self._strategy = None
        self._safety: TradingSafety | None = None
        self._config: dict = {}
        self._db = None
        self._tickers: list[str] = []
        self._last_analysis: dict[str, dict] = {}
        self._last_eval_time: dict[str, datetime] = {}

    def _load_config(self):
        try:
            from data.database import get_client, get_setting, get_watchlist

            self._db = get_client()
            self._config = get_setting("trading_config") or {}
            watchlist = get_watchlist()
            self._tickers = [w["ticker"] for w in watchlist]

            self._portfolio = PortfolioManager(self._db, self._config)
            self._portfolio.load_state()

            strategy_name = self._config.get("strategy", "signal_score")
            self._strategy = get_strategy(strategy_name, self._config)

            self._safety = TradingSafety(self._config)

            logger.info(f"설정 로드 완료: 전략={strategy_name}, "
                        f"종목={len(self._tickers)}개, "
                        f"잔고=${self._portfolio.cash:,.2f}")
        except Exception as e:
            logger.error(f"설정 로드 실패: {e}")
            raise

    def _is_market_hours(self) -> bool:
        from datetime import timezone as tz
        try:
            import zoneinfo
            et = zoneinfo.ZoneInfo("America/New_York")
        except ImportError:
            et = timezone(offset=-datetime.timedelta(hours=4))

        now_et = datetime.now(tz=et)
        current_time = now_et.time()

        if now_et.weekday() >= 5:
            return False
        return MARKET_OPEN <= current_time <= MARKET_CLOSE

    def _get_latest_prices(self) -> dict[str, float]:
        prices = {}
        try:
            for ticker in self._tickers:
                result = self._db.table("realtime_ticks").select(
                    "price").eq("ticker", ticker).order(
                    "timestamp", desc=True).limit(1).execute()
                if result.data:
                    prices[ticker] = float(result.data[0]["price"])
        except Exception as e:
            logger.error(f"가격 조회 실패: {e}")
        return prices

    def _get_historical_df(self, ticker: str, days: int = 60) -> pd.DataFrame:
        try:
            import yfinance as yf
            df = yf.Ticker(ticker).history(period=f"{days}d")
            if not df.empty:
                return df
        except Exception as e:
            logger.debug(f"Yahoo 데이터 실패 ({ticker}): {e}")
        return pd.DataFrame()

    def _run_analysis(self, ticker: str, df: pd.DataFrame) -> dict:
        try:
            from analysis.engine import run_analysis_from_db

            def _get_setting(key):
                return self._db.table("settings").select(
                    "value").eq("key", key).maybe_single().execute().data
            result = run_analysis_from_db(ticker, df, _get_setting)
            return result
        except Exception as e:
            logger.error(f"분석 실패 ({ticker}): {e}")
            return {}

    def _calculate_quantity(self, ticker: str, price: float,
                            signal: TradeSignal) -> int:
        if signal.action != "buy":
            pos = self._portfolio.positions.get(ticker)
            if pos:
                return int(pos.quantity * signal.quantity_pct)
            return 0

        target_value = self._portfolio.total_value * signal.quantity_pct
        qty = int(target_value / price) if price > 0 else 0
        return max(qty, 0)

    async def _evaluate_ticker(self, ticker: str, current_price: float):
        rebalance_min = self._config.get("rebalance_interval_min", 5)
        now = datetime.now(timezone.utc)

        last = self._last_eval_time.get(ticker)
        if last and (now - last).total_seconds() < rebalance_min * 60:
            return

        df = self._get_historical_df(ticker)
        if df.empty:
            return

        analysis = self._run_analysis(ticker, df)
        if not analysis:
            return

        self._last_analysis[ticker] = analysis
        self._last_eval_time[ticker] = now

        pos = self._portfolio.positions.get(ticker)
        pos_dict = None
        if pos:
            pos.current_price = current_price
            pos_dict = {
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": current_price,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
            }

        signal = self._strategy.evaluate(ticker, analysis, pos_dict)

        if signal.action == "hold":
            logger.debug(f"[{ticker}] {signal.reason}")
            return

        safe, safety_msg = self._safety.validate_order(
            ticker, signal.action,
            self._calculate_quantity(ticker, current_price, signal),
            current_price, self._portfolio.total_value)

        if not safe:
            logger.warning(f"[{ticker}] 안전장치 거부: {safety_msg}")
            return

        quantity = self._calculate_quantity(ticker, current_price, signal)
        if quantity <= 0:
            return

        if signal.action == "buy":
            ok, msg = self._portfolio.execute_buy(
                ticker, current_price, quantity,
                reason=signal.reason, strategy=self._strategy.name,
                signal_score=signal.score, confidence=signal.confidence)
        elif signal.action == "sell":
            ok, msg = self._portfolio.execute_sell(
                ticker, current_price, quantity,
                reason=signal.reason, strategy=self._strategy.name,
                signal_score=signal.score, confidence=signal.confidence)
        else:
            return

        if ok:
            self._safety.record_trade(ticker, signal.action, current_price, quantity)

    async def _trading_loop(self):
        while self._running:
            if not self._is_market_hours():
                logger.info("장 시간 아님 — 대기 중")
                await asyncio.sleep(60)
                continue

            prices = self._get_latest_prices()
            if prices:
                self._portfolio.update_prices(prices)

            for ticker in self._tickers:
                price = prices.get(ticker)
                if price:
                    try:
                        await self._evaluate_ticker(ticker, price)
                    except Exception as e:
                        logger.error(f"[{ticker}] 평가 오류: {e}")

                await asyncio.sleep(0.5)

            rebalance_min = self._config.get("rebalance_interval_min", 5)
            await asyncio.sleep(rebalance_min * 60)

    async def _snapshot_loop(self):
        while self._running:
            await asyncio.sleep(300)
            try:
                self._portfolio.take_snapshot()
            except Exception as e:
                logger.error(f"스냅샷 오류: {e}")

    async def _status_loop(self):
        while self._running:
            await asyncio.sleep(60)
            summary = self._portfolio.get_summary()
            safety = self._safety.get_status() if self._safety else {}
            logger.info(
                f"[STATUS] 총자산: ${summary['total_value']:,.2f} "
                f"(PnL: {summary['total_pnl_pct']:.2f}%) "
                f"현금: ${summary['cash']:,.2f} "
                f"포지션: {summary['position_count']}개 "
                f"서킷브레이커: {'ON' if safety.get('circuit_breaker_active') else 'OFF'}")

    async def start(self):
        logger.info("=" * 60)
        logger.info("Spectratic 자동매매 엔진 시작")
        logger.info("=" * 60)

        self._load_config()
        self._running = True

        trading_task = asyncio.create_task(self._trading_loop())
        snapshot_task = asyncio.create_task(self._snapshot_loop())
        status_task = asyncio.create_task(self._status_loop())

        try:
            await asyncio.gather(trading_task, snapshot_task, status_task)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("매매 엔진 종료 중...")
            self._running = False
            self._portfolio.take_snapshot()
            self._portfolio.save_state()
            logger.info("매매 엔진 종료 완료")

    async def stop(self):
        self._running = False


async def main():
    engine = TradingEngine()

    loop = asyncio.get_event_loop()

    def _shutdown():
        logger.info("종료 시그널 수신")
        asyncio.ensure_future(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await engine.start()


if __name__ == "__main__":
    asyncio.run(main())
