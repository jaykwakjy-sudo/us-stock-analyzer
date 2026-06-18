"""분석 엔진 오케스트레이터

DB 설정 로드 → 활성 지표 인스턴스화 → 순차 실행 → 스코어 합산 → 결과 반환
모든 파라미터와 가중치는 DB settings 테이블에서 로드. 코드 내 하드코딩 없음.
"""

import pandas as pd
import logging

from analysis.indicators.trend import ALL_INDICATORS as TREND_INDICATORS
from analysis.indicators.momentum import ALL_INDICATORS as MOMENTUM_INDICATORS
from analysis.indicators.volatility import ALL_INDICATORS as VOLATILITY_INDICATORS
from analysis.indicators.volume import ALL_INDICATORS as VOLUME_INDICATORS
from analysis.indicators.pattern import ALL_INDICATORS as PATTERN_INDICATORS
from analysis.fundamental import get_fundamental_analysis
from analysis.scoring import aggregate_signals

logger = logging.getLogger(__name__)

INDICATOR_REGISTRY = {}
for ind_list in [TREND_INDICATORS, MOMENTUM_INDICATORS, VOLATILITY_INDICATORS,
                 VOLUME_INDICATORS, PATTERN_INDICATORS]:
    for cls in ind_list:
        INDICATOR_REGISTRY[cls.name] = cls


def get_default_indicator_config() -> dict:
    """DB에 시드할 기본 지표 설정. 각 지표의 활성 여부, 파라미터, 가중치."""
    config = {}
    for name, cls in INDICATOR_REGISTRY.items():
        config[name] = {
            "enabled": True,
            "params": cls.default_params(),
            "category": cls.category,
        }
    return config


def get_default_scoring_weights() -> dict:
    """DB에 시드할 기본 스코어링 가중치."""
    return {
        "technical": {
            "trend": 0.25, "momentum": 0.25, "volatility": 0.15,
            "volume": 0.15, "pattern": 0.20,
        },
        "fundamental": {
            "valuation": 0.30, "growth": 0.30, "quality": 0.20, "analyst": 0.20,
        },
        "blend": {"technical": 0.6, "fundamental": 0.4},
        "thresholds": {
            "strong_buy": 75, "buy": 60,
            "strong_sell": 25, "sell": 40,
            "min_confidence": 0.3,
        },
    }


def run_analysis(ticker: str, df: pd.DataFrame,
                 indicator_config: dict = None,
                 scoring_weights: dict = None,
                 fundamental_params: dict = None,
                 include_fundamental: bool = True) -> dict:
    """종합 분석 실행.

    Args:
        ticker: 종목코드
        df: OHLCV DataFrame (Yahoo Finance 형식)
        indicator_config: DB에서 로드한 지표 설정 (None이면 기본값)
        scoring_weights: DB에서 로드한 스코어링 가중치 (None이면 기본값)
        fundamental_params: DB에서 로드한 펀더멘탈 분석 파라미터
        include_fundamental: 펀더멘탈 분석 포함 여부

    Returns:
        {
            "ticker": str,
            "technical": {"indicators": [...], "df": DataFrame},
            "fundamental": {...} or None,
            "result": aggregate_signals 결과,
        }
    """
    if indicator_config is None:
        indicator_config = get_default_indicator_config()
    if scoring_weights is None:
        scoring_weights = get_default_scoring_weights()

    enriched_df = df.copy()
    technical_signals = []

    for name, cls in INDICATOR_REGISTRY.items():
        config = indicator_config.get(name, {})
        if not config.get("enabled", True):
            continue

        params = config.get("params", cls.default_params())
        indicator = cls(params)

        try:
            enriched_df = indicator.compute(enriched_df)
            signal = indicator.get_signal(enriched_df)
            if signal and signal.get("confidence", 0) > 0:
                technical_signals.append(signal)
        except Exception as e:
            logger.warning(f"지표 {name} 실행 실패: {e}")
            continue

    fundamental_result = None
    fundamental_signals = []
    if include_fundamental:
        try:
            fundamental_result = get_fundamental_analysis(
                ticker, params=fundamental_params)
            fundamental_signals = fundamental_result.get("signals", [])
        except Exception as e:
            logger.warning(f"펀더멘탈 분석 실패 ({ticker}): {e}")

    result = aggregate_signals(technical_signals, fundamental_signals, scoring_weights)

    return {
        "ticker": ticker,
        "technical": {
            "signals": technical_signals,
            "df": enriched_df,
        },
        "fundamental": fundamental_result,
        "result": result,
    }


def run_analysis_from_db(ticker: str, df: pd.DataFrame,
                         get_setting_fn=None) -> dict:
    """DB settings를 자동 로드하여 분석 실행. Streamlit 페이지에서 사용.

    get_setting_fn: data.database.get_setting 함수 (의존성 주입)
    """
    indicator_config = None
    scoring_weights = None
    fundamental_params = None

    if get_setting_fn:
        indicator_config = get_setting_fn("indicator_config")
        scoring_weights = get_setting_fn("scoring_weights")
        fundamental_params = get_setting_fn("fundamental_params")

    return run_analysis(
        ticker, df,
        indicator_config=indicator_config,
        scoring_weights=scoring_weights,
        fundamental_params=fundamental_params,
    )


def list_available_indicators() -> list[dict]:
    """등록된 모든 지표 목록 반환 (설정 UI용)"""
    result = []
    for name, cls in INDICATOR_REGISTRY.items():
        result.append({
            "name": name,
            "category": cls.category,
            "description": cls.description,
            "default_params": cls.default_params(),
        })
    return sorted(result, key=lambda x: (x["category"], x["name"]))
