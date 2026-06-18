"""Finnhub WebSocket 데이터 소스 — 진짜 실시간 (수십ms 레이턴시)

무료 플랜: 실시간 미국주식 WebSocket (체결 데이터)
가입: https://finnhub.io → 무료 API 키 발급
설정: DB settings에 {"finnhub_api_key": "your_key"} 저장
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from .base import BaseDataSource, MarketTick, DataType, register_source

logger = logging.getLogger(__name__)

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


@register_source
class FinnhubWebSocketSource(BaseDataSource):
    name = "finnhub"
    is_realtime = True
    supports_websocket = True

    WS_URL = "wss://ws.finnhub.io"

    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self._ws = None
        self._subscribed: set[str] = set()
        self._recv_task: asyncio.Task | None = None
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._last_prices: dict[str, MarketTick] = {}
        self._tick_count = 0
        self._connect_time: datetime | None = None

    @property
    def api_key(self) -> str:
        return self.config.get("finnhub_api_key", "")

    async def connect(self):
        if not HAS_WEBSOCKETS:
            raise ImportError("pip install websockets 필요")
        if not self.api_key:
            raise ValueError("finnhub_api_key가 설정되지 않음")

        self._running = True
        await self._do_connect()

    async def _do_connect(self):
        url = f"{self.WS_URL}?token={self.api_key}"
        try:
            self._ws = await websockets.connect(url, ping_interval=30, ping_timeout=10)
            self._connect_time = datetime.now(timezone.utc)
            self._reconnect_delay = 1
            logger.info("Finnhub WebSocket 연결 성공")

            for ticker in self._subscribed:
                await self._ws.send(json.dumps({"type": "subscribe", "symbol": ticker}))

            self._recv_task = asyncio.create_task(self._recv_loop())
        except Exception as e:
            logger.error(f"Finnhub 연결 실패: {e}")
            await self._schedule_reconnect()

    async def _schedule_reconnect(self):
        if not self._running:
            return
        logger.info(f"Finnhub 재연결 대기 {self._reconnect_delay}초...")
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        await self._do_connect()

    async def _recv_loop(self):
        try:
            async for message in self._ws:
                if not self._running:
                    break
                try:
                    data = json.loads(message)
                    if data.get("type") == "trade":
                        for trade in data.get("data", []):
                            tick = MarketTick(
                                ticker=trade["s"],
                                price=float(trade["p"]),
                                volume=int(trade["v"]),
                                timestamp=datetime.fromtimestamp(
                                    trade["t"] / 1000, tz=timezone.utc),
                                source=self.name,
                                data_type=DataType.TRADE,
                                conditions=trade.get("c", []),
                            )
                            self._last_prices[tick.ticker] = tick
                            self._tick_count += 1
                            self._emit(tick)
                    elif data.get("type") == "ping":
                        pass
                except (KeyError, ValueError) as e:
                    logger.debug(f"Finnhub 메시지 파싱 오류: {e}")
        except Exception as e:
            logger.warning(f"Finnhub WebSocket 끊김: {e}")
            if self._running:
                await self._schedule_reconnect()

    async def disconnect(self):
        self._running = False
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
        if self._ws:
            try:
                for ticker in self._subscribed:
                    await self._ws.send(json.dumps({"type": "unsubscribe", "symbol": ticker}))
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        logger.info("Finnhub WebSocket 연결 해제")

    async def subscribe(self, tickers: list[str]):
        new_tickers = [t.upper() for t in tickers if t.upper() not in self._subscribed]
        self._subscribed.update(t.upper() for t in tickers)
        if self._ws:
            for ticker in new_tickers:
                await self._ws.send(json.dumps({"type": "subscribe", "symbol": ticker}))
                logger.info(f"Finnhub 구독: {ticker}")

    async def unsubscribe(self, tickers: list[str]):
        for t in tickers:
            t_upper = t.upper()
            self._subscribed.discard(t_upper)
            if self._ws:
                await self._ws.send(json.dumps({"type": "unsubscribe", "symbol": t_upper}))

    def get_snapshot(self, ticker: str) -> MarketTick | None:
        return self._last_prices.get(ticker.upper())

    def get_historical(self, ticker: str, period: str = "1y") -> list[dict]:
        from .yahoo import YahooFinanceSource
        return YahooFinanceSource({}).get_historical(ticker, period)

    def get_status(self) -> dict:
        return {
            "connected": self._ws is not None and self._running,
            "subscribed": list(self._subscribed),
            "tick_count": self._tick_count,
            "connected_since": self._connect_time.isoformat() if self._connect_time else None,
            "cached_tickers": list(self._last_prices.keys()),
        }
