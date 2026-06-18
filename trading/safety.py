"""매매 안전장치 — 서킷브레이커, 이상 거래 감지, 롤백

모든 임계값은 DB trading_config에서 로드.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class TradingSafety:
    def __init__(self, config: dict):
        self._config = config
        self._circuit_breaker_active = False
        self._circuit_breaker_until: datetime | None = None
        self._recent_prices: dict[str, deque] = {}
        self._trade_log: deque = deque(maxlen=1000)

    def check_circuit_breaker(self, ticker: str, current_price: float) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)

        if self._circuit_breaker_active and self._circuit_breaker_until:
            if now < self._circuit_breaker_until:
                remaining = (self._circuit_breaker_until - now).total_seconds()
                return False, f"서킷브레이커 발동 중 (해제까지 {remaining:.0f}초)"
            self._circuit_breaker_active = False
            self._circuit_breaker_until = None
            logger.info(f"서킷브레이커 해제: {ticker}")

        threshold_pct = self._config.get("circuit_breaker_pct", 3)
        window_min = self._config.get("circuit_breaker_window_min", 5)

        if ticker not in self._recent_prices:
            self._recent_prices[ticker] = deque(maxlen=300)

        prices = self._recent_prices[ticker]
        prices.append((now, current_price))

        cutoff = now - timedelta(minutes=window_min)
        while prices and prices[0][0] < cutoff:
            prices.popleft()

        if len(prices) >= 2:
            oldest_price = prices[0][1]
            change_pct = abs((current_price - oldest_price) / oldest_price * 100)

            if change_pct >= threshold_pct:
                self._circuit_breaker_active = True
                self._circuit_breaker_until = now + timedelta(minutes=window_min)
                msg = (f"서킷브레이커 발동: {ticker} "
                       f"{change_pct:.1f}% 변동 ({window_min}분 내)")
                logger.warning(msg)
                return False, msg

        return True, "OK"

    def validate_order(self, ticker: str, side: str, quantity: int,
                       price: float, portfolio_value: float) -> tuple[bool, str]:
        max_order_pct = self._config.get("max_position_pct", 15)
        order_value = price * quantity
        order_pct = (order_value / portfolio_value * 100) if portfolio_value > 0 else 100

        if order_pct > max_order_pct:
            return False, f"단일 주문 비중 초과: {order_pct:.1f}% > {max_order_pct}%"

        if price <= 0:
            return False, f"비정상 가격: ${price}"

        if quantity <= 0:
            return False, f"비정상 수량: {quantity}"

        safe, reason = self.check_circuit_breaker(ticker, price)
        if not safe:
            return False, reason

        return True, "OK"

    def record_trade(self, ticker: str, side: str, price: float, quantity: int):
        self._trade_log.append({
            "ticker": ticker,
            "side": side,
            "price": price,
            "quantity": quantity,
            "timestamp": datetime.now(timezone.utc),
        })

    def get_status(self) -> dict:
        return {
            "circuit_breaker_active": self._circuit_breaker_active,
            "circuit_breaker_until": (
                self._circuit_breaker_until.isoformat()
                if self._circuit_breaker_until else None),
            "recent_trades": len(self._trade_log),
            "monitored_tickers": list(self._recent_prices.keys()),
        }
