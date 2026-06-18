"""개별주 분석 페이지 — 새 분석 엔진 연동 (기술적 + 펀더멘탈)"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data.collector import get_stock_data, get_stock_info
from data.database import get_watchlist, cache_prices, get_setting
from analysis.engine import run_analysis_from_db

st.set_page_config(page_title="종목 분석", page_icon="🔍", layout="wide")
st.title("🔍 개별주 분석")

watchlist = get_watchlist()
watchlist_map = {w["ticker"]: w["name"] for w in watchlist}

# --- 관심종목 요약 ---
st.subheader("관심종목 현황")

with st.spinner("데이터 로딩 중..."):
    summaries = []
    for w in watchlist:
        try:
            hist = get_stock_data(w["ticker"], period="5d")
            if len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change_pct = ((current - prev) / prev) * 100
            else:
                current = hist["Close"].iloc[-1] if len(hist) > 0 else 0
                change_pct = 0
            summaries.append({
                "ticker": w["ticker"], "name": w["name"],
                "price": round(current, 2), "change_pct": round(change_pct, 2),
                "strategy": w.get("strategy_type", ""),
            })
        except Exception:
            summaries.append({"ticker": w["ticker"], "name": w["name"],
                              "price": 0, "change_pct": 0, "strategy": ""})

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
st.subheader("종합 분석")

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
    with st.spinner(f"{selected_ticker} 종합 분석 중..."):
        df = get_stock_data(selected_ticker, period=period)
        info = get_stock_info(selected_ticker)

        if not df.empty:
            try:
                cache_prices(selected_ticker, df)
            except Exception:
                pass

    if not df.empty:
        st.markdown(f"### {info['name']} ({selected_ticker})")

        db_info = next((w for w in watchlist if w["ticker"] == selected_ticker), None)

        info_cols = st.columns(6)
        info_cols[0].metric("시가총액", f"${info['market_cap']/1e9:.0f}B" if info['market_cap'] else "N/A")
        info_cols[1].metric("PER", f"{info['pe_ratio']:.1f}" if info['pe_ratio'] else "N/A")
        info_cols[2].metric("Forward PER", f"{info['forward_pe']:.1f}" if info['forward_pe'] else "N/A")
        info_cols[3].metric("배당률", f"{info['dividend_yield']*100:.2f}%" if info['dividend_yield'] else "N/A")
        info_cols[4].metric("Beta", f"{info['beta']:.2f}" if info['beta'] else "N/A")
        info_cols[5].metric("목표가", f"${info['target_price']:.0f}" if info['target_price'] else "N/A")

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

        # ─── 새 분석 엔진 실행 ───
        analysis = run_analysis_from_db(selected_ticker, df, get_setting_fn=get_setting)
        result = analysis["result"]
        tech_df = analysis["technical"]["df"]

        # ─── 종합 판단 헤더 ───
        action_colors = {
            "STRONG_BUY": "#00E676", "BUY": "#69F0AE",
            "HOLD": "#FFD54F",
            "SELL": "#FF8A80", "STRONG_SELL": "#FF1744",
        }
        action = result["action"]
        action_color = action_colors.get(action, "#FFD54F")

        hdr1, hdr2, hdr3, hdr4 = st.columns(4)
        hdr1.markdown(
            f"<div style='text-align:center; padding:12px; background:{action_color}22; "
            f"border:2px solid {action_color}; border-radius:8px;'>"
            f"<h2 style='margin:0; color:{action_color};'>{result['action_kr']}</h2>"
            f"<p style='margin:4px 0 0; font-size:0.8em;'>종합 점수 {result['final_score']:.0f}/100</p></div>",
            unsafe_allow_html=True)
        hdr2.metric("기술 점수", f"{result['technical_score']:.0f}")
        hdr3.metric("펀더멘탈 점수", f"{result['fundamental_score']:.0f}")
        hdr4.metric("신뢰도", f"{result['confidence']:.0%}")

        if result.get("conflict_ratio", 0) > 0.3:
            st.warning(f"시그널 충돌 비율: {result['conflict_ratio']:.0%} — 신중한 판단 필요")

        st.caption(result.get("reasoning", ""))

        # ─── 시그널 상세 ───
        with st.expander("기술적 시그널 상세", expanded=True):
            tech_signals = analysis["technical"]["signals"]
            if tech_signals:
                categories = {}
                for s in tech_signals:
                    cat = {"trend": "추세", "momentum": "모멘텀",
                           "volatility": "변동성", "volume": "거래량",
                           "pattern": "패턴"}.get(
                        next((cls.category for cls in __import__("analysis.indicators.trend", fromlist=["ALL_INDICATORS"]).ALL_INDICATORS if cls.name == s["name"]), "기타"), "기타")
                    from analysis.scoring import CATEGORY_MAP
                    cat_key = CATEGORY_MAP.get(s["name"], "other")
                    cat_label = {"trend": "추세", "momentum": "모멘텀",
                                 "volatility": "변동성", "volume": "거래량",
                                 "pattern": "패턴"}.get(cat_key, "기타")
                    categories.setdefault(cat_label, []).append(s)

                for cat_name, sigs in categories.items():
                    st.markdown(f"**{cat_name}**")
                    sig_cols = st.columns(min(len(sigs), 4))
                    for i, sig in enumerate(sigs):
                        with sig_cols[i % len(sig_cols)]:
                            dir_icon = {"buy": "🟢", "sell": "🔴", "neutral": "⚪"}.get(sig["direction"], "⚪")
                            score_bar = "█" * (sig["score"] // 10) + "░" * (10 - sig["score"] // 10)
                            st.markdown(f"{dir_icon} **{sig['name']}**")
                            st.markdown(f"{sig['signal']}")
                            st.markdown(f"`{sig['value']}` | 점수 {sig['score']}")
                            st.caption(f"{score_bar}")

        fund = analysis.get("fundamental")
        if fund:
            with st.expander("펀더멘탈 분석 상세"):
                f1, f2 = st.columns(2)
                with f1:
                    st.markdown(f"**종합 등급: {fund['grade']}** (점수 {fund['overall_score']:.0f})")
                    for section in ["valuation", "growth", "quality", "earnings"]:
                        data = fund.get(section, {})
                        label = {"valuation": "밸류에이션", "growth": "성장성",
                                 "quality": "재무건전성", "earnings": "어닝/컨센서스"}.get(section, section)
                        st.markdown(f"- {label}: **{data.get('score', 'N/A')}점**")
                        for sig_text in data.get("signals", []):
                            st.caption(f"  {sig_text}")
                with f2:
                    fund_signals = fund.get("signals", [])
                    for fs in fund_signals:
                        dir_icon = {"buy": "🟢", "sell": "🔴", "neutral": "⚪"}.get(fs["direction"], "⚪")
                        st.markdown(f"{dir_icon} **{fs['name']}**: {fs['signal']}")

        # ─── 차트 ───
        fig = make_subplots(
            rows=4, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.5, 0.15, 0.15, 0.2],
            subplot_titles=("가격 & 이동평균 & 볼린저", "RSI", "MACD", "거래량 & OBV"),
        )

        fig.add_trace(go.Candlestick(
            x=tech_df.index, open=tech_df["Open"], high=tech_df["High"],
            low=tech_df["Low"], close=tech_df["Close"], name="Price",
        ), row=1, col=1)

        sma_colors = {"SMA_20": "#FFA726", "SMA_50": "#42A5F5",
                       "SMA_100": "#66BB6A", "SMA_200": "#EF5350"}
        for sma, color in sma_colors.items():
            if sma in tech_df.columns:
                fig.add_trace(go.Scatter(
                    x=tech_df.index, y=tech_df[sma], name=sma,
                    line=dict(color=color, width=1),
                ), row=1, col=1)

        for ema_col in [c for c in tech_df.columns if c.startswith("EMA_")]:
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df[ema_col], name=ema_col,
                line=dict(width=1, dash="dot"), visible="legendonly",
            ), row=1, col=1)

        if "BB_Upper" in tech_df.columns:
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["BB_Upper"], name="BB Upper",
                line=dict(color="gray", width=1, dash="dot"), showlegend=False,
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["BB_Lower"], name="BB Lower",
                line=dict(color="gray", width=1, dash="dot"),
                fill="tonexty", fillcolor="rgba(128,128,128,0.1)", showlegend=False,
            ), row=1, col=1)

        if "Ichi_SpanA" in tech_df.columns:
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["Ichi_SpanA"], name="Ichimoku A",
                line=dict(color="rgba(0,200,100,0.3)", width=0),
                visible="legendonly",
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["Ichi_SpanB"], name="Ichimoku B",
                line=dict(color="rgba(200,0,0,0.3)", width=0),
                fill="tonexty", fillcolor="rgba(100,100,255,0.05)",
                visible="legendonly",
            ), row=1, col=1)

        if "RSI" in tech_df.columns:
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["RSI"], name="RSI",
                line=dict(color="#AB47BC"),
            ), row=2, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        if "MACD" in tech_df.columns:
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["MACD"], name="MACD",
                line=dict(color="#26A69A"),
            ), row=3, col=1)
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["MACD_Signal"], name="Signal",
                line=dict(color="#EF5350"),
            ), row=3, col=1)
            fig.add_trace(go.Bar(
                x=tech_df.index, y=tech_df["MACD_Hist"], name="Histogram",
                marker_color=["#00C853" if v >= 0 else "#FF1744"
                              for v in tech_df["MACD_Hist"].fillna(0)],
            ), row=3, col=1)

        fig.add_trace(go.Bar(
            x=tech_df.index, y=tech_df["Volume"], name="Volume",
            marker_color="rgba(100,100,200,0.5)",
        ), row=4, col=1)

        if "Vol_SMA" in tech_df.columns:
            fig.add_trace(go.Scatter(
                x=tech_df.index, y=tech_df["Vol_SMA"], name="Vol MA",
                line=dict(color="#FF9800", width=1),
            ), row=4, col=1)

        fig.update_layout(
            height=950,
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.error(f"{selected_ticker} 데이터를 불러올 수 없습니다.")
