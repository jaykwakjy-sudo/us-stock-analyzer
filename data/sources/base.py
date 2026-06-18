"""데이터 소스 베이스 클래스

모든 데이터 소스(Yahoo, Finnhub, Alpaca, Polygon 등)는 이 인터페이스를 구현.
새 소스 추가 = 이 클래스 상속 + SOURCE_REGISTRY에 등록.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, List, Dict, Type


class DataType(Enum):
    TRADE = "trade"
    QUOTE = "quote"
    BAR = "bar"


@dataclass
class MarketTick:
    """실시간 시장 데이터의 최소 단위. 모든 소스가 이 형식으로 정규화."""
    ticker: str
    price: float
    volume: int
    timestamp: datetime
    source: str
    data_type: DataType = DataType.TRADE
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    vwap: Optional[float] = None
    conditions: List[str] = field(default_factory=list)

    @property
    def timestamp_utc(self) -> datetime:
        if self.timestamp.tzinfo is None:
            return self.timestamp.replace(tzinfo=timezone.utc)
        return self.timestamp.astimezone(timezone.utc)

    @property
    def timestamp_ms(self) -> int:
        return int(self.timestamp_utc.timestamp() * 1000)

    @property
    def latency_ms(self) -> float:
        now = datetime.now(timezone.utc)
        return (now - self.timestamp_utc).total_seconds() * 1000

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "volume": self.volume,
            "timestamp": self.timestamp_utc.isoformat(),
            "timestamp_ms": self.timestamp_ms,
            "source": self.source,
            "data_type": self.data_type.value,
            "bid": self.bid,
            "ask": self.ask,
            "high": self.high,
            "low": self.low,
            "open": self.open,
            "vwap": self.vwap,
            "latency_ms": round(self.latency_ms, 1),
        }


class BaseDataSource(ABC):
    name: str = ""
    is_realtime: bool = False
    supports_websocket: bool = False

    def __init__(self, config: dict):
        self.config = config
        self._callbacks: List[Callable] = []
        self._running = False

    def on_tick(self, callback: Callable):
        self._callbacks.append(callback)

    def _emit(self, tick: MarketTick):
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception:
                pass

    @abstractmethod
    async def connect(self):
        """데이터 소스 연결"""

    @abstractmethod
    async def disconnect(self):
        """연결 해제"""

    @abstractmethod
    async def subscribe(self, tickers: list[str]):
        """종목 구독 시작"""

    @abstractmethod
    async def unsubscribe(self, tickers: list[str]):
        """종목 구독 해제"""

    @abstractmethod
    def get_snapshot(self, ticker: str) -> Optional[MarketTick]:
        """현재가 스냅샷 (동기)"""

    @abstractmethod
    def get_historical(self, ticker: str, period: str = "1y") -> list[dict]:
        """과거 데이터 조회 (동기)"""


SOURCE_REGISTRY: Dict[str, Type[BaseDataSource]] = {}


def register_source(cls: Type[BaseDataSource]):
    SOURCE_REGISTRY[cls.name] = cls
    return cls
