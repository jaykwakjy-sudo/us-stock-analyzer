"""포트폴리오 매니저 — 가상 자산/포지션/주문 관리

모든 종목 수, 금액, 비중 한도는 DB trading_config에서 로드.
코드에 종목명이나 매직넘버 없음.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Position:
    ticker: str
    quantity: int
    avg_price: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_price

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0
        return (self.unrealized_pnl / self.cost_basis) * 100


@dataclass
class Order:
    ticker: str
    side: str
    quantity: int
    price: float
    reason: str
    strategy: str = ""
    signal_score: float = 0
    confidence: float = 0
    commission: float = 0
    slippage: float = 0


class PortfolioManager:
    def __init__(self, db_client, config: dict):
        self._db = db_client
        self._config = config
        self._cash: float = config.get("initial_capital", 100000)
        self._positions: dict[str, Position] = {}
        self._daily_trade_count = 0
        self._daily_trade_date: str = ""

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def total_value(self) -> float:
        positions_value = sum(p.market_value for p in self._positions.values())
        return self._cash + positions_value

    @property
    def positions_value(self) -> float:
        return sum(p.market_value for p in self._positions.values())

    def load_state(self):
        try:
            state = self._db.table("settings").select("value").eq(
                "key", "portfolio_state").maybe_single().execute()
            if state.data:
                s = state.data["value"]
                self._cash = s.get("cash", self._config.get("initial_capital", 100000))

            positions = self._db.table("virtual_positions").select("*").execute()
            self._positions = {}
            for p in (positions.data or []):
                self._positions[p["ticker"]] = Position(
                    ticker=p["ticker"],
                    quantity=p["quantity"],
                    avg_price=float(p["avg_price"]),
                    current_price=float(p.get("current_price") or p["avg_price"]),
                )
            logger.info(f"포트폴리오 로드: 잔고=${self._cash:,.2f} 포지션={len(self._positions)}개")
        except Exception as e:
            logger.error(f"포트폴리오 로드 실패: {e}")

    def save_state(self):
        try:
            state = {
                "cash": round(self._cash, 2),
                "initial_capital": self._config.get("initial_capital", 100000),
                "total_trades": self._daily_trade_count,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self._db.table("settings").upsert(
                {"key": "portfolio_state", "value": state},
                on_conflict="key").execute()
        except Exception as e:
            logger.error(f"포트폴리오 저장 실패: {e}")

    def _save_position(self, pos: Position):
        self._db.table("virtual_positions").upsert({
            "ticker": pos.ticker,
            "quantity": pos.quantity,
            "avg_price": round(pos.avg_price, 4),
            "current_price": round(pos.current_price, 4),
            "unrealized_pnl": round(pos.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(pos.unrealized_pnl_pct, 4),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="ticker").execute()

    def _remove_position(self, ticker: str):
        self._db.table("virtual_positions").delete().eq("ticker", ticker).execute()

    def _record_order(self, order: Order, status: str = "filled"):
        self._db.table("virtual_orders").insert({
            "ticker": order.ticker,
            "side": order.side,
            "order_type": "market",
            "requested_qty": order.quantity,
            "filled_qty": order.quantity if status == "filled" else 0,
            "filled_price": round(order.price, 4),
            "commission": round(order.commission, 4),
            "slippage": round(order.slippage, 4),
            "status": status,
            "reason": order.reason,
            "strategy": order.strategy,
            "signal_score": round(order.signal_score, 2),
            "confidence": round(order.confidence, 4),
        }).execute()

    def _check_daily_limit(self) -> bool:
        today = date.today().isoformat()
        if self._daily_trade_date != today:
            self._daily_trade_date = today
            self._daily_trade_count = 0
        max_daily = self._config.get("max_daily_trades", 50)
        return self._daily_trade_count < max_daily

    def can_buy(self, ticker: str, price: float, quantity: int) -> tuple[bool, str]:
        cost = price * quantity
        commission = self._config.get("commission_per_share", 0) * quantity
        total_cost = cost + commission

        if total_cost > self._cash:
            return False, f"잔고 부족: 필요 ${total_cost:,.2f} > 잔고 ${self._cash:,.2f}"

        min_order = self._config.get("min_order_value", 100)
        if cost < min_order:
            return False, f"최소 주문금액 미달: ${cost:,.2f} < ${min_order}"

        max_pct = self._config.get("max_position_pct", 15) / 100
        max_position_value = self.total_value * max_pct
        existing = self._positions.get(ticker)
        existing_value = existing.market_value if existing else 0
        if existing_value + cost > max_position_value:
            return False, f"종목 비중 초과: {(existing_value + cost)/self.total_value*100:.1f}% > {max_pct*100}%"

        max_positions = self._config.get("max_total_positions", 20)
        if ticker not in self._positions and len(self._positions) >= max_positions:
            return False, f"최대 보유 종목 수 초과: {len(self._positions)} >= {max_positions}"

        if not self._check_daily_limit():
            return False, f"일일 거래 횟수 초과"

        return True, "OK"

    def execute_buy(self, ticker: str, price: float, quantity: int,
                    reason: str, strategy: str = "", signal_score: float = 0,
                    confidence: float = 0) -> tuple[bool, str]:
        can, msg = self.can_buy(ticker, price, quantity)
        if not can:
            order = Order(ticker=ticker, side="buy", quantity=quantity,
                         price=price, reason=f"거부: {msg}")
            self._record_order(order, status="rejected")
            return False, msg

        commission = self._config.get("commission_per_share", 0) * quantity
        total_cost = (price * quantity) + commission

        self._cash -= total_cost

        if ticker in self._positions:
            pos = self._positions[ticker]
            total_qty = pos.quantity + quantity
            pos.avg_price = ((pos.avg_price * pos.quantity) + (price * quantity)) / total_qty
            pos.quantity = total_qty
            pos.current_price = price
        else:
            self._positions[ticker] = Position(
                ticker=ticker, quantity=quantity,
                avg_price=price, current_price=price)

        self._daily_trade_count += 1

        order = Order(ticker=ticker, side="buy", quantity=quantity,
                     price=price, reason=reason, strategy=strategy,
                     signal_score=signal_score, confidence=confidence,
                     commission=commission)
        self._record_order(order)
        self._save_position(self._positions[ticker])
        self.save_state()

        logger.info(f"[BUY] {ticker} x{quantity} @ ${price:.2f} "
                    f"(${total_cost:,.2f}) 사유: {reason}")
        return True, f"매수 완료: {ticker} x{quantity} @ ${price:.2f}"

    def execute_sell(self, ticker: str, price: float, quantity: int,
                     reason: str, strategy: str = "", signal_score: float = 0,
                     confidence: float = 0) -> tuple[bool, str]:
        pos = self._positions.get(ticker)
        if not pos:
            return False, f"보유하지 않은 종목: {ticker}"
        if quantity > pos.quantity:
            return False, f"수량 초과: 요청 {quantity} > 보유 {pos.quantity}"

        if not self._check_daily_limit():
            return False, "일일 거래 횟수 초과"

        commission = self._config.get("commission_per_share", 0) * quantity
        proceeds = (price * quantity) - commission
        realized_pnl = (price - pos.avg_price) * quantity - commission

        self._cash += proceeds
        pos.quantity -= quantity
        self._daily_trade_count += 1

        order = Order(ticker=ticker, side="sell", quantity=quantity,
                     price=price, reason=reason, strategy=strategy,
                     signal_score=signal_score, confidence=confidence,
                     commission=commission)
        self._record_order(order)

        if pos.quantity == 0:
            del self._positions[ticker]
            self._remove_position(ticker)
        else:
            pos.current_price = price
            self._save_position(pos)

        self.save_state()

        pnl_label = f"+${realized_pnl:,.2f}" if realized_pnl >= 0 else f"-${abs(realized_pnl):,.2f}"
        logger.info(f"[SELL] {ticker} x{quantity} @ ${price:.2f} "
                    f"실현손익: {pnl_label} 사유: {reason}")
        return True, f"매도 완료: {ticker} x{quantity} @ ${price:.2f} ({pnl_label})"

    def update_prices(self, prices: dict[str, float]):
        for ticker, price in prices.items():
            if ticker in self._positions:
                self._positions[ticker].current_price = price

    def take_snapshot(self):
        try:
            initial = self._config.get("initial_capital", 100000)
            total = self.total_value
            total_pnl = total - initial
            total_pnl_pct = (total_pnl / initial) * 100 if initial else 0

            self._db.table("portfolio_snapshots").upsert({
                "snapshot_date": date.today().isoformat(),
                "cash": round(self._cash, 2),
                "positions_value": round(self.positions_value, 2),
                "total_value": round(total, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl_pct, 4),
                "position_count": len(self._positions),
            }, on_conflict="snapshot_date").execute()
        except Exception as e:
            logger.error(f"스냅샷 저장 실패: {e}")

    def get_summary(self) -> dict:
        initial = self._config.get("initial_capital", 100000)
        total = self.total_value
        return {
            "cash": round(self._cash, 2),
            "positions_value": round(self.positions_value, 2),
            "total_value": round(total, 2),
            "total_pnl": round(total - initial, 2),
            "total_pnl_pct": round((total - initial) / initial * 100, 4) if initial else 0,
            "position_count": len(self._positions),
            "positions": {t: {
                "quantity": p.quantity,
                "avg_price": p.avg_price,
                "current_price": p.current_price,
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 2),
            } for t, p in self._positions.items()},
        }
