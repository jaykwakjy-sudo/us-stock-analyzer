"""모멘텀/오실레이터 지표: RSI, MACD, Stochastic, Williams %R, CCI, MFI"""

import pandas as pd
import ta
from .base import BaseIndicator


class RSIIndicator(BaseIndicator):
    category = "momentum"
    name = "RSI"
    description = "상대강도지수 - 과매수/과매도 판단"

    @classmethod
    def default_params(cls):
        return {"period": 14, "overbought": 70, "oversold": 30}

    def compute(self, df):
        df = df.copy()
        df["RSI"] = ta.momentum.rsi(df["Close"], window=self.params.get("period", 14))
        return df

    def get_signal(self, df):
        rsi = self._safe_latest(df, "RSI")
        if rsi is None:
            return {"name": "RSI", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        ob = self.params.get("overbought", 70)
        os_ = self.params.get("oversold", 30)
        rsi_val = round(rsi, 1)

        has_divergence = self._check_divergence(df)

        if rsi > ob:
            score = max(5, int(100 - (rsi - 50) * 2))
            signal = "과매수 (하향 다이버전스)" if has_divergence == "bearish" else "과매수 구간"
            confidence = 0.85 if has_divergence == "bearish" else 0.7
            return {"name": "RSI", "value": rsi_val, "signal": signal,
                    "direction": "sell", "score": score, "confidence": confidence}
        elif rsi < os_:
            score = min(95, int((50 - rsi) * 2 + 50))
            signal = "과매도 (상향 다이버전스)" if has_divergence == "bullish" else "과매도 구간"
            confidence = 0.85 if has_divergence == "bullish" else 0.7
            return {"name": "RSI", "value": rsi_val, "signal": signal,
                    "direction": "buy", "score": score, "confidence": confidence}

        score = int(100 - rsi)
        return {"name": "RSI", "value": rsi_val, "signal": "중립 구간",
                "direction": "neutral", "score": score, "confidence": 0.4}

    def _check_divergence(self, df):
        if len(df) < 20 or "RSI" not in df.columns:
            return None
        prices = df["Close"].tail(20)
        rsi_vals = df["RSI"].tail(20).dropna()
        if len(rsi_vals) < 10:
            return None
        if prices.iloc[-1] > prices.iloc[-10] and rsi_vals.iloc[-1] < rsi_vals.iloc[-10]:
            return "bearish"
        if prices.iloc[-1] < prices.iloc[-10] and rsi_vals.iloc[-1] > rsi_vals.iloc[-10]:
            return "bullish"
        return None


class MACDIndicator(BaseIndicator):
    category = "momentum"
    name = "MACD"
    description = "이동평균수렴확산 - 추세 모멘텀 및 전환"

    @classmethod
    def default_params(cls):
        return {"fast": 12, "slow": 26, "signal": 9}

    def compute(self, df):
        df = df.copy()
        macd = ta.trend.MACD(df["Close"],
                             window_slow=self.params.get("slow", 26),
                             window_fast=self.params.get("fast", 12),
                             window_sign=self.params.get("signal", 9))
        df["MACD"] = macd.macd()
        df["MACD_Signal"] = macd.macd_signal()
        df["MACD_Hist"] = macd.macd_diff()
        return df

    def get_signal(self, df):
        hist = self._safe_latest(df, "MACD_Hist")
        macd_val = self._safe_latest(df, "MACD")
        if hist is None:
            return {"name": "MACD", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        prev_hist = df["MACD_Hist"].iloc[-2] if len(df) >= 2 and "MACD_Hist" in df.columns else None

        if prev_hist is not None and pd.notna(prev_hist):
            if hist > 0 and prev_hist <= 0:
                return {"name": "MACD", "value": round(hist, 3), "signal": "골든크로스 (매수 전환)",
                        "direction": "buy", "score": 85, "confidence": 0.8}
            if hist < 0 and prev_hist >= 0:
                return {"name": "MACD", "value": round(hist, 3), "signal": "데드크로스 (매도 전환)",
                        "direction": "sell", "score": 15, "confidence": 0.8}

        hist_increasing = False
        if len(df) >= 3 and "MACD_Hist" in df.columns:
            recent = df["MACD_Hist"].tail(3).dropna()
            if len(recent) == 3:
                hist_increasing = recent.iloc[-1] > recent.iloc[-2] > recent.iloc[-3]

        if hist > 0:
            score = min(80, 60 + int(hist_increasing) * 15)
            signal = "상승 모멘텀 강화" if hist_increasing else "상승 모멘텀"
            return {"name": "MACD", "value": round(hist, 3), "signal": signal,
                    "direction": "buy", "score": score, "confidence": 0.6}
        else:
            score = max(20, 40 - int(hist_increasing) * 15)
            signal = "하락 모멘텀"
            return {"name": "MACD", "value": round(hist, 3), "signal": signal,
                    "direction": "sell", "score": score, "confidence": 0.6}


class StochasticIndicator(BaseIndicator):
    category = "momentum"
    name = "Stochastic"
    description = "스토캐스틱 - 현재 가격의 범위 내 위치"

    @classmethod
    def default_params(cls):
        return {"k_period": 14, "d_period": 3, "overbought": 80, "oversold": 20}

    def compute(self, df):
        df = df.copy()
        stoch = ta.momentum.StochasticOscillator(
            df["High"], df["Low"], df["Close"],
            window=self.params.get("k_period", 14),
            smooth_window=self.params.get("d_period", 3))
        df["Stoch_K"] = stoch.stoch()
        df["Stoch_D"] = stoch.stoch_signal()
        return df

    def get_signal(self, df):
        k = self._safe_latest(df, "Stoch_K")
        d = self._safe_latest(df, "Stoch_D")
        if k is None:
            return {"name": "Stochastic", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        ob = self.params.get("overbought", 80)
        os_ = self.params.get("oversold", 20)

        cross = None
        if d is not None and len(df) >= 2:
            prev_k = df["Stoch_K"].iloc[-2] if "Stoch_K" in df.columns else None
            prev_d = df["Stoch_D"].iloc[-2] if "Stoch_D" in df.columns else None
            if prev_k is not None and prev_d is not None and pd.notna(prev_k) and pd.notna(prev_d):
                if k > d and prev_k <= prev_d:
                    cross = "golden"
                elif k < d and prev_k >= prev_d:
                    cross = "dead"

        if k > ob:
            if cross == "dead":
                return {"name": "Stochastic", "value": round(k, 1),
                        "signal": "과매수 + 데드크로스",
                        "direction": "sell", "score": 10, "confidence": 0.85}
            return {"name": "Stochastic", "value": round(k, 1), "signal": "과매수 구간",
                    "direction": "sell", "score": 20, "confidence": 0.6}
        elif k < os_:
            if cross == "golden":
                return {"name": "Stochastic", "value": round(k, 1),
                        "signal": "과매도 + 골든크로스",
                        "direction": "buy", "score": 90, "confidence": 0.85}
            return {"name": "Stochastic", "value": round(k, 1), "signal": "과매도 구간",
                    "direction": "buy", "score": 80, "confidence": 0.6}

        score = int(100 - k)
        return {"name": "Stochastic", "value": round(k, 1), "signal": "중립",
                "direction": "neutral", "score": score, "confidence": 0.3}


class WilliamsRIndicator(BaseIndicator):
    category = "momentum"
    name = "Williams %R"
    description = "윌리엄스 %R - 스토캐스틱 변형, 과매수/과매도"

    @classmethod
    def default_params(cls):
        return {"period": 14}

    def compute(self, df):
        df = df.copy()
        df["Williams_R"] = ta.momentum.williams_r(
            df["High"], df["Low"], df["Close"],
            lbp=self.params.get("period", 14))
        return df

    def get_signal(self, df):
        wr = self._safe_latest(df, "Williams_R")
        if wr is None:
            return {"name": "Williams %R", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        if wr > -20:
            return {"name": "Williams %R", "value": round(wr, 1), "signal": "과매수",
                    "direction": "sell", "score": 20, "confidence": 0.6}
        elif wr < -80:
            return {"name": "Williams %R", "value": round(wr, 1), "signal": "과매도",
                    "direction": "buy", "score": 80, "confidence": 0.6}

        score = int((-wr / 100) * 100)
        return {"name": "Williams %R", "value": round(wr, 1), "signal": "중립",
                "direction": "neutral", "score": score, "confidence": 0.3}


class CCIIndicator(BaseIndicator):
    category = "momentum"
    name = "CCI"
    description = "상품채널지수 - 가격의 평균 대비 이탈 정도"

    @classmethod
    def default_params(cls):
        return {"period": 20, "overbought": 100, "oversold": -100}

    def compute(self, df):
        df = df.copy()
        df["CCI"] = ta.trend.cci(df["High"], df["Low"], df["Close"],
                                  window=self.params.get("period", 20))
        return df

    def get_signal(self, df):
        cci = self._safe_latest(df, "CCI")
        if cci is None:
            return {"name": "CCI", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        ob = self.params.get("overbought", 100)
        os_ = self.params.get("oversold", -100)

        if cci > ob * 2:
            return {"name": "CCI", "value": round(cci, 1), "signal": "극단적 과매수",
                    "direction": "sell", "score": 5, "confidence": 0.8}
        elif cci > ob:
            return {"name": "CCI", "value": round(cci, 1), "signal": "과매수",
                    "direction": "sell", "score": 25, "confidence": 0.6}
        elif cci < os_ * 2:
            return {"name": "CCI", "value": round(cci, 1), "signal": "극단적 과매도",
                    "direction": "buy", "score": 95, "confidence": 0.8}
        elif cci < os_:
            return {"name": "CCI", "value": round(cci, 1), "signal": "과매도",
                    "direction": "buy", "score": 75, "confidence": 0.6}

        score = int(50 - (cci / (ob * 2)) * 50)
        score = max(0, min(100, score))
        return {"name": "CCI", "value": round(cci, 1), "signal": "중립",
                "direction": "neutral", "score": score, "confidence": 0.3}


class MFIIndicator(BaseIndicator):
    category = "momentum"
    name = "MFI"
    description = "자금흐름지수 - 거래량 가중 RSI"

    @classmethod
    def default_params(cls):
        return {"period": 14, "overbought": 80, "oversold": 20}

    def compute(self, df):
        df = df.copy()
        df["MFI"] = ta.volume.money_flow_index(
            df["High"], df["Low"], df["Close"], df["Volume"],
            window=self.params.get("period", 14))
        return df

    def get_signal(self, df):
        mfi = self._safe_latest(df, "MFI")
        if mfi is None:
            return {"name": "MFI", "value": "N/A", "signal": "데이터 부족",
                    "direction": "neutral", "score": 50, "confidence": 0}

        ob = self.params.get("overbought", 80)
        os_ = self.params.get("oversold", 20)

        if mfi > ob:
            return {"name": "MFI", "value": round(mfi, 1), "signal": "자금 과유입 (과매수)",
                    "direction": "sell", "score": 20, "confidence": 0.65}
        elif mfi < os_:
            return {"name": "MFI", "value": round(mfi, 1), "signal": "자금 유출 (과매도)",
                    "direction": "buy", "score": 80, "confidence": 0.65}

        score = int(100 - mfi)
        return {"name": "MFI", "value": round(mfi, 1), "signal": "중립",
                "direction": "neutral", "score": score, "confidence": 0.3}


ALL_INDICATORS = [RSIIndicator, MACDIndicator, StochasticIndicator,
                  WilliamsRIndicator, CCIIndicator, MFIIndicator]
