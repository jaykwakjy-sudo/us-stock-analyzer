"""변동성 지표: Bollinger Bands, ATR, Keltner Channel"""

import pandas as pd
import ta
from .base import BaseIndicator


class BollingerBandsIndicator(BaseIndicator):
    category = "volatility"
    name = "Bollinger Bands"
    description = "볼린저 밴드 - 변동성 기반 과매수/과매도 및 스퀴즈"

    @classmethod
    def default_params(cls):
        return {"period": 20, "std_dev": 2}

    def compute(self, df):
        df = df.copy()
        bb = ta.volatility.BollingerBands(
            df["Close"],
            window=self.params.get("period", 20),
            window_dev=self.params.get("std_dev", 2))
        df["BB_Upper"] = bb.bollinger_hband()
        df["BB_Middle"] = bb.bollinger_mavg()
        df["BB_Lower"] = bb.bollinger_lband()
        df["BB_PctB"] = bb.bollinger_pband()
        df["BB_Width"] = bb.bollinger_wband()
        return df

    def get_signal(self, df):
        price = df["Close"].iloc[-1]
        upper = self._safe_latest(df, "BB_Upper")
        lower = self._safe_latest(df, "BB_Lower")
        pct_b = self._safe_latest(df, "BB_PctB")
        width = self._safe_latest(df, "BB_Width")

        if upper is None or lower is None:
            return {"name": "Bollinger", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        squeeze = False
        if width is not None and "BB_Width" in df.columns:
            avg_width = df["BB_Width"].tail(50).mean()
            if pd.notna(avg_width) and avg_width > 0:
                squeeze = width < avg_width * 0.5

        if price >= upper:
            signal = "상단 돌파 (스퀴즈 후 돌파)" if squeeze else "상단 돌파 (과매수)"
            direction = "buy" if squeeze else "sell"
            score = 75 if squeeze else 20
            return {"name": "Bollinger", "value": f"%B={round(pct_b * 100, 0) if pct_b else '?'}%",
                    "signal": signal, "direction": direction,
                    "score": score, "confidence": 0.7}
        elif price <= lower:
            signal = "하단 돌파 (스퀴즈 후 돌파)" if squeeze else "하단 돌파 (과매도)"
            direction = "sell" if squeeze else "buy"
            score = 25 if squeeze else 80
            return {"name": "Bollinger", "value": f"%B={round(pct_b * 100, 0) if pct_b else '?'}%",
                    "signal": signal, "direction": direction,
                    "score": score, "confidence": 0.7}

        if squeeze:
            return {"name": "Bollinger", "value": f"Width={round(width, 4) if width else '?'}",
                    "signal": "스퀴즈 (폭발 대기)", "direction": "neutral",
                    "score": 50, "confidence": 0.5}

        score = int(100 - (pct_b * 100)) if pct_b is not None else 50
        score = max(0, min(100, score))
        return {"name": "Bollinger", "value": f"%B={round(pct_b * 100, 0) if pct_b else '?'}%",
                "signal": "밴드 내", "direction": "neutral",
                "score": score, "confidence": 0.4}


class ATRIndicator(BaseIndicator):
    category = "volatility"
    name = "ATR"
    description = "평균진폭범위 - 변동성 크기 측정 (포지션 사이징용)"

    @classmethod
    def default_params(cls):
        return {"period": 14}

    def compute(self, df):
        df = df.copy()
        df["ATR"] = ta.volatility.average_true_range(
            df["High"], df["Low"], df["Close"],
            window=self.params.get("period", 14))
        df["ATR_Pct"] = df["ATR"] / df["Close"] * 100
        return df

    def get_signal(self, df):
        atr = self._safe_latest(df, "ATR")
        atr_pct = self._safe_latest(df, "ATR_Pct")
        if atr is None:
            return {"name": "ATR", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        if "ATR_Pct" in df.columns:
            avg_atr_pct = df["ATR_Pct"].tail(50).mean()
            if pd.notna(avg_atr_pct) and avg_atr_pct > 0:
                ratio = atr_pct / avg_atr_pct if atr_pct else 1
                if ratio > 1.5:
                    return {"name": "ATR", "value": f"${round(atr, 2)} ({round(atr_pct, 1)}%)",
                            "signal": "높은 변동성 (리스크 주의)", "direction": "neutral",
                            "score": 50, "confidence": 0.6}
                elif ratio < 0.6:
                    return {"name": "ATR", "value": f"${round(atr, 2)} ({round(atr_pct, 1)}%)",
                            "signal": "낮은 변동성 (돌파 대기)", "direction": "neutral",
                            "score": 50, "confidence": 0.5}

        return {"name": "ATR", "value": f"${round(atr, 2)} ({round(atr_pct, 1) if atr_pct else '?'}%)",
                "signal": "보통 변동성", "direction": "neutral",
                "score": 50, "confidence": 0.3}


class KeltnerChannelIndicator(BaseIndicator):
    category = "volatility"
    name = "Keltner Channel"
    description = "켈트너 채널 - ATR 기반 채널, 볼린저와 함께 스퀴즈 감지"

    @classmethod
    def default_params(cls):
        return {"period": 20, "atr_period": 10, "multiplier": 2}

    def compute(self, df):
        df = df.copy()
        p = self.params.get("period", 20)
        atr_p = self.params.get("atr_period", 10)
        mult = self.params.get("multiplier", 2)
        kc = ta.volatility.KeltnerChannel(
            df["High"], df["Low"], df["Close"],
            window=p, window_atr=atr_p, multiplier=mult)
        df["KC_Upper"] = kc.keltner_channel_hband()
        df["KC_Middle"] = kc.keltner_channel_mband()
        df["KC_Lower"] = kc.keltner_channel_lband()
        return df

    def get_signal(self, df):
        price = df["Close"].iloc[-1]
        upper = self._safe_latest(df, "KC_Upper")
        lower = self._safe_latest(df, "KC_Lower")
        middle = self._safe_latest(df, "KC_Middle")

        if upper is None or lower is None:
            return {"name": "Keltner", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        bb_upper = self._safe_latest(df, "BB_Upper")
        bb_lower = self._safe_latest(df, "BB_Lower")
        squeeze = False
        if bb_upper is not None and bb_lower is not None:
            squeeze = bb_upper < upper and bb_lower > lower

        if price > upper:
            signal = "상단 돌파 (강한 모멘텀)" if not squeeze else "스퀴즈 후 상방 돌파"
            return {"name": "Keltner", "value": f"상단 ${round(upper, 2)}",
                    "signal": signal, "direction": "buy", "score": 75, "confidence": 0.65}
        elif price < lower:
            signal = "하단 돌파 (약세 모멘텀)" if not squeeze else "스퀴즈 후 하방 돌파"
            return {"name": "Keltner", "value": f"하단 ${round(lower, 2)}",
                    "signal": signal, "direction": "sell", "score": 25, "confidence": 0.65}

        if squeeze:
            return {"name": "Keltner", "value": "BB ⊂ KC",
                    "signal": "스퀴즈 (볼린저 < 켈트너, 폭발 임박)",
                    "direction": "neutral", "score": 50, "confidence": 0.6}

        position = (price - lower) / (upper - lower) * 100 if upper != lower else 50
        score = int(100 - position)
        return {"name": "Keltner", "value": f"{position:.0f}%",
                "signal": "채널 내", "direction": "neutral",
                "score": score, "confidence": 0.3}


ALL_INDICATORS = [BollingerBandsIndicator, ATRIndicator, KeltnerChannelIndicator]
