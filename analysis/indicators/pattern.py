"""패턴 인식: 캔들스틱 패턴, 지지/저항, 피보나치"""

import pandas as pd
import numpy as np
from .base import BaseIndicator


class CandlestickPatternIndicator(BaseIndicator):
    category = "pattern"
    name = "Candlestick"
    description = "캔들스틱 패턴 - Doji, Hammer, Engulfing 등 자동 감지"

    @classmethod
    def default_params(cls):
        return {"body_threshold": 0.1, "shadow_ratio": 2.0}

    def compute(self, df):
        df = df.copy()
        o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
        body = abs(c - o)
        full_range = h - l
        upper_shadow = h - df[["Open", "Close"]].max(axis=1)
        lower_shadow = df[["Open", "Close"]].min(axis=1) - l

        threshold = self.params.get("body_threshold", 0.1)

        df["CDL_Doji"] = (body / full_range.replace(0, np.nan) < threshold).astype(int)
        df["CDL_Hammer"] = ((lower_shadow > body * self.params.get("shadow_ratio", 2.0)) &
                            (upper_shadow < body * 0.5) & (c > o)).astype(int)
        df["CDL_InvHammer"] = ((upper_shadow > body * self.params.get("shadow_ratio", 2.0)) &
                                (lower_shadow < body * 0.5) & (c < o)).astype(int)

        df["CDL_BullEngulf"] = 0
        df["CDL_BearEngulf"] = 0
        if len(df) >= 2:
            prev_o = o.shift(1)
            prev_c = c.shift(1)
            df["CDL_BullEngulf"] = ((prev_c < prev_o) & (c > o) &
                                    (o <= prev_c) & (c >= prev_o)).astype(int)
            df["CDL_BearEngulf"] = ((prev_c > prev_o) & (c < o) &
                                    (o >= prev_c) & (c <= prev_o)).astype(int)

        df["CDL_MorningStar"] = 0
        df["CDL_EveningStar"] = 0
        if len(df) >= 3:
            body_1 = abs(c.shift(2) - o.shift(2))
            body_2 = abs(c.shift(1) - o.shift(1))
            body_3 = body
            small_body = body_2 < body_1 * 0.3
            df["CDL_MorningStar"] = ((c.shift(2) < o.shift(2)) & small_body &
                                     (c > o) & (c > (o.shift(2) + c.shift(2)) / 2)).astype(int)
            df["CDL_EveningStar"] = ((c.shift(2) > o.shift(2)) & small_body &
                                     (c < o) & (c < (o.shift(2) + c.shift(2)) / 2)).astype(int)
        return df

    def get_signal(self, df):
        bullish_patterns = []
        bearish_patterns = []

        pattern_map = {
            "CDL_Hammer": ("해머", "buy"),
            "CDL_BullEngulf": ("상승 장악형", "buy"),
            "CDL_MorningStar": ("모닝스타", "buy"),
            "CDL_InvHammer": ("역 해머", "sell"),
            "CDL_BearEngulf": ("하락 장악형", "sell"),
            "CDL_EveningStar": ("이브닝스타", "sell"),
            "CDL_Doji": ("도지", "neutral"),
        }

        detected = []
        for col, (name, direction) in pattern_map.items():
            val = self._safe_latest(df, col)
            if val and val > 0:
                detected.append((name, direction))
                if direction == "buy":
                    bullish_patterns.append(name)
                elif direction == "sell":
                    bearish_patterns.append(name)

        if not detected:
            return {"name": "Candlestick", "value": "패턴 없음", "signal": "특이 패턴 미감지",
                    "direction": "neutral", "score": 50, "confidence": 0}

        if bullish_patterns:
            return {"name": "Candlestick", "value": ", ".join(bullish_patterns),
                    "signal": f"강세 패턴 감지 ({len(bullish_patterns)}개)",
                    "direction": "buy", "score": 70, "confidence": 0.6}
        elif bearish_patterns:
            return {"name": "Candlestick", "value": ", ".join(bearish_patterns),
                    "signal": f"약세 패턴 감지 ({len(bearish_patterns)}개)",
                    "direction": "sell", "score": 30, "confidence": 0.6}
        else:
            return {"name": "Candlestick", "value": detected[0][0],
                    "signal": "전환 가능 패턴", "direction": "neutral",
                    "score": 50, "confidence": 0.4}


class SupportResistanceIndicator(BaseIndicator):
    category = "pattern"
    name = "Support/Resistance"
    description = "지지선/저항선 자동 감지 - 피봇 포인트 기반"

    @classmethod
    def default_params(cls):
        return {"lookback": 20, "tolerance_pct": 1.0}

    def compute(self, df):
        df = df.copy()
        lookback = self.params.get("lookback", 20)

        if len(df) < lookback * 2:
            return df

        highs = df["High"].rolling(window=lookback, center=True).max()
        lows = df["Low"].rolling(window=lookback, center=True).min()

        df["Pivot_High"] = df["High"].where(df["High"] == highs, np.nan)
        df["Pivot_Low"] = df["Low"].where(df["Low"] == lows, np.nan)

        h = df["High"].iloc[-1]
        l_val = df["Low"].iloc[-1]
        c = df["Close"].iloc[-1]
        df["Pivot_PP"] = (h + l_val + c) / 3
        df["Pivot_R1"] = 2 * df["Pivot_PP"] - l_val
        df["Pivot_S1"] = 2 * df["Pivot_PP"] - h
        df["Pivot_R2"] = df["Pivot_PP"] + (h - l_val)
        df["Pivot_S2"] = df["Pivot_PP"] - (h - l_val)

        return df

    def get_signal(self, df):
        price = df["Close"].iloc[-1]
        pp = self._safe_latest(df, "Pivot_PP")
        r1 = self._safe_latest(df, "Pivot_R1")
        s1 = self._safe_latest(df, "Pivot_S1")
        r2 = self._safe_latest(df, "Pivot_R2")
        s2 = self._safe_latest(df, "Pivot_S2")

        if pp is None:
            return {"name": "S/R", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        tol = self.params.get("tolerance_pct", 1.0) / 100

        if r1 and abs(price - r1) / r1 < tol:
            return {"name": "S/R", "value": f"R1=${round(r1, 2)}",
                    "signal": "1차 저항선 근접", "direction": "sell",
                    "score": 35, "confidence": 0.6}
        elif s1 and abs(price - s1) / s1 < tol:
            return {"name": "S/R", "value": f"S1=${round(s1, 2)}",
                    "signal": "1차 지지선 근접", "direction": "buy",
                    "score": 65, "confidence": 0.6}
        elif r2 and price > r1:
            return {"name": "S/R", "value": f"R1 돌파, R2=${round(r2, 2)}",
                    "signal": "1차 저항 돌파 (강세)", "direction": "buy",
                    "score": 70, "confidence": 0.55}
        elif s2 and price < s1:
            return {"name": "S/R", "value": f"S1 이탈, S2=${round(s2, 2)}",
                    "signal": "1차 지지 이탈 (약세)", "direction": "sell",
                    "score": 30, "confidence": 0.55}
        elif price > pp:
            return {"name": "S/R", "value": f"PP=${round(pp, 2)}",
                    "signal": "피봇 위 (상승 편향)", "direction": "buy",
                    "score": 60, "confidence": 0.4}
        else:
            return {"name": "S/R", "value": f"PP=${round(pp, 2)}",
                    "signal": "피봇 아래 (하락 편향)", "direction": "sell",
                    "score": 40, "confidence": 0.4}


class FibonacciIndicator(BaseIndicator):
    category = "pattern"
    name = "Fibonacci"
    description = "피보나치 되돌림 - 38.2%, 50%, 61.8% 수준"

    @classmethod
    def default_params(cls):
        return {"lookback": 60, "levels": [0.236, 0.382, 0.5, 0.618, 0.786]}

    def compute(self, df):
        df = df.copy()
        lookback = self.params.get("lookback", 60)
        recent = df.tail(lookback)

        swing_high = recent["High"].max()
        swing_low = recent["Low"].min()
        diff = swing_high - swing_low

        levels = self.params.get("levels", [0.236, 0.382, 0.5, 0.618, 0.786])
        for lvl in levels:
            pct = str(round(lvl * 100, 1)).replace(".", "_")
            df[f"Fib_{pct}"] = swing_high - diff * lvl

        df["Fib_High"] = swing_high
        df["Fib_Low"] = swing_low
        return df

    def get_signal(self, df):
        price = df["Close"].iloc[-1]
        fib_high = self._safe_latest(df, "Fib_High")
        fib_low = self._safe_latest(df, "Fib_Low")

        if fib_high is None or fib_low is None or fib_high == fib_low:
            return {"name": "Fibonacci", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        diff = fib_high - fib_low
        retracement = (fib_high - price) / diff

        levels = self.params.get("levels", [0.236, 0.382, 0.5, 0.618, 0.786])
        closest_level = min(levels, key=lambda l: abs(retracement - l))
        tol = 0.03

        near_level = abs(retracement - closest_level) < tol
        pct_label = f"{closest_level * 100:.1f}%"

        if near_level:
            if closest_level <= 0.382:
                return {"name": "Fibonacci", "value": f"{pct_label} 근접",
                        "signal": f"얕은 되돌림 ({pct_label}) - 강세 지속 가능",
                        "direction": "buy", "score": 65, "confidence": 0.6}
            elif closest_level <= 0.5:
                return {"name": "Fibonacci", "value": f"{pct_label} 근접",
                        "signal": f"50% 되돌림 - 주요 분기점",
                        "direction": "neutral", "score": 50, "confidence": 0.55}
            else:
                return {"name": "Fibonacci", "value": f"{pct_label} 근접",
                        "signal": f"깊은 되돌림 ({pct_label}) - 추세 반전 주의",
                        "direction": "sell", "score": 35, "confidence": 0.6}

        retrace_pct = retracement * 100
        score = int(max(0, min(100, 50 + (50 - retrace_pct))))
        direction = "buy" if retracement < 0.382 else ("sell" if retracement > 0.618 else "neutral")
        return {"name": "Fibonacci", "value": f"{retrace_pct:.1f}% 되돌림",
                "signal": f"고점 대비 {retrace_pct:.1f}% 조정",
                "direction": direction, "score": score, "confidence": 0.4}


ALL_INDICATORS = [CandlestickPatternIndicator, SupportResistanceIndicator, FibonacciIndicator]
