"""주요 일정 페이지"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data.collector import get_earnings_calendar

st.set_page_config(page_title="주요 일정", page_icon="📅", layout="wide")
st.title("📅 주요 일정")

# --- FOMC 및 주요 경제 일정 (2025-2026 수동 입력) ---
st.subheader("🏛️ FOMC 회의 일정")

fomc_dates = [
    {"date": "2026-01-27", "event": "FOMC 회의", "detail": "1월 정례회의 (1/27-28)"},
    {"date": "2026-03-17", "event": "FOMC 회의", "detail": "3월 정례회의 (3/17-18)"},
    {"date": "2026-05-05", "event": "FOMC 회의", "detail": "5월 정례회의 (5/5-6)"},
    {"date": "2026-06-16", "event": "FOMC 회의", "detail": "6월 정례회의 (6/16-17) ⭐ 점도표 발표"},
    {"date": "2026-07-28", "event": "FOMC 회의", "detail": "7월 정례회의 (7/28-29)"},
    {"date": "2026-09-15", "event": "FOMC 회의", "detail": "9월 정례회의 (9/15-16) ⭐ 점도표 발표"},
    {"date": "2026-11-03", "event": "FOMC 회의", "detail": "11월 정례회의 (11/3-4)"},
    {"date": "2026-12-15", "event": "FOMC 회의", "detail": "12월 정례회의 (12/15-16) ⭐ 점도표 발표"},
]

today = datetime.now().strftime("%Y-%m-%d")
upcoming_fomc = [f for f in fomc_dates if f["date"] >= today]

if upcoming_fomc:
    for fomc in upcoming_fomc[:4]:
        days_until = (datetime.strptime(fomc["date"], "%Y-%m-%d") - datetime.now()).days
        badge = "🔴 임박" if days_until <= 7 else "🟡 예정" if days_until <= 30 else "🟢"
        st.markdown(f"{badge} **{fomc['date']}** — {fomc['detail']} (D-{days_until})")
else:
    st.info("올해 예정된 FOMC 회의가 없습니다.")

st.markdown("---")

# --- 주요 경제지표 발표 일정 ---
st.subheader("📊 주요 경제지표")

econ_events = [
    {"type": "CPI", "description": "소비자물가지수 — 인플레이션 핵심 지표. 예상 상회 시 금리 인상 압력"},
    {"type": "고용보고서", "description": "비농업 고용, 실업률 — 매월 첫째 금요일 발표"},
    {"type": "PPI", "description": "생산자물가지수 — CPI 선행 지표"},
    {"type": "GDP", "description": "국내총생산 — 분기별 발표 (속보→잠정→확정)"},
    {"type": "PCE", "description": "개인소비지출 — 연준이 선호하는 인플레이션 지표"},
    {"type": "ISM 제조업", "description": "제조업 구매관리자지수 — 50 기준 경기 확장/수축"},
]

for event in econ_events:
    with st.expander(f"📌 {event['type']}"):
        st.write(event["description"])

st.markdown("---")

# --- 관심종목 실적발표 ---
st.subheader("💰 관심종목 실적발표 일정")

with st.spinner("실적 일정 로딩 중..."):
    earnings = get_earnings_calendar()

if earnings:
    df_earnings = pd.DataFrame(earnings)
    st.dataframe(
        df_earnings.rename(columns={
            "ticker": "종목코드", "name": "종목명",
            "date": "발표일", "type": "유형",
        }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("향후 30일 내 예정된 실적발표가 없거나 데이터를 불러올 수 없습니다.")

st.markdown("---")

# --- 나만의 일정 추가 ---
st.subheader("📝 나만의 일정 메모")
st.text_area(
    "중요 일정 메모",
    placeholder="예: 7/15 TSLA 실적발표 예정, 반도체 재고 이슈 체크 필요...",
    height=150,
    key="custom_memo",
)
st.caption("💡 이 메모는 새로고침 시 사라집니다. 추후 DB 연동 예정")
