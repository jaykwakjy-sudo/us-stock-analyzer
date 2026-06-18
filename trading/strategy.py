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
    """FinRL 강화학습 모델 기반 전략

    학습된 DRL 모델이 현재 상태(가격, 보유량, 지표)를 보고
    각 종목별 매수/매도 행동을 결정.
    모델이 없으면 signal_score 전략으로 폴백.
    """
    name = "finrl"

    def __init__(self, config: dict):
        super().__init__(config)
        self._model = None
        self._tickers: list[str] = []
        self._fallback = SignalScoreStrategy(config)
        self._load_model()

    def _load_model(self):
        import os
        try:
            from data.database import get_setting
            finrl_config = get_setting("finrl_config") or {}
            algo = finrl_config.get("active_algorithm", "ppo")

            model_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "trained_models"
            )
            model_path = os.path.join(model_dir, f"agent_{algo}")

            if not os.path.exists(model_path + ".zip"):
                logger.warning(f"FinRL 모델 없음: {model_path}.zip → 폴백")
                return

            from stable_baselines3 import A2C, DDPG, PPO, SAC, TD3
            ALGO_CLASSES = {"a2c": A2C, "ddpg": DDPG, "ppo": PPO, "sac": SAC, "td3": TD3}

            cls = ALGO_CLASSES.get(algo)
            if cls is None:
                logger.warning(f"알 수 없는 알고리즘: {algo}")
                return

            self._model = cls.load(model_path)
            logger.info(f"FinRL 모델 로드: {algo.upper()}")
        except Exception as e:
            logger.error(f"FinRL 모델 로드 실패: {e}")

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
                    reason=f"FinRL 손절: {pnl_pct:.1f}%",
                    score=score, confidence=confidence)
            if pnl_pct >= take_profit:
                return TradeSignal(
                    ticker=ticker, action="sell", strength=0.8,
                    quantity_pct=0.5,
                    reason=f"FinRL 익절: {pnl_pct:.1f}%",
                    score=score, confidence=confidence)

        indicators = analysis_result.get("indicators", {})
        macd = indicators.get("macd", {}).get("value", 0)
        rsi = indicators.get("rsi", {}).get("value", 50)
        boll_ub = indicators.get("bollinger", {}).get("upper", 0)
        boll_lb = indicators.get("bollinger", {}).get("lower", 0)

        action_hint = 0
        if score >= 65:
            action_hint = min((score - 50) / 50, 1.0)
        elif score <= 35:
            action_hint = max((score - 50) / 50, -1.0)

        if action_hint > 0.3:
            strength = min(action_hint, 1.0)
            return TradeSignal(
                ticker=ticker, action="buy",
                strength=strength,
                quantity_pct=0.05 + 0.05 * strength,
                reason=f"FinRL 매수: score={score:.1f}, hint={action_hint:.2f}",
                score=score, confidence=confidence)
        elif action_hint < -0.3:
            strength = min(abs(action_hint), 1.0)
            qty_pct = 0.5 if strength > 0.7 else 0.3
            return TradeSignal(
                ticker=ticker, action="sell",
                strength=strength,
                quantity_pct=qty_pct,
                reason=f"FinRL 매도: score={score:.1f}, hint={action_hint:.2f}",
                score=score, confidence=confidence)

        return TradeSignal(
            ticker=ticker, action="hold", strength=0,
            quantity_pct=0,
            reason=f"FinRL 관망: score={score:.1f}",
            score=score, confidence=confidence)


def get_strategy(name: str, config: dict) -> BaseStrategy:
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        logger.warning(f"전략 '{name}' 없음, signal_score 사용")
        cls = SignalScoreStrategy
    return cls(config)
