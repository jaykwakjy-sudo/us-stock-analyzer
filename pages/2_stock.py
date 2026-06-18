"""개별주 분석 페이지 (DB 관심종목 연동)"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data.collector import get_stock_data, get_stock_info, get_watchlist_summary
from data.database import get_watchlist, cache_prices
from analysis.technical import add_all_indicators, get_signal_summary

st.set_page_config(page_title="종목 분석", page_icon="🔍", layout="wide")
st.title("🔍 개별주 분석")

# DB에서 관심종목 가져오기
watchlist = get_watchlist()
watchlist_map = {w["ticker"]: w["name"] for w in watchlist}

# --- 관심종목 요약 ---
st.subheader("관심종목 현황")

with st.spinner("데이터 로딩 중..."):
    summaries = []
    for w in watchlist:
        try:
            from data.collector import get_stock_data as gsd
            hist = gsd(w["ticker"], period="5d")
            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change_pct = ((current - prev) / prev) * 100
            else:
                current = hist["Close"].iloc[-1] if len(hist) > 0 else 0
                change_pct = 0
            summaries.append({
                "ticker": w["ticker"],
                "name": w["name"],
                "price": round(current, 2),
                "change_pct": round(change_pct, 2),
                "strategy": w.get("strategy_type", ""),
            })
        except Exception:
            summaries.append({"ticker": w["ticker"], "name": w["name"], "price": 0, "change_pct": 0, "strategy": ""})

if summaries:
    cols = st.columns(min(len(summaries), 7))
    for i, stock in enumerate(summaries[:7]):
        with cols[i]:
            change = stock["change_pct"]
            color = "🟢" if change >= 0 else "🔴"
            st.metric(
                label=f"{color} {stock['ticker']}",
                value=f"${stock['price']:,.2f}",
                delta=f"{change:+.2f}%",
            )

st.markdown("---")

# --- 상세 분석 ---
st.subheader("상세 기술적 분석")

col_select, col_period = st.columns([2, 1])
with col_select:
    all_tickers = [w["ticker"] for w in watchlist]
    custom = st.text_input("직접 입력 (예: AAPL)", "")
    if custom:
        selected_ticker = custom.upper()
    else:
        selected_ticker = st.selectbox("종목 선택", all_tickers)

with col_period:
    period = st.selectbox("분석 기간", ["3mo", "6mo", "1y", "2y"], index=2, key="stock_period")

if selected_ticker:
    with st.spinner(f"{selected_ticker} 분석 중..."):
        df = get_stock_data(selected_ticker, period=period)
        info = get_stock_info(selected_ticker)

        # DB에 주가 캐시 저장
        if not df.empty:
            try:
                cache_prices(selected_ticker, df)
            except Exception:
                pass

    if not df.empty:
        st.markdown(f"### {info['name']} ({selected_ticker})")

        # DB에 목표가/손절가 있으면 표시
        db_info = next((w for w in watchlist if w["ticker"] == selected_ticker), None)

        info_cols = st.columns(6)
        info_cols[0].metric("시가총액", f"${info['market_cap']/1e9:.0f}B" if info['market_cap'] else "N/A")
        info_cols[1].metric("PER", f"{info['pe_ratio']:.1f}" if info['pe_ratio'] else "N/A")
        info_cols[2].metric("Forward PER", f"{info['forward_pe']:.1f}" if info['forward_pe'] else "N/A")
        info_cols[3].metric("배당률", f"{info['dividend_yield']*100:.2f}%" if info['dividend_yield'] else "N/A")
        info_cols[4].metric("Beta", f"{info['beta']:.2f}" if info['beta'] else "N/A")
        info_cols[5].metric("목표가", f"${info['target_price']:.0f}" if info['target_price'] else "N/A")

        # DB에 목표 매수/매도/손절가 있으면 추가 표시
        if db_info and any(db_info.get(k) for k in ["target_buy_price", "target_sell_price", "stop_loss_price"]):
            st.markdown("**나의 전략:**")
            scols = st.columns(4)
            scols[0].markdown(f"전략: **{db_info.get('strategy_type', 'N/A')}**")
            if db_info.get("target_buy_price"):
                scols[1].markdown(f"목표 매수: **${db_info['target_buy_price']}**")
            if db_info.get("target_sell_price"):
                scols[2].markdown(f"목표 매도: **${db_info['target_sell_price']}**")
            if db_info.get("stop_loss_price"):
                scols[3].markdown(f"손절가: **${db_info['stop_loss_price']}**")

        # 기술적 지표 계산
        df_ta = add_all_indicators(df)
        signals = get_signal_summary(df_ta)

        st.markdown(f"#### 종합 시그널: {signals['overall']}")

        if signals["signals"]:
            signal_cols = st.columns(len(signals["signals"]))
            for i, sig in enumerate(signals["signals"]):
                with signal_cols[i]:
                    st.markdown(f"**{sig['name']}**")
                    st.markdown(f"{sig['signal']}")
                    st.markdown(f"`{sig['value']}`")

        # 차트
        fig = make_subplots(
            rows=4, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.5, 0.15, 0.15, 0.2],
            subplot_titles=("가격 & 이동평균", "RSI", "MACD", "거래량"),
        )

        fig.add_trace(go.Candlestick(
            x=df_ta.index, open=df_ta["Open"], high=df_ta["High"],
            low=df_ta["Low"], close=df_ta["Close"], name="Price",
        ), row=1, col=1)

        colors = {"SMA_20": "#FFA726", "SMA_50": "#42A5F5", "SMA_200": "#EF5350"}
        for sma, color in colors.items():
            if sma in df_ta.columns:
                fig.add_trace(go.Scatter(
                    x=df_ta.index, y=df_ta[sma], name=sma,
                    line=dict(color=color, width=1),
                ), row=1, col=1)

        if "BB_Upper" in df_ta.columns:
            fig.add_trace(go.Scatter(
                x=df_ta.index, y=df_ta["BB_Upper"], name="BB Upper",
                line=dict(color="gray", width=1, dash="dot"), showlegend=False,
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=df_ta.index, y=df_ta["BB_Lower"], name="BB Lower",
                line=dict(color="gray", width=1, dash="dot"),
                fill="tonexty", fillcolor="rgba(128,128,128,0.1)", showlegend=False,
            ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df_ta.index, y=df_ta["RSI"], name="RSI",
            line=dict(color="#AB47BC"),
        ), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        fig.add_trace(go.Scatter(
            x=df_ta.index, y=df_ta["MACD"], name="MACD",
            line=dict(color="#26A69A"),
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df_ta.index, y=df_ta["MACD_Signal"], name="Signal",
            line=dict(color="#EF5350"),
        ), row=3, col=1)
        fig.add_trace(go.Bar(
            x=df_ta.index, y=df_ta["MACD_Hist"], name="Histogram",
            marker_color=["#00C853" if v >= 0 else "#FF1744" for v in df_ta["MACD_Hist"].fillna(0)],
        ), row=3, col=1)

        fig.add_trace(go.Bar(
            x=df_ta.index, y=df_ta["Volume"], name="Volume",
            marker_color="rgba(100,100,200,0.5)",
        ), row=4, col=1)
        if "Volume_SMA_20" in df_ta.columns:
            fig.add_trace(go.Scatter(
                x=df_ta.index, y=df_ta["Volume_SMA_20"], name="Vol MA20",
                line=dict(color="#FF9800", width=1),
            ), row=4, col=1)

        fig.update_layout(
            height=900,
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.error(f"{selected_ticker} 데이터를 불러올 수 없습니다.")
