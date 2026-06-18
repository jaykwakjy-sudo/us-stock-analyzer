"""거래량 지표: OBV, VWAP, A/D Line, Chaikin Money Flow"""

import pandas as pd
import ta
from .base import BaseIndicator


class OBVIndicator(BaseIndicator):
    category = "volume"
    name = "OBV"
    description = "거래량 잔고 - 가격 변동과 거래량의 관계"

    @classmethod
    def default_params(cls):
        return {"sma_period": 20}

    def compute(self, df):
        df = df.copy()
        df["OBV"] = ta.volume.on_balance_volume(df["Close"], df["Volume"])
        sma_p = self.params.get("sma_period", 20)
        df["OBV_SMA"] = ta.trend.sma_indicator(df["OBV"], window=sma_p)
        return df

    def get_signal(self, df):
        obv = self._safe_latest(df, "OBV")
        obv_sma = self._safe_latest(df, "OBV_SMA")
        if obv is None or obv_sma is None:
            return {"name": "OBV", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        price_up = False
        obv_up = False
        if len(df) >= 10:
            price_up = df["Close"].iloc[-1] > df["Close"].iloc[-10]
            obv_up = df["OBV"].iloc[-1] > df["OBV"].iloc[-10]

        if price_up and not obv_up:
            return {"name": "OBV", "value": "약세 다이버전스",
                    "signal": "가격↑ 거래량↓ (상승 의심)", "direction": "sell",
                    "score": 30, "confidence": 0.7}
        elif not price_up and obv_up:
            return {"name": "OBV", "value": "강세 다이버전스",
                    "signal": "가격↓ 거래량↑ (매집 가능성)", "direction": "buy",
                    "score": 70, "confidence": 0.7}

        if obv > obv_sma:
            return {"name": "OBV", "value": "SMA 위",
                    "signal": "거래량 유입 확대", "direction": "buy",
                    "score": 65, "confidence": 0.5}
        else:
            return {"name": "OBV", "value": "SMA 아래",
                    "signal": "거래량 유입 감소", "direction": "sell",
                    "score": 35, "confidence": 0.5}


class VolumeAnalysisIndicator(BaseIndicator):
    category = "volume"
    name = "Volume"
    description = "거래량 분석 - 평균 대비 거래량 비율"

    @classmethod
    def default_params(cls):
        return {"sma_period": 20, "surge_threshold": 2.0, "high_threshold": 1.5}

    def compute(self, df):
        df = df.copy()
        p = self.params.get("sma_period", 20)
        df["Vol_SMA"] = ta.trend.sma_indicator(df["Volume"], window=p)
        df["Vol_Ratio"] = df["Volume"] / df["Vol_SMA"]
        return df

    def get_signal(self, df):
        ratio = self._safe_latest(df, "Vol_Ratio")
        if ratio is None:
            return {"name": "Volume", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        surge = self.params.get("surge_threshold", 2.0)
        high = self.params.get("high_threshold", 1.5)

        price_change = 0
        if len(df) >= 2:
            price_change = (df["Close"].iloc[-1] - df["Close"].iloc[-2]) / df["Close"].iloc[-2] * 100

        if ratio > surge:
            direction = "buy" if price_change > 0 else ("sell" if price_change < 0 else "neutral")
            signal = f"폭발 거래량 (가격 {'상승' if price_change > 0 else '하락'} {abs(price_change):.1f}%)"
            score = 75 if direction == "buy" else (25 if direction == "sell" else 50)
            return {"name": "Volume", "value": f"{ratio:.1f}x",
                    "signal": signal, "direction": direction,
                    "score": score, "confidence": 0.7}
        elif ratio > high:
            return {"name": "Volume", "value": f"{ratio:.1f}x",
                    "signal": "높은 거래량", "direction": "neutral",
                    "score": 50, "confidence": 0.4}
        elif ratio < 0.5:
            return {"name": "Volume", "value": f"{ratio:.1f}x",
                    "signal": "매우 낮은 거래량 (관심 감소)", "direction": "neutral",
                    "score": 50, "confidence": 0.3}

        return {"name": "Volume", "value": f"{ratio:.1f}x",
                "signal": "보통 거래량", "direction": "neutral",
                "score": 50, "confidence": 0.2}


class ADLineIndicator(BaseIndicator):
    category = "volume"
    name = "A/D Line"
    description = "누적분배선 - 매집/분배 추적"

    @classmethod
    def default_params(cls):
        return {}

    def compute(self, df):
        df = df.copy()
        df["AD_Line"] = ta.volume.acc_dist_index(df["High"], df["Low"], df["Close"], df["Volume"])
        return df

    def get_signal(self, df):
        if "AD_Line" not in df.columns or len(df) < 10:
            return {"name": "A/D Line", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        ad_trend = df["AD_Line"].iloc[-1] > df["AD_Line"].iloc[-10]
        price_trend = df["Close"].iloc[-1] > df["Close"].iloc[-10]

        if price_trend and not ad_trend:
            return {"name": "A/D Line", "value": "약세 다이버전스",
                    "signal": "가격↑ 분배↑ (매도 압력)", "direction": "sell",
                    "score": 30, "confidence": 0.65}
        elif not price_trend and ad_trend:
            return {"name": "A/D Line", "value": "강세 다이버전스",
                    "signal": "가격↓ 매집↑ (매수 기회)", "direction": "buy",
                    "score": 70, "confidence": 0.65}
        elif ad_trend:
            return {"name": "A/D Line", "value": "상승",
                    "signal": "매집 진행 중", "direction": "buy",
                    "score": 60, "confidence": 0.45}
        else:
            return {"name": "A/D Line", "value": "하락",
                    "signal": "분배 진행 중", "direction": "sell",
                    "score": 40, "confidence": 0.45}


class CMFIndicator(BaseIndicator):
    category = "volume"
    name = "CMF"
    description = "채킨 자금흐름 - 일정 기간 매집/분배 강도"

    @classmethod
    def default_params(cls):
        return {"period": 20}

    def compute(self, df):
        df = df.copy()
        df["CMF"] = ta.volume.chaikin_money_flow(
            df["High"], df["Low"], df["Close"], df["Volume"],
            window=self.params.get("period", 20))
        return df

    def get_signal(self, df):
        cmf = self._safe_latest(df, "CMF")
        if cmf is None:
            return {"name": "CMF", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        if cmf > 0.25:
            return {"name": "CMF", "value": round(cmf, 3),
                    "signal": "강한 매수 압력", "direction": "buy",
                    "score": 80, "confidence": 0.7}
        elif cmf > 0.05:
            return {"name": "CMF", "value": round(cmf, 3),
                    "signal": "완만한 매수 압력", "direction": "buy",
                    "score": 60, "confidence": 0.5}
        elif cmf < -0.25:
            return {"name": "CMF", "value": round(cmf, 3),
                    "signal": "강한 매도 압력", "direction": "sell",
                    "score": 20, "confidence": 0.7}
        elif cmf < -0.05:
            return {"name": "CMF", "value": round(cmf, 3),
                    "signal": "완만한 매도 압력", "direction": "sell",
                    "score": 40, "confidence": 0.5}

        return {"name": "CMF", "value": round(cmf, 3),
                "signal": "중립", "direction": "neutral",
                "score": 50, "confidence": 0.3}


ALL_INDICATORS = [OBVIndicator, VolumeAnalysisIndicator, ADLineIndicator, CMFIndicator]
