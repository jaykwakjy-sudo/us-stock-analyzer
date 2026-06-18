"""기술적 분석 모듈"""

import pandas as pd
import ta
from config import TECHNICAL


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """모든 기술적 지표 추가"""
    df = df.copy()

    # 이동평균선 (SMA)
    for period in TECHNICAL["sma_periods"]:
        df[f"SMA_{period}"] = ta.trend.sma_indicator(df["Close"], window=period)

    # RSI
    df["RSI"] = ta.momentum.rsi(df["Close"], window=TECHNICAL["rsi_period"])

    # MACD
    macd = ta.trend.MACD(
        df["Close"],
        window_slow=TECHNICAL["macd_slow"],
        window_fast=TECHNICAL["macd_fast"],
        window_sign=TECHNICAL["macd_signal"],
    )
    df["MACD"] = macd.macd()
    df["MACD_Signal"] = macd.macd_signal()
    df["MACD_Hist"] = macd.macd_diff()

    # 볼린저 밴드
    bb = ta.volatility.BollingerBands(
        df["Close"],
        window=TECHNICAL["bollinger_period"],
        window_dev=TECHNICAL["bollinger_std"],
    )
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Middle"] = bb.bollinger_mavg()
    df["BB_Lower"] = bb.bollinger_lband()

    # 거래량 이동평균
    df["Volume_SMA_20"] = ta.trend.sma_indicator(df["Volume"], window=20)

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(df["High"], df["Low"], df["Close"])
    df["Stoch_K"] = stoch.stoch()
    df["Stoch_D"] = stoch.stoch_signal()

    return df


def get_signal_summary(df: pd.DataFrame) -> dict:
    """현재 시그널 종합 판단"""
    if df.empty:
        return {"overall": "데이터 없음", "signals": []}

    latest = df.iloc[-1]
    signals = []

    # RSI 판단
    rsi = latest.get("RSI")
    if rsi is not None:
        if rsi > 70:
            signals.append({"name": "RSI", "value": round(rsi, 1), "signal": "과매수 ⚠️", "direction": "sell"})
        elif rsi < 30:
            signals.append({"name": "RSI", "value": round(rsi, 1), "signal": "과매도 🔥", "direction": "buy"})
        else:
            signals.append({"name": "RSI", "value": round(rsi, 1), "signal": "중립", "direction": "neutral"})

    # 이동평균 정배열/역배열
    sma20 = latest.get("SMA_20")
    sma50 = latest.get("SMA_50")
    sma200 = latest.get("SMA_200")
    price = latest["Close"]

    if all(v is not None and pd.notna(v) for v in [sma20, sma50, sma200]):
        if price > sma20 > sma50 > sma200:
            signals.append({"name": "이동평균", "value": "정배열", "signal": "강한 상승 추세 📈", "direction": "buy"})
        elif price < sma20 < sma50 < sma200:
            signals.append({"name": "이동평균", "value": "역배열", "signal": "강한 하락 추세 📉", "direction": "sell"})
        elif price > sma200:
            signals.append({"name": "이동평균", "value": "200일선 위", "signal": "장기 상승 추세", "direction": "buy"})
        else:
            signals.append({"name": "이동평균", "value": "200일선 아래", "signal": "장기 하락 추세", "direction": "sell"})

    # MACD 판단
    macd_hist = latest.get("MACD_Hist")
    if macd_hist is not None and pd.notna(macd_hist):
        prev_hist = df["MACD_Hist"].iloc[-2] if len(df) >= 2 else 0
        if macd_hist > 0 and prev_hist <= 0:
            signals.append({"name": "MACD", "value": round(macd_hist, 3), "signal": "골든크로스 🔥", "direction": "buy"})
        elif macd_hist < 0 and prev_hist >= 0:
            signals.append({"name": "MACD", "value": round(macd_hist, 3), "signal": "데드크로스 ⚠️", "direction": "sell"})
        elif macd_hist > 0:
            signals.append({"name": "MACD", "value": round(macd_hist, 3), "signal": "상승 모멘텀", "direction": "buy"})
        else:
            signals.append({"name": "MACD", "value": round(macd_hist, 3), "signal": "하락 모멘텀", "direction": "sell"})

    # 볼린저 밴드 판단
    bb_upper = latest.get("BB_Upper")
    bb_lower = latest.get("BB_Lower")
    if bb_upper is not None and bb_lower is not None:
        if pd.notna(bb_upper) and pd.notna(bb_lower):
            if price >= bb_upper:
                signals.append({"name": "볼린저", "value": "상단 돌파", "signal": "과매수 구간", "direction": "sell"})
            elif price <= bb_lower:
                signals.append({"name": "볼린저", "value": "하단 돌파", "signal": "과매도 구간", "direction": "buy"})
            else:
                bb_pct = (price - bb_lower) / (bb_upper - bb_lower) * 100
                signals.append({"name": "볼린저", "value": f"{bb_pct:.0f}%", "signal": "밴드 내", "direction": "neutral"})

    # 거래량 판단
    vol = latest.get("Volume")
    vol_sma = latest.get("Volume_SMA_20")
    if vol is not None and vol_sma is not None and vol_sma > 0:
        vol_ratio = vol / vol_sma
        if vol_ratio > 2:
            signals.append({"name": "거래량", "value": f"{vol_ratio:.1f}x", "signal": "폭발적 거래량 🔥", "direction": "neutral"})
        elif vol_ratio > 1.5:
            signals.append({"name": "거래량", "value": f"{vol_ratio:.1f}x", "signal": "높은 거래량", "direction": "neutral"})

    # 종합 판단
    buy_count = sum(1 for s in signals if s["direction"] == "buy")
    sell_count = sum(1 for s in signals if s["direction"] == "sell")

    if buy_count > sell_count + 1:
        overall = "매수 우위 📈"
    elif sell_count > buy_count + 1:
        overall = "매도 우위 📉"
    else:
        overall = "중립/관망 ⏸️"

    return {"overall": overall, "signals": signals, "buy_count": buy_count, "sell_count": sell_count}
