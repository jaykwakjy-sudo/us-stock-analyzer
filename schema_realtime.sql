-- 실시간 틱 데이터 테이블 (Supabase SQL Editor에서 실행)

-- 1. 실시간 체결 데이터
CREATE TABLE IF NOT EXISTS realtime_ticks (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    price DECIMAL(12,4) NOT NULL,
    volume INTEGER DEFAULT 0,
    timestamp TIMESTAMPTZ NOT NULL,
    timestamp_ms BIGINT NOT NULL,
    source VARCHAR(20) NOT NULL,
    bid DECIMAL(12,4),
    ask DECIMAL(12,4),
    latency_ms DECIMAL(8,1),
    received_at TIMESTAMPTZ DEFAULT NOW()
);

-- 타임스탬프 기반 빠른 조회
CREATE INDEX IF NOT EXISTS idx_ticks_ticker_ts ON realtime_ticks(ticker, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON realtime_ticks(timestamp DESC);

-- 파티셔닝 대신 자동 정리 (7일 이상 데이터 삭제)
-- Supabase pg_cron 또는 별도 cron으로 실행
-- DELETE FROM realtime_ticks WHERE timestamp < NOW() - INTERVAL '7 days';

-- 2. 분봉 집계 테이블 (실시간 틱 → 1분 OHLCV 집계)
CREATE TABLE IF NOT EXISTS realtime_bars (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    interval VARCHAR(5) NOT NULL DEFAULT '1m',
    bar_time TIMESTAMPTZ NOT NULL,
    open DECIMAL(12,4),
    high DECIMAL(12,4),
    low DECIMAL(12,4),
    close DECIMAL(12,4),
    volume BIGINT DEFAULT 0,
    vwap DECIMAL(12,4),
    tick_count INTEGER DEFAULT 0,
    source VARCHAR(20),
    UNIQUE(ticker, interval, bar_time)
);

CREATE INDEX IF NOT EXISTS idx_bars_ticker_time ON realtime_bars(ticker, bar_time DESC);

-- 3. 파이프라인 상태 모니터링
CREATE TABLE IF NOT EXISTS pipeline_status (
    id BIGSERIAL PRIMARY KEY,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    status JSONB NOT NULL
);

-- 4. 파이프라인 설정 시드
INSERT INTO settings (key, value)
VALUES ('pipeline_config', '{
    "source": "auto",
    "poll_interval_sec": 10,
    "flush_interval_sec": 5,
    "finnhub_api_key": "",
    "alpaca_api_key": "",
    "alpaca_secret_key": "",
    "alpaca_paper": true
}')
ON CONFLICT (key) DO NOTHING;

INSERT INTO settings (key, value)
VALUES ('validator_config', '{
    "max_price_change_pct": 25.0,
    "max_latency_ms": 30000,
    "min_price": 0.01,
    "max_price": 100000.0,
    "max_volume_single": 50000000
}')
ON CONFLICT (key) DO NOTHING;
