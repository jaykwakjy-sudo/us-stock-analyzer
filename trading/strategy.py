"""매매 전략 플러그인 — 분석 엔진 시그널 기반 판단

BaseStrategy ABC를 상속해서 새 전략 추가.
STRATEGY_REGISTRY에 자동 등록, DB에서 전략 선택.
나중에 FinRL 전략도 같은 인터페이스로 교체 가능.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

STRATEGY_REGISTRY: dict[str, type] = {}


def register_strategy(cls):
    STRATEGY_REGISTRY[cls.name] = cls
    return cls


@dataclass
class TradeSignal:
    ticker: str
    action: str  # "buy", "sell", "hold"
    strength: float  # 0~1
    quantity_pct: float  # 자본 대비 비율 0~1
    reason: str
    score: float = 0
    confidence: float = 0


class BaseStrategy(ABC):
    name: str = ""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def evaluate(self, ticker: str, analysis_result: dict,
                 position: Optional[dict] = None) -> TradeSignal:
        """분석 결과를 받아 매매 시그널 반환"""


@register_strategy
class SignalScoreStrategy(BaseStrategy):
    """분석 엔진의 종합 점수 기반 전략

    점수 > buy_threshold → 매수
    점수 < sell_threshold → 매도
    그 사이 → 홀드

    포지션 없으면 매수만, 있으면 매도/추가매수 판단.
    손절/익절 자동 체크.
    """
    name = "signal_score"

    def evaluate(self, ticker: str, analysis_result: dict,
                 position: Optional[dict] = None) -> TradeSignal:
        score = analysis_result.get("final_score", 50)
        confidence = analysis_result.get("confidence", 0)
        action_label = analysis_result.get("action", "HOLD")

        buy_threshold = self.config.get("buy_threshold", 65)
        sell_threshold = self.config.get("sell_threshold", 35)
        strong_buy = self.config.get("strong_buy_threshold", 80)
        strong_sell = self.config.get("strong_sell_threshold", 20)
        stop_loss = self.config.get("stop_loss_pct", 5)
        take_profit = self.config.get("take_profit_pct", 15)

        if position and position.get("quantity", 0) > 0:
            pnl_pct = position.get("unrealized_pnl_pct", 0)

            if pnl_pct <= -stop_loss:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=1.0,
                    quantity_pct=1.0,
                    reason=f"손절: {pnl_pct:.1f}% (한도 -{stop_loss}%)",
                    score=score, confidence=confidence)

            if pnl_pct >= take_profit:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=0.8,
                    quantity_pct=0.5,
                    reason=f"익절: {pnl_pct:.1f}% (한도 +{take_profit}%)",
                    score=score, confidence=confidence)

            if score < strong_sell:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=0.9,
                    quantity_pct=1.0,
                    reason=f"강력 매도 시그널: {score:.1f} (action: {action_label})",
                    score=score, confidence=confidence)

            if score < sell_threshold:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=0.6,
                    quantity_pct=0.5,
                    reason=f"매도 시그널: {score:.1f} (action: {action_label})",
                    score=score, confidence=confidence)

            return TradeSignal(
                ticker=ticker, action="hold", strength=0,
                quantity_pct=0,
                reason=f"홀드: score {score:.1f}, pnl {pnl_pct:.1f}%",
                score=score, confidence=confidence)

        if score >= strong_buy and confidence >= 0.5:
            return TradeSignal(
                ticker=ticker, action="buy", strength=0.9,
                quantity_pct=0.1,
                reason=f"강력 매수: {score:.1f} (신뢰도 {confidence:.1%}, {action_label})",
                score=score, confidence=confidence)

        if score >= buy_threshold and confidence >= 0.3:
            return TradeSignal(
                ticker=ticker, action="buy", strength=0.6,
                quantity_pct=0.05,
                reason=f"매수 시그널: {score:.1f} (신뢰도 {confidence:.1%}, {action_label})",
                score=score, confidence=confidence)

        return TradeSignal(
            ticker=ticker, action="hold", strength=0,
            quantity_pct=0,
            reason=f"관망: score {score:.1f} < threshold {buy_threshold}",
            score=score, confidence=confidence)


@register_strategy
class FinRLStrategy(BaseStrategy):
    """FinRL-X 가중치 기반 강화학습 전략

    학습된 DRL 모델이 종목별 포트폴리오 가중치를 출력.
    가중치 변화량으로 매수/매도/홀드 판단.
    모델이 없으면 signal_score 전략으로 폴백.
    """
    name = "finrl"

    def __init__(self, config: dict):
        super().__init__(config)
        self._model = None
        self._algo: str = ""
        self._tickers: list[str] = []
        self._current_weights: dict[str, float] = {}
        self._fallback = SignalScoreStrategy(config)
        self._load_model()

    def _load_model(self):
        import os
        try:
            from data.database import get_setting
            finrl_config = get_setting("finrl_config") or {}
            self._algo = finrl_config.get("active_algorithm", "ppo")
            self._tickers = finrl_config.get("tickers", [])

            finrl_results = get_setting("finrl_results") or {}
            best_weights = finrl_results.get("best_weights", {})
            if best_weights:
                self._current_weights = best_weights

            model_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "trained_models"
            )
            model_path = os.path.join(model_dir, f"agent_{self._algo}")

            if not os.path.exists(model_path + ".zip"):
                logger.warning(f"FinRL-X 모델 없음: {model_path}.zip → 폴백")
                return

            from stable_baselines3 import A2C, DDPG, PPO, SAC, TD3
            ALGO_CLASSES = {"a2c": A2C, "ddpg": DDPG, "ppo": PPO, "sac": SAC, "td3": TD3}

            cls = ALGO_CLASSES.get(self._algo)
            if cls is None:
                logger.warning(f"알 수 없는 알고리즘: {self._algo}")
                return

            self._model = cls.load(model_path)
            logger.info(f"FinRL-X 모델 로드: {self._algo.upper()} (weight-centric)")
        except Exception as e:
            logger.error(f"FinRL-X 모델 로드 실패: {e}")

    def evaluate(self, ticker: str, analysis_result: dict,
                 position: Optional[dict] = None) -> TradeSignal:
        if self._model is None:
            return self._fallback.evaluate(ticker, analysis_result, position)

        score = analysis_result.get("final_score", 50)
        confidence = analysis_result.get("confidence", 0)

        stop_loss = self.config.get("stop_loss_pct", 5)
        take_profit = self.config.get("take_profit_pct", 15)

        if position and position.get("quantity", 0) > 0:
            pnl_pct = position.get("unrealized_pnl_pct", 0)
            if pnl_pct <= -stop_loss:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=1.0,
                    quantity_pct=1.0,
                    reason=f"FinRL-X 손절: {pnl_pct:.1f}%",
                    score=score, confidence=confidence)
            if pnl_pct >= take_profit:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=0.8,
                    quantity_pct=0.5,
                    reason=f"FinRL-X 익절: {pnl_pct:.1f}%",
                    score=score, confidence=confidence)

        target_weight = self._current_weights.get(ticker, 0)
        equal_weight = 1.0 / max(len(self._tickers), 1)

        weight_delta = target_weight - equal_weight
        buy_threshold = self.config.get("weight_buy_threshold", 0.02)
        sell_threshold = self.config.get("weight_sell_threshold", -0.02)

        if weight_delta > buy_threshold:
            strength = min(weight_delta / 0.1, 1.0)
            return TradeSignal(
                ticker=ticker, action="buy",
                strength=strength,
                quantity_pct=target_weight,
                reason=f"FinRL-X 매수: weight={target_weight:.3f} (delta={weight_delta:+.3f})",
                score=score, confidence=confidence)
        elif weight_delta < sell_threshold:
            strength = min(abs(weight_delta) / 0.1, 1.0)
            qty_pct = min(abs(weight_delta) / equal_weight, 1.0) if equal_weight > 0 else 0.5
            return TradeSignal(
                ticker=ticker, action="sell",
                strength=strength,
                quantity_pct=qty_pct,
                reason=f"FinRL-X 매도: weight={target_weight:.3f} (delta={weight_delta:+.3f})",
                score=score, confidence=confidence)

        return TradeSignal(
            ticker=ticker, action="hold", strength=0,
            quantity_pct=0,
            reason=f"FinRL-X 관망: weight={target_weight:.3f}",
            score=score, confidence=confidence)


def get_strategy(name: str, config: dict) -> BaseStrategy:
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        logger.warning(f"전략 '{name}' 없음, signal_score 사용")
        cls = SignalScoreStrategy
    return cls(config)
