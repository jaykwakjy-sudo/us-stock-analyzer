"""Yahoo Finance 데이터 소스 — 폴링 기반 (폴백 & 히스토리컬)

실시간 정확도: ~15초 딜레이 (1분봉 폴링)
용도: WebSocket 소스 불가 시 폴백, 과거 데이터, 기본 정보
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd

from .base import BaseDataSource, MarketTick, DataType, register_source


@register_source
class YahooFinanceSource(BaseDataSource):
    name = "yahoo"
    is_realtime = False
    supports_websocket = False

    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self._subscribed: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._last_prices: dict[str, float] = {}

    async def connect(self):
        self._running = True

    async def disconnect(self):
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()

    async def subscribe(self, tickers: list[str]):
        self._subscribed.update(t.upper() for t in tickers)
        if self._running and not self._poll_task:
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def unsubscribe(self, tickers: list[str]):
        for t in tickers:
            self._subscribed.discard(t.upper())

    async def _poll_loop(self):
        interval = self.config.get("poll_interval_sec", 10)
        while self._running and self._subscribed:
            tickers = list(self._subscribed)
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._fetch_batch, tickers)
            except Exception:
                pass
            await asyncio.sleep(interval)

    def _fetch_batch(self, tickers: list[str]):
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                fast = stock.fast_info
                price = getattr(fast, "last_price", None)
                if price is None:
                    continue

                prev = getattr(fast, "previous_close", None)
                market_cap = getattr(fast, "market_cap", None)

                now = datetime.now(timezone.utc)
                tick = MarketTick(
                    ticker=ticker,
                    price=float(price),
                    volume=0,
                    timestamp=now,
                    source=self.name,
                    data_type=DataType.TRADE,
                )
                self._last_prices[ticker] = float(price)
                self._emit(tick)
            except Exception:
                continue

    def get_snapshot(self, ticker: str) -> MarketTick | None:
        ticker = ticker.upper()
        try:
            stock = yf.Ticker(ticker)
            fast = stock.fast_info
            price = getattr(fast, "last_price", None)
            if price is None:
                return None

            return MarketTick(
                ticker=ticker,
                price=float(price),
                volume=0,
                timestamp=datetime.now(timezone.utc),
                source=self.name,
                data_type=DataType.TRADE,
            )
        except Exception:
            return None

    def get_historical(self, ticker: str, period: str = "1y") -> list[dict]:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty:
            return []
        rows = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            rows.append({
                "ticker": ticker.upper(),
                "timestamp": ts.isoformat(),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return rows

    def get_intraday(self, ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
        """장중 분봉 데이터 — 가장 빠른 Yahoo 실시간 대안"""
        return yf.Ticker(ticker).history(period=period, interval=interval)
