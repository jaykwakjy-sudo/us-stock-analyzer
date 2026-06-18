"""매매 일지 & 자기 피드백 시스템"""

import json
import os
from datetime import datetime

JOURNAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "journal_data")
os.makedirs(JOURNAL_DIR, exist_ok=True)


def _journal_path() -> str:
    return os.path.join(JOURNAL_DIR, "trading_journal.json")


def _load_journal() -> list[dict]:
    path = _journal_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_journal(entries: list[dict]):
    with open(_journal_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add_entry(
    ticker: str,
    action: str,
    price: float,
    quantity: int,
    reason: str,
    strategy_type: str = "swing",
    notes: str = "",
) -> dict:
    """매매 기록 추가

    Args:
        ticker: 종목 코드
        action: "buy" 또는 "sell"
        price: 매매 가격
        quantity: 수량
        reason: 매매 근거
        strategy_type: "long_term" 또는 "swing"
        notes: 추가 메모
    """
    entries = _load_journal()
    entry = {
        "id": len(entries) + 1,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ticker": ticker.upper(),
        "action": action,
        "price": price,
        "quantity": quantity,
        "total": round(price * quantity, 2),
        "reason": reason,
        "strategy_type": strategy_type,
        "notes": notes,
        "feedback": None,
        "result_price": None,
        "result_pnl": None,
    }
    entries.append(entry)
    _save_journal(entries)
    return entry


def add_feedback(entry_id: int, feedback: str, result_price: float = None):
    """매매에 대한 자기 피드백 추가"""
    entries = _load_journal()
    for entry in entries:
        if entry["id"] == entry_id:
            entry["feedback"] = feedback
            entry["feedback_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            if result_price:
                entry["result_price"] = result_price
                pnl = (result_price - entry["price"]) / entry["price"] * 100
                if entry["action"] == "sell":
                    pnl = -pnl
                entry["result_pnl"] = round(pnl, 2)
            _save_journal(entries)
            return entry
    return None


def get_journal(ticker: str = None, limit: int = 50) -> list[dict]:
    """매매 일지 조회"""
    entries = _load_journal()
    if ticker:
        entries = [e for e in entries if e["ticker"] == ticker.upper()]
    return entries[-limit:]


def get_daily_analysis():
    """오늘의 시장 분석 기록 조회"""
    path = os.path.join(JOURNAL_DIR, "daily_analysis.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            analyses = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        return analyses.get(today)
    return None


def save_daily_analysis(analysis: dict):
    """오늘의 시장 분석 저장"""
    path = os.path.join(JOURNAL_DIR, "daily_analysis.json")
    analyses = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            analyses = json.load(f)
    today = datetime.now().strftime("%Y-%m-%d")
    analysis["date"] = today
    analyses[today] = analysis
    with open(path, "w", encoding="utf-8") as f:
        json.dump(analyses, f, ensure_ascii=False, indent=2)


def get_performance_stats() -> dict:
    """매매 성과 통계"""
    entries = _load_journal()
    if not entries:
        return {"total_trades": 0}

    completed = [e for e in entries if e.get("result_pnl") is not None]
    wins = [e for e in completed if e["result_pnl"] > 0]
    losses = [e for e in completed if e["result_pnl"] <= 0]

    return {
        "total_trades": len(entries),
        "completed_trades": len(completed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(completed) * 100, 1) if completed else 0,
        "avg_pnl": round(sum(e["result_pnl"] for e in completed) / len(completed), 2) if completed else 0,
        "best_trade": max((e["result_pnl"] for e in completed), default=0),
        "worst_trade": min((e["result_pnl"] for e in completed), default=0),
        "avg_win": round(sum(e["result_pnl"] for e in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(e["result_pnl"] for e in losses) / len(losses), 2) if losses else 0,
    }
