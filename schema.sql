-- Supabase SQL Editor에서 실행할 테이블 생성 스크립트

-- 1. 매매 일지
CREATE TABLE trading_journal (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(4) NOT NULL CHECK (action IN ('buy', 'sell')),
    price DECIMAL(12,2) NOT NULL,
    quantity INTEGER NOT NULL,
    total DECIMAL(14,2) GENERATED ALWAYS AS (price * quantity) STORED,
    reason TEXT NOT NULL,
    strategy_type VARCHAR(20) DEFAULT 'swing' CHECK (strategy_type IN ('swing', 'long_term')),
    notes TEXT DEFAULT '',
    feedback TEXT,
    feedback_date TIMESTAMPTZ,
    result_price DECIMAL(12,2),
    result_pnl DECIMAL(8,2)
);

-- 2. 일별 시장 분석 기록
CREATE TABLE daily_analysis (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    market_summary JSONB,
    sector_leaders TEXT[],
    sector_laggards TEXT[],
    vix DECIMAL(6,2),
    memo TEXT
);

-- 3. 주가 히스토리 캐시 (야후 API 호출 절약)
CREATE TABLE price_cache (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    open DECIMAL(12,2),
    high DECIMAL(12,2),
    low DECIMAL(12,2),
    close DECIMAL(12,2),
    volume BIGINT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, date)
);

-- 4. 관심종목 리스트
CREATE TABLE watchlist (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    strategy_type VARCHAR(20) DEFAULT 'swing',
    target_buy_price DECIMAL(12,2),
    target_sell_price DECIMAL(12,2),
    stop_loss_price DECIMAL(12,2),
    notes TEXT DEFAULT ''
);

-- 5. 주요 일정
CREATE TABLE calendar_events (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    ticker VARCHAR(10),
    importance VARCHAR(10) DEFAULT 'medium' CHECK (importance IN ('low', 'medium', 'high')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. 전략 설정 (key-value)
CREATE TABLE settings (
    key VARCHAR(50) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스 추가
CREATE INDEX idx_journal_ticker ON trading_journal(ticker);
CREATE INDEX idx_journal_date ON trading_journal(created_at);
CREATE INDEX idx_price_cache_ticker_date ON price_cache(ticker, date);
CREATE INDEX idx_calendar_date ON calendar_events(date);

-- 기본 관심종목 삽입
INSERT INTO watchlist (ticker, name, strategy_type) VALUES
    ('AAPL', 'Apple', 'long_term'),
    ('MSFT', 'Microsoft', 'long_term'),
    ('GOOGL', 'Alphabet', 'long_term'),
    ('AMZN', 'Amazon', 'long_term'),
    ('NVDA', 'NVIDIA', 'swing'),
    ('META', 'Meta', 'swing'),
    ('TSLA', 'Tesla', 'swing');

-- 기본 전략 설정 삽입
INSERT INTO settings (key, value) VALUES
    ('position_ratio', '{"long_term": 0.6, "swing": 0.4}'),
    ('risk_management', '{"stop_loss_pct": -7, "take_profit_pct": 15, "swing_stop_loss_pct": -5, "swing_take_profit_pct": 10, "max_single_stock": 0.25}'),
    ('technical_params', '{"sma_periods": [20, 50, 200], "rsi_period": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9}');
