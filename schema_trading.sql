-- 가상 매매 엔진 테이블 (Supabase SQL Editor에서 실행)

-- 1. 가상 포트폴리오 — 현재 보유 포지션
CREATE TABLE IF NOT EXISTS virtual_positions (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_price DECIMAL(12,4) NOT NULL,
    current_price DECIMAL(12,4),
    unrealized_pnl DECIMAL(14,2),
    unrealized_pnl_pct DECIMAL(8,4),
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 가상 주문 히스토리
CREATE TABLE IF NOT EXISTS virtual_orders (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type VARCHAR(10) NOT NULL DEFAULT 'market',
    requested_qty INTEGER NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    requested_price DECIMAL(12,4),
    filled_price DECIMAL(12,4),
    commission DECIMAL(8,4) DEFAULT 0,
    slippage DECIMAL(8,4) DEFAULT 0,
    status VARCHAR(10) NOT NULL DEFAULT 'filled' CHECK (status IN ('pending', 'filled', 'rejected', 'cancelled')),
    reason TEXT,
    strategy VARCHAR(30),
    signal_score DECIMAL(5,2),
    confidence DECIMAL(5,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_ticker ON virtual_orders(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_created ON virtual_orders(created_at DESC);

-- 3. 포트폴리오 스냅샷 (일별 자산 추적)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL UNIQUE,
    cash DECIMAL(14,2) NOT NULL,
    positions_value DECIMAL(14,2) NOT NULL DEFAULT 0,
    total_value DECIMAL(14,2) NOT NULL,
    daily_pnl DECIMAL(14,2) DEFAULT 0,
    daily_pnl_pct DECIMAL(8,4) DEFAULT 0,
    total_pnl DECIMAL(14,2) DEFAULT 0,
    total_pnl_pct DECIMAL(8,4) DEFAULT 0,
    position_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 매매 엔진 설정 시드
INSERT INTO settings (key, value)
VALUES ('trading_config', '{
    "initial_capital": 100000,
    "max_position_pct": 15,
    "max_total_positions": 20,
    "max_daily_trades": 50,
    "commission_per_share": 0,
    "min_order_value": 100,
    "stop_loss_pct": 5,
    "take_profit_pct": 15,
    "circuit_breaker_pct": 3,
    "circuit_breaker_window_min": 5,
    "strategy": "signal_score",
    "buy_threshold": 65,
    "sell_threshold": 35,
    "strong_buy_threshold": 80,
    "strong_sell_threshold": 20,
    "rebalance_interval_min": 5
}')
ON CONFLICT (key) DO NOTHING;

-- 5. 포트폴리오 잔고 (단일 행)
INSERT INTO settings (key, value)
VALUES ('portfolio_state', '{
    "cash": 100000,
    "initial_capital": 100000,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "total_realized_pnl": 0,
    "started_at": null
}')
ON CONFLICT (key) DO NOTHING;
