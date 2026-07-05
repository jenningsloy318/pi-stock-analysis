#!/usr/bin/env python3
"""Compute deterministic 1-10 component scores from script outputs.

Usage:
    compute_scores.py \
        --metrics ./reports/AAPL/metrics.json \
        --macro ./reports/macro.json \
        --technicals ./reports/[TICKER]/tech.json \
        --alternatives ./reports/[TICKER]/alt-data.json \
        --sentiment ./reports/[TICKER]/sentiment.json \
        --capital-structure ./reports/[TICKER]/capital_structure.json \
        --report-type long \
        [--gics-sector 45] \
        [--output ./reports/[TICKER]/scores.json]

Produces reproducible, rubric-based 1-10 scores for 11 conviction
components: Financial Health, Moat Quality, Management Quality, Valuation
Attractiveness, Macro Tailwind, Risk Profile, Alternative Alignment,
Technical Setup, Capital Structure, Weinstein Alignment, and CANSLIM.

Then computes the final conviction rating using the per-report-type
weighted formulas, applying override rules (component ≤3 caps at Hold,
3+ missing components forces Low confidence).
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Scoring utilities
# ---------------------------------------------------------------------------


def _clamp(score: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, round(score, 1)))


def _time_decay_weight(n: int, decay: float = 0.90) -> list[float]:
    """Generate exponential time-decay weights for a series of length n.

    Most recent value gets weight 1.0, older values decay exponentially.
    Useful for RS, momentum, revision signals where recent data matters more.

    Args:
        n: Length of the time series.
        decay: Decay factor per period (0.90 = 10% decay per period).

    Returns:
        List of weights [oldest, ..., newest] normalized to sum to 1.0.
    """
    if n <= 0:
        return []
    raw = [decay ** (n - 1 - i) for i in range(n)]
    total = sum(raw)
    return [w / total for w in raw] if total > 0 else [1.0 / n] * n


def _weighted_mean(values: list[float], weights: list[float]) -> float | None:
    """Compute weighted mean. Returns None if inputs are empty or mismatched."""
    if not values or len(values) != len(weights):
        return None
    total_w = sum(weights)
    if total_w == 0:
        return None
    return sum(v * w for v, w in zip(values, weights)) / total_w


def _score_from_percentile(
    value: float | None,
    bullish_25: float,
    bullish_75: float,
    bearish_25: float,
    bearish_75: float,
    higher_is_better: bool = True,
) -> float | None:
    """Map a value to 1-10 using percentile-style thresholds.

    bullish_25/75: thresholds where score transitions from 5→7.5→10
    bearish_25/75: thresholds where score transitions from 5→2.5→1
    """
    if value is None:
        return None
    # Guard: if bullish_25 == bullish_75, simple threshold scoring to avoid division by zero
    if bullish_75 == bullish_25:
        return 7.5 if value >= bullish_25 else 5.0
    if higher_is_better:
        if value >= bullish_75:
            return 9.0 + (value - bullish_75) / (bullish_75 * 2)  # 9-10 range
        elif value >= bullish_25:
            return 6.0 + 3.0 * (value - bullish_25) / (bullish_75 - bullish_25)
        elif value >= bearish_75:
            return 4.0 + 2.0 * (value - bearish_75) / (bullish_25 - bearish_75)
        elif value >= bearish_25:
            return 1.5 + 2.5 * (value - bearish_25) / (bearish_75 - bearish_25)
        else:
            return 1.0
    else:
        # Lower is better (e.g., debt/equity)
        if value <= bearish_25:
            return 9.0 + (bearish_25 - value) / max(bearish_25 * 2, 0.01)
        elif value <= bearish_75:
            return 6.0 + 3.0 * (bearish_75 - value) / (bearish_75 - bearish_25)
        elif value <= bullish_25:
            return 4.0 + 2.0 * (bullish_25 - value) / (bullish_25 - bearish_75)
        elif value <= bullish_75:
            return 1.5 + 2.5 * (bullish_75 - value) / (bullish_75 - bullish_25)
        else:
            return 1.0


# ---------------------------------------------------------------------------
# 1. Financial Health Score (1-10)
# ---------------------------------------------------------------------------


def compute_financial_health(metrics: dict, sector: int | None = None) -> dict:
    """Score financial health from computed metrics.

    Weights: Margin quality (25%), ROE/ROIC (20%), Leverage (20%),
             FCF generation (20%), Growth stability (15%).
    """
    ratios = metrics.get("ratios", {})
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}
    weights: dict[str, float] = {
        "margin_quality": 0.25,
        "roe_roic": 0.20,
        "leverage": 0.20,
        "fcf_generation": 0.20,
        "growth_stability": 0.15,
    }

    # --- Margin Quality ---
    op_margin = ratios.get("operating_margin")
    net_margin = ratios.get("net_margin")
    score_margin = None
    if op_margin is not None:
        # Sector-adjusted thresholds
        if sector in (45, 50):  # Tech, Comm Services
            score_margin = _score_from_percentile(op_margin, 0.20, 0.35, 0.10, 0.05)
        elif sector == 35:  # Health Care
            score_margin = _score_from_percentile(op_margin, 0.25, 0.40, 0.12, 0.05)
        elif (
            sector == 60
        ):  # REITs — NOI margins are naturally high; use lenient thresholds
            score_margin = _score_from_percentile(op_margin, 0.30, 0.50, 0.20, 0.10)
        elif sector == 20:  # Industrials — lower margins, higher asset turns
            score_margin = _score_from_percentile(op_margin, 0.12, 0.20, 0.06, 0.03)
        elif sector == 15:  # Materials/Mining — commodity-driven, cyclical margins
            score_margin = _score_from_percentile(op_margin, 0.15, 0.30, 0.08, 0.03)
        elif sector == 30:  # Consumer Staples
            score_margin = _score_from_percentile(op_margin, 0.15, 0.25, 0.08, 0.03)
        elif sector == 10:  # Energy — highly cyclical, FCF matters more than margins
            score_margin = _score_from_percentile(op_margin, 0.15, 0.30, 0.05, 0.00)
        elif sector == 25:  # Consumer Discretionary — wide range by sub-industry
            score_margin = _score_from_percentile(op_margin, 0.10, 0.20, 0.05, 0.02)
        elif sector == 55:  # Utilities — regulated, stable but low margins
            score_margin = _score_from_percentile(op_margin, 0.15, 0.25, 0.10, 0.05)
        else:
            score_margin = _score_from_percentile(op_margin, 0.15, 0.25, 0.08, 0.03)
        if score_margin:
            reasons.append(
                f"Operating margin: {op_margin:.1%} → sub-score {score_margin:.1f}"
            )
    # Margin trajectory bonus/penalty
    margin_traj = ratios.get("margin_trajectory")
    if margin_traj and score_margin is not None:
        trend = margin_traj.get("trend", "stable")
        if trend == "expanding":
            score_margin = min(10.0, score_margin + 0.5)
            reasons.append("Margin trajectory: expanding (+0.5)")
        elif trend == "contracting":
            score_margin = max(1.0, score_margin - 0.5)
            reasons.append("Margin trajectory: contracting (-0.5)")
    sub_scores["margin_quality"] = score_margin

    # --- ROE / ROIC ---
    roe = ratios.get("roe")
    roic = ratios.get("roic")
    incremental_roic = ratios.get("incremental_roic")
    dupont = ratios.get("dupont", {})
    negative_equity = dupont.get("negative_equity", False)
    score_roe = None
    if negative_equity and roic is not None:
        # Negative equity (buyback-heavy companies like SBUX, MCD, PM) — use ROIC instead
        score_roe = _score_from_percentile(roic, 0.12, 0.20, 0.06, 0.02)
        reasons.append(
            f"Negative equity → using ROIC: {roic:.1%} (substituted for ROE) → sub-score {score_roe:.1f}"
        )
    elif roe is not None:
        # Penalize leverage-driven ROE
        leverage_driven = dupont.get("interpretation", {}).get("leverage_driven", False)
        if leverage_driven:
            score_roe = _score_from_percentile(roe, 0.20, 0.35, 0.10, 0.05)
            reasons.append(
                f"ROE: {roe:.1%} (leverage-driven → penalized) → sub-score {score_roe:.1f}"
            )
        else:
            score_roe = _score_from_percentile(roe, 0.12, 0.20, 0.06, 0.02)
            reasons.append(
                f"ROE: {roe:.1%} (operationally-driven) → sub-score {score_roe:.1f}"
            )
    sub_scores["roe_roic"] = score_roe
    # Incremental ROIC bonus: high incremental ROIC means new capital is deployed well
    if incremental_roic is not None and score_roe is not None:
        if incremental_roic > 0.20:
            score_roe = min(10.0, score_roe + 0.5)
            reasons.append(f"Incremental ROIC: {incremental_roic:.1%} (>20% → +0.5)")
        elif incremental_roic < 0.0:
            score_roe = max(1.0, score_roe - 0.5)
            reasons.append(
                f"Incremental ROIC: {incremental_roic:.1%} (negative → -0.5)"
            )
        sub_scores["roe_roic"] = score_roe

    # --- Leverage ---
    debt_to_equity = ratios.get("debt_to_equity")
    net_debt = ratios.get("net_debt")
    score_leverage = None
    if debt_to_equity is not None:
        if (
            sector == 60
        ):  # REITs — higher leverage is structural, use lenient thresholds
            score_leverage = _score_from_percentile(
                debt_to_equity, 1.0, 2.5, 0.5, 1.2, higher_is_better=False
            )
        elif sector == 40:  # Financials — also higher leverage structural
            score_leverage = _score_from_percentile(
                debt_to_equity, 2.0, 5.0, 1.0, 2.0, higher_is_better=False
            )
        elif sector == 15:  # Materials/Mining — capex-heavy, moderate leverage ok
            score_leverage = _score_from_percentile(
                debt_to_equity, 0.7, 2.0, 0.4, 1.0, higher_is_better=False
            )
        elif sector == 10:  # Energy — capital-intensive, tolerate higher leverage
            score_leverage = _score_from_percentile(
                debt_to_equity, 0.6, 1.8, 0.3, 0.9, higher_is_better=False
            )
        elif sector == 55:  # Utilities — regulated, high leverage is structural
            score_leverage = _score_from_percentile(
                debt_to_equity, 1.5, 3.0, 0.8, 1.5, higher_is_better=False
            )
        elif sector == 25:  # Consumer Discretionary — moderate leverage acceptable
            score_leverage = _score_from_percentile(
                debt_to_equity, 0.6, 1.5, 0.3, 0.8, higher_is_better=False
            )
        else:
            score_leverage = _score_from_percentile(
                debt_to_equity, 0.5, 1.5, 0.3, 0.8, higher_is_better=False
            )
        if score_leverage:
            reasons.append(
                f"Debt/Equity: {debt_to_equity:.2f} → sub-score {score_leverage:.1f}"
            )
    elif net_debt is not None:
        # Approximate from net debt
        adj_leverage = 1.0 if net_debt > 0 else 0.3
        score_leverage = _score_from_percentile(
            adj_leverage, 0.5, 1.5, 0.3, 0.8, higher_is_better=False
        )
    # Current ratio adjustment: penalize weak liquidity
    current_ratio = ratios.get("current_ratio")
    if current_ratio is not None and score_leverage is not None:
        if current_ratio < 1.0:
            score_leverage = max(1.0, score_leverage - 1.0)
            reasons.append(
                f"Current ratio: {current_ratio:.2f} (<1.0 → -1.0 leverage penalty)"
            )
        elif current_ratio > 2.0:
            score_leverage = min(10.0, score_leverage + 0.3)
            reasons.append(
                f"Current ratio: {current_ratio:.2f} (>2.0 → +0.3 liquidity bonus)"
            )
    sub_scores["leverage"] = score_leverage

    # --- FCF Generation ---
    fcf_yield = ratios.get("fcf_yield")
    ocf_to_ni = ratios.get("ocf_to_ni")
    score_fcf = None
    signals = []
    if fcf_yield is not None:
        fcf_score = _score_from_percentile(fcf_yield, 0.03, 0.08, 0.01, 0.0)
        signals.append(f"FCF yield: {fcf_yield:.1%}")
    else:
        fcf_score = 5.0
    if ocf_to_ni is not None:
        if ocf_to_ni < 0.7:
            fcf_score = min(fcf_score or 5.0, 3.0)
            signals.append(f"OCF/NI: {ocf_to_ni:.2f} (poor quality)")
    if signals:
        score_fcf = _clamp(fcf_score or 5.0)
        reasons.append(f"FCF signals: {'; '.join(signals)} → sub-score {score_fcf:.1f}")
    sub_scores["fcf_generation"] = score_fcf

    # --- Growth Stability ---
    rev_cagr = ratios.get("revenue_cagr_5yr")
    ni_cagr = ratios.get("ni_cagr_5yr")
    fcf_cagr = ratios.get("fcf_cagr_5yr")
    score_growth = None
    if rev_cagr is not None and ni_cagr is not None:
        avg_growth = (rev_cagr + ni_cagr) / 2
        # High growth good, but negative is bad, and extreme growth unsustainable
        if avg_growth > 0.30:
            gscore = 7.0  # High but flag as potentially unsustainable
        elif avg_growth > 0.15:
            gscore = 8.5
        elif avg_growth > 0.08:
            gscore = 7.0
        elif avg_growth > 0.03:
            gscore = 5.5
        elif avg_growth > 0:
            gscore = 4.0
        else:
            gscore = 2.0
        # Stability: if NI CAGR and FCF CAGR diverge wildly, penalize
        if fcf_cagr is not None and rev_cagr is not None:
            divergence = abs(rev_cagr - fcf_cagr)
            if divergence > 0.15:
                gscore -= 1.5
                reasons.append(f"Revenue/FCF growth divergence: {divergence:.1%}")
        score_growth = _clamp(gscore)
        reasons.append(
            f"Avg revenue/NI CAGR: {avg_growth:.1%} → sub-score {score_growth:.1f}"
        )
    sub_scores["growth_stability"] = score_growth

    # Composite
    valid = {k: v for k, v in sub_scores.items() if v is not None}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    total = sum(valid[k] * weights[k] for k in valid)
    total /= sum(weights[k] for k in valid)
    final = _clamp(total)

    if final >= 7.5:
        assessment = (
            "Excellent — expanding margins, strong FCF, low leverage, consistent growth"
        )
    elif final >= 6.0:
        assessment = "Good — healthy but not exceptional across all dimensions"
    elif final >= 4.5:
        assessment = "Adequate — mixed signals, some metrics below sector norms"
    elif final >= 3.0:
        assessment = "Weak — multiple metrics concerning, warrants caution"
    else:
        assessment = "Poor — significant financial distress indicators"

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "sub_score_weights": weights,
        "reasons": reasons,
        "methodology": "Financial Health = Margin(25%) + ROE(20%) + Leverage(20%) + FCF(20%) + Growth(15%)",
    }


# ---------------------------------------------------------------------------
# 2. Moat Quality Score (1-10)
# ---------------------------------------------------------------------------


def compute_moat_quality(metrics: dict, sector: int | None = None) -> dict:
    """Score competitive moat from DISTINCT indicators (no overlap with Financial Health).

    Sub-metrics (designed to avoid double-counting with Financial Health):
    1. Gross Margin Stability (25%): CV of gross margin over 5 years — pricing power
    2. ROIC vs WACC Spread Persistence (25%): sustained excess returns — moat durability
    3. Revenue Retention Rate (25%): absence of revenue declines — customer stickiness
    4. Market Share Trend (25%): revenue growth vs industry — competitive position
    """
    ratios = metrics.get("ratios", {})
    eva_data = metrics.get("economic_value_added", {})
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}

    # --- 1. Gross Margin Stability (CV of gross margin over available years) ---
    score_gm_stability = None
    margin_traj = ratios.get("margin_trajectory")
    if margin_traj and isinstance(margin_traj, dict):
        gm_history = margin_traj.get("history", [])
        if len(gm_history) >= 3:
            mean_gm = statistics.mean(gm_history)
            if mean_gm > 0:
                stdev_gm = statistics.stdev(gm_history)
                cv = stdev_gm / mean_gm
                # Score: CV < 0.05 = 10, CV > 0.20 = 2
                if cv < 0.05:
                    score_gm_stability = 10.0
                elif cv < 0.08:
                    score_gm_stability = 8.5
                elif cv < 0.12:
                    score_gm_stability = 7.0
                elif cv < 0.15:
                    score_gm_stability = 5.5
                elif cv < 0.20:
                    score_gm_stability = 4.0
                else:
                    score_gm_stability = 2.0
                reasons.append(
                    f"Gross margin CV: {cv:.3f} (over {len(gm_history)} years, mean={mean_gm:.1%}) → stability {score_gm_stability:.1f}"
                )
            else:
                score_gm_stability = 2.0
                reasons.append("Gross margin mean ≤ 0 → no pricing power")
    sub_scores["gross_margin_stability"] = score_gm_stability

    # --- 2. ROIC vs WACC Spread Persistence ---
    score_spread = None
    roic = ratios.get("roic")
    # Get WACC from EVA data or from ratios
    wacc = eva_data.get("wacc") if eva_data else None
    if wacc is None:
        # Default WACC assumption if not computed
        wacc = 0.09  # 9% reasonable default for spread calculation
    if roic is not None:
        spread_pp = (roic - wacc) * 100  # in percentage points
        # Score: spread > 15pp = 10, spread < 0 = 2
        if spread_pp > 15:
            score_spread = 10.0
        elif spread_pp > 10:
            score_spread = 8.5
        elif spread_pp > 6:
            score_spread = 7.0
        elif spread_pp > 3:
            score_spread = 5.5
        elif spread_pp > 0:
            score_spread = 4.0
        elif spread_pp > -3:
            score_spread = 3.0
        else:
            score_spread = 2.0
        reasons.append(
            f"ROIC-WACC spread: {spread_pp:.1f}pp (ROIC={roic:.1%}, WACC={wacc:.1%}) → {score_spread:.1f}"
        )
    sub_scores["roic_wacc_spread"] = score_spread

    # --- 3. Revenue Retention Rate (absence of declines = sticky customers) ---
    score_retention = None
    rev_cagr = ratios.get("revenue_cagr_5yr")
    ni_cagr = ratios.get("ni_cagr_5yr")
    if rev_cagr is not None:
        # Use CAGR as proxy: strongly positive = no meaningful declines
        # Negative CAGR implies at least some years had declines
        if rev_cagr >= 0.10:
            score_retention = 10.0  # Strong consistent growth — no declines
        elif rev_cagr >= 0.05:
            score_retention = 8.5
        elif rev_cagr >= 0.02:
            score_retention = 7.0
        elif rev_cagr >= 0.0:
            score_retention = 5.5  # Flat but no decline
        elif rev_cagr >= -0.05:
            score_retention = 4.0  # Mild decline
        elif rev_cagr >= -0.10:
            score_retention = 3.0
        else:
            score_retention = 2.0  # Significant revenue loss > 20% decline somewhere
        reasons.append(
            f"Revenue CAGR 5yr: {rev_cagr:.1%} → retention proxy {score_retention:.1f}"
        )
    sub_scores["revenue_retention"] = score_retention

    # --- 4. Market Share Trend (rev growth vs industry benchmark) ---
    score_mkt_share = None
    # Industry growth proxy: use sector-typical growth rates
    sector_growth_benchmarks = {
        45: 0.10,  # Technology — high secular growth
        35: 0.08,  # Healthcare
        25: 0.05,  # Consumer Discretionary
        30: 0.03,  # Consumer Staples
        20: 0.04,  # Industrials
        10: 0.02,  # Energy — low organic growth
        15: 0.03,  # Materials
        40: 0.04,  # Financials
        50: 0.06,  # Communication Services
        55: 0.02,  # Utilities
        60: 0.03,  # Real Estate
    }
    industry_growth = sector_growth_benchmarks.get(sector, 0.04) if sector else 0.04

    if rev_cagr is not None:
        excess_growth_pp = (rev_cagr - industry_growth) * 100
        # Score: +10pp excess = 10, -10pp = 2
        if excess_growth_pp >= 10:
            score_mkt_share = 10.0
        elif excess_growth_pp >= 6:
            score_mkt_share = 8.5
        elif excess_growth_pp >= 3:
            score_mkt_share = 7.0
        elif excess_growth_pp >= 0:
            score_mkt_share = 5.5
        elif excess_growth_pp >= -3:
            score_mkt_share = 4.5
        elif excess_growth_pp >= -6:
            score_mkt_share = 3.5
        elif excess_growth_pp >= -10:
            score_mkt_share = 2.5
        else:
            score_mkt_share = 2.0
        reasons.append(
            f"Rev growth vs industry: {excess_growth_pp:+.1f}pp (rev={rev_cagr:.1%}, industry≈{industry_growth:.1%}) → {score_mkt_share:.1f}"
        )
    sub_scores["market_share_trend"] = score_mkt_share

    # --- Sector premium (tech/healthcare get structural moat bonus) ---
    sector_bonus = 0.0
    if sector in (45, 35):  # Tech, Healthcare
        sector_bonus = 0.5
        reasons.append(f"GICS {sector}: sector structural moat bonus +{sector_bonus}")

    valid = {k: v for k, v in sub_scores.items() if v is not None}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    weights = {
        "gross_margin_stability": 0.25,
        "roic_wacc_spread": 0.25,
        "revenue_retention": 0.25,
        "market_share_trend": 0.25,
    }
    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid)
    total += sector_bonus
    final = _clamp(total)

    if final >= 7.5:
        assessment = "Wide moat — stable margins, persistent excess returns, growing market share"
    elif final >= 6.0:
        assessment = (
            "Narrow moat — some competitive advantages but not fully entrenched"
        )
    elif final >= 4.0:
        assessment = "No moat — returns near cost of capital, market share stagnant"
    else:
        assessment = (
            "Moat erosion — declining share, narrowing spreads, unstable margins"
        )

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "adjustable": True,
        "adjustment_range": [-2.0, 2.0],
        "adjustment_note": "LLM agent may adjust ±2.0 based on qualitative moat analysis (Morningstar framework findings)",
        "methodology": "Moat = GM_Stability(25%) + ROIC-WACC_Spread(25%) + Revenue_Retention(25%) + Market_Share_Trend(25%) + SectorBonus",
    }


# ---------------------------------------------------------------------------
# 3. Management Quality Score (1-10)
# ---------------------------------------------------------------------------


def compute_management_quality(metrics: dict, sentiment: dict | None = None) -> dict:
    """Score management quality from quantitative proxies.

    Adjustable ±2.0 by LLM agent based on qualitative leadership assessment.
    """
    ratios = metrics.get("ratios", {})
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}

    # --- Capital Allocation (ROIC vs WACC spread proxy via ROE or ROIC) ---
    roe = ratios.get("roe")
    roic = ratios.get("roic")
    dupont = ratios.get("dupont", {})
    negative_equity = dupont.get("negative_equity", False)
    # Use ROIC instead of ROE when equity is negative (buyback-heavy companies)
    capital_metric = roic if negative_equity and roic is not None else roe
    capital_metric_name = "ROIC" if (negative_equity and roic is not None) else "ROE"
    score_capital = None
    if capital_metric is not None:
        if capital_metric > 0.20:
            score_capital = 8.5
        elif capital_metric > 0.14:
            score_capital = 7.0
        elif capital_metric > 0.10:
            score_capital = 5.5
        elif capital_metric > 0.05:
            score_capital = 4.0
        else:
            score_capital = 2.0
        reasons.append(
            f"{capital_metric_name} {capital_metric:.1%} → capital allocation proxy {score_capital:.1f}"
        )
        if negative_equity:
            reasons.append("(Negative equity from buybacks — substituted ROIC for ROE)")
    sub_scores["capital_allocation"] = score_capital

    # --- Insider Activity ---
    score_insider = 5.0  # Neutral default
    if sentiment:
        insider = sentiment.get("insider", {})
        summary = insider.get("summary", {})
        buys = summary.get("buys_count", 0)
        sells = summary.get("sells_count", 0)
        clusters = insider.get("cluster_detection") or []

        if buys > sells * 2 and any(
            c.get("type") == "cluster_buying" for c in clusters
        ):
            score_insider = 9.0
            reasons.append(
                f"Strong insider buying: {buys} buys vs {sells} sells with cluster"
            )
        elif buys > sells:
            score_insider = 7.0
            reasons.append(f"Net insider buying: {buys} buys vs {sells} sells")
        elif sells > buys * 3:
            score_insider = 2.0
            reasons.append(f"Heavy insider selling: {sells} sells vs {buys} buys")
        elif sells > buys:
            score_insider = 4.0
            reasons.append(f"Net insider selling: {sells} sells vs {buys} buys")
        if any(c.get("type") == "cluster_buying" for c in clusters):
            reasons.append("Cluster buying detected — strong bullish signal")
        if any(c.get("type") == "cluster_selling" for c in clusters):
            reasons.append("Cluster selling detected — bearish signal")
            score_insider = min(score_insider, 3.0)
    sub_scores["insider_activity"] = score_insider

    # --- Guidance Accuracy (earnings beat streak proxy) ---
    score_guidance = 5.0
    if sentiment:
        earnings = sentiment.get("earnings", {})
        beat_streak = earnings.get("beat_streak", 0)
        if beat_streak >= 4:
            score_guidance = 9.0
            reasons.append(f"Consistent earnings beats: {beat_streak}-quarter streak")
        elif beat_streak >= 2:
            score_guidance = 7.0
            reasons.append(f"Recent earnings beats: {beat_streak}-quarter streak")
        elif beat_streak == 1:
            score_guidance = 6.0
        else:
            # Check for misses
            surprises = earnings.get("past_surprises", [])
            misses = sum(
                1
                for s in surprises
                if s.get("surprise") is not None and s["surprise"] < 0
            )
            if misses >= 2:
                score_guidance = 3.0
                reasons.append(f"{misses} earnings misses in recent quarters")
    sub_scores["guidance_accuracy"] = score_guidance

    # --- Shareholder returns (buyback + dividend) ---
    score_shareholder = 5.0
    # No direct buyback data in current scripts; leave as neutral
    sub_scores["shareholder_returns"] = score_shareholder

    weights = {
        "capital_allocation": 0.40,
        "insider_activity": 0.35,
        "guidance_accuracy": 0.25,
    }
    valid = {
        k: v
        for k, v in sub_scores.items()
        if k != "shareholder_returns" and v is not None
    }
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid)
    final = _clamp(total)

    if final >= 7.5:
        assessment = "Excellent — strong capital allocation, insider alignment, consistent delivery"
    elif final >= 6.0:
        assessment = "Good — competent management with some areas for improvement"
    elif final >= 4.0:
        assessment = "Adequate — mixed signals, some governance concerns"
    else:
        assessment = "Poor — significant management concerns or misalignment"

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "adjustable": True,
        "adjustment_range": [-2.0, 2.0],
        "adjustment_note": "LLM agent may adjust ±2.0 based on qualitative leadership assessment (Fisher's 15 points, Glassdoor trends, CEO track record)",
        "methodology": "Management = CapitalAlloc(40%) + Insider(35%) + Guidance(25%)",
    }


# ---------------------------------------------------------------------------
# 4. Valuation Attractiveness Score (1-10)
# ---------------------------------------------------------------------------


def compute_valuation(metrics: dict, sector: int | None = None) -> dict:
    """Score valuation attractiveness from DCF, comps, and reverse DCF."""
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}

    # --- DCF Margin of Safety ---
    dcf = metrics.get("dcf_valuation", {})
    dcf_value = dcf.get("per_share_value")
    ratios = metrics.get("ratios", {})
    pe = ratios.get("pe_ratio")
    score_dcf = None
    if dcf_value and pe:
        # Approximate current price from P/E * EPS
        eps = ratios.get("eps")
        if eps:
            current_price = pe * eps
            mos = (
                (dcf_value - current_price) / current_price if current_price > 0 else 0
            )
            if mos > 0.30:
                score_dcf = 9.5
            elif mos > 0.15:
                score_dcf = 8.0
            elif mos > 0.05:
                score_dcf = 6.5
            elif mos > -0.05:
                score_dcf = 5.0
            elif mos > -0.15:
                score_dcf = 3.5
            elif mos > -0.30:
                score_dcf = 2.0
            else:
                score_dcf = 1.0
            reasons.append(
                f"DCF margin of safety: {mos:.1%} → sub-score {score_dcf:.1f}"
            )
    sub_scores["dcf_mos"] = score_dcf

    # Damodaran-aligned: Adjust DCF confidence based on terminal value sensitivity
    # High TV% is NORMAL for growth — don't abandon DCF, but note reduced precision
    tv_sensitivity = dcf.get("tv_sensitivity", "LOW")
    if score_dcf is not None and tv_sensitivity == "HIGH":
        # Pull DCF score toward neutral (5.0) by 30% — reflects higher uncertainty
        score_dcf_adj = score_dcf * 0.7 + 5.0 * 0.3
        reasons.append(
            f"DCF terminal-value-sensitive (TV>85%): score moderated {score_dcf:.1f}→{score_dcf_adj:.1f} "
            f"(Damodaran: normal for growth, but assumption-dependent)"
        )
        score_dcf = round(score_dcf_adj, 1)
        sub_scores["dcf_mos"] = score_dcf

    # --- P/E vs history / sector ---
    score_pe = None
    if pe and pe > 0:
        # Sector-adjusted P/E expectations
        if sector in (45, 50):  # Tech, Comm Services — growth justifies higher P/E
            pe_tiers = (15, 22, 30, 40, 55)
        elif sector == 35:  # Healthcare — pipeline optionality justifies premium
            pe_tiers = (12, 18, 25, 35, 50)
        elif sector in (55, 60):  # Utilities, REITs — yield plays, lower P/E expected
            pe_tiers = (8, 12, 16, 20, 28)
        elif sector == 10:  # Energy — cyclical, use normalized P/E
            pe_tiers = (6, 10, 14, 20, 30)
        elif sector == 40:  # Financials — P/B more relevant, but P/E still useful
            pe_tiers = (8, 12, 15, 20, 30)
        else:  # Industrials, Consumer, Materials — moderate expectations
            pe_tiers = (10, 15, 20, 25, 35)
        if pe < pe_tiers[0]:
            score_pe = 9.0
        elif pe < pe_tiers[1]:
            score_pe = 7.5
        elif pe < pe_tiers[2]:
            score_pe = 6.0
        elif pe < pe_tiers[3]:
            score_pe = 5.0
        elif pe < pe_tiers[4]:
            score_pe = 3.5
        else:
            score_pe = 1.5
        # Percentile-based correction: tech stocks (sector 45) with PE > 40 are overvalued
        if sector == 45 and pe > 40:
            score_pe = min(score_pe, 4.0)
        reasons.append(
            f"P/E: {pe:.1f} (GICS {sector or 'generic'} adjusted) → sub-score {score_pe:.1f}"
        )
    sub_scores["pe_level"] = score_pe

    # --- PEG Ratio (Lynch) ---
    peg = ratios.get("peg_ratio")
    score_peg = None
    if peg is not None:
        if peg < 0.8:
            score_peg = 9.0
        elif peg < 1.2:
            score_peg = 7.5
        elif peg < 1.8:
            score_peg = 6.0
        elif peg < 2.5:
            score_peg = 4.5
        else:
            score_peg = 2.5
        reasons.append(f"PEG: {peg:.2f} → sub-score {score_peg:.1f}")
    sub_scores["peg_ratio"] = score_peg

    # --- FCF Yield vs Risk-Free ---
    fcf_yield = ratios.get("fcf_yield")
    score_fcf_yield = None
    if fcf_yield is not None:
        if fcf_yield > 0.08:
            score_fcf_yield = 9.0
        elif fcf_yield > 0.05:
            score_fcf_yield = 7.5
        elif fcf_yield > 0.03:
            score_fcf_yield = 5.5
        elif fcf_yield > 0.01:
            score_fcf_yield = 3.5
        else:
            score_fcf_yield = 1.5
        reasons.append(f"FCF yield: {fcf_yield:.1%} → sub-score {score_fcf_yield:.1f}")
    sub_scores["fcf_yield"] = score_fcf_yield

    # --- Reverse DCF ---
    rev_dcf = metrics.get("reverse_dcf", {})
    implied_growth = rev_dcf.get("implied_growth_rate")
    rev_cagr = ratios.get("revenue_cagr_5yr")
    score_reverse = None
    if implied_growth is not None and rev_cagr is not None:
        gap = implied_growth - rev_cagr
        if gap < -0.05:
            score_reverse = 9.0  # Market underpricing growth
        elif gap < 0:
            score_reverse = 7.0
        elif gap < 0.05:
            score_reverse = 5.0
        elif gap < 0.10:
            score_reverse = 3.0
        else:
            score_reverse = 1.5  # Market pricing unrealistic growth
        reasons.append(
            f"Reverse DCF implied growth {implied_growth:.1%} vs historical {rev_cagr:.1%} → sub-score {score_reverse:.1f}"
        )
    sub_scores["reverse_dcf"] = score_reverse

    # --- Earnings Yield (Greenblatt Magic Formula) ---
    earnings_yield = ratios.get("earnings_yield")
    score_ey = None
    if earnings_yield is not None and earnings_yield > 0:
        if earnings_yield > 0.12:
            score_ey = 9.0
        elif earnings_yield > 0.08:
            score_ey = 7.5
        elif earnings_yield > 0.05:
            score_ey = 5.5
        elif earnings_yield > 0.03:
            score_ey = 3.5
        else:
            score_ey = 2.0
        reasons.append(
            f"Earnings yield (EBIT/EV): {earnings_yield:.1%} → sub-score {score_ey:.1f}"
        )
    sub_scores["earnings_yield"] = score_ey

    weights = {
        "dcf_mos": 0.25,
        "pe_level": 0.15,
        "peg_ratio": 0.15,
        "fcf_yield": 0.15,
        "reverse_dcf": 0.15,
        "earnings_yield": 0.15,
    }
    valid = {k: v for k, v in sub_scores.items() if v is not None}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid)
    final = _clamp(total)

    if final >= 7.5:
        assessment = (
            "Significantly undervalued — large margin of safety, attractive multiples"
        )
    elif final >= 6.0:
        assessment = "Moderately undervalued — reasonable price for quality"
    elif final >= 4.5:
        assessment = "Fairly valued — price near intrinsic, no margin of safety"
    elif final >= 3.0:
        assessment = "Moderately overvalued — premium pricing, limited upside"
    else:
        assessment = (
            "Significantly overvalued — extreme multiples, unrealistic growth priced in"
        )

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "methodology": "Valuation = DCF_MoS(25%) + PE(15%) + PEG(15%) + FCF_Yield(15%) + ReverseDCF(15%) + EarningsYield(15%)",
    }


# ---------------------------------------------------------------------------
# 5. Macro Tailwind Score (1-10)
# ---------------------------------------------------------------------------


def compute_macro_tailwind(macro: dict, metrics: dict | None = None) -> dict:
    """Score macro environment favorability.

    10 = strong tailwinds, 1 = strong headwinds, 5 = neutral.
    """
    summary = macro.get("macro_summary", {})
    indicators = macro.get("indicators", {})
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}

    # --- Dalio Regime ---
    regime = summary.get("macro_regime", "unknown")
    if regime == "goldilocks":
        score_regime = 8.5
        reasons.append(
            "Goldilocks regime (rising growth + stable inflation) — optimal for equities"
        )
    elif regime == "reflation":
        score_regime = 6.5
        reasons.append(
            "Reflation regime (rising growth + rising inflation) — favorable but watch rates"
        )
    elif regime == "deflation":
        score_regime = 4.0
        reasons.append(
            "Deflationary regime (falling growth + low inflation) — challenging for equities"
        )
    elif regime == "stagflation":
        score_regime = 2.0
        reasons.append(
            "Stagflation regime (falling growth + rising inflation) — worst for equities"
        )
    else:
        score_regime = 5.0
        reasons.append("Unknown/ambiguous macro regime")
    sub_scores["dalio_regime"] = score_regime

    # --- Yield Curve ---
    key_levels = summary.get("key_levels", {})
    inverted = key_levels.get("yield_curve_inverted", False)
    spread = key_levels.get("ten_two_spread")
    if inverted:
        score_yc = 2.5
        spread_str = f"{spread:.2f}%" if spread is not None else "N/A"
        reasons.append(f"Yield curve inverted ({spread_str}) — recession signal active")
    elif spread is not None and spread < 0.5:
        score_yc = 4.0
        reasons.append(f"Yield curve flat ({spread:.2f}%) — caution")
    else:
        score_yc = 6.5
        spread_str = f"{spread:.2f}%" if spread is not None else "data unavailable"
        reasons.append(f"Yield curve normal ({spread_str}) — no recession signal")
    sub_scores["yield_curve"] = score_yc

    # --- PMI ---
    pmi = key_levels.get("ism_pmi")
    if pmi is not None:
        if pmi > 55:
            score_pmi = 8.0
            reasons.append(f"PMI {pmi:.1f} — strong expansion")
        elif pmi > 50:
            score_pmi = 6.0
            reasons.append(f"PMI {pmi:.1f} — mild expansion")
        elif pmi > 45:
            score_pmi = 4.0
            reasons.append(f"PMI {pmi:.1f} — contraction warning")
        else:
            score_pmi = 2.0
            reasons.append(f"PMI {pmi:.1f} — significant contraction")
        sub_scores["pmi"] = score_pmi

    # --- Recession Risk ---
    recession = summary.get("recession_risk", "unknown")
    if recession == "low":
        score_recession = 7.5
    elif recession == "elevated":
        score_recession = 4.5
    elif recession == "high":
        score_recession = 2.0
    else:
        score_recession = 5.0
    reasons.append(f"Recession risk: {recession}")
    sub_scores["recession_risk"] = score_recession

    # --- Fed Direction ---
    ff_rate = key_levels.get("fed_funds_rate")
    # Compare to 6-month trend in macro data
    fed_data = indicators.get("DFF", {}).get("data", [])
    if len(fed_data) >= 2:
        recent = fed_data[0].get("value", 0) or 0
        prior_6m = fed_data[min(5, len(fed_data) - 1)].get("value", 0) or 0
        if recent < prior_6m * 0.9:
            # Fed cutting → bullish
            score_fed = 8.0
            reasons.append("Fed cutting rates — accommodative")
        elif recent > prior_6m * 1.05:
            score_fed = 3.0
            reasons.append("Fed hiking rates — restrictive")
        else:
            score_fed = 5.5
            reasons.append("Fed on hold — neutral")
    else:
        score_fed = 5.0
    sub_scores["fed_direction"] = score_fed

    weights = {
        "dalio_regime": 0.30,
        "yield_curve": 0.20,
        "pmi": 0.15,
        "recession_risk": 0.20,
        "fed_direction": 0.15,
    }
    valid = {k: v for k, v in sub_scores.items() if v is not None}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid)
    final = _clamp(total)

    if final >= 7.0:
        assessment = (
            "Strong macro tailwinds — expansionary, accommodative, low recession risk"
        )
    elif final >= 5.5:
        assessment = "Mild tailwinds — generally favorable with some caution areas"
    elif final >= 4.0:
        assessment = "Mixed — some headwinds offsetting tailwinds"
    elif final >= 2.5:
        assessment = "Headwinds dominating — multiple macro concerns"
    else:
        assessment = "Strong headwinds — recessionary signals, restrictive policy"

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "methodology": "Macro = DalioRegime(30%) + YieldCurve(20%) + PMI(15%) + RecessionRisk(20%) + FedDirection(15%)",
    }


# ---------------------------------------------------------------------------
# 6. Risk Profile Score (1-10)
# ---------------------------------------------------------------------------


def compute_risk_profile(metrics: dict) -> dict:
    """Score risk profile. Higher = lower risk (safer)."""
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}
    ratios = metrics.get("ratios", {})

    # --- Altman Z-Score ---
    altman = metrics.get("altman_zscore", {})
    zscore = altman.get("zscore")
    zone = altman.get("zone", "")
    score_altman = None
    if zscore is not None:
        if zone == "Safe":
            score_altman = 9.0
            reasons.append(f"Altman Z: {zscore:.2f} (Safe zone)")
        elif zone == "Grey":
            score_altman = 5.0
            reasons.append(f"Altman Z: {zscore:.2f} (Grey zone — monitor)")
        else:
            score_altman = 2.0
            reasons.append(
                f"Altman Z: {zscore:.2f} (Distress zone — elevated bankruptcy risk)"
            )
    sub_scores["altman_z"] = score_altman

    # --- Beneish M-Score ---
    beneish = metrics.get("beneish_mscore", {})
    mscore = beneish.get("mscore")
    flagged = beneish.get("flag", False)
    score_beneish = None
    if flagged:
        score_beneish = 2.0
        reasons.append(f"Beneish M-Score: {mscore:.2f} (> -1.78 → manipulation risk)")
    elif mscore is not None:
        score_beneish = 8.0
        reasons.append(f"Beneish M-Score: {mscore:.2f} (clean)")
    sub_scores["beneish_m"] = score_beneish

    # --- Leverage ---
    debt_eq = ratios.get("debt_to_equity")
    score_leverage = None
    if debt_eq is not None:
        if debt_eq < 0.5:
            score_leverage = 9.0
        elif debt_eq < 1.0:
            score_leverage = 7.5
        elif debt_eq < 2.0:
            score_leverage = 5.0
        elif debt_eq < 3.5:
            score_leverage = 3.0
        else:
            score_leverage = 1.5
        reasons.append(f"Debt/Equity: {debt_eq:.2f} → sub-score {score_leverage:.1f}")
    sub_scores["leverage"] = score_leverage

    # --- FCF / OCF quality ---
    ocf_to_ni = ratios.get("ocf_to_ni")
    score_cf_quality = None
    if ocf_to_ni is not None:
        if ocf_to_ni > 1.2:
            score_cf_quality = 9.0
        elif ocf_to_ni > 0.9:
            score_cf_quality = 7.0
        elif ocf_to_ni > 0.7:
            score_cf_quality = 5.0
        else:
            score_cf_quality = 2.5
        reasons.append(f"OCF/NI: {ocf_to_ni:.2f} → sub-score {score_cf_quality:.1f}")
    sub_scores["cash_flow_quality"] = score_cf_quality

    # --- EPS Growth stability ---
    ni_cagr = ratios.get("ni_cagr_5yr")
    score_earnings_stability = None
    if ni_cagr is not None:
        if ni_cagr > 0.10:
            score_earnings_stability = 8.0
        elif ni_cagr > 0.03:
            score_earnings_stability = 6.0
        elif ni_cagr > -0.05:
            score_earnings_stability = 4.0
        else:
            score_earnings_stability = 2.0
    sub_scores["earnings_stability"] = score_earnings_stability

    weights = {
        "altman_z": 0.25,
        "beneish_m": 0.25,
        "leverage": 0.20,
        "cash_flow_quality": 0.20,
        "earnings_stability": 0.10,
    }
    valid = {k: v for k, v in sub_scores.items() if v is not None}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid)
    final = _clamp(total)

    if final >= 7.5:
        assessment = (
            "Low risk — strong balance sheet, clean forensic signals, quality earnings"
        )
    elif final >= 6.0:
        assessment = "Moderate risk — manageable but some areas warrant monitoring"
    elif final >= 4.0:
        assessment = "Elevated risk — multiple concerns, hedge or reduce position"
    else:
        assessment = (
            "High risk — active red flags, potential for permanent capital loss"
        )

    # Red flag detection
    red_flags = []
    if flagged:
        red_flags.append("Beneish M-Score flagged (> -1.78)")
    if zone == "Distress":
        red_flags.append("Altman Z in Distress zone (< 1.81)")
    if ocf_to_ni is not None and ocf_to_ni < 0.7:
        red_flags.append(f"Poor OCF/NI quality ({ocf_to_ni:.2f})")
    if debt_eq is not None and debt_eq > 3.5:
        red_flags.append(f"Excessive leverage ({debt_eq:.2f})")

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "red_flags": red_flags,
        "red_flag_count": len(red_flags),
        "override": len(red_flags) >= 3,  # 3+ red flags → no Buy rating
        "methodology": "Risk = AltmanZ(25%) + BeneishM(25%) + Leverage(20%) + CFQuality(20%) + EarnStability(10%)",
    }


# ---------------------------------------------------------------------------
# 7. Alternative Alignment Score (1-10)
# ---------------------------------------------------------------------------


def compute_alternative_alignment(alternatives: dict) -> dict:
    """Score alternative data alignment with reported fundamentals.

    Higher = alternative data confirms/exceeds reported trends.
    """
    alt_data = alternatives.get("alternative_data", {})
    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}
    null_count = 0
    total_sources = 0

    # --- Web Traffic ---
    web = alt_data.get("web", {})
    total_sources += 1
    if (
        web
        and web.get("source") != "unavailable_paywall"
        and web.get("search_interest_trend")
    ):
        trend = web.get("search_interest_trend")
        if trend == "rising":
            sub_scores["web_traffic"] = 8.0
        elif trend == "stable":
            sub_scores["web_traffic"] = 6.0
        elif trend == "declining":
            sub_scores["web_traffic"] = 3.0
        else:
            sub_scores["web_traffic"] = 5.0
        reasons.append(f"Web search interest: {trend}")
    else:
        null_count += 1

    # --- Social Sentiment ---
    social = alt_data.get("social", {})
    total_sources += 1
    if social and social.get("reddit_sentiment_score") is not None:
        sent = social["reddit_sentiment_score"]
        if sent > 0.3:
            sub_scores["social_sentiment"] = 8.5
        elif sent > 0.1:
            sub_scores["social_sentiment"] = 7.0
        elif sent > -0.1:
            sub_scores["social_sentiment"] = 5.0
        elif sent > -0.3:
            sub_scores["social_sentiment"] = 3.0
        else:
            sub_scores["social_sentiment"] = 1.5
        reasons.append(f"Reddit sentiment: {sent:.3f}")
    else:
        # Try Finnhub social as fallback
        null_count += 1

    # --- Patents ---
    patents = alt_data.get("patents", {})
    total_sources += 1
    if patents and patents.get("recent_patents", 0) > 0:
        count = patents.get("recent_patents", 0)
        if count > 50:
            sub_scores["innovation"] = 9.0
        elif count > 20:
            sub_scores["innovation"] = 7.5
        elif count > 5:
            sub_scores["innovation"] = 6.0
        else:
            sub_scores["innovation"] = 4.0
        reasons.append(f"Recent patents: {count}")
    else:
        null_count += 1

    # --- Glassdoor ---
    glassdoor = alt_data.get("glassdoor", {})
    total_sources += 1
    if glassdoor and glassdoor.get("overall_rating") is not None:
        rating = glassdoor["overall_rating"]
        if rating > 4.0:
            sub_scores["employee_sentiment"] = 8.5
        elif rating > 3.5:
            sub_scores["employee_sentiment"] = 6.5
        elif rating > 3.0:
            sub_scores["employee_sentiment"] = 5.0
        else:
            sub_scores["employee_sentiment"] = 3.0
        reasons.append(f"Glassdoor rating: {rating}")
    else:
        null_count += 1

    # --- Hiring ---
    total_sources += 1
    hiring = alt_data.get("hiring", {})
    if hiring and hiring.get("source") != "unavailable_paywall":
        pass  # Would score if data available
    else:
        null_count += 1

    # --- Transactions ---
    total_sources += 1
    txn = alt_data.get("transactions", {})
    if txn and txn.get("source") != "unavailable_paywall":
        pass
    else:
        null_count += 1

    sub_score_weights = {
        "web_traffic": 0.20,
        "social_sentiment": 0.20,
        "innovation": 0.20,
        "employee_sentiment": 0.20,
        "hiring": 0.10,
        "transactions": 0.10,
    }
    valid = {k: v for k, v in sub_scores.items()}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
            "data_availability": f"{total_sources - null_count}/{total_sources} sources",
        }

    total = sum(valid[k] * sub_score_weights.get(k, 0.17) for k in valid)
    total /= sum(sub_score_weights.get(k, 0.17) for k in valid)
    final = _clamp(total)

    if final >= 7.0:
        assessment = "Alternative data confirms/exceeds reported trends"
    elif final >= 5.0:
        assessment = "Mixed — some alt signals align, some neutral"
    elif final >= 3.5:
        assessment = "Alternative data diverging negative — potential early warning"
    else:
        assessment = "Significant negative divergence — investigate further"

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "data_availability": f"{total_sources - null_count}/{total_sources} sources",
        "methodology": "AltAlign = Web(20%) + Social(20%) + Innovation(20%) + Employee(20%) + Hiring(10%) + Txn(10%)",
    }


# ---------------------------------------------------------------------------
# 8. Technical Setup Score (1-10)
# ---------------------------------------------------------------------------


def compute_technical_setup(technicals: dict) -> dict:
    """Score technical setup quality from computed indicators."""
    # Handle per-ticker structure from fetch_technicals.py
    if not technicals:
        return {"score": None, "assessment": "insufficient_data"}

    # Find the first ticker's data
    ticker_data = None
    for key, val in technicals.items():
        if isinstance(val, dict) and "trend_strength" in val:
            ticker_data = val
            break

    if not ticker_data:
        return {"score": None, "assessment": "insufficient_data"}

    trend = ticker_data.get("trend_strength", {})
    momentum = ticker_data.get("momentum", {})
    setup_quality = ticker_data.get("setup_quality")
    volume = ticker_data.get("volume", {})
    reasons: list[str] = []

    # Use pre-computed composite if available
    if setup_quality is not None:
        final = _clamp(setup_quality)
        reasons.append(f"Pre-computed setup quality: {setup_quality}")
    else:
        # Combine trend + momentum scores
        t_score = trend.get("score", 5.0) or 5.0
        m_score = momentum.get("score", 5.0) or 5.0
        final = _clamp((t_score + m_score) / 2)
        reasons.append(f"Trend: {t_score}, Momentum: {m_score} → composite {final}")

    if trend.get("assessment"):
        reasons.append(f"Trend: {trend['assessment']}")
    if momentum.get("assessment"):
        reasons.append(f"Momentum: {momentum['assessment']}")
    if volume.get("assessment"):
        reasons.append(f"Volume: {volume['assessment']}")

    if final >= 7.0:
        assessment = "Strong technical setup — trend + momentum aligned bullishly"
    elif final >= 5.5:
        assessment = "Moderate setup — positive bias but not all signals confirming"
    elif final >= 4.5:
        assessment = "Neutral — range-bound or mixed signals"
    elif final >= 3.0:
        assessment = "Weak setup — bearish bias, negative momentum"
    else:
        assessment = "Broken setup — strong bearish trend, distribution"

    return {
        "score": final,
        "assessment": assessment,
        "trend_score": trend.get("score"),
        "momentum_score": momentum.get("score"),
        "reasons": reasons,
        "methodology": "Technical = avg(TrendScore, MomentumScore); adjusted for volume signals",
    }


# ---------------------------------------------------------------------------
# 9. Capital Structure Score (1-10)
# ---------------------------------------------------------------------------


def compute_capital_structure(capital_data: dict) -> dict:
    """Score capital structure and shareholder returns quality.

    Higher = better capital allocation (buybacks at discount, low dilution,
    optimal leverage, strong total capital return).
    """
    if not capital_data:
        return {"score": None, "assessment": "insufficient_data"}

    reasons: list[str] = []
    sub_scores: dict[str, float | None] = {}

    # --- Buyback Effectiveness ---
    buyback = capital_data.get("buyback_analysis", {})
    buyback_roi = buyback.get("buyback_roi_annualized")
    score_buyback = None
    if buyback_roi is not None:
        if buyback_roi > 0.15:
            score_buyback = 9.0
        elif buyback_roi > 0.08:
            score_buyback = 7.5
        elif buyback_roi > 0.0:
            score_buyback = 5.5
        elif buyback_roi > -0.10:
            score_buyback = 3.5
        else:
            score_buyback = 1.5
        reasons.append(
            f"Buyback ROI: {buyback_roi:.1%} → sub-score {score_buyback:.1f}"
        )
    sub_scores["buyback_effectiveness"] = score_buyback

    # --- SBC Dilution ---
    sbc = capital_data.get("sbc_dilution", {})
    sbc_pct = sbc.get("sbc_to_revenue")
    score_sbc = None
    if sbc_pct is not None:
        if sbc_pct < 0.02:
            score_sbc = 9.0
        elif sbc_pct < 0.05:
            score_sbc = 7.0
        elif sbc_pct < 0.10:
            score_sbc = 5.0
        elif sbc_pct < 0.15:
            score_sbc = 3.0
        else:
            score_sbc = 1.5
        reasons.append(f"SBC/Revenue: {sbc_pct:.1%} → sub-score {score_sbc:.1f}")
    sub_scores["sbc_dilution"] = score_sbc

    # --- Total Capital Return ---
    cap_return = capital_data.get("capital_return", {})
    total_yield = cap_return.get("total_capital_return_yield")
    # total_capital_return_yield may be a nested dict (from fetch_capital_structure.py)
    # with a 'total_yield' sub-key. Extract the scalar if needed.
    if isinstance(total_yield, dict):
        total_yield = total_yield.get("total_yield")
    score_return = None
    if total_yield is not None:
        if total_yield > 0.06:
            score_return = 9.0
        elif total_yield > 0.04:
            score_return = 7.5
        elif total_yield > 0.02:
            score_return = 6.0
        elif total_yield > 0.0:
            score_return = 4.5
        else:
            score_return = 2.5
        reasons.append(
            f"Total capital return yield: {total_yield:.1%} → sub-score {score_return:.1f}"
        )
    sub_scores["total_return"] = score_return

    # --- Leverage Optimality (distance from optimal WACC point) ---
    structure = capital_data.get("capital_structure", {})
    wacc_current = structure.get("wacc_current")
    wacc_sensitivity = structure.get("wacc_sensitivity", [])
    score_leverage_opt = None
    if wacc_current is not None and wacc_sensitivity:
        min_wacc = min(
            (s.get("wacc", 1.0) for s in wacc_sensitivity), default=wacc_current
        )
        gap = wacc_current - min_wacc
        if gap < 0.005:
            score_leverage_opt = 9.0
        elif gap < 0.01:
            score_leverage_opt = 7.0
        elif gap < 0.02:
            score_leverage_opt = 5.0
        else:
            score_leverage_opt = 3.0
        reasons.append(
            f"WACC gap from optimal: {gap:.2%} → sub-score {score_leverage_opt:.1f}"
        )
    sub_scores["leverage_optimality"] = score_leverage_opt

    weights = {
        "buyback_effectiveness": 0.30,
        "sbc_dilution": 0.25,
        "total_return": 0.25,
        "leverage_optimality": 0.20,
    }
    valid = {k: v for k, v in sub_scores.items() if v is not None}
    if not valid:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "sub_scores": sub_scores,
            "reasons": reasons,
        }

    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid)
    final = _clamp(total)

    if final >= 7.5:
        assessment = "Excellent capital allocation — buybacks at discount, low dilution, strong returns"
    elif final >= 6.0:
        assessment = "Good — generally shareholder-friendly capital decisions"
    elif final >= 4.0:
        assessment = (
            "Adequate — mixed capital allocation, some dilution or misallocation"
        )
    else:
        assessment = (
            "Poor — value-destructive buybacks, excessive SBC, or suboptimal leverage"
        )

    return {
        "score": final,
        "assessment": assessment,
        "sub_scores": sub_scores,
        "reasons": reasons,
        "methodology": "CapStructure = Buyback(30%) + SBC(25%) + TotalReturn(25%) + LeverageOpt(20%)",
    }


# ---------------------------------------------------------------------------
# 10. Weinstein Stage Alignment Score (1-10)
# ---------------------------------------------------------------------------


def compute_weinstein_alignment(technicals: dict) -> dict:
    """Score Weinstein stage alignment for timing purposes.

    Stage 2 (advancing) = highest score for longs.
    Stage 4 (declining) = lowest score for longs.
    """
    if not technicals:
        return {"score": None, "assessment": "insufficient_data"}

    ticker_data = None
    for key, val in technicals.items():
        if isinstance(val, dict) and "weinstein_stage" in val:
            ticker_data = val
            break

    if not ticker_data or "weinstein_stage" not in ticker_data:
        return {"score": None, "assessment": "No Weinstein data available"}

    weinstein = ticker_data["weinstein_stage"]
    stage = weinstein.get("stage")
    stage_name = weinstein.get("stage_name", "")
    slope = weinstein.get("wma_slope_4wk", 0)

    reasons: list[str] = []
    score = 5.0

    if stage == 2:
        score = 9.0 if slope > 0.2 else 7.5
        reasons.append(f"Weinstein Stage 2 (Advancing) — 30WMA slope: {slope:.4f}")
    elif stage == 1:
        score = 5.5
        reasons.append("Weinstein Stage 1 (Basing) — accumulation phase")
    elif stage == 3:
        score = 3.5
        reasons.append("Weinstein Stage 3 (Topping) — distribution phase")
    elif stage == 4:
        score = 1.5
        reasons.append("Weinstein Stage 4 (Declining) — avoid or short")

    # Relative strength bonus/penalty (time-decay weighted: recent RS matters more)
    rs = ticker_data.get("relative_strength", {})
    composite_rs = rs.get("composite_rs")
    rs_1m = rs.get("rs_1m")
    rs_3m = rs.get("rs_3m")
    rs_6m = rs.get("rs_6m")

    # Prefer time-decay weighted RS when multi-period data available
    effective_rs = None
    if rs_1m is not None and rs_3m is not None:
        rs_values = [v for v in [rs_6m, rs_3m, rs_1m] if v is not None]
        rs_weights = _time_decay_weight(len(rs_values), decay=0.75)
        effective_rs = _weighted_mean(rs_values, rs_weights)
    if effective_rs is None:
        effective_rs = composite_rs

    if effective_rs is not None:
        if effective_rs > 10.0:
            score = min(10.0, score + 1.0)
            reasons.append(
                f"RS (decay-weighted) {effective_rs:.2f}pp > 10pp — outperforming market"
            )
        elif effective_rs < -10.0:
            score = max(1.0, score - 1.0)
            reasons.append(
                f"RS (decay-weighted) {effective_rs:.2f}pp < -10pp — underperforming market"
            )

    final = _clamp(score)

    if final >= 7.0:
        assessment = f"Stage {stage} ({stage_name}) — favorable for long positions"
    elif final >= 5.0:
        assessment = f"Stage {stage} ({stage_name}) — neutral, wait for confirmation"
    else:
        assessment = f"Stage {stage} ({stage_name}) — unfavorable for new longs"

    return {
        "score": final,
        "assessment": assessment,
        "stage": stage,
        "stage_name": stage_name,
        "reasons": reasons,
        "methodology": "Weinstein Stage scoring: S2=9, S1=5.5, S3=3.5, S4=1.5 ± RS adjustment",
    }


# ---------------------------------------------------------------------------
# 11. CANSLIM Score (1-10)
# ---------------------------------------------------------------------------


def compute_canslim(
    metrics: dict, technicals: dict, sentiment: dict | None = None
) -> dict:
    """Score O'Neil CANSLIM criteria (7 factors → 1-10).

    C = Current quarterly EPS growth
    A = Annual EPS growth
    N = New (highs, products, management)
    S = Supply/Demand (volume + float)
    L = Leader/Laggard (relative strength)
    I = Institutional sponsorship
    M = Market direction
    """
    ratios = metrics.get("ratios", {})
    reasons: list[str] = []
    factors: dict[str, float | None] = {}

    # C — Current quarterly EPS growth (>25% is passing)
    eps_growth_q = ratios.get("eps_growth_qoq")
    if eps_growth_q is not None:
        if eps_growth_q > 0.40:
            factors["C"] = 10.0
        elif eps_growth_q > 0.25:
            factors["C"] = 8.0
        elif eps_growth_q > 0.15:
            factors["C"] = 6.0
        elif eps_growth_q > 0.0:
            factors["C"] = 4.0
        else:
            factors["C"] = 2.0
        reasons.append(f"C: Quarterly EPS growth {eps_growth_q:.0%}")
    else:
        factors["C"] = None

    # A — Annual EPS growth (>25% for 3yr)
    ni_cagr = ratios.get("ni_cagr_5yr") or ratios.get("ni_cagr_3yr")
    if ni_cagr is not None:
        if ni_cagr > 0.25:
            factors["A"] = 9.0
        elif ni_cagr > 0.15:
            factors["A"] = 7.0
        elif ni_cagr > 0.08:
            factors["A"] = 5.0
        elif ni_cagr > 0.0:
            factors["A"] = 3.5
        else:
            factors["A"] = 1.5
        reasons.append(f"A: Annual EPS CAGR {ni_cagr:.0%}")
    else:
        factors["A"] = None

    # N — New highs (price near 52wk high)
    ticker_data = None
    for key, val in (technicals or {}).items():
        if isinstance(val, dict) and (
            "weinstein_stage" in val or "trend_strength" in val
        ):
            ticker_data = val
            break

    if ticker_data:
        # position_in_52wk_range is inside weinstein_stage sub-dict (0-100 scale)
        weinstein = ticker_data.get("weinstein_stage", {})
        pos_52w_pct = (
            weinstein.get("position_in_52wk_range")
            if isinstance(weinstein, dict)
            else None
        )
        pos_52w = pos_52w_pct / 100.0 if pos_52w_pct is not None else None
        if pos_52w is not None:
            if pos_52w > 0.90:
                factors["N"] = 9.0
                reasons.append(
                    f"N: Price at {pos_52w:.0%} of 52-week range — new high territory"
                )
            elif pos_52w > 0.75:
                factors["N"] = 7.0
            elif pos_52w > 0.50:
                factors["N"] = 5.0
            else:
                factors["N"] = 3.0
                reasons.append(
                    f"N: Price at {pos_52w:.0%} of 52-week range — not near highs"
                )
        else:
            factors["N"] = None
    else:
        factors["N"] = None

    # S — Supply/demand (volume trend)
    if ticker_data:
        volume_data = ticker_data.get("volume", {})
        vol_ratio = volume_data.get("volume_ratio")
        if vol_ratio is not None:
            if vol_ratio > 1.5:
                factors["S"] = 8.5
            elif vol_ratio > 1.0:
                factors["S"] = 6.5
            elif vol_ratio > 0.7:
                factors["S"] = 4.5
            else:
                factors["S"] = 3.0
        else:
            factors["S"] = None
    else:
        factors["S"] = None

    # L — Leader (relative strength)
    if ticker_data:
        rs = ticker_data.get("relative_strength", {})
        composite = rs.get("composite_rs")
        if composite is not None:
            if composite > 20.0:
                factors["L"] = 9.5
            elif composite > 5.0:
                factors["L"] = 8.0
            elif composite > -5.0:
                factors["L"] = 6.0
            elif composite > -20.0:
                factors["L"] = 4.0
            else:
                factors["L"] = 1.5
            reasons.append(f"L: RS composite {composite:.2f}pp")
        else:
            factors["L"] = None
    else:
        factors["L"] = None

    # I — Institutional sponsorship (from sentiment/insider)
    #     Enhanced: incorporates analyst revision momentum (time-decay weighted)
    if sentiment:
        analyst = sentiment.get("analyst", {})
        total_analysts = 0
        rec_trends = analyst.get("recommendation_trends", [])
        if rec_trends:
            latest = rec_trends[0]
            total_analysts = sum(
                latest.get(k, 0)
                for k in ["strongBuy", "buy", "hold", "sell", "strongSell"]
            )
        # Base score from coverage breadth
        if total_analysts > 20:
            base_i = 8.0
        elif total_analysts > 10:
            base_i = 6.5
        elif total_analysts > 5:
            base_i = 5.0
        else:
            base_i = 3.5

        # Revision momentum bonus/penalty (±1.5 points max)
        rev_momentum = analyst.get("revision_momentum", {})
        momentum_score = rev_momentum.get("momentum_score")
        if momentum_score is not None:
            # Map 0-10 momentum to -1.5..+1.5 adjustment
            momentum_adj = (momentum_score - 5.0) * 0.3
            base_i = max(1.0, min(10.0, base_i + momentum_adj))
            reasons.append(
                f"I: {total_analysts} analysts, revision momentum "
                f"{momentum_score:.1f}/10 (adj {momentum_adj:+.1f})"
            )
        else:
            reasons.append(f"I: {total_analysts} analysts covering")

        factors["I"] = round(base_i, 1)
    else:
        factors["I"] = None

    # M — Market direction (simplified: use market RS if available)
    factors["M"] = 5.0  # Neutral default; agent overrides based on macro

    valid = {k: v for k, v in factors.items() if v is not None}
    if len(valid) < 3:
        return {
            "score": None,
            "assessment": "insufficient_data",
            "factors": factors,
            "reasons": reasons,
        }

    avg = sum(valid.values()) / len(valid)
    final = _clamp(avg)

    pass_count = sum(1 for v in valid.values() if v >= 6.0)
    fail_count = sum(1 for v in valid.values() if v < 4.0)

    if final >= 7.5:
        assessment = f"Strong CANSLIM — {pass_count}/{len(valid)} factors passing"
    elif final >= 6.0:
        assessment = f"Moderate CANSLIM — {pass_count}/{len(valid)} factors passing"
    elif final >= 4.5:
        assessment = f"Weak CANSLIM — only {pass_count}/{len(valid)} factors passing, {fail_count} failing"
    else:
        assessment = f"CANSLIM fail — {fail_count}/{len(valid)} factors failing"

    return {
        "score": final,
        "assessment": assessment,
        "factors": factors,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "reasons": reasons,
        "methodology": "CANSLIM = avg(C,A,N,S,L,I,M) where each factor scored 1-10",
    }


# ---------------------------------------------------------------------------
# Framework divergence detection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 12. Ecosystem Momentum Score (1-10)
# ---------------------------------------------------------------------------


def compute_ecosystem_momentum(ecosystem_data: dict | None) -> dict:
    """Score supply chain ecosystem health from fetch_supply_chain_ecosystem.py output.

    Measures whether upstream suppliers and downstream customers are thriving
    or collapsing — a leading indicator of future company performance.

    Score = ecosystem_momentum.score from fetch script, adjusted for propagation risks.
    Penalty: -0.5 per HIGH-severity propagation risk (min floor 1.0).
    """
    if not ecosystem_data:
        return {
            "score": None,
            "rationale": "No ecosystem data available",
            "sub_scores": {},
        }

    eco = ecosystem_data.get("ecosystem_momentum", {})
    base_score = eco.get("score")
    if base_score is None:
        upstream = ecosystem_data.get("upstream", {}).get("health_score")
        downstream = ecosystem_data.get("downstream", {}).get("health_score")
        if upstream is not None and downstream is not None:
            base_score = (upstream + downstream) / 2.0
        elif upstream is not None:
            base_score = upstream
        elif downstream is not None:
            base_score = downstream
        else:
            return {
                "score": None,
                "rationale": "No upstream or downstream health scores available",
                "sub_scores": {},
            }

    # Apply propagation risk penalty
    risks = ecosystem_data.get("propagation_risks", [])
    high_risks = [r for r in risks if r.get("severity") == "HIGH"]
    penalty = len(high_risks) * 0.5

    final_score = max(1.0, round(base_score - penalty, 1))

    # Build rationale
    direction = eco.get("direction", "unknown")
    upstream_health = ecosystem_data.get("upstream", {}).get("health_score")
    downstream_health = ecosystem_data.get("downstream", {}).get("health_score")
    upstream_trend = ecosystem_data.get("upstream", {}).get("trend", "unknown")
    downstream_trend = ecosystem_data.get("downstream", {}).get("trend", "unknown")

    parts = []
    if upstream_health is not None:
        parts.append(f"upstream={upstream_health:.1f}({upstream_trend})")
    if downstream_health is not None:
        parts.append(f"downstream={downstream_health:.1f}({downstream_trend})")
    if high_risks:
        parts.append(f"{len(high_risks)} HIGH propagation risks (-{penalty:.1f})")
    parts.append(f"direction={direction}")

    rationale = "; ".join(parts)

    return {
        "score": _clamp(final_score),
        "rationale": rationale,
        "sub_scores": {
            "upstream_health": upstream_health,
            "downstream_health": downstream_health,
            "propagation_risk_penalty": -penalty if penalty > 0 else 0,
        },
        "direction": direction,
        "convergence": eco.get("convergence", False),
        "high_risk_count": len(high_risks),
    }


# ---------------------------------------------------------------------------
# 13. Industry Trajectory Score (1-10)
# ---------------------------------------------------------------------------


def compute_industry_trajectory(trajectory_data: dict | None) -> dict:
    """Score industry trajectory from compute_industry_trajectory.py output.

    Measures whether the company's industry is getting better or worse —
    revenue acceleration, margin direction, RS momentum, fund flows,
    valuation change, and capital cycle position.
    """
    if not trajectory_data:
        return {
            "score": None,
            "rationale": "No industry trajectory data available",
            "sub_scores": {},
        }

    # Handle both single-trajectory and multi-trajectory formats
    traj = trajectory_data.get("trajectories", trajectory_data)
    if isinstance(traj, list):
        traj = traj[0] if traj else {}

    base_score = traj.get("trajectory_score")
    if base_score is None:
        return {
            "score": None,
            "rationale": "Trajectory score not computed",
            "sub_scores": {},
        }

    direction = traj.get("trajectory_direction", "unknown")
    positive = traj.get("positive_signals", 0)
    negative = traj.get("negative_signals", 0)

    # Extract dimension sub-scores
    dims = traj.get("dimensions", {})
    sub_scores = {}
    for dim_name, dim_data in dims.items():
        if isinstance(dim_data, dict) and dim_data.get("score") is not None:
            sub_scores[dim_name] = dim_data["score"]

    # Build rationale
    parts = [f"direction={direction}"]
    parts.append(f"+signals={positive}, -signals={negative}")
    if dims.get("revenue_acceleration", {}).get("direction"):
        parts.append(f"rev={dims['revenue_acceleration']['direction']}")
    if dims.get("margin_direction", {}).get("direction"):
        parts.append(f"margin={dims['margin_direction']['direction']}")
    if dims.get("capital_cycle", {}).get("position"):
        parts.append(f"cycle={dims['capital_cycle']['position']}")

    return {
        "score": _clamp(base_score),
        "rationale": "; ".join(parts),
        "sub_scores": sub_scores,
        "direction": direction,
        "positive_signals": positive,
        "negative_signals": negative,
    }


# ---------------------------------------------------------------------------
# 14. Money Flow Confirmation Score (1-10)
# ---------------------------------------------------------------------------


def compute_money_flow_confirmation(money_flow_data: dict | None) -> dict:
    """Score money flow confirmation from compute_money_flow.py output.

    Measures volume-price synchronization (量价齐升): whether institutional
    capital is flowing in with price confirmation. Composite score from the
    money flow script maps directly (already 0-10 scale).

    If money flow data is unavailable, returns None score (weight redistributed).
    """
    if not money_flow_data:
        return {
            "score": None,
            "rationale": "No money flow data available",
            "sub_scores": {},
        }

    composite = money_flow_data.get("composite_score")
    if composite is None:
        return {
            "score": None,
            "rationale": "Money flow composite score not computed",
            "sub_scores": {},
        }

    streak = money_flow_data.get("streak_analysis", {})
    consecutive_inflow = streak.get("consecutive_inflow_days", 0)
    volume_price_symmetry = money_flow_data.get("volume_price_symmetry", False)

    reasons: list[str] = []
    reasons.append(f"Money flow composite: {composite:.1f}/10")

    if consecutive_inflow >= 3:
        reasons.append(f"Consecutive inflow streak: {consecutive_inflow} days")
    if volume_price_symmetry:
        reasons.append("Volume-price symmetry confirmed (量价齐升)")

    confirmed_accumulation = consecutive_inflow >= 3 and volume_price_symmetry

    final = _clamp(composite)

    if final >= 7.5:
        assessment = "Strong institutional accumulation — volume and price confirming"
    elif final >= 5.5:
        assessment = "Moderate money flow — some institutional interest"
    elif final >= 4.0:
        assessment = "Neutral — no clear directional flow"
    else:
        assessment = "Distribution — outflow dominates, institutional selling"

    return {
        "score": final,
        "assessment": assessment,
        "composite_score": composite,
        "consecutive_inflow_days": consecutive_inflow,
        "volume_price_symmetry": volume_price_symmetry,
        "confirmed_accumulation": confirmed_accumulation,
        "reasons": reasons,
        "sub_scores": {
            "composite": composite,
            "streak": min(10.0, consecutive_inflow * 2.0),
            "symmetry": 8.0 if volume_price_symmetry else 4.0,
        },
        "methodology": "MoneyFlow = composite_score from compute_money_flow.py (0-10 direct mapping)",
    }


# ---------------------------------------------------------------------------
# Directional conviction count (Pitfall 5: capped-upside vs conviction)
# ---------------------------------------------------------------------------


def compute_conviction_count_directional(
    metrics: dict,
    technicals: dict,
    sentiment: dict | None,
    short_interest: dict | None,
    alternatives: dict | None,
    options_data: dict | None = None,
) -> dict:
    """Compute bull / bear conviction count (each 0-8) for short-term structure selection.

    Inspired by `himself65/trade-skills` pitfall 24. When count >= 4, capped-upside
    structures (Jade Lizard, Iron Condor, Calendar, Diagonal, Covered Call) are
    forbidden — must use uncapped or wide-upside structures instead.

    Each of 8 factors contributes 1 point if met. Returns count, factor breakdown,
    banned_structures[] when count >= 4, required_structures[].

    See: references/pitfalls/05-capped-upside-vs-conviction.md
    """
    bull_factors: list[dict] = []
    bear_factors: list[dict] = []

    # 1. 3+ independent bullish/bearish channel checks (alt-data)
    primary = (alternatives or {}).get("primary_research") or {}
    convergence = primary.get("convergence_score") or {}
    bullish_sources = convergence.get("bullish_distinct_sources", 0) or 0
    bearish_sources = convergence.get("bearish_distinct_sources", 0) or 0
    if bullish_sources >= 3:
        bull_factors.append(
            {"name": "channel_check_confluence", "value": bullish_sources}
        )
    if bearish_sources >= 3:
        bear_factors.append(
            {"name": "channel_check_confluence", "value": bearish_sources}
        )

    # 2. Sector / thematic narrative actively re-rating
    sector_rs = (technicals or {}).get("sector_rs") or {}
    sector_rs_score = sector_rs.get("sector_rs_score")
    if sector_rs_score is not None:
        if sector_rs_score >= 7.0:
            bull_factors.append({"name": "sector_rerate", "value": sector_rs_score})
        elif sector_rs_score <= 3.0:
            bear_factors.append({"name": "sector_rerate", "value": sector_rs_score})

    # 3. Stock down >20% from recent high (de-risked) for bull / up >20% from low for bear
    pct_off_high = (technicals or {}).get("pct_off_52w_high")
    pct_off_low = (technicals or {}).get("pct_off_52w_low")
    if pct_off_high is not None and pct_off_high <= -20:
        bull_factors.append({"name": "de_risked_setup", "value": pct_off_high})
    if pct_off_low is not None and pct_off_low >= 20:
        bear_factors.append({"name": "extended_setup", "value": pct_off_low})

    # 4. Past 4 quarters: ≥3 positive earnings reactions (bull) / ≥3 negative (bear)
    earnings_edge = (sentiment or {}).get("earnings_edge") or {}
    pos_reactions = earnings_edge.get("positive_reactions_last_4q", 0) or 0
    neg_reactions = earnings_edge.get("negative_reactions_last_4q", 0) or 0
    if pos_reactions >= 3:
        bull_factors.append(
            {"name": "positive_earnings_history", "value": pos_reactions}
        )
    if neg_reactions >= 3:
        bear_factors.append(
            {"name": "negative_earnings_history", "value": neg_reactions}
        )

    # 5. NEW information likely to be disclosed (forward catalyst with high impact)
    catalysts = (sentiment or {}).get("upcoming_catalysts") or []
    if any(
        (c.get("expected_impact_magnitude", 0) or 0) >= 4
        and (c.get("direction") or "").lower() in ("positive", "bull", "bullish")
        for c in catalysts
    ):
        bull_factors.append({"name": "high_impact_positive_catalyst", "value": True})
    if any(
        (c.get("expected_impact_magnitude", 0) or 0) >= 4
        and (c.get("direction") or "").lower() in ("negative", "bear", "bearish")
        for c in catalysts
    ):
        bear_factors.append({"name": "high_impact_negative_catalyst", "value": True})

    # 6. Net options flow back-month bullish (call premium dominance, 5d rolling)
    flow = (options_data or {}).get("flow") or {}
    net_call_5d = flow.get("net_call_premium_5d_usd")
    net_put_5d = flow.get("net_put_premium_5d_usd")
    if net_call_5d is not None and net_call_5d >= 5_000_000 and (net_put_5d or 0) <= 0:
        bull_factors.append({"name": "options_flow_bullish", "value": net_call_5d})
    if net_put_5d is not None and net_put_5d >= 5_000_000 and (net_call_5d or 0) <= 0:
        bear_factors.append({"name": "options_flow_bearish", "value": net_put_5d})

    # 7. Short interest >10% (squeeze potential for bull, distribution risk for bear)
    si = (short_interest or {}).get("short_interest") or {}
    si_pct = si.get("short_pct_float")
    if si_pct is not None and si_pct >= 10:
        # High SI is a *bull-conviction amplifier* (squeeze potential), not bear
        bull_factors.append({"name": "short_squeeze_potential", "value": si_pct})

    # 8. Implied move materially below recent realized average
    iv_data = (options_data or {}).get("iv") or {}
    implied_move = iv_data.get("implied_move_pct")
    realized_30d = iv_data.get("realized_vol_30d_pct")
    if (
        implied_move is not None
        and realized_30d is not None
        and implied_move > 0
        and realized_30d > 0
        and implied_move < 0.7 * realized_30d
    ):
        # Symmetric — tells us the market is underpricing movement; both sides see asymmetry
        bull_factors.append({"name": "implied_below_realized", "value": implied_move})
        bear_factors.append({"name": "implied_below_realized", "value": implied_move})

    bull_count = len(bull_factors)
    bear_count = len(bear_factors)

    # Banned structures activate at count >= 4 (per pitfall 5)
    banned_structures: list[str] = []
    required_structures: list[str] = []
    direction: str | None = None

    if bull_count >= 4 and bull_count > bear_count:
        direction = "bull"
        banned_structures = [
            "Jade Lizard",
            "Iron Condor",
            "Calendar",
            "Diagonal (tight strikes)",
            "Covered Call",
        ]
        required_structures = [
            "Naked Short Put (cash-secured, far OTM)",
            "Bull Put Spread",
            "Risk Reversal",
            "Long Call (single)",
            "Bull Call Debit Spread",
            "Synthetic Long",
        ]
    elif bear_count >= 4 and bear_count > bull_count:
        direction = "bear"
        banned_structures = [
            "Reverse Jade Lizard",
            "Iron Condor",
            "Calendar (tight strikes)",
            "Cash-Secured Put on falling knife",
        ]
        required_structures = [
            "Bear Call Spread",
            "Long Put",
            "Bear Put Debit Spread",
            "Risk Reversal (sell call + buy put)",
        ]

    return {
        "bull_conviction_count": bull_count,
        "bear_conviction_count": bear_count,
        "bull_factors": bull_factors,
        "bear_factors": bear_factors,
        "high_conviction_directional": direction,
        "asymmetry_rule_active": direction is not None,
        "banned_structures": banned_structures,
        "required_structures": required_structures,
        "methodology": (
            "Pitfall 5 (asymmetry axis): tally 8 factors. Count >= 4 with directional "
            "dominance activates banned-structures rule. See "
            "references/pitfalls/05-capped-upside-vs-conviction.md"
        ),
    }


def classify_tape_class(
    ticker: str,
    technicals: dict | None,
    liquidity: dict | None,
    alternatives: dict | None,
) -> dict:
    """Classify tape behavior (pitfall 8): institutional|retail|manipulator|lowliquidity.

    Drives short-term structure selection: manipulator tapes default to selling
    premium with wide-strike structures; institutional tapes use standard frameworks;
    retail tapes pair float-saturation checks with structure choice; lowliquidity
    tapes invalidate orderbook-based frameworks.

    Seed list of known manipulator-class names from `references/pitfalls/08-manipulator-tape.md`.
    Override via observed metrics: realized vol >70%, mean overnight gap >2.5%,
    implied/realized ratio <0.85 for sustained period.
    """
    seed_manipulator = {"APP", "MSTR", "COIN", "PLTR", "DJT"}
    rationale: list[str] = []
    tape_class = "institutional"

    if ticker.upper() in seed_manipulator:
        tape_class = "manipulator"
        rationale.append(f"{ticker} on seed manipulator-class list (pitfall 8)")

    tech = technicals or {}
    realized_vol_30d = tech.get("realized_vol_30d_pct") or tech.get("hist_vol_30d")
    overnight_gap_avg = tech.get("avg_overnight_gap_pct")

    # Override: high realized vol + frequent gap behavior → manipulator
    if (
        realized_vol_30d is not None
        and realized_vol_30d >= 70
        and overnight_gap_avg is not None
        and overnight_gap_avg >= 2.5
    ):
        if tape_class != "manipulator":
            rationale.append(
                f"realized vol {realized_vol_30d:.0f}% + avg overnight gap "
                f"{overnight_gap_avg:.1f}% → manipulator class"
            )
        tape_class = "manipulator"

    # Liquidity override
    liq = liquidity or {}
    liq_score = liq.get("liquidity_score")
    if liq_score is not None and liq_score < 4.0:
        tape_class = "lowliquidity"
        rationale.append(
            f"liquidity score {liq_score:.1f} <4.0 → orderbook frameworks invalid"
        )

    # Retail saturation override (pitfall 9 cross-check)
    sat = (alternatives or {}).get("social_saturation") or {}
    sat_score = sat.get("social_saturation_score")
    if tape_class == "institutional" and sat_score is not None and sat_score >= 60:
        tape_class = "retail"
        rationale.append(
            f"social saturation {sat_score:.0f} ≥60 → retail-dominated tape"
        )

    structure_default = {
        "institutional": "Standard frameworks apply (gamma + price-action)",
        "retail": "Pair float-saturation check with structure (pitfall 9)",
        "manipulator": "Sell premium (Jade Lizard/IC/bull put spread); avoid long-dated calls",
        "lowliquidity": "Orderbook frameworks unreliable; manipulator-tape rules apply",
    }[tape_class]

    return {
        "tape_class": tape_class,
        "rationale": rationale,
        "structure_default": structure_default,
        "methodology": (
            "Pitfall 8 (manipulator-tape): seed list + realized vol / overnight gap "
            "/ liquidity / saturation overrides. See references/pitfalls/08-manipulator-tape.md"
        ),
    }


def detect_framework_divergence(scores: dict) -> dict:
    """Detect when component scores strongly disagree, indicating analytical tension.

    Flags pairs of components where one is bullish (≥7.5) and the other is
    bearish (≤3.5). These divergences require human investigation.
    """
    components = [
        "financial_health",
        "moat_quality",
        "management_quality",
        "valuation_attractiveness",
        "macro_tailwind",
        "risk_profile",
        "alternative_alignment",
        "technical_setup",
        "capital_structure",
        "weinstein_alignment",
        "canslim",
    ]

    score_values = {}
    for comp in components:
        obj = scores.get(comp, {})
        s = obj.get("score") if isinstance(obj, dict) else None
        if s is not None:
            score_values[comp] = s

    divergences = []

    # Known meaningful divergence pairs
    tension_pairs = [
        ("financial_health", "valuation_attractiveness", "Value trap or recovery?"),
        ("moat_quality", "technical_setup", "Moat intact but market disagrees?"),
        ("macro_tailwind", "financial_health", "Strong company in weak macro?"),
        ("alternative_alignment", "financial_health", "Alt data sees deterioration?"),
        ("management_quality", "risk_profile", "Good management but high risk?"),
        ("valuation_attractiveness", "technical_setup", "Cheap but in downtrend?"),
        ("weinstein_alignment", "moat_quality", "Technical stage conflicts moat?"),
    ]

    for comp_a, comp_b, question in tension_pairs:
        a = score_values.get(comp_a)
        b = score_values.get(comp_b)
        if a is None or b is None:
            continue
        spread = abs(a - b)
        if spread >= 4.0 and ((a >= 7.5 and b <= 3.5) or (b >= 7.5 and a <= 3.5)):
            divergences.append(
                {
                    "pair": [comp_a, comp_b],
                    "scores": [a, b],
                    "spread": round(spread, 1),
                    "investigation_prompt": question,
                    "severity": "high" if spread >= 5.0 else "moderate",
                }
            )

    # Overall dispersion (standard deviation of available scores)
    if len(score_values) >= 4:
        values = list(score_values.values())
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        dispersion = variance**0.5
    else:
        dispersion = None

    return {
        "divergences": divergences,
        "divergence_count": len(divergences),
        "score_dispersion": round(dispersion, 2) if dispersion else None,
        "high_conviction_signal": len(divergences) == 0 and (dispersion or 0) < 1.5,
        "investigation_required": len(divergences) > 0,
    }


# ---------------------------------------------------------------------------
# Final conviction computation
# ---------------------------------------------------------------------------


def compute_conviction(scores: dict, report_type: str) -> dict:
    """Compute final conviction rating from component scores.

    Applies per-report-type weights and override rules.
    """
    weights = {
        "long": {
            "financial_health": 0.15,
            "moat_quality": 0.15,
            "management_quality": 0.15,
            "valuation_attractiveness": 0.15,
            "capital_structure": 0.10,
            "macro_tailwind": 0.05,
            "risk_profile": 0.10,
            "weinstein_alignment": 0.05,
            "ecosystem_momentum": 0.05,
            "industry_trajectory": 0.05,
        },
        "mid": {
            "financial_health": 0.10,
            "moat_quality": 0.10,
            "management_quality": 0.10,
            "valuation_attractiveness": 0.15,
            "macro_tailwind": 0.10,
            "risk_profile": 0.10,
            "weinstein_alignment": 0.10,
            "canslim": 0.10,
            "ecosystem_momentum": 0.05,
            "industry_trajectory": 0.05,
            "money_flow_confirmation": 0.05,
        },
        "short": {
            "valuation_attractiveness": 0.10,
            "macro_tailwind": 0.10,
            "risk_profile": 0.10,
            "alternative_alignment": 0.15,
            "technical_setup": 0.15,
            "weinstein_alignment": 0.10,
            "canslim": 0.10,
            "ecosystem_momentum": 0.10,
            "industry_trajectory": 0.05,
            "money_flow_confirmation": 0.05,
        },
        "quick": {
            "financial_health": 0.20,
            "valuation_attractiveness": 0.30,
            "risk_profile": 0.20,
            "technical_setup": 0.15,
            "weinstein_alignment": 0.15,
        },
    }

    wt = weights.get(report_type, weights["mid"])

    # Gather component scores
    component_scores = {}
    for comp in wt:
        key_map = {
            "financial_health": "financial_health",
            "moat_quality": "moat_quality",
            "management_quality": "management_quality",
            "valuation_attractiveness": "valuation_attractiveness",
            "capital_structure": "capital_structure",
            "macro_tailwind": "macro_tailwind",
            "risk_profile": "risk_profile",
            "alternative_alignment": "alternative_alignment",
            "technical_setup": "technical_setup",
            "weinstein_alignment": "weinstein_alignment",
            "canslim": "canslim",
            "ecosystem_momentum": "ecosystem_momentum",
            "industry_trajectory": "industry_trajectory",
            "money_flow_confirmation": "money_flow_confirmation",
        }
        score_obj = scores.get(key_map[comp], {})
        component_scores[comp] = score_obj.get("score")

    # Count missing
    missing = [k for k, v in component_scores.items() if v is None]
    low_components = [
        k for k, v in component_scores.items() if v is not None and v <= 3.0
    ]

    # Compute weighted average with available components
    available = {k: v for k, v in component_scores.items() if v is not None}
    if not available:
        return {
            "conviction": None,
            "rating": "Unable to rate",
            "confidence": "No data",
            "error": "No component scores available",
        }

    total_weight = sum(wt[k] for k in available)
    conviction = sum(available[k] * wt[k] for k in available) / total_weight

    # Apply override rules
    overrides = []
    confidence = "High"

    # Rule: any component ≤3 caps at Hold
    if low_components:
        conviction = min(conviction, 5.9)
        overrides.append(
            f"Component(s) ≤3 ({', '.join(low_components)}) → capped at Hold (5.9)"
        )

    # Rule: 3+ missing components → Low confidence
    if len(missing) >= 3:
        confidence = "Low"
        overrides.append(f"{len(missing)} missing components → Low confidence")

    # Rule: framework divergence reduces confidence
    divergence = scores.get("framework_divergence", {})
    if divergence.get("divergence_count", 0) >= 2:
        if confidence == "High":
            confidence = "Medium"
        overrides.append(
            f"{divergence['divergence_count']} framework divergences → confidence capped at Medium"
        )

    # Rule: red flag override
    risk_obj = scores.get("risk_profile", {})
    if risk_obj.get("override"):
        conviction = min(conviction, 3.9)
        overrides.append("3+ forensic red flags → capped at Sell (3.9)")

    # Rule: long-term report valuation penalty — prevent "Buy overvalued stock for long-term"
    if report_type == "long":
        val_score = component_scores.get("valuation_attractiveness")
        if val_score is not None and val_score <= 4.0:
            conviction = min(conviction, 7.0)
            overrides.append(
                f"Valuation ≤ 4.0 ({val_score:.1f}) for long-term → conviction capped at 7.0"
            )

    conviction = round(conviction, 1)

    # Lollapalooza bonus — apply BEFORE rating assignment so rating reflects final conviction
    # Safety: bonus CANNOT apply when low_components exist (any component ≤ 3.0)
    lollapalooza = False
    high_components = [
        k for k, v in component_scores.items() if v is not None and v >= 7.5
    ]
    if (
        len(high_components) >= 3
        and not low_components
        and not risk_obj.get("override")
    ):
        # M10: Timing-risk guard for short-term — don't apply bonus when overextended
        apply_bonus = True
        if report_type == "short":
            canslim_n = scores.get("canslim", {}).get("factors", {}).get("N")
            if canslim_n is not None and canslim_n >= 9.0:
                # 52w position > 90% — too extended for short-term bonus
                apply_bonus = False
                overrides.append(
                    "Lollapalooza suppressed: short-term + 52w position > 90%"
                )
        if apply_bonus:
            lollapalooza = True
            conviction = min(10.0, round(conviction + 1.5, 1))
            overrides.append(
                f"Lollapalooza Effect detected ({len(high_components)} strong components) → +1.5 bonus"
            )

    # Re-apply valuation cap after Lollapalooza — bonus must not bypass the cap
    if report_type == "long":
        val_score = component_scores.get("valuation_attractiveness")
        if val_score is not None and val_score <= 4.0:
            conviction = min(conviction, 7.0)

    # Rating
    if conviction >= 9.0:
        rating = "Strong Buy"
    elif conviction >= 7.5:
        rating = "Buy"
    elif conviction >= 6.0:
        rating = "Hold / Accumulate"
    elif conviction >= 4.0:
        rating = "Hold / Reduce"
    elif conviction >= 2.0:
        rating = "Sell"
    else:
        rating = "Strong Sell"

    return {
        "conviction": round(conviction, 1),
        "rating": rating,
        "confidence": confidence,
        "component_scores": component_scores,
        "missing_components": missing,
        "low_components": low_components,
        "overrides": overrides,
        "lollapalooza_detected": lollapalooza,
        "methodology": f"Conviction = Σ(component × weight) for {report_type}-term report. Override rules applied.",
    }


# ---------------------------------------------------------------------------
# Score Enrichment Functions (integrate supplementary data into base scores)
# ---------------------------------------------------------------------------


def _enrich_risk_profile(
    risk_result: dict,
    credit_data: dict,
    correlation_data: dict,
    forecast_data: dict,
) -> None:
    """Enrich risk_profile score with credit spreads, tail correlation, and GARCH vol.

    Adjusts the existing score ±1.5 based on supplementary risk signals.
    Modifies risk_result in-place.
    """
    if risk_result.get("score") is None:
        return

    base_score = risk_result["score"]
    adj = 0.0
    reasons = risk_result.get("reasons", [])
    sub_scores = risk_result.get("sub_scores", {})

    # 1. Credit spread signal (fetch_credit.py)
    if credit_data:
        spread_trend = credit_data.get("spread_trend", {})
        spread_z = spread_trend.get("z_score")  # z-score of current spread vs history
        rating = credit_data.get("credit_rating", {}).get("rating")

        if spread_z is not None:
            if spread_z > 2.0:
                adj -= 1.0
                reasons.append(
                    f"Credit: spread z-score {spread_z:.1f} (widening stress)"
                )
            elif spread_z > 1.0:
                adj -= 0.5
                reasons.append(f"Credit: spread z-score {spread_z:.1f} (elevated)")
            elif spread_z < -1.0:
                adj += 0.3
                reasons.append(f"Credit: spread z-score {spread_z:.1f} (tight/benign)")
            sub_scores["credit_spread_z"] = max(1.0, min(10.0, 5.5 - spread_z * 1.5))

        if rating:
            investment_grade = rating.startswith(("AAA", "AA", "A", "BBB"))
            if not investment_grade:
                adj -= 0.5
                reasons.append(f"Credit: sub-investment-grade rating ({rating})")
            sub_scores["credit_rating"] = 8.0 if investment_grade else 3.0

    # 2. Tail correlation / asymmetric beta (compute_correlation_regime.py)
    if correlation_data:
        regime = correlation_data.get("regime", "normal")
        asym_beta = correlation_data.get("asymmetric_beta", {})
        downside_beta = asym_beta.get("downside_beta")
        tail_corr = correlation_data.get("tail_correlation")

        if regime == "crisis":
            adj -= 0.8
            reasons.append("Correlation: crisis regime — diversification fails")
        elif regime == "elevated":
            adj -= 0.3
            reasons.append("Correlation: elevated regime — reduced diversification")

        if downside_beta is not None and downside_beta > 1.5:
            adj -= 0.5
            reasons.append(
                f"Asymmetric beta: downside={downside_beta:.2f} (amplifies losses)"
            )
            sub_scores["downside_beta"] = max(1.0, 8.0 - (downside_beta - 1.0) * 3)
        elif downside_beta is not None:
            sub_scores["downside_beta"] = max(
                1.0, min(10.0, 8.0 - (downside_beta - 1.0) * 3)
            )

        if tail_corr is not None and tail_corr > 0.7:
            adj -= 0.3
            reasons.append(f"Tail correlation: {tail_corr:.2f} (contagion risk)")

    # 3. GARCH volatility / fat-tail risk (forecast.py)
    if forecast_data:
        garch = forecast_data.get("garch", {})
        annual_vol = garch.get("annualized_vol")
        fat_tail = forecast_data.get("fat_tail", {})
        tail_index = fat_tail.get("tail_index")  # lower = fatter tails

        if annual_vol is not None:
            if annual_vol > 0.60:
                adj -= 0.8
                reasons.append(f"GARCH vol: {annual_vol:.0%} annualized (extreme)")
            elif annual_vol > 0.40:
                adj -= 0.4
                reasons.append(f"GARCH vol: {annual_vol:.0%} annualized (high)")
            elif annual_vol < 0.20:
                adj += 0.2
                reasons.append(f"GARCH vol: {annual_vol:.0%} annualized (low)")
            sub_scores["garch_vol"] = max(
                1.0, min(10.0, 8.0 - (annual_vol - 0.25) * 10)
            )

        if tail_index is not None and tail_index < 3.0:
            adj -= 0.4
            reasons.append(f"Fat-tail index: {tail_index:.1f} (extreme events likely)")

    # Apply adjustment (capped at ±1.5)
    adj = max(-1.5, min(1.5, adj))
    new_score = _clamp(base_score + adj)
    risk_result["score"] = new_score
    risk_result["enrichment_adj"] = round(adj, 2)
    risk_result["sub_scores"] = sub_scores
    risk_result["reasons"] = reasons
    if adj != 0:
        risk_result["methodology"] += (
            f" + Credit/Correlation/GARCH enrichment (adj={adj:+.2f})"
        )


def _enrich_valuation(
    val_result: dict,
    tam_adj_peg_data: dict,
    bayesian_growth_data: dict,
) -> None:
    """Enrich valuation score with TAM-adjusted PEG and Bayesian growth analysis.

    Adjusts the existing score ±1.5 based on growth runway signals.
    Modifies val_result in-place.
    """
    if val_result.get("score") is None:
        return

    base_score = val_result["score"]
    adj = 0.0
    reasons = val_result.get("reasons", [])

    # 1. TAM-Adjusted PEG (compute_tam_adj_peg.py)
    if tam_adj_peg_data:
        category = tam_adj_peg_data.get("category", "")
        tam_peg = tam_adj_peg_data.get("tam_adj_peg")
        interpretation = tam_adj_peg_data.get("interpretation", "")

        if tam_peg is not None:
            if tam_peg < 0.5:
                adj += 1.0
                reasons.append(
                    f"TAM-adj PEG: {tam_peg:.2f} (deeply undervalued for growth runway)"
                )
            elif tam_peg < 1.0:
                adj += 0.5
                reasons.append(
                    f"TAM-adj PEG: {tam_peg:.2f} (undervalued vs TAM opportunity)"
                )
            elif tam_peg > 2.5:
                adj -= 0.8
                reasons.append(f"TAM-adj PEG: {tam_peg:.2f} (overpriced even for TAM)")
            elif tam_peg > 1.5:
                adj -= 0.3
                reasons.append(f"TAM-adj PEG: {tam_peg:.2f} (full valuation)")

        if category:
            val_result["growth_category"] = category

    # 2. Bayesian intrinsic growth (compute_bayesian_growth.py)
    if bayesian_growth_data:
        verdict = bayesian_growth_data.get("verdict", "")
        fomo_score = bayesian_growth_data.get("fomo_score")
        gap = bayesian_growth_data.get("intrinsic_minus_implied")

        if verdict == "UNDERPRICED_GROWTH":
            adj += 0.8
            reasons.append(
                f"Bayesian: UNDERPRICED_GROWTH (gap={gap:+.1%})"
                if gap
                else "Bayesian: UNDERPRICED_GROWTH"
            )
        elif verdict == "OVERPRICED_GROWTH":
            adj -= 0.8
            reasons.append(
                f"Bayesian: OVERPRICED_GROWTH (gap={gap:+.1%})"
                if gap
                else "Bayesian: OVERPRICED_GROWTH"
            )

        if fomo_score is not None and fomo_score > 70:
            adj -= 0.3
            reasons.append(f"FOMO score: {fomo_score}/100 (priced for perfection)")

        val_result["bayesian_verdict"] = verdict
        val_result["fomo_score"] = fomo_score

    # Apply adjustment
    adj = max(-1.5, min(1.5, adj))
    new_score = _clamp(base_score + adj)
    val_result["score"] = new_score
    val_result["enrichment_adj"] = round(adj, 2)
    val_result["reasons"] = reasons


def _enrich_technical_setup(
    tech_result: dict,
    health_index_data: dict,
) -> None:
    """Enrich technical setup with GF-DMA Health Index.

    Health Index is a 0-100 composite of fundamental speed × DMA structure.
    Adjusts technical score ±1.0 based on health band.
    Modifies tech_result in-place.
    """
    if tech_result.get("score") is None or not health_index_data:
        return

    base_score = tech_result["score"]
    adj = 0.0
    reasons = tech_result.get("reasons", [])

    health_score = health_index_data.get("health_index")
    band = health_index_data.get("band", "")

    if health_score is not None:
        if band == "ELITE_HEALTHY" or health_score >= 80:
            adj += 1.0
            reasons.append(
                f"GF-DMA Health: {health_score}/100 ({band}) — elite momentum+fundamentals"
            )
        elif band == "HEALTHY" or health_score >= 60:
            adj += 0.5
            reasons.append(f"GF-DMA Health: {health_score}/100 ({band}) — healthy")
        elif band == "OVERHEATED" or health_score >= 40:
            adj -= 0.3
            reasons.append(
                f"GF-DMA Health: {health_score}/100 ({band}) — overheated risk"
            )
        elif band == "UNHEALTHY" or health_score < 30:
            adj -= 1.0
            reasons.append(f"GF-DMA Health: {health_score}/100 ({band}) — unhealthy")

        tech_result["health_index"] = health_score
        tech_result["health_band"] = band

    adj = max(-1.0, min(1.0, adj))
    new_score = _clamp(base_score + adj)
    tech_result["score"] = new_score
    tech_result["enrichment_adj"] = round(adj, 2)
    tech_result["reasons"] = reasons


def _enrich_canslim(
    canslim_result: dict,
    earnings_edge_data: dict,
    seasonality_data: dict,
) -> None:
    """Enrich CANSLIM score with earnings edge (beat rate, PEAD) and seasonality.

    Adjusts CANSLIM ±1.0 based on historical earnings patterns.
    Modifies canslim_result in-place.
    """
    if canslim_result.get("score") is None:
        return

    base_score = canslim_result["score"]
    adj = 0.0
    reasons = canslim_result.get("reasons", [])

    # 1. Earnings Edge (compute_earnings_edge.py)
    if earnings_edge_data:
        beat_rate = earnings_edge_data.get("beat_rate")
        pead = earnings_edge_data.get("pead_tendency")  # positive/negative/none
        days_to_earnings = earnings_edge_data.get("days_to_next_earnings")

        if beat_rate is not None:
            if beat_rate >= 0.80:
                adj += 0.8
                reasons.append(
                    f"Earnings edge: beat rate {beat_rate:.0%} (serial beater)"
                )
            elif beat_rate >= 0.65:
                adj += 0.4
                reasons.append(f"Earnings edge: beat rate {beat_rate:.0%} (consistent)")
            elif beat_rate <= 0.35:
                adj -= 0.5
                reasons.append(
                    f"Earnings edge: beat rate {beat_rate:.0%} (serial misser)"
                )

        if pead == "positive":
            adj += 0.3
            reasons.append("PEAD: positive post-earnings drift history")
        elif pead == "negative":
            adj -= 0.3
            reasons.append("PEAD: negative post-earnings drift history")

        # Proximity bonus/warning (within 10 days of earnings → heightened signal)
        if days_to_earnings is not None and days_to_earnings <= 10:
            canslim_result["earnings_imminent"] = True
            reasons.append(f"Earnings in {days_to_earnings} days — signal amplified")

    # 2. Seasonality (compute_seasonality.py)
    if seasonality_data:
        seasonal_index = seasonality_data.get("current_quarter_index")
        seasonal_assessment = seasonality_data.get("assessment", "")

        if seasonal_index is not None:
            if seasonal_index > 1.15:
                adj += 0.3
                reasons.append(
                    f"Seasonality: Q index {seasonal_index:.2f} (historically strong quarter)"
                )
            elif seasonal_index < 0.85:
                adj -= 0.3
                reasons.append(
                    f"Seasonality: Q index {seasonal_index:.2f} (historically weak quarter)"
                )

    adj = max(-1.0, min(1.0, adj))
    new_score = _clamp(base_score + adj)
    canslim_result["score"] = new_score
    canslim_result["enrichment_adj"] = round(adj, 2)
    canslim_result["reasons"] = reasons


def _enrich_conviction_count_with_cot(
    conviction_count: dict,
    cot_data: dict,
) -> None:
    """Add COT institutional positioning as a conviction factor.

    Modifies conviction_count in-place.
    """
    if not cot_data or not conviction_count:
        return

    positioning = cot_data.get("positioning", {})
    net_position = positioning.get("net_speculative")
    trend = positioning.get("trend")  # increasing/decreasing/flat

    bull_factors = conviction_count.get("bull_factors", [])
    bear_factors = conviction_count.get("bear_factors", [])

    if net_position is not None and trend:
        if net_position > 0 and trend == "increasing":
            bull_factors.append(
                {"name": "cot_institutional_bullish", "value": net_position}
            )
            conviction_count["bull_conviction_count"] = (
                conviction_count.get("bull_conviction_count", 0) + 1
            )
        elif net_position < 0 and trend == "decreasing":
            bear_factors.append(
                {"name": "cot_institutional_bearish", "value": net_position}
            )
            conviction_count["bear_conviction_count"] = (
                conviction_count.get("bear_conviction_count", 0) + 1
            )

    conviction_count["bull_factors"] = bull_factors
    conviction_count["bear_factors"] = bear_factors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compute deterministic component scores and conviction rating"
    )
    parser.add_argument("--metrics", help="Path to calculate_metrics.py output JSON")
    parser.add_argument("--macro", help="Path to fetch_macro.py output JSON")
    parser.add_argument("--technicals", help="Path to fetch_technicals.py output JSON")
    parser.add_argument(
        "--alternatives", help="Path to fetch_alternatives.py output JSON"
    )
    parser.add_argument("--sentiment", help="Path to fetch_sentiment.py output JSON")
    parser.add_argument(
        "--report-type",
        choices=["long", "mid", "short", "quick"],
        default="mid",
        help="Report type for conviction weighting",
    )
    parser.add_argument(
        "--gics-sector", type=int, help="GICS sector code (e.g., 45 for Tech)"
    )
    parser.add_argument(
        "--capital-structure", help="Path to fetch_capital_structure.py output JSON"
    )
    parser.add_argument("--liquidity", help="Path to compute_liquidity.py output JSON")
    parser.add_argument(
        "--short-interest", help="Path to fetch_short_interest.py output JSON"
    )
    parser.add_argument(
        "--activist", help="Path to fetch_activist_exposure.py output JSON"
    )
    parser.add_argument(
        "--options",
        help=(
            "Path to calculate_options.py output JSON (enables conviction-count + "
            "banned-structures emission for short-term reports — pitfall 5)"
        ),
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--ticker", default="UNKNOWN", help="Ticker symbol for output labeling"
    )
    parser.add_argument(
        "--ecosystem", help="Path to fetch_supply_chain_ecosystem.py output JSON"
    )
    parser.add_argument(
        "--trajectory", help="Path to compute_industry_trajectory.py output JSON"
    )
    parser.add_argument("--credit", help="Path to fetch_credit.py output JSON")
    parser.add_argument(
        "--correlation", help="Path to compute_correlation_regime.py output JSON"
    )
    parser.add_argument("--forecast", help="Path to forecast.py output JSON")
    parser.add_argument(
        "--earnings-edge", help="Path to compute_earnings_edge.py output JSON"
    )
    parser.add_argument(
        "--health-index", help="Path to compute_health_index.py output JSON"
    )
    parser.add_argument(
        "--tam-adj-peg", help="Path to compute_tam_adj_peg.py output JSON"
    )
    parser.add_argument(
        "--bayesian-growth", help="Path to compute_bayesian_growth.py output JSON"
    )
    parser.add_argument("--cot", help="Path to fetch_cot.py output JSON")
    parser.add_argument(
        "--seasonality", help="Path to compute_seasonality.py output JSON"
    )
    parser.add_argument(
        "--money-flow", help="Path to compute_money_flow.py output JSON"
    )
    args = parser.parse_args()

    # Load inputs
    metrics = {}
    macro = {}
    technicals = {}
    alternatives = {}
    sentiment = {}
    capital_data = {}

    if args.metrics:
        with open(args.metrics) as f:
            metrics = json.load(f)
    if args.macro:
        with open(args.macro) as f:
            macro = json.load(f)
    if args.technicals:
        with open(args.technicals) as f:
            technicals = json.load(f)
    if args.alternatives:
        with open(args.alternatives) as f:
            alternatives = json.load(f)
    if args.sentiment:
        with open(args.sentiment) as f:
            raw_sent = json.load(f)
            if args.ticker in raw_sent:
                sentiment = raw_sent[args.ticker]
            elif raw_sent:
                sentiment = list(raw_sent.values())[0]
    if args.capital_structure:
        with open(args.capital_structure) as f:
            capital_data = json.load(f)

    liquidity_data = {}
    if args.liquidity:
        with open(args.liquidity) as f:
            liquidity_data = json.load(f)

    short_interest_data = {}
    if args.short_interest:
        with open(args.short_interest) as f:
            short_interest_data = json.load(f)

    activist_data = {}
    if args.activist:
        with open(args.activist) as f:
            activist_data = json.load(f)

    options_data = {}
    if args.options:
        with open(args.options) as f:
            options_data = json.load(f)

    scores = {
        "ticker": args.ticker,
        "report_type": args.report_type,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Compute each component score
    scores["financial_health"] = compute_financial_health(metrics, args.gics_sector)
    scores["moat_quality"] = compute_moat_quality(metrics, args.gics_sector)
    scores["management_quality"] = compute_management_quality(metrics, sentiment)
    scores["valuation_attractiveness"] = compute_valuation(metrics, args.gics_sector)
    scores["macro_tailwind"] = compute_macro_tailwind(macro, metrics)
    scores["risk_profile"] = compute_risk_profile(metrics)
    scores["alternative_alignment"] = compute_alternative_alignment(alternatives)
    scores["technical_setup"] = compute_technical_setup(technicals)
    scores["capital_structure"] = compute_capital_structure(capital_data)
    scores["weinstein_alignment"] = compute_weinstein_alignment(technicals)
    scores["canslim"] = compute_canslim(metrics, technicals, sentiment)

    # --- Load supplementary data for score enrichment ---
    def _load_json(path: str | None) -> dict:
        if not path:
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            sys.stderr.write(f"Warning: could not load {path}: {e}\n")
            return {}

    credit_data = _load_json(args.credit)
    correlation_data = _load_json(args.correlation)
    forecast_data = _load_json(args.forecast)
    earnings_edge_data = _load_json(args.earnings_edge)
    health_index_data = _load_json(args.health_index)
    tam_adj_peg_data = _load_json(args.tam_adj_peg)
    bayesian_growth_data = _load_json(args.bayesian_growth)
    cot_data = _load_json(args.cot)
    seasonality_data = _load_json(args.seasonality)

    # --- Enrich risk_profile with credit + correlation + forecast data ---
    _enrich_risk_profile(
        scores["risk_profile"], credit_data, correlation_data, forecast_data
    )

    # --- Enrich valuation with TAM-adj-PEG + Bayesian growth ---
    _enrich_valuation(
        scores["valuation_attractiveness"], tam_adj_peg_data, bayesian_growth_data
    )

    # --- Enrich technical_setup with health_index ---
    _enrich_technical_setup(scores["technical_setup"], health_index_data)

    # --- Enrich CANSLIM with earnings_edge + seasonality ---
    _enrich_canslim(scores["canslim"], earnings_edge_data, seasonality_data)

    # --- Enrich conviction_count with COT institutional positioning ---
    # (applied later after conviction_count is computed)

    # Ecosystem momentum (supply chain health)
    ecosystem_data = {}
    if args.ecosystem:
        try:
            with open(args.ecosystem) as f:
                ecosystem_data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            sys.stderr.write(f"Warning: could not load ecosystem data: {e}\n")
    scores["ecosystem_momentum"] = compute_ecosystem_momentum(ecosystem_data or None)

    # Industry trajectory
    trajectory_data = {}
    if args.trajectory:
        try:
            with open(args.trajectory) as f:
                trajectory_data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            sys.stderr.write(f"Warning: could not load trajectory data: {e}\n")
    scores["industry_trajectory"] = compute_industry_trajectory(trajectory_data or None)

    # Money flow confirmation
    money_flow_data = _load_json(args.money_flow)
    scores["money_flow_confirmation"] = compute_money_flow_confirmation(
        money_flow_data or None
    )

    # Framework divergence detection
    scores["framework_divergence"] = detect_framework_divergence(scores)

    # Tape class (pitfall 8) — manipulator | retail | institutional | lowliquidity
    scores["tape_class"] = classify_tape_class(
        ticker=args.ticker,
        technicals=technicals,
        liquidity=liquidity_data,
        alternatives=alternatives,
    )

    # Directional conviction count + banned/required structures (pitfall 5)
    # Always computed; consumed primarily by short-term report writer.
    scores["conviction_count_directional"] = compute_conviction_count_directional(
        metrics=metrics,
        technicals=technicals,
        sentiment=sentiment,
        short_interest=short_interest_data,
        alternatives=alternatives,
        options_data=options_data,
    )

    # Enrich conviction count with COT institutional positioning
    _enrich_conviction_count_with_cot(scores["conviction_count_directional"], cot_data)

    # Conviction
    scores["conviction"] = compute_conviction(scores, args.report_type)

    # Liquidity-adjusted position sizing
    if liquidity_data:
        liq_score = liquidity_data.get("liquidity_score", 10.0)
        warnings = liquidity_data.get("warnings", [])
        pos_sizing = liquidity_data.get("position_sizing", {})
        scores["liquidity"] = {
            "score": liq_score,
            "rating": liquidity_data.get("liquidity_rating", "Unknown"),
            "days_to_liquidate": pos_sizing.get("days_to_liquidate"),
            "market_impact_bps": pos_sizing.get("estimated_slippage_bps"),
            "liquidity_constrained": pos_sizing.get("liquidity_constrained", False),
            "warnings": warnings,
        }
        conv = scores["conviction"]
        if liq_score < 4.0:
            conv["position_size_cap"] = "micro_cap_max_2pct"
            conv["liquidity_note"] = (
                "Liquidity score <4: max position 2% AUM regardless of conviction"
            )
        elif liq_score < 6.0:
            conv["position_size_cap"] = "small_cap_max_4pct"
            conv["liquidity_note"] = "Liquidity score <6: max position 4% AUM"
        else:
            conv["position_size_cap"] = "standard"

    # Short interest integration
    if short_interest_data:
        squeeze = short_interest_data.get("squeeze_analysis", {})
        positioning = short_interest_data.get("positioning", {})
        si = short_interest_data.get("short_interest", {})
        scores["short_interest"] = {
            "short_pct_float": si.get("short_pct_float"),
            "days_to_cover": squeeze.get("days_to_cover"),
            "squeeze_score": squeeze.get("squeeze_score"),
            "squeeze_risk_level": squeeze.get("squeeze_risk_level"),
            "momentum_vs_short": squeeze.get("momentum_vs_short"),
            "effective_free_float_pct": positioning.get("effective_free_float_pct"),
        }
        # For short-term reports, high squeeze score boosts conviction
        conv = scores["conviction"]
        sq_score = squeeze.get("squeeze_score", 0)
        if args.report_type == "short" and sq_score >= 7.0:
            conv["squeeze_catalyst"] = True
            conv["squeeze_note"] = (
                f"Squeeze score {sq_score:.1f}/10 — short-term upside catalyst"
            )
        elif sq_score >= 8.0:
            conv.setdefault("catalysts", []).append(
                f"High squeeze potential ({sq_score:.1f}/10)"
            )

    # Activist exposure integration
    if activist_data:
        activist_exp = activist_data.get("activist_exposure", {})
        insider = activist_data.get("insider_activity", {})
        scores["activist_exposure"] = {
            "activist_presence_score": activist_exp.get("activist_presence_score"),
            "proxy_fight_probability": activist_exp.get("proxy_fight_probability"),
            "activists_detected": activist_exp.get("activists_detected", []),
            "insider_confidence_ratio": insider.get("insider_confidence_ratio"),
            "cluster_selling_detected": insider.get("cluster_selling_detected"),
        }
        conv = scores["conviction"]
        presence = activist_exp.get("activist_presence_score", 0)
        if presence >= 7:
            conv.setdefault("catalysts", []).append(
                f"Activist involvement (score {presence}/10) — potential catalyst"
            )
        if insider.get("cluster_selling_detected"):
            conv.setdefault("warnings", []).append(
                "Insider cluster selling detected — management confidence flag"
            )

    # --- Portfolio Complementarity Analysis ---
    # Add portfolio_complementarity field for downstream consumption.
    # The orchestrator calls analyze_portfolio_complementarity() with all ranked
    # companies after individual scoring is complete.
    scores["portfolio_complementarity_available"] = True

    output = json.dumps(scores, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Portfolio Complementarity Analysis
# ---------------------------------------------------------------------------


def analyze_portfolio_complementarity(
    ranked_companies: list[dict],
) -> dict:
    """Analyze portfolio complementarity for the top-ranked companies.

    Checks for concentration risk and assigns position types.
    Called by the scorer agent after all companies are scored and ranked.

    Args:
        ranked_companies: List of company dicts, each containing at minimum:
            - ticker: str
            - composite_score: float
            - gics_sub_industry_code: str (8-digit GICS Level 4 code)
            - volatility: float (annualized, optional)
            - moat_score: float (1-10, optional)
            - beta: float (optional)
            - pe_ratio: float (optional)
            - growth_rate: float (optional)

    Returns:
        dict with position_types, concentration_warnings, and enriched rankings.
    """
    if not ranked_companies:
        return {"error": "No companies provided", "concentration_warnings": []}

    warnings: list[str] = []
    top5 = ranked_companies[:5]

    # --- Sub-industry concentration check ---
    # If >=3 of top-5 companies share the same GICS Level 4 code -> flag
    if len(top5) >= 3:
        gics_codes = [c.get("gics_sub_industry_code", "unknown") for c in top5]
        code_counts = Counter(gics_codes)
        for code, count in code_counts.items():
            if count >= 3 and code != "unknown":
                warnings.append(
                    f"⚠️ 行业集中度过高: "
                    f"{count}/5 companies share GICS L4 code {code}"
                )

    # --- Factor style check ---
    # If all top-5 have similar characteristics -> flag
    if len(top5) >= 3:
        high_beta_count = sum(1 for c in top5 if (c.get("beta") or 1.0) > 1.3)
        low_pe_count = sum(
            1 for c in top5 if c.get("pe_ratio") is not None and c["pe_ratio"] < 15
        )
        high_growth_count = sum(
            1
            for c in top5
            if c.get("growth_rate") is not None and c["growth_rate"] > 0.20
        )

        if high_beta_count >= 4:
            warnings.append(
                "⚠️ 风格同质化: "
                "4+ of top-5 are high-beta (>1.3) — portfolio amplifies market swings"
            )
        if low_pe_count >= 4:
            warnings.append(
                "⚠️ 风格同质化: "
                "4+ of top-5 are low-PE value (<15) — consider adding growth exposure"
            )
        if high_growth_count >= 4:
            warnings.append(
                "⚠️ 风格同质化: "
                "4+ of top-5 are high-growth (>20%) — consider adding defensive names"
            )

    # --- Position type classification ---
    enriched: list[dict] = []
    for company in ranked_companies:
        score = company.get("composite_score", 5.0)
        vol = company.get("volatility", 0.25)
        moat = company.get("moat_score", 5.0)
        beta = company.get("beta", 1.0)

        # Classification logic:
        # core: High score + low vol + strong moat -> defensive, >20% position worthy
        # satellite: Mid-high score + moderate characteristics -> 5-20% position
        # option: High score driven by momentum/growth but higher risk -> <5% speculative
        if score >= 7.0 and vol <= 0.30 and moat >= 7.0:
            position_type = "core"
            position_rationale = "High conviction + low volatility + strong moat -> defensive core (>20%)"
        elif score >= 6.0 and vol <= 0.45:
            position_type = "satellite"
            position_rationale = (
                "Solid score + moderate risk -> satellite position (5-20%)"
            )
        elif score >= 6.5 and (vol > 0.45 or beta > 1.5):
            position_type = "option"
            position_rationale = (
                "High score but elevated risk -> speculative option (<5%)"
            )
        elif score >= 5.5:
            position_type = "satellite"
            position_rationale = (
                "Moderate conviction -> smaller satellite position (5-10%)"
            )
        else:
            position_type = "option"
            position_rationale = (
                "Lower conviction or higher risk -> speculative only (<5%)"
            )

        enriched.append(
            {
                **company,
                "position_type": position_type,
                "position_rationale": position_rationale,
            }
        )

    # Summary statistics
    type_counts = Counter(e["position_type"] for e in enriched)

    return {
        "enriched_rankings": enriched,
        "concentration_warnings": warnings,
        "position_type_distribution": dict(type_counts),
        "portfolio_health": {
            "has_concentration_risk": len(warnings) > 0,
            "warning_count": len(warnings),
            "core_count": type_counts.get("core", 0),
            "satellite_count": type_counts.get("satellite", 0),
            "option_count": type_counts.get("option", 0),
        },
        "methodology": (
            "Position types: core (high score + low vol + moat >= 7 -> >20%), "
            "satellite (mid-high score + moderate risk -> 5-20%), "
            "option (high score but elevated risk -> <5%). "
            "Concentration: flags >= 3/5 same GICS L4 or 4/5 same factor style."
        ),
    }


if __name__ == "__main__":
    main()
