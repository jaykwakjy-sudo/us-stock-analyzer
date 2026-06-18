"""Alpaca WebSocket 데이터 소스 — 실시간 + 가상매매 API 통합

무료: IEX 실시간 피드 (Paper Trading 계정)
가입: https://app.alpaca.markets → Paper Trading 계정 생성
설정: DB settings에 {"alpaca_api_key": "...", "alpaca_secret_key": "...", "alpaca_paper": true}

장점: 나중에 토스 대신 Alpaca로 실제 매매도 가능 (미국 브로커)
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
class AlpacaWebSocketSource(BaseDataSource):
    name = "alpaca"
    is_realtime = True
    supports_websocket = True

    IEX_URL = "wss://stream.data.alpaca.markets/v2/iex"
    SIP_URL = "wss://stream.data.alpaca.markets/v2/sip"

    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self._ws = None
        self._subscribed_trades: set[str] = set()
        self._subscribed_quotes: set[str] = set()
        self._recv_task: asyncio.Task | None = None
        self._reconnect_delay = 1
        self._last_prices: dict[str, MarketTick] = {}
        self._tick_count = 0
        self._authenticated = False

    @property
    def _ws_url(self) -> str:
        return self.SIP_URL if self.config.get("alpaca_sip") else self.IEX_URL

    async def connect(self):
        if not HAS_WEBSOCKETS:
            raise ImportError("pip install websockets 필요")

        api_key = self.config.get("alpaca_api_key", "")
        secret_key = self.config.get("alpaca_secret_key", "")
        if not api_key or not secret_key:
            raise ValueError("alpaca_api_key / alpaca_secret_key 필요")

        self._running = True
        await self._do_connect()

    async def _do_connect(self):
        try:
            self._ws = await websockets.connect(self._ws_url, ping_interval=30)
            self._authenticated = False

            welcome = await self._ws.recv()
            data = json.loads(welcome)
            if isinstance(data, list) and data[0].get("T") == "success":
                logger.info("Alpaca WebSocket 연결 성공")

            auth_msg = {
                "action": "auth",
                "key": self.config["alpaca_api_key"],
                "secret": self.config["alpaca_secret_key"],
            }
            await self._ws.send(json.dumps(auth_msg))
            auth_resp = await self._ws.recv()
            auth_data = json.loads(auth_resp)

            if isinstance(auth_data, list) and auth_data[0].get("T") == "success":
                self._authenticated = True
                self._reconnect_delay = 1
                logger.info("Alpaca 인증 성공")
            else:
                raise ValueError(f"Alpaca 인증 실패: {auth_data}")

            if self._subscribed_trades or self._subscribed_quotes:
                sub_msg = {"action": "subscribe"}
                if self._subscribed_trades:
                    sub_msg["trades"] = list(self._subscribed_trades)
                if self._subscribed_quotes:
                    sub_msg["quotes"] = list(self._subscribed_quotes)
                await self._ws.send(json.dumps(sub_msg))

            self._recv_task = asyncio.create_task(self._recv_loop())

        except Exception as e:
            logger.error(f"Alpaca 연결 실패: {e}")
            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)
                await self._do_connect()

    async def _recv_loop(self):
        try:
            async for message in self._ws:
                if not self._running:
                    break
                try:
                    items = json.loads(message)
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        msg_type = item.get("T")
                        if msg_type == "t":
                            tick = MarketTick(
                                ticker=item["S"],
                                price=float(item["p"]),
                                volume=int(item["s"]),
                                timestamp=datetime.fromisoformat(
                                    item["t"].replace("Z", "+00:00")),
                                source=self.name,
                                data_type=DataType.TRADE,
                                conditions=item.get("c", []),
                            )
                            self._last_prices[tick.ticker] = tick
                            self._tick_count += 1
                            self._emit(tick)
                        elif msg_type == "q":
                            tick = MarketTick(
                                ticker=item["S"],
                                price=(float(item["bp"]) + float(item["ap"])) / 2,
                                volume=0,
                                timestamp=datetime.fromisoformat(
                                    item["t"].replace("Z", "+00:00")),
                                source=self.name,
                                data_type=DataType.QUOTE,
                                bid=float(item["bp"]),
                                ask=float(item["ap"]),
                                bid_size=int(item["bs"]),
                                ask_size=int(item["as"]),
                            )
                            self._emit(tick)
                except (KeyError, ValueError) as e:
                    logger.debug(f"Alpaca 메시지 파싱 오류: {e}")
        except Exception as e:
            logger.warning(f"Alpaca WebSocket 끊김: {e}")
            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)
                await self._do_connect()

    async def disconnect(self):
        self._running = False
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None

    async def subscribe(self, tickers: list[str]):
        upper = [t.upper() for t in tickers]
        self._subscribed_trades.update(upper)
        if self._ws and self._authenticated:
            await self._ws.send(json.dumps({
                "action": "subscribe", "trades": upper,
            }))

    async def unsubscribe(self, tickers: list[str]):
        upper = [t.upper() for t in tickers]
        for t in upper:
            self._subscribed_trades.discard(t)
        if self._ws and self._authenticated:
            await self._ws.send(json.dumps({
                "action": "unsubscribe", "trades": upper,
            }))

    def get_snapshot(self, ticker: str) -> MarketTick | None:
        return self._last_prices.get(ticker.upper())

    def get_historical(self, ticker: str, period: str = "1y") -> list[dict]:
        from .yahoo import YahooFinanceSource
        return YahooFinanceSource({}).get_historical(ticker, period)
