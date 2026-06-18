"""프로젝트 설정 — 폴백 전용 (DB 설정이 없을 때만 사용)

모든 운영 설정은 Supabase settings 테이블에서 로드됩니다.
이 파일은 DB 연결 전 또는 설정 미등록 시 안전한 기본값을 제공합니다.
"""

INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^VIX": "VIX (공포지수)",
    "^TNX": "미국 10년 국채금리",
}

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

# 레거시 호환용 — 새 코드는 DB에서 로드
TECHNICAL = {
    "sma_periods": [20, 50, 200],
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bollinger_period": 20,
    "bollinger_std": 2,
}
