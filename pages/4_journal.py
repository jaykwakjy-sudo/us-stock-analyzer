"""매매 일지 & 자기 피드백 페이지 (Supabase DB 연동)"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data.database import add_trade, add_trade_feedback, get_trades, get_trade_stats, get_watchlist

st.set_page_config(page_title="매매 일지", page_icon="📝", layout="wide")
st.title("📝 매매 일지 & 자기 피드백")

watchlist = get_watchlist()
ticker_options = [w["ticker"] for w in watchlist]

tab1, tab2, tab3 = st.tabs(["매매 기록", "피드백 추가", "성과 분석"])

# --- 매매 기록 탭 ---
with tab1:
    st.subheader("새 매매 기록")

    col1, col2 = st.columns(2)
    with col1:
        ticker = st.selectbox("종목", ticker_options + ["직접입력"])
        if ticker == "직접입력":
            ticker = st.text_input("종목코드 입력").upper()
        action = st.selectbox("매매 유형", ["buy", "sell"])
        price = st.number_input("가격 ($)", min_value=0.01, step=0.01)
        quantity = st.number_input("수량", min_value=1, step=1)

    with col2:
        strategy_type = st.selectbox("전략", ["swing", "long_term"])
        reason = st.text_area("매매 근거", placeholder="왜 이 시점에 매수/매도하는지 기록")
        notes = st.text_input("추가 메모", "")

    if st.button("기록 저장", type="primary"):
        if ticker and price > 0 and reason:
            entry = add_trade(ticker, action, price, quantity, reason, strategy_type, notes)
            st.success(f"매매 기록 저장 완료!")
        else:
            st.warning("종목, 가격, 매매 근거를 모두 입력해주세요.")

    st.markdown("---")
    st.subheader("매매 기록 조회")

    filter_ticker = st.selectbox("종목 필터", ["전체"] + ticker_options, key="filter")
    entries = get_trades(ticker=None if filter_ticker == "전체" else filter_ticker)

    if entries:
        df = pd.DataFrame(entries)
        display_cols = ["id", "created_at", "ticker", "action", "price", "quantity", "total", "strategy_type", "reason"]
        available_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[available_cols].rename(columns={
                "id": "#", "created_at": "날짜", "ticker": "종목", "action": "매매",
                "price": "가격", "quantity": "수량", "total": "총액",
                "strategy_type": "전략", "reason": "매매근거",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("아직 매매 기록이 없습니다.")

# --- 피드백 탭 ---
with tab2:
    st.subheader("매매 피드백 추가")
    st.markdown("과거 매매를 돌아보고 배운 점을 기록하세요.")

    entries = get_trades()
    no_feedback = [e for e in entries if not e.get("feedback")]

    if no_feedback:
        entry_options = {
            f"#{e['id']} {e['created_at'][:10]} {e['ticker']} {e['action']} ${e['price']}": e["id"]
            for e in no_feedback
        }
        selected = st.selectbox("피드백할 매매 선택", list(entry_options.keys()))
        entry_id = entry_options[selected]

        selected_entry = next(e for e in no_feedback if e["id"] == entry_id)
        st.markdown(f"**매매근거:** {selected_entry['reason']}")

        result_price = st.number_input("현재/청산 가격 ($)", min_value=0.01, step=0.01)
        feedback = st.text_area(
            "자기 피드백",
            placeholder="이 매매에서 배운 점은? 다시 한다면 어떻게 할 것인가?",
        )

        if st.button("피드백 저장", type="primary"):
            if feedback:
                result = add_trade_feedback(entry_id, feedback, result_price if result_price > 0 else None)
                if result:
                    pnl = result.get("result_pnl")
                    if pnl is not None:
                        color = "+" if pnl >= 0 else ""
                        st.success(f"피드백 저장! 수익률: {color}{pnl:.2f}%")
                    else:
                        st.success("피드백 저장 완료!")
            else:
                st.warning("피드백을 입력해주세요.")
    else:
        st.info("피드백할 매매 기록이 없습니다.")

# --- 성과 분석 탭 ---
with tab3:
    st.subheader("매매 성과 분석")

    stats = get_trade_stats()

    if stats["total_trades"] > 0:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("총 매매 횟수", stats["total_trades"])
        col2.metric("완료된 매매", stats["completed_trades"])
        col3.metric("승률", f"{stats['win_rate']}%")
        col4.metric("평균 수익률", f"{stats['avg_pnl']:+.2f}%")

        if stats["completed_trades"] > 0:
            col5, col6, col7, col8 = st.columns(4)
            col5.metric("승리", stats["win_count"])
            col6.metric("패배", stats["loss_count"])
            col7.metric("최고 수익", f"{stats['best_trade']:+.2f}%")
            col8.metric("최대 손실", f"{stats['worst_trade']:+.2f}%")

            st.markdown("---")
            st.markdown("### 학습 포인트")
            st.markdown("""
            - **승률이 50% 미만이면**: 진입 타이밍과 매매 근거를 재점검
            - **평균 손실 > 평균 수익이면**: 손절 기준을 더 엄격하게 설정
            - **최대 손실이 -10% 이상이면**: 포지션 크기 조절 필요
            """)
    else:
        st.info("아직 매매 기록이 없습니다. 매매 기록 탭에서 첫 기록을 시작하세요!")
