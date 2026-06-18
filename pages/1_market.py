"""증시 분석 페이지"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data.collector import get_market_overview, get_sector_performance, get_stock_data
from config import INDICES

st.set_page_config(page_title="증시 분석", page_icon="📈", layout="wide")
st.title("📈 증시 분석")

# --- 주요 지수 현황 ---
st.subheader("주요 지수 현황")

with st.spinner("지수 데이터 로딩 중..."):
    market = get_market_overview()

if market:
    cols = st.columns(len(market))
    for i, (name, data) in enumerate(market.items()):
        with cols[i]:
            change = data["change_pct"]
            color = "🟢" if change >= 0 else "🔴"
            st.metric(
                label=f"{color} {name}",
                value=f"{data['price']:,.2f}",
                delta=f"{change:+.2f}%",
            )

st.markdown("---")

# --- 지수 차트 ---
st.subheader("지수 차트")
period = st.selectbox("기간", ["1mo", "3mo", "6mo", "1y", "2y"], index=2)

selected_indices = st.multiselect(
    "지수 선택",
    options=list(INDICES.values()),
    default=["S&P 500", "NASDAQ"],
)

if selected_indices:
    ticker_map = {v: k for k, v in INDICES.items()}
    fig = go.Figure()
    for name in selected_indices:
        ticker = ticker_map[name]
        df = get_stock_data(ticker, period=period)
        if not df.empty:
            normalized = (df["Close"] / df["Close"].iloc[0] - 1) * 100
            fig.add_trace(go.Scatter(x=df.index, y=normalized, name=name, mode="lines"))

    fig.update_layout(
        title="지수 수익률 비교 (%)",
        yaxis_title="수익률 (%)",
        height=500,
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# --- 섹터 수익률 ---
st.subheader("섹터별 수익률")

with st.spinner("섹터 데이터 로딩 중..."):
    sectors = get_sector_performance()

if sectors:
    df_sectors = pd.DataFrame(sectors)

    fig_sector = go.Figure()
    fig_sector.add_trace(go.Bar(
        x=df_sectors["sector"],
        y=df_sectors["change_1w"],
        name="1주 수익률",
        marker_color=["#00C853" if x >= 0 else "#FF1744" for x in df_sectors["change_1w"]],
    ))
    fig_sector.update_layout(title="섹터별 1주 수익률 (%)", height=400)
    st.plotly_chart(fig_sector, use_container_width=True)

    st.dataframe(
        df_sectors[["sector", "ticker", "price", "change_1w", "change_1m"]].rename(columns={
            "sector": "섹터", "ticker": "ETF", "price": "가격",
            "change_1w": "1주 (%)", "change_1m": "1개월 (%)",
        }),
        use_container_width=True,
        hide_index=True,
    )
