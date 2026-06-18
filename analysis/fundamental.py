"""펀더멘탈 분석 모듈 - yfinance 기반 밸류에이션/성장성/재무건전성"""

import yfinance as yf
import pandas as pd
import numpy as np


def get_fundamental_analysis(ticker: str, params: dict = None) -> dict:
    """종합 펀더멘탈 분석 실행.
    params: DB에서 로드한 펀더멘탈 분석 파라미터 (없으면 기본값 사용)
    """
    params = params or {}
    stock = yf.Ticker(ticker)
    info = stock.info

    valuation = _analyze_valuation(info, params.get("valuation", {}))
    growth = _analyze_growth(info, stock, params.get("growth", {}))
    quality = _analyze_quality(info, params.get("quality", {}))
    earnings = _analyze_earnings(info, stock, params.get("earnings", {}))

    scores = [
        valuation.get("score", 50),
        growth.get("score", 50),
        quality.get("score", 50),
        earnings.get("score", 50),
    ]
    weights = params.get("weights", {"valuation": 0.3, "growth": 0.3, "quality": 0.2, "earnings": 0.2})
    weighted_score = (
        valuation.get("score", 50) * weights.get("valuation", 0.3) +
        growth.get("score", 50) * weights.get("growth", 0.3) +
        quality.get("score", 50) * weights.get("quality", 0.2) +
        earnings.get("score", 50) * weights.get("earnings", 0.2)
    )

    grade = _score_to_grade(weighted_score)

    return {
        "ticker": ticker,
        "valuation": valuation,
        "growth": growth,
        "quality": quality,
        "earnings": earnings,
        "overall_score": round(weighted_score, 1),
        "grade": grade,
        "signals": _build_fundamental_signals(valuation, growth, quality, earnings),
    }


def _analyze_valuation(info: dict, params: dict) -> dict:
    pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    pb = info.get("priceToBook")
    ps = info.get("priceToSalesTrailing12Months")
    peg = info.get("pegRatio")
    ev_ebitda = info.get("enterpriseToEbitda")

    signals = []
    scores = []

    if pe is not None and pe > 0:
        pe_threshold = params.get("pe_expensive", 35)
        pe_cheap = params.get("pe_cheap", 15)
        if pe < pe_cheap:
            scores.append(80)
            signals.append(f"P/E {pe:.1f} (저평가)")
        elif pe > pe_threshold:
            scores.append(20)
            signals.append(f"P/E {pe:.1f} (고평가)")
        else:
            scores.append(50)
            signals.append(f"P/E {pe:.1f} (적정)")

    if forward_pe is not None and pe is not None and pe > 0:
        if forward_pe < pe * 0.8:
            scores.append(70)
            signals.append(f"Forward P/E {forward_pe:.1f} (이익 성장 기대)")
        elif forward_pe > pe * 1.2:
            scores.append(30)
            signals.append(f"Forward P/E {forward_pe:.1f} (이익 감소 우려)")

    if peg is not None and peg > 0:
        if peg < 1:
            scores.append(80)
            signals.append(f"PEG {peg:.2f} (성장 대비 저평가)")
        elif peg > 2:
            scores.append(25)
            signals.append(f"PEG {peg:.2f} (성장 대비 고평가)")
        else:
            scores.append(55)

    if pb is not None and pb > 0:
        if pb < 3:
            scores.append(65)
        elif pb > 10:
            scores.append(30)
        else:
            scores.append(50)

    avg_score = sum(scores) / len(scores) if scores else 50

    return {
        "pe": pe,
        "forward_pe": forward_pe,
        "pb": pb,
        "ps": ps,
        "peg": peg,
        "ev_ebitda": ev_ebitda,
        "score": round(avg_score, 1),
        "signals": signals,
    }


def _analyze_growth(info: dict, stock, params: dict) -> dict:
    revenue_growth = info.get("revenueGrowth")
    earnings_growth = info.get("earningsGrowth")
    quarterly_rev_growth = info.get("revenueQuarterlyGrowth")
    quarterly_earnings_growth = info.get("earningsQuarterlyGrowth")

    signals = []
    scores = []

    if revenue_growth is not None:
        rg_pct = revenue_growth * 100
        if rg_pct > 20:
            scores.append(85)
            signals.append(f"매출 성장 {rg_pct:.1f}% (고성장)")
        elif rg_pct > 5:
            scores.append(60)
            signals.append(f"매출 성장 {rg_pct:.1f}% (안정)")
        elif rg_pct > 0:
            scores.append(45)
            signals.append(f"매출 성장 {rg_pct:.1f}% (둔화)")
        else:
            scores.append(20)
            signals.append(f"매출 감소 {rg_pct:.1f}%")

    if earnings_growth is not None:
        eg_pct = earnings_growth * 100
        if eg_pct > 25:
            scores.append(85)
            signals.append(f"이익 성장 {eg_pct:.1f}% (고성장)")
        elif eg_pct > 0:
            scores.append(55)
            signals.append(f"이익 성장 {eg_pct:.1f}%")
        else:
            scores.append(20)
            signals.append(f"이익 감소 {eg_pct:.1f}%")

    if quarterly_earnings_growth is not None:
        qeg = quarterly_earnings_growth * 100
        if qeg > 30:
            scores.append(80)
            signals.append(f"분기 이익 {qeg:.1f}% 성장")

    avg_score = sum(scores) / len(scores) if scores else 50
    return {"revenue_growth": revenue_growth, "earnings_growth": earnings_growth,
            "score": round(avg_score, 1), "signals": signals}


def _analyze_quality(info: dict, params: dict) -> dict:
    roe = info.get("returnOnEquity")
    roa = info.get("returnOnAssets")
    profit_margin = info.get("profitMargins")
    operating_margin = info.get("operatingMargins")
    debt_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")
    fcf = info.get("freeCashflow")
    revenue = info.get("totalRevenue")

    signals = []
    scores = []

    if roe is not None:
        roe_pct = roe * 100
        if roe_pct > 20:
            scores.append(85)
            signals.append(f"ROE {roe_pct:.1f}% (우수)")
        elif roe_pct > 10:
            scores.append(60)
            signals.append(f"ROE {roe_pct:.1f}% (양호)")
        elif roe_pct > 0:
            scores.append(40)
        else:
            scores.append(15)
            signals.append(f"ROE {roe_pct:.1f}% (적자)")

    if profit_margin is not None:
        pm_pct = profit_margin * 100
        if pm_pct > 20:
            scores.append(80)
            signals.append(f"순이익률 {pm_pct:.1f}% (고수익)")
        elif pm_pct > 5:
            scores.append(55)
        else:
            scores.append(25)

    if debt_equity is not None:
        if debt_equity < 50:
            scores.append(80)
            signals.append(f"부채비율 {debt_equity:.0f}% (안정)")
        elif debt_equity < 100:
            scores.append(55)
        else:
            scores.append(25)
            signals.append(f"부채비율 {debt_equity:.0f}% (높음)")

    if fcf is not None and revenue is not None and revenue > 0:
        fcf_margin = fcf / revenue * 100
        if fcf_margin > 15:
            scores.append(80)
            signals.append(f"FCF 마진 {fcf_margin:.1f}%")
        elif fcf_margin > 0:
            scores.append(55)
        else:
            scores.append(20)

    avg_score = sum(scores) / len(scores) if scores else 50
    return {"roe": roe, "profit_margin": profit_margin, "debt_equity": debt_equity,
            "score": round(avg_score, 1), "signals": signals}


def _analyze_earnings(info: dict, stock, params: dict) -> dict:
    recommendation = info.get("recommendationKey", "none")
    target_price = info.get("targetMeanPrice")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    num_analysts = info.get("numberOfAnalystOpinions", 0)

    signals = []
    scores = []

    rec_scores = {"strong_buy": 90, "buy": 75, "overweight": 65,
                  "hold": 50, "underweight": 35, "sell": 25, "strong_sell": 10}
    if recommendation in rec_scores:
        scores.append(rec_scores[recommendation])
        signals.append(f"애널리스트: {recommendation} ({num_analysts}명)")

    if target_price and current_price and current_price > 0:
        upside = (target_price - current_price) / current_price * 100
        if upside > 20:
            scores.append(80)
            signals.append(f"목표가 ${target_price:.0f} (상승여력 {upside:.1f}%)")
        elif upside > 0:
            scores.append(60)
            signals.append(f"목표가 ${target_price:.0f} (상승여력 {upside:.1f}%)")
        else:
            scores.append(30)
            signals.append(f"목표가 ${target_price:.0f} (하락여력 {upside:.1f}%)")

    institutional = info.get("heldPercentInstitutions")
    if institutional is not None:
        inst_pct = institutional * 100
        if inst_pct > 70:
            scores.append(65)
            signals.append(f"기관 보유 {inst_pct:.1f}%")
        elif inst_pct < 30:
            scores.append(40)

    avg_score = sum(scores) / len(scores) if scores else 50
    return {"recommendation": recommendation, "target_price": target_price,
            "num_analysts": num_analysts, "score": round(avg_score, 1), "signals": signals}


def _score_to_grade(score: float) -> str:
    if score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 35:
        return "D"
    return "F"


def _build_fundamental_signals(valuation, growth, quality, earnings) -> list[dict]:
    """펀더멘탈 시그널을 기술적 시그널과 동일한 형식으로 변환"""
    result = []

    v_score = valuation.get("score", 50)
    v_dir = "buy" if v_score >= 65 else ("sell" if v_score <= 35 else "neutral")
    result.append({
        "name": "Valuation",
        "value": f"{v_score:.0f}점",
        "signal": "; ".join(valuation.get("signals", [])[:2]) or "정보 부족",
        "direction": v_dir,
        "score": v_score,
        "confidence": 0.6,
    })

    g_score = growth.get("score", 50)
    g_dir = "buy" if g_score >= 65 else ("sell" if g_score <= 35 else "neutral")
    result.append({
        "name": "Growth",
        "value": f"{g_score:.0f}점",
        "signal": "; ".join(growth.get("signals", [])[:2]) or "정보 부족",
        "direction": g_dir,
        "score": g_score,
        "confidence": 0.5,
    })

    q_score = quality.get("score", 50)
    q_dir = "buy" if q_score >= 65 else ("sell" if q_score <= 35 else "neutral")
    result.append({
        "name": "Quality",
        "value": f"{q_score:.0f}점",
        "signal": "; ".join(quality.get("signals", [])[:2]) or "정보 부족",
        "direction": q_dir,
        "score": q_score,
        "confidence": 0.55,
    })

    e_score = earnings.get("score", 50)
    e_dir = "buy" if e_score >= 65 else ("sell" if e_score <= 35 else "neutral")
    result.append({
        "name": "Analyst",
        "value": f"{e_score:.0f}점",
        "signal": "; ".join(earnings.get("signals", [])[:2]) or "정보 부족",
        "direction": e_dir,
        "score": e_score,
        "confidence": 0.5,
    })

    return result
