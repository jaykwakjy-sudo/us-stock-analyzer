"""시그널 스코어링 & 가중 합산 엔진

모든 가중치와 임계값은 외부(DB)에서 주입됨.
"""


def aggregate_signals(technical_signals: list[dict],
                      fundamental_signals: list[dict],
                      weights: dict = None) -> dict:
    """기술적 + 펀더멘탈 시그널을 가중 합산하여 최종 판단.

    weights 예시:
    {
        "technical": {
            "trend": 0.25, "momentum": 0.25, "volatility": 0.15,
            "volume": 0.15, "pattern": 0.20
        },
        "fundamental": {
            "valuation": 0.30, "growth": 0.30, "quality": 0.20, "analyst": 0.20
        },
        "blend": {"technical": 0.6, "fundamental": 0.4}
    }
    """
    weights = weights or _default_weights()

    tech_score, tech_confidence, tech_details = _score_category(
        technical_signals, weights.get("technical", {}))
    fund_score, fund_confidence, fund_details = _score_category(
        fundamental_signals, weights.get("fundamental", {}))

    blend = weights.get("blend", {"technical": 0.6, "fundamental": 0.4})
    tech_w = blend.get("technical", 0.6)
    fund_w = blend.get("fundamental", 0.4)

    if tech_confidence == 0 and fund_confidence == 0:
        final_score = 50
        final_confidence = 0
    elif fund_confidence == 0:
        final_score = tech_score
        final_confidence = tech_confidence * 0.7
    elif tech_confidence == 0:
        final_score = fund_score
        final_confidence = fund_confidence * 0.7
    else:
        final_score = tech_score * tech_w + fund_score * fund_w
        final_confidence = tech_confidence * tech_w + fund_confidence * fund_w

    conflict_ratio = _measure_conflict(technical_signals + fundamental_signals)
    if conflict_ratio > 0.4:
        final_confidence *= (1 - conflict_ratio * 0.5)

    action, action_kr = _score_to_action(final_score, final_confidence,
                                          weights.get("thresholds", {}))

    buy_count = sum(1 for s in technical_signals + fundamental_signals if s.get("direction") == "buy")
    sell_count = sum(1 for s in technical_signals + fundamental_signals if s.get("direction") == "sell")
    neutral_count = sum(1 for s in technical_signals + fundamental_signals if s.get("direction") == "neutral")

    return {
        "action": action,
        "action_kr": action_kr,
        "final_score": round(final_score, 1),
        "confidence": round(final_confidence, 3),
        "conflict_ratio": round(conflict_ratio, 3),
        "technical_score": round(tech_score, 1),
        "fundamental_score": round(fund_score, 1),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "neutral_count": neutral_count,
        "all_signals": technical_signals + fundamental_signals,
        "reasoning": _build_reasoning(action, technical_signals, fundamental_signals,
                                       tech_score, fund_score, conflict_ratio),
    }


def _default_weights():
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


CATEGORY_MAP = {
    "SMA": "trend", "EMA": "trend", "ADX": "trend",
    "Ichimoku": "trend", "PSAR": "trend",
    "RSI": "momentum", "MACD": "momentum", "Stochastic": "momentum",
    "Williams %R": "momentum", "CCI": "momentum", "MFI": "momentum",
    "Bollinger": "volatility", "ATR": "volatility", "Keltner": "volatility",
    "OBV": "volume", "Volume": "volume", "A/D Line": "volume", "CMF": "volume",
    "Candlestick": "pattern", "S/R": "pattern", "Fibonacci": "pattern",
    "Valuation": "valuation", "Growth": "growth", "Quality": "quality", "Analyst": "analyst",
}


def _score_category(signals: list[dict], category_weights: dict) -> tuple:
    if not signals:
        return 50, 0, {}

    by_cat = {}
    for s in signals:
        cat = CATEGORY_MAP.get(s.get("name", ""), "other")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(s)

    weighted_score = 0
    total_weight = 0
    total_confidence = 0

    for cat, cat_signals in by_cat.items():
        w = category_weights.get(cat, 1.0 / max(len(by_cat), 1))
        cat_scores = [s.get("score", 50) for s in cat_signals if s.get("confidence", 0) > 0]
        cat_confs = [s.get("confidence", 0) for s in cat_signals]

        if cat_scores:
            avg = sum(cat_scores) / len(cat_scores)
            avg_conf = sum(cat_confs) / len(cat_confs)
            weighted_score += avg * w
            total_weight += w
            total_confidence += avg_conf * w

    if total_weight > 0:
        final = weighted_score / total_weight
        conf = total_confidence / total_weight
    else:
        final = 50
        conf = 0

    return final, conf, by_cat


def _measure_conflict(signals: list[dict]) -> float:
    """시그널 간 충돌 비율 (0~1)"""
    valid = [s for s in signals if s.get("direction") in ("buy", "sell") and s.get("confidence", 0) > 0.3]
    if len(valid) < 2:
        return 0

    buy = sum(1 for s in valid if s["direction"] == "buy")
    sell = sum(1 for s in valid if s["direction"] == "sell")
    total = buy + sell
    if total == 0:
        return 0

    minority = min(buy, sell)
    return minority / total


def _score_to_action(score: float, confidence: float, thresholds: dict) -> tuple[str, str]:
    min_conf = thresholds.get("min_confidence", 0.3)

    if confidence < min_conf:
        return "HOLD", "관망 (신뢰도 부족)"

    sb = thresholds.get("strong_buy", 75)
    b = thresholds.get("buy", 60)
    ss = thresholds.get("strong_sell", 25)
    s = thresholds.get("sell", 40)

    if score >= sb:
        return "STRONG_BUY", "적극 매수"
    elif score >= b:
        return "BUY", "매수"
    elif score <= ss:
        return "STRONG_SELL", "적극 매도"
    elif score <= s:
        return "SELL", "매도"
    else:
        return "HOLD", "관망"


def _build_reasoning(action, tech_signals, fund_signals, tech_score, fund_score, conflict) -> str:
    parts = []
    parts.append(f"기술 점수 {tech_score:.0f}, 펀더멘탈 점수 {fund_score:.0f}")

    strong_tech = [s for s in tech_signals if abs(s.get("score", 50) - 50) > 25 and s.get("confidence", 0) > 0.5]
    if strong_tech:
        names = ", ".join(s["name"] for s in strong_tech[:3])
        parts.append(f"주요 기술 시그널: {names}")

    strong_fund = [s for s in fund_signals if abs(s.get("score", 50) - 50) > 20]
    if strong_fund:
        names = ", ".join(s["name"] for s in strong_fund[:2])
        parts.append(f"주요 펀더멘탈: {names}")

    if conflict > 0.3:
        parts.append(f"시그널 충돌 {conflict:.0%} (신뢰도 감점)")

    return ". ".join(parts)
