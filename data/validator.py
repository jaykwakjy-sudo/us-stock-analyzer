"""데이터 검증 & 정규화 — 오염 방지의 첫 관문

모든 수신 데이터는 이 검증을 통과해야 DB에 저장됨.
AI 안전 원칙: 잘못된 데이터가 학습에 들어가지 않도록 차단.
"""

import logging
from datetime import datetime, timezone, timedelta
from data.sources.base import MarketTick

logger = logging.getLogger(__name__)


class DataValidator:
    def __init__(self, config: dict = None):
        config = config or {}
        self.max_price_change_pct = config.get("max_price_change_pct", 25.0)
        self.max_latency_ms = config.get("max_latency_ms", 30000)
        self.min_price = config.get("min_price", 0.01)
        self.max_price = config.get("max_price", 100000.0)
        self.max_volume_single = config.get("max_volume_single", 50_000_000)
        self._last_valid: dict[str, MarketTick] = {}
        self._reject_count = 0
        self._accept_count = 0

    def validate(self, tick: MarketTick) -> tuple[bool, str]:
        """틱 데이터 검증. Returns (통과 여부, 사유)"""

        if tick.price < self.min_price or tick.price > self.max_price:
            self._reject_count += 1
            return False, f"가격 범위 이탈: ${tick.price}"

        if tick.volume < 0:
            self._reject_count += 1
            return False, f"음수 거래량: {tick.volume}"

        if tick.volume > self.max_volume_single:
            self._reject_count += 1
            return False, f"비정상 거래량: {tick.volume:,}"

        if tick.timestamp_utc > datetime.now(timezone.utc) + timedelta(seconds=5):
            self._reject_count += 1
            return False, f"미래 타임스탬프: {tick.timestamp_utc}"

        if tick.latency_ms > self.max_latency_ms:
            self._reject_count += 1
            return False, f"과도한 지연: {tick.latency_ms:.0f}ms"

        last = self._last_valid.get(tick.ticker)
        if last and last.price > 0:
            change_pct = abs(tick.price - last.price) / last.price * 100
            if change_pct > self.max_price_change_pct:
                self._reject_count += 1
                return False, f"급격한 가격 변동: {change_pct:.1f}% (${last.price}→${tick.price})"

        if tick.bid is not None and tick.ask is not None:
            if tick.bid > tick.ask:
                self._reject_count += 1
                return False, f"bid > ask: ${tick.bid} > ${tick.ask}"
            spread_pct = (tick.ask - tick.bid) / tick.ask * 100 if tick.ask > 0 else 0
            if spread_pct > 10:
                self._reject_count += 1
                return False, f"비정상 스프레드: {spread_pct:.1f}%"

        self._last_valid[tick.ticker] = tick
        self._accept_count += 1
        return True, "OK"

    def get_stats(self) -> dict:
        total = self._accept_count + self._reject_count
        return {
            "accepted": self._accept_count,
            "rejected": self._reject_count,
            "total": total,
            "reject_rate": round(self._reject_count / total * 100, 2) if total > 0 else 0,
            "tracked_tickers": len(self._last_valid),
        }
