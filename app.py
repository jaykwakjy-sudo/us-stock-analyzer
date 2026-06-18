"""US Stock Analyzer - 메인 대시보드"""

import streamlit as st

st.set_page_config(
    page_title="US Stock Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 US Stock Analyzer")
st.caption("미국주식 분석 & 매매전략 대시보드")

st.markdown("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📈 증시 분석")
    st.markdown("주요 지수, 섹터 수익률, 시장 전반 분석")
    st.page_link("pages/1_market.py", label="증시 분석 바로가기", icon="📈")

with col2:
    st.markdown("### 🔍 개별주 분석")
    st.markdown("관심종목 상세 차트, 기술적 분석, 시그널")
    st.page_link("pages/2_stock.py", label="종목 분석 바로가기", icon="🔍")

with col3:
    st.markdown("### 📅 주요 일정")
    st.markdown("FOMC, 실적발표, 경제지표 일정")
    st.page_link("pages/3_calendar.py", label="일정 바로가기", icon="📅")

st.markdown("---")

col4, col5 = st.columns(2)

with col4:
    st.markdown("### 📝 매매 일지")
    st.markdown("매매 기록, 자기 피드백, 성과 분석")
    st.page_link("pages/4_journal.py", label="매매 일지 바로가기", icon="📝")

with col5:
    st.markdown("### 🎯 전략 설정")
    st.markdown("포지션 비율, 손절/익절 기준, 관심종목 관리")
    st.page_link("pages/5_settings.py", label="전략 설정 바로가기", icon="🎯")

st.markdown("---")
st.caption("💡 토스 증권 API 출시 후 자동매매 모듈 연동 예정")
