"""추세 지표: SMA, EMA, ADX, Ichimoku, Parabolic SAR"""

import pandas as pd
import ta
from .base import BaseIndicator


class SMAIndicator(BaseIndicator):
    category = "trend"
    name = "SMA"
    description = "단순이동평균선 - 추세 방향 및 지지/저항"

    @classmethod
    def default_params(cls):
        return {"periods": [20, 50, 100, 200]}

    def compute(self, df):
        df = df.copy()
        for p in self.params.get("periods", [20, 50, 200]):
            df[f"SMA_{p}"] = ta.trend.sma_indicator(df["Close"], window=p)
        return df

    def get_signal(self, df):
        periods = sorted(self.params.get("periods", [20, 50, 200]))
        price = df["Close"].iloc[-1]
        sma_vals = {}
        for p in periods:
            v = self._safe_latest(df, f"SMA_{p}")
            if v is not None:
                sma_vals[p] = v

        if len(sma_vals) < 2:
            return {"name": "SMA", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        above_count = sum(1 for v in sma_vals.values() if price > v)
        total = len(sma_vals)
        score = int(above_count / total * 100)

        sorted_smas = [sma_vals[p] for p in sorted(sma_vals.keys())]
        if all(sorted_smas[i] >= sorted_smas[i + 1] for i in range(len(sorted_smas) - 1)) and price > sorted_smas[0]:
            return {"name": "SMA", "value": "정배열", "signal": "강한 상승 추세",
                    "direction": "buy", "score": 90, "confidence": 0.9}
        elif all(sorted_smas[i] <= sorted_smas[i + 1] for i in range(len(sorted_smas) - 1)) and price < sorted_smas[0]:
            return {"name": "SMA", "value": "역배열", "signal": "강한 하락 추세",
                    "direction": "sell", "score": 10, "confidence": 0.9}

        longest = max(sma_vals.keys())
        if price > sma_vals[longest]:
            direction = "buy"
            signal = f"{longest}일선 위 (장기 상승)"
        else:
            direction = "sell"
            signal = f"{longest}일선 아래 (장기 하락)"

        return {"name": "SMA", "value": f"{above_count}/{total} 위", "signal": signal,
                "direction": direction, "score": score, "confidence": 0.6}


class EMAIndicator(BaseIndicator):
    category = "trend"
    name = "EMA"
    description = "지수이동평균선 - 최근 가격에 더 큰 가중치"

    @classmethod
    def default_params(cls):
        return {"periods": [12, 26, 50]}

    def compute(self, df):
        df = df.copy()
        for p in self.params.get("periods", [12, 26, 50]):
            df[f"EMA_{p}"] = ta.trend.ema_indicator(df["Close"], window=p)
        return df

    def get_signal(self, df):
        periods = sorted(self.params.get("periods", [12, 26, 50]))
        price = df["Close"].iloc[-1]
        ema_vals = {}
        for p in periods:
            v = self._safe_latest(df, f"EMA_{p}")
            if v is not None:
                ema_vals[p] = v

        if len(ema_vals) < 2:
            return {"name": "EMA", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        short_p, long_p = min(ema_vals.keys()), max(ema_vals.keys())
        short_v, long_v = ema_vals[short_p], ema_vals[long_p]

        if len(df) >= 2:
            prev_short = df[f"EMA_{short_p}"].iloc[-2] if f"EMA_{short_p}" in df.columns else None
            prev_long = df[f"EMA_{long_p}"].iloc[-2] if f"EMA_{long_p}" in df.columns else None
            if prev_short is not None and prev_long is not None and pd.notna(prev_short) and pd.notna(prev_long):
                if short_v > long_v and prev_short <= prev_long:
                    return {"name": "EMA", "value": "골든크로스", "signal": f"EMA{short_p} > EMA{long_p} 돌파",
                            "direction": "buy", "score": 85, "confidence": 0.8}
                elif short_v < long_v and prev_short >= prev_long:
                    return {"name": "EMA", "value": "데드크로스", "signal": f"EMA{short_p} < EMA{long_p} 하향",
                            "direction": "sell", "score": 15, "confidence": 0.8}

        above = sum(1 for v in ema_vals.values() if price > v)
        score = int(above / len(ema_vals) * 100)
        direction = "buy" if score > 60 else ("sell" if score < 40 else "neutral")
        return {"name": "EMA", "value": f"{above}/{len(ema_vals)} 위",
                "signal": "단기 상승" if direction == "buy" else ("단기 하락" if direction == "sell" else "횡보"),
                "direction": direction, "score": score, "confidence": 0.5}


class ADXIndicator(BaseIndicator):
    category = "trend"
    name = "ADX"
    description = "평균방향지수 - 추세 강도 측정 (방향 무관)"

    @classmethod
    def default_params(cls):
        return {"period": 14, "strong_threshold": 25, "very_strong": 50}

    def compute(self, df):
        df = df.copy()
        p = self.params.get("period", 14)
        adx = ta.trend.ADXIndicator(df["High"], df["Low"], df["Close"], window=p)
        df["ADX"] = adx.adx()
        df["ADX_POS"] = adx.adx_pos()
        df["ADX_NEG"] = adx.adx_neg()
        return df

    def get_signal(self, df):
        adx = self._safe_latest(df, "ADX")
        pos = self._safe_latest(df, "ADX_POS")
        neg = self._safe_latest(df, "ADX_NEG")
        if adx is None:
            return {"name": "ADX", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        strong = self.params.get("strong_threshold", 25)
        very_strong = self.params.get("very_strong", 50)

        if adx < strong:
            return {"name": "ADX", "value": round(adx, 1), "signal": "약한 추세 (횡보)",
                    "direction": "neutral", "score": 50, "confidence": 0.3}

        if pos is not None and neg is not None:
            direction = "buy" if pos > neg else "sell"
        else:
            direction = "neutral"

        strength = "매우 강한" if adx >= very_strong else "강한"
        trend_dir = "상승" if direction == "buy" else ("하락" if direction == "sell" else "")
        score = 75 if direction == "buy" else (25 if direction == "sell" else 50)
        confidence = min(adx / 100, 0.95)

        return {"name": "ADX", "value": round(adx, 1),
                "signal": f"{strength} {trend_dir} 추세",
                "direction": direction, "score": score, "confidence": confidence}


class IchimokuIndicator(BaseIndicator):
    category = "trend"
    name = "Ichimoku"
    description = "일목균형표 - 추세/지지/저항/모멘텀 종합"

    @classmethod
    def default_params(cls):
        return {"tenkan": 9, "kijun": 26, "senkou_b": 52}

    def compute(self, df):
        df = df.copy()
        t = self.params.get("tenkan", 9)
        k = self.params.get("kijun", 26)
        s = self.params.get("senkou_b", 52)
        ichi = ta.trend.IchimokuIndicator(df["High"], df["Low"], window1=t, window2=k, window3=s)
        df["Ichi_Tenkan"] = ichi.ichimoku_conversion_line()
        df["Ichi_Kijun"] = ichi.ichimoku_base_line()
        df["Ichi_SpanA"] = ichi.ichimoku_a()
        df["Ichi_SpanB"] = ichi.ichimoku_b()
        return df

    def get_signal(self, df):
        price = df["Close"].iloc[-1]
        tenkan = self._safe_latest(df, "Ichi_Tenkan")
        kijun = self._safe_latest(df, "Ichi_Kijun")
        span_a = self._safe_latest(df, "Ichi_SpanA")
        span_b = self._safe_latest(df, "Ichi_SpanB")

        if any(v is None for v in [tenkan, kijun, span_a, span_b]):
            return {"name": "Ichimoku", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)
        bullish_cloud = span_a > span_b

        signals_buy = 0
        signals_total = 4

        if price > cloud_top:
            signals_buy += 1
        if tenkan > kijun:
            signals_buy += 1
        if bullish_cloud:
            signals_buy += 1
        if price > kijun:
            signals_buy += 1

        score = int(signals_buy / signals_total * 100)
        if signals_buy >= 3:
            return {"name": "Ichimoku", "value": f"{signals_buy}/4 강세",
                    "signal": "구름 위 + 전환>기준 (강세)", "direction": "buy",
                    "score": score, "confidence": 0.75}
        elif signals_buy <= 1:
            return {"name": "Ichimoku", "value": f"{signals_buy}/4 약세",
                    "signal": "구름 아래 + 전환<기준 (약세)", "direction": "sell",
                    "score": score, "confidence": 0.75}
        else:
            in_cloud = cloud_bottom <= price <= cloud_top
            signal = "구름 내 (전환 구간)" if in_cloud else "혼조세"
            return {"name": "Ichimoku", "value": f"{signals_buy}/4", "signal": signal,
                    "direction": "neutral", "score": score, "confidence": 0.4}


class ParabolicSARIndicator(BaseIndicator):
    category = "trend"
    name = "Parabolic SAR"
    description = "파라볼릭 SAR - 추세 반전 감지 및 트레일링 스탑"

    @classmethod
    def default_params(cls):
        return {"step": 0.02, "max_step": 0.2}

    def compute(self, df):
        df = df.copy()
        step = self.params.get("step", 0.02)
        max_step = self.params.get("max_step", 0.2)
        psar = ta.trend.PSARIndicator(df["High"], df["Low"], df["Close"],
                                       step=step, max_step=max_step)
        df["PSAR_Up"] = psar.psar_up()
        df["PSAR_Down"] = psar.psar_down()
        return df

    def get_signal(self, df):
        price = df["Close"].iloc[-1]
        psar_up = self._safe_latest(df, "PSAR_Up")
        psar_down = self._safe_latest(df, "PSAR_Down")

        if psar_up is not None and pd.notna(psar_up):
            return {"name": "PSAR", "value": round(psar_up, 2),
                    "signal": "SAR 아래 (상승 추세)", "direction": "buy",
                    "score": 70, "confidence": 0.6}
        elif psar_down is not None and pd.notna(psar_down):
            return {"name": "PSAR", "value": round(psar_down, 2),
                    "signal": "SAR 위 (하락 추세)", "direction": "sell",
                    "score": 30, "confidence": 0.6}

        return {"name": "PSAR", "value": "N/A", "signal": "판단 불가",
                "direction": "neutral", "score": 50, "confidence": 0}


ALL_INDICATORS = [SMAIndicator, EMAIndicator, ADXIndicator, IchimokuIndicator, ParabolicSARIndicator]
