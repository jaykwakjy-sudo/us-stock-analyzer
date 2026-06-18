"""Supabase 데이터베이스 연결 및 CRUD 모듈"""

import os
import streamlit as st
from supabase import create_client, Client
from datetime import datetime, date
import pandas as pd


def get_client() -> Client:
    """Supabase 클라이언트 (싱글턴)"""
    url = st.secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        st.error("Supabase 설정이 없습니다. .streamlit/secrets.toml을 확인하세요.")
        st.stop()
    return create_client(url, key)


# ─── 매매 일지 ─────────────────────────────────────────

def add_trade(ticker: str, action: str, price: float, quantity: int,
              reason: str, strategy_type: str = "swing", notes: str = "") -> dict:
    db = get_client()
    data = {
        "ticker": ticker.upper(),
        "action": action,
        "price": price,
        "quantity": quantity,
        "reason": reason,
        "strategy_type": strategy_type,
        "notes": notes,
    }
    result = db.table("trading_journal").insert(data).execute()
    return result.data[0] if result.data else {}


def add_trade_feedback(trade_id: int, feedback: str, result_price: float = None) -> dict:
    db = get_client()
    update = {
        "feedback": feedback,
        "feedback_date": datetime.now().isoformat(),
    }
    if result_price:
        trade = db.table("trading_journal").select("price, action").eq("id", trade_id).single().execute()
        if trade.data:
            pnl = (result_price - trade.data["price"]) / trade.data["price"] * 100
            if trade.data["action"] == "sell":
                pnl = -pnl
            update["result_price"] = result_price
            update["result_pnl"] = round(pnl, 2)
    result = db.table("trading_journal").update(update).eq("id", trade_id).execute()
    return result.data[0] if result.data else {}


def get_trades(ticker: str = None, limit: int = 50) -> list[dict]:
    db = get_client()
    query = db.table("trading_journal").select("*").order("created_at", desc=True).limit(limit)
    if ticker:
        query = query.eq("ticker", ticker.upper())
    result = query.execute()
    return result.data or []


def get_trade_stats() -> dict:
    db = get_client()
    all_trades = db.table("trading_journal").select("*").execute().data or []
    if not all_trades:
        return {"total_trades": 0}

    completed = [t for t in all_trades if t.get("result_pnl") is not None]
    wins = [t for t in completed if t["result_pnl"] > 0]
    losses = [t for t in completed if t["result_pnl"] <= 0]

    return {
        "total_trades": len(all_trades),
        "completed_trades": len(completed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(completed) * 100, 1) if completed else 0,
        "avg_pnl": round(sum(t["result_pnl"] for t in completed) / len(completed), 2) if completed else 0,
        "best_trade": max((t["result_pnl"] for t in completed), default=0),
        "worst_trade": min((t["result_pnl"] for t in completed), default=0),
        "avg_win": round(sum(t["result_pnl"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["result_pnl"] for t in losses) / len(losses), 2) if losses else 0,
    }


# ─── 일별 분석 ─────────────────────────────────────────

def save_daily_analysis(analysis: dict):
    db = get_client()
    today = date.today().isoformat()
    data = {
        "date": today,
        "market_summary": analysis.get("market_summary"),
        "sector_leaders": analysis.get("sector_leaders", []),
        "sector_laggards": analysis.get("sector_laggards", []),
        "vix": analysis.get("vix"),
        "memo": analysis.get("memo", ""),
    }
    db.table("daily_analysis").upsert(data, on_conflict="date").execute()


def get_daily_analysis(target_date: str = None):
    db = get_client()
    d = target_date or date.today().isoformat()
    result = db.table("daily_analysis").select("*").eq("date", d).maybe_single().execute()
    return result.data


# ─── 주가 캐시 ─────────────────────────────────────────

def cache_prices(ticker: str, df: pd.DataFrame):
    """주가 데이터를 DB에 캐시"""
    db = get_client()
    rows = []
    for idx, row in df.iterrows():
        rows.append({
            "ticker": ticker.upper(),
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })
    if rows:
        db.table("price_cache").upsert(rows, on_conflict="ticker,date").execute()


def get_cached_prices(ticker: str, start_date: str = None) -> pd.DataFrame:
    db = get_client()
    query = db.table("price_cache").select("*").eq("ticker", ticker.upper()).order("date")
    if start_date:
        query = query.gte("date", start_date)
    result = query.execute()
    if result.data:
        df = pd.DataFrame(result.data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.columns = [c.capitalize() if c in ("open","high","low","close","volume") else c for c in df.columns]
        return df
    return pd.DataFrame()


# ─── 관심종목 ──────────────────────────────────────────

def get_watchlist() -> list[dict]:
    db = get_client()
    result = db.table("watchlist").select("*").order("added_at").execute()
    return result.data or []


def add_to_watchlist(ticker: str, name: str, strategy_type: str = "swing",
                     target_buy: float = None, target_sell: float = None,
                     stop_loss: float = None, notes: str = "") -> dict:
    db = get_client()
    data = {
        "ticker": ticker.upper(),
        "name": name,
        "strategy_type": strategy_type,
        "target_buy_price": target_buy,
        "target_sell_price": target_sell,
        "stop_loss_price": stop_loss,
        "notes": notes,
    }
    result = db.table("watchlist").upsert(data, on_conflict="ticker").execute()
    return result.data[0] if result.data else {}


def remove_from_watchlist(ticker: str):
    db = get_client()
    db.table("watchlist").delete().eq("ticker", ticker.upper()).execute()


# ─── 일정 ─────────────────────────────────────────────

def add_calendar_event(event_date: str, event_type: str, title: str,
                       description: str = "", ticker: str = None,
                       importance: str = "medium") -> dict:
    db = get_client()
    data = {
        "date": event_date,
        "event_type": event_type,
        "title": title,
        "description": description,
        "ticker": ticker,
        "importance": importance,
    }
    result = db.table("calendar_events").insert(data).execute()
    return result.data[0] if result.data else {}


def get_upcoming_events(days_ahead: int = 30) -> list[dict]:
    db = get_client()
    today = date.today().isoformat()
    result = (db.table("calendar_events")
              .select("*")
              .gte("date", today)
              .order("date")
              .limit(50)
              .execute())
    return result.data or []


# ─── 설정 ─────────────────────────────────────────────

def get_setting(key: str):
    db = get_client()
    result = db.table("settings").select("value").eq("key", key).maybe_single().execute()
    return result.data["value"] if result.data else None


def save_setting(key: str, value: dict):
    db = get_client()
    db.table("settings").upsert({"key": key, "value": value}, on_conflict="key").execute()
