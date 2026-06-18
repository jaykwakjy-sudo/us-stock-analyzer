"""Yahoo Finance 데이터 수집 모듈"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from config import INDICES, SECTOR_ETFS


def get_stock_data(ticker: str, period: str = "1y") -> pd.DataFrame:
    """개별 종목 주가 데이터 조회"""
    stock = yf.Ticker(ticker)
    df = stock.history(period=period)
    return df


def get_stock_info(ticker: str) -> dict:
    """종목 기본 정보 (시가총액, PER, 배당률 등)"""
    stock = yf.Ticker(ticker)
    info = stock.info
    return {
        "name": info.get("longName", ticker),
        "sector": info.get("sector", "N/A"),
        "market_cap": info.get("marketCap", 0),
        "pe_ratio": info.get("trailingPE", None),
        "forward_pe": info.get("forwardPE", None),
        "dividend_yield": info.get("dividendYield", None),
        "52w_high": info.get("fiftyTwoWeekHigh", None),
        "52w_low": info.get("fiftyTwoWeekLow", None),
        "avg_volume": info.get("averageVolume", 0),
        "beta": info.get("beta", None),
        "target_price": info.get("targetMeanPrice", None),
        "recommendation": info.get("recommendationKey", "N/A"),
        "earnings_date": info.get("earningsTimestamp", None),
    }


def get_market_overview() -> dict:
    """주요 지수 현황"""
    result = {}
    for ticker, name in INDICES.items():
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="5d")
            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change_pct = ((current - prev) / prev) * 100
                result[name] = {
                    "price": current,
                    "change_pct": round(change_pct, 2),
                    "ticker": ticker,
                }
            elif len(hist) == 1:
                result[name] = {
                    "price": hist["Close"].iloc[-1],
                    "change_pct": 0,
                    "ticker": ticker,
                }
        except Exception:
            continue
    return result


def get_watchlist_summary(watchlist_items: list[dict] = None) -> list[dict]:
    """관심종목 요약 데이터. watchlist_items: DB에서 로드한 관심종목 리스트"""
    if watchlist_items is None:
        from data.database import get_watchlist
        watchlist_items = get_watchlist()

    summaries = []
    for w in watchlist_items:
        ticker = w["ticker"]
        name = w["name"]
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            info = stock.info

            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change_pct = ((current - prev) / prev) * 100
            else:
                current = hist["Close"].iloc[-1] if len(hist) > 0 else 0
                change_pct = 0

            summaries.append({
                "ticker": ticker,
                "name": name,
                "price": round(current, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(hist["Volume"].iloc[-1]) if len(hist) > 0 else 0,
                "market_cap": info.get("marketCap", 0),
                "pe_ratio": info.get("trailingPE", None),
            })
        except Exception:
            summaries.append({
                "ticker": ticker, "name": name,
                "price": 0, "change_pct": 0, "volume": 0,
                "market_cap": 0, "pe_ratio": None,
            })
    return summaries


def get_sector_performance() -> list[dict]:
    """섹터별 수익률"""
    performances = []
    for ticker, name in SECTOR_ETFS.items():
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="1mo")
            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                month_ago = hist["Close"].iloc[0]
                change_1m = ((current - month_ago) / month_ago) * 100

                hist_5d = hist.tail(5)
                week_ago = hist_5d["Close"].iloc[0]
                change_1w = ((current - week_ago) / week_ago) * 100

                performances.append({
                    "sector": name,
                    "ticker": ticker,
                    "price": round(current, 2),
                    "change_1w": round(change_1w, 2),
                    "change_1m": round(change_1m, 2),
                })
        except Exception:
            continue
    return sorted(performances, key=lambda x: x["change_1w"], reverse=True)


def get_earnings_calendar(days_ahead: int = 30, watchlist_items: list[dict] = None) -> list[dict]:
    """관심종목 실적발표 일정"""
    if watchlist_items is None:
        from data.database import get_watchlist
        watchlist_items = get_watchlist()

    calendar = []
    for w in watchlist_items:
        ticker, name = w["ticker"], w["name"]
        try:
            stock = yf.Ticker(ticker)
            cal = stock.calendar
            if cal is not None and not cal.empty:
                if "Earnings Date" in cal.index:
                    dates = cal.loc["Earnings Date"]
                    for d in (dates if isinstance(dates, list) else [dates]):
                        if isinstance(d, (datetime, pd.Timestamp)):
                            calendar.append({
                                "ticker": ticker,
                                "name": name,
                                "date": d.strftime("%Y-%m-%d"),
                                "type": "Earnings",
                            })
        except Exception:
            continue
    return sorted(calendar, key=lambda x: x["date"])
