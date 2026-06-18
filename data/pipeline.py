"""실시간 데이터 파이프라인 — EC2 백그라운드 서비스

데이터 흐름:
  WebSocket/Polling → Validator → Normalizer → DB 저장 + 메모리 캐시

실행: python3 -m data.pipeline
설정: DB settings 테이블에서 로드 (data_source, poll_interval 등)

시간 정확성 보장:
  - 모든 타임스탬프 UTC (timezone-aware)
  - 소스 원본 타임스탬프 보존 (exchange timestamp)
  - 수신 시각과 소스 시각 둘 다 기록
  - 레이턴시 실시간 모니터링
"""

import asyncio
import logging
import signal
import sys
import os
from datetime import datetime, timezone, timedelta
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from data.sources.base import MarketTick, SOURCE_REGISTRY
from data.sources.yahoo import YahooFinanceSource
from data.sources.finnhub_ws import FinnhubWebSocketSource
from data.sources.alpaca_ws import AlpacaWebSocketSource
from data.validator import DataValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline")


class RealtimePipeline:
    def __init__(self):
        self._source = None
        self._validator = None
        self._running = False
        self._tickers: list[str] = []
        self._tick_buffer: deque[MarketTick] = deque(maxlen=10000)
        self._latest: dict[str, MarketTick] = {}
        self._db_client = None
        self._flush_interval = 5
        self._stats = {
            "started_at": None,
            "ticks_received": 0,
            "ticks_validated": 0,
            "ticks_rejected": 0,
            "ticks_stored": 0,
            "avg_latency_ms": 0,
            "latency_samples": deque(maxlen=100),
        }

    def _load_config(self) -> dict:
        """DB에서 파이프라인 설정 로드"""
        try:
            from data.database import get_setting, get_watchlist
            pipeline_config = get_setting("pipeline_config") or {}
            watchlist = get_watchlist()
            self._tickers = [w["ticker"] for w in watchlist]

            validator_config = get_setting("validator_config") or {}
            self._validator = DataValidator(validator_config)

            return pipeline_config
        except Exception as e:
            logger.warning(f"DB 설정 로드 실패, 기본값 사용: {e}")
            self._validator = DataValidator()
            return {}

    def _init_source(self, config: dict):
        """설정에 따라 최적의 데이터 소스 선택"""
        preferred = config.get("source", "auto")

        if preferred == "auto":
            if config.get("finnhub_api_key"):
                preferred = "finnhub"
            elif config.get("alpaca_api_key"):
                preferred = "alpaca"
            else:
                preferred = "yahoo"

        source_cls = SOURCE_REGISTRY.get(preferred)
        if source_cls is None:
            logger.warning(f"소스 '{preferred}' 없음, Yahoo 폴백")
            source_cls = YahooFinanceSource

        self._source = source_cls(config)
        logger.info(f"데이터 소스: {self._source.name} "
                     f"(실시간: {self._source.is_realtime}, "
                     f"WebSocket: {self._source.supports_websocket})")

    def _on_tick(self, tick: MarketTick):
        """틱 수신 콜백"""
        self._stats["ticks_received"] += 1

        valid, reason = self._validator.validate(tick)
        if not valid:
            self._stats["ticks_rejected"] += 1
            logger.debug(f"검증 실패 [{tick.ticker}]: {reason}")
            return

        self._stats["ticks_validated"] += 1
        self._stats["latency_samples"].append(tick.latency_ms)

        self._latest[tick.ticker] = tick
        self._tick_buffer.append(tick)

        if len(self._stats["latency_samples"]) > 0:
            self._stats["avg_latency_ms"] = round(
                sum(self._stats["latency_samples"]) / len(self._stats["latency_samples"]), 1)

    async def _flush_to_db(self):
        """버퍼의 틱 데이터를 DB에 일괄 저장"""
        while self._running:
            await asyncio.sleep(self._flush_interval)

            if not self._tick_buffer:
                continue

            batch = []
            while self._tick_buffer:
                tick = self._tick_buffer.popleft()
                batch.append({
                    "ticker": tick.ticker,
                    "price": tick.price,
                    "volume": tick.volume,
                    "timestamp": tick.timestamp_utc.isoformat(),
                    "timestamp_ms": tick.timestamp_ms,
                    "source": tick.source,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "latency_ms": round(tick.latency_ms, 1),
                })

            if batch:
                try:
                    from data.database import get_client
                    db = get_client()
                    db.table("realtime_ticks").insert(batch).execute()
                    self._stats["ticks_stored"] += len(batch)
                    logger.debug(f"DB 저장: {len(batch)}건")
                except Exception as e:
                    logger.error(f"DB 저장 실패: {e}")
                    for item in batch:
                        self._tick_buffer.appendleft(
                            MarketTick(
                                ticker=item["ticker"],
                                price=item["price"],
                                volume=item["volume"],
                                timestamp=datetime.fromisoformat(item["timestamp"]),
                                source=item["source"],
                            ))

    async def _log_stats(self):
        """주기적 상태 로깅"""
        while self._running:
            await asyncio.sleep(30)
            s = self._stats
            v = self._validator.get_stats() if self._validator else {}
            logger.info(
                f"[STATS] 수신:{s['ticks_received']} 유효:{s['ticks_validated']} "
                f"거부:{s['ticks_rejected']} 저장:{s['ticks_stored']} "
                f"평균지연:{s['avg_latency_ms']}ms "
                f"종목:{len(self._latest)}개 "
                f"검증거부율:{v.get('reject_rate', 0)}%"
            )

            for ticker, tick in self._latest.items():
                logger.info(
                    f"  {ticker}: ${tick.price:.2f} "
                    f"(vol:{tick.volume:,} latency:{tick.latency_ms:.0f}ms "
                    f"@ {tick.timestamp_utc.strftime('%H:%M:%S.%f')[:-3]})")

    async def start(self):
        """파이프라인 시작"""
        logger.info("=" * 60)
        logger.info("Spectratic 실시간 데이터 파이프라인 시작")
        logger.info("=" * 60)

        config = self._load_config()
        self._init_source(config)
        self._flush_interval = config.get("flush_interval_sec", 5)

        self._source.on_tick(self._on_tick)
        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()

        await self._source.connect()

        if self._tickers:
            await self._source.subscribe(self._tickers)
            logger.info(f"구독 종목: {', '.join(self._tickers)}")
        else:
            logger.warning("관심종목이 없습니다. Settings에서 추가하세요.")

        flush_task = asyncio.create_task(self._flush_to_db())
        stats_task = asyncio.create_task(self._log_stats())

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("파이프라인 종료 중...")
            self._running = False
            flush_task.cancel()
            stats_task.cancel()
            await self._source.disconnect()
            logger.info("파이프라인 종료 완료")

    async def stop(self):
        self._running = False

    def get_latest(self, ticker: str = None) -> dict:
        """최신 가격 조회 (Streamlit 페이지용)"""
        if ticker:
            tick = self._latest.get(ticker.upper())
            return tick.to_dict() if tick else None
        return {t: tick.to_dict() for t, tick in self._latest.items()}


async def main():
    pipeline = RealtimePipeline()

    loop = asyncio.get_event_loop()

    def _shutdown():
        logger.info("종료 시그널 수신")
        asyncio.ensure_future(pipeline.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await pipeline.start()


if __name__ == "__main__":
    asyncio.run(main())
