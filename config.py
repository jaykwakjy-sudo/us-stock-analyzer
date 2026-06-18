"""프로젝트 설정"""

# 관심 종목 (빅테크 중심)
WATCHLIST = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "META": "Meta",
    "TSLA": "Tesla",
}

# 주요 지수
INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^VIX": "VIX (공포지수)",
    "^TNX": "미국 10년 국채금리",
}

# 섹터 ETF
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLC": "Communication Services",
}

# 기술적 분석 기본 설정
TECHNICAL = {
    "sma_periods": [20, 50, 200],
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bollinger_period": 20,
    "bollinger_std": 2,
}

# 포지션 전략
STRATEGY = {
    "long_term_ratio": 0.6,      # 장기투자 비중 60%
    "swing_ratio": 0.4,          # 스윙 비중 40%
    "max_single_stock": 0.25,    # 단일 종목 최대 25%
    "stop_loss_pct": -7,         # 손절 기준 -7%
    "take_profit_pct": 15,       # 익절 기준 +15%
    "swing_stop_loss_pct": -5,   # 스윙 손절 -5%
    "swing_take_profit_pct": 10, # 스윙 익절 +10%
}
