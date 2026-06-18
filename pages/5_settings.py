"""전략 설정 페이지 (Supabase DB 연동)"""

import streamlit as st
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data.database import (
    get_watchlist, add_to_watchlist, remove_from_watchlist,
    get_setting, save_setting,
)

st.set_page_config(page_title="전략 설정", page_icon="🎯", layout="wide")
st.title("🎯 전략 설정")

# --- 포지션 전략 ---
st.subheader("포지션 전략")

position = get_setting("position_ratio") or {"long_term": 0.6, "swing": 0.4}
risk = get_setting("risk_management") or {
    "stop_loss_pct": -7, "take_profit_pct": 15,
    "swing_stop_loss_pct": -5, "swing_take_profit_pct": 10,
    "max_single_stock": 0.25,
}

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 포지션 비중")
    long_ratio = st.slider("장기투자 비중 (%)", 0, 100, int(position["long_term"] * 100))
    swing_ratio = 100 - long_ratio
    st.markdown(f"스윙 비중: **{swing_ratio}%**")
    max_single = st.slider("단일 종목 최대 비중 (%)", 5, 50, int(risk["max_single_stock"] * 100))

with col2:
    st.markdown("### 손절/익절 기준")
    stop_loss = st.number_input("장기 손절 (%)", value=float(risk["stop_loss_pct"]), step=1.0)
    take_profit = st.number_input("장기 익절 (%)", value=float(risk["take_profit_pct"]), step=1.0)
    swing_stop = st.number_input("스윙 손절 (%)", value=float(risk["swing_stop_loss_pct"]), step=1.0)
    swing_profit = st.number_input("스윙 익절 (%)", value=float(risk["swing_take_profit_pct"]), step=1.0)

if st.button("전략 설정 저장", type="primary"):
    save_setting("position_ratio", {"long_term": long_ratio / 100, "swing": swing_ratio / 100})
    save_setting("risk_management", {
        "stop_loss_pct": stop_loss, "take_profit_pct": take_profit,
        "swing_stop_loss_pct": swing_stop, "swing_take_profit_pct": swing_profit,
        "max_single_stock": max_single / 100,
    })
    st.success("전략 설정이 저장되었습니다!")

st.markdown("---")

# --- 관심종목 관리 ---
st.subheader("관심종목 관리")

watchlist = get_watchlist()

if watchlist:
    st.markdown("**현재 관심종목:**")
    for w in watchlist:
        col_t, col_n, col_s, col_del = st.columns([1, 2, 1, 1])
        col_t.markdown(f"**{w['ticker']}**")
        col_n.markdown(w["name"])
        col_s.markdown(f"`{w.get('strategy_type', 'swing')}`")
        if col_del.button("삭제", key=f"del_{w['ticker']}"):
            remove_from_watchlist(w["ticker"])
            st.rerun()

st.markdown("---")

st.markdown("**종목 추가:**")
col_a1, col_a2, col_a3 = st.columns(3)
with col_a1:
    new_ticker = st.text_input("종목코드", placeholder="AAPL")
with col_a2:
    new_name = st.text_input("종목명", placeholder="Apple")
with col_a3:
    new_strategy = st.selectbox("전략", ["swing", "long_term"], key="new_strat")

col_b1, col_b2, col_b3 = st.columns(3)
with col_b1:
    buy_target = st.number_input("목표 매수가 ($)", min_value=0.0, step=0.01, key="new_buy")
with col_b2:
    sell_target = st.number_input("목표 매도가 ($)", min_value=0.0, step=0.01, key="new_sell")
with col_b3:
    sl_price = st.number_input("손절가 ($)", min_value=0.0, step=0.01, key="new_sl")

new_notes = st.text_input("메모", "", key="new_notes")

if st.button("종목 추가", type="primary"):
    if new_ticker and new_name:
        add_to_watchlist(
            new_ticker, new_name, new_strategy,
            target_buy=buy_target if buy_target > 0 else None,
            target_sell=sell_target if sell_target > 0 else None,
            stop_loss=sl_price if sl_price > 0 else None,
            notes=new_notes,
        )
        st.success(f"{new_ticker} 추가 완료!")
        st.rerun()
    else:
        st.warning("종목코드와 종목명을 입력해주세요.")

st.markdown("---")

# --- 로드맵 ---
st.subheader("🗺️ 개발 로드맵")

phases = {
    "Phase 1 ✅": [
        "야후파이낸스 데이터 수집",
        "기술적 분석 (이동평균, RSI, MACD, 볼린저)",
        "관심종목 대시보드",
        "매매 일지 & 피드백 시스템",
        "Supabase DB 연동",
        "웹 배포 (Streamlit Cloud)",
    ],
    "Phase 2 🔜": [
        "실시간 뉴스 피드 연동",
        "알림 시스템 (이메일/텔레그램)",
        "백테스트 엔진",
        "포트폴리오 시뮬레이션",
    ],
    "Phase 3 🚀": [
        "토스 증권 API 연동",
        "자동 매매 시스템",
        "실시간 포지션 관리",
        "리스크 관리 자동화",
    ],
}

for phase, items in phases.items():
    with st.expander(phase, expanded=phase.startswith("Phase 1")):
        for item in items:
            st.markdown(f"- {item}")
