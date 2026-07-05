#!/usr/bin/env python3
"""
detect_growth_inflection.py — Detect business growth inflection points.

Forward-looking signals that a company's growth trajectory is changing
(accelerating or decelerating). Integrates at Stage 5-6 (fundamental analysis).

Usage:
    uv run python detect_growth_inflection.py INPUT_JSON
    uv run python detect_growth_inflection.py INPUT_JSON --output reports/inflection.json
    uv run python detect_growth_inflection.py INPUT_JSON --segments-json segments.json
    uv run python detect_growth_inflection.py INPUT_JSON --peer-growth-json peers.json

Input:
    INPUT_JSON — Path to raw financials JSON (from fetch_financials.py).
                 Expected structure: {financials: {income_statement: {...}, balance_sheet: {...}}}
                 or {TICKER: {financials: {...}}} for multi-ticker format.

    --segments-json — Optional segment breakdown data:
        {"segments": [{"name": "...", "revenue": [{"period": "...", "value": N}, ...]}]}

    --peer-growth-json — Optional peer growth rates:
        {"peers": [{"ticker": "...", "yoy_growth_rates": [0.12, 0.15, ...]}]}

Output (JSON):
    Composite inflection score (-10 to +10) across 5 dimensions:
      1. Revenue Acceleration (二阶导): growth rate acceleration/deceleration
      2. Segment Mix Shift (新业务占比突变): new business emergence
      3. Margin Regime Change (毛利率结构性拐点): structural margin inflection
      4. R&D-to-Revenue Transmission (研发→收入转化): R&D payoff signals
      5. Customer/Revenue Concentration (客户集中度骤变): diversification shifts

Methodology:
    Deterministic scoring — no external API calls required.
    Graceful degradation: missing dimensions excluded, weights re-normalized.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _safe_div(num: float | None, den: float | None) -> float | None:
    """Safe division: returns None if numerator/denominator is None or zero denominator."""
    if num is None or den is None:
        return None
    if den == 0:
        return None
    return num / den


def _r(value: float | None, places: int = 4) -> float | None:
    """Round value to given decimal places; pass-through None."""
    if value is None:
        return None
    return round(value, places)


def _extract(series: list | None) -> list[float]:
    """Extract numeric values from [{period, value}, ...] format, preserving order."""
    if not series:
        return []
    result = []
    for item in series:
        if isinstance(item, dict):
            v = item.get("value")
            if v is not None:
                try:
                    result.append(float(v))
                except (TypeError, ValueError):
                    pass
        elif isinstance(item, (int, float)):
            result.append(float(item))
    return result


def _extract_with_periods(series: list | None) -> list[tuple[str, float]]:
    """Extract (period, value) tuples from [{period, value}, ...] format."""
    if not series:
        return []
    result = []
    for item in series:
        if isinstance(item, dict):
            period = item.get("period", "")
            v = item.get("value")
            if v is not None:
                try:
                    result.append((period, float(v)))
                except (TypeError, ValueError):
                    pass
    return result


def _mean(values: list[float]) -> float | None:
    """Simple arithmetic mean; returns None if empty."""
    if not values:
        return None
    return sum(values) / len(values)


def _stdev(values: list[float]) -> float | None:
    """Sample standard deviation (n-1); returns None if < 2 values."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((x - avg) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _linear_regression_slope(values: list[float]) -> float | None:
    """Simple linear regression slope over indices 0..n-1. Returns None if < 3 values."""
    n = len(values)
    if n < 3:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return None
    return numerator / denominator


def _compute_yoy_growth(values: list[float], periods_per_year: int = 4) -> list[float]:
    """Compute YoY growth rates. Values assumed chronological (oldest first).
    Returns growth rates aligned to the later period."""
    if len(values) <= periods_per_year:
        return []
    growth_rates = []
    for i in range(periods_per_year, len(values)):
        prev = values[i - periods_per_year]
        curr = values[i]
        if prev and prev != 0:
            growth_rates.append((curr - prev) / abs(prev))
        else:
            growth_rates.append(0.0)
    return growth_rates


def _compute_acceleration(growth_rates: list[float]) -> list[float]:
    """Compute acceleration (first difference of growth rates)."""
    if len(growth_rates) < 2:
        return []
    return [growth_rates[i] - growth_rates[i - 1] for i in range(1, len(growth_rates))]


def _compute_jerk(acceleration: list[float]) -> list[float]:
    """Compute jerk (second difference — first difference of acceleration)."""
    if len(acceleration) < 2:
        return []
    return [acceleration[i] - acceleration[i - 1] for i in range(1, len(acceleration))]


def _compute_hhi(shares: list[float]) -> float | None:
    """Herfindahl-Hirschman Index from percentage shares (0-100 scale).
    Returns 0-10000 scale."""
    if not shares:
        return None
    total = sum(shares)
    if total == 0:
        return None
    normalized = [s / total * 100 for s in shares]
    return sum(s**2 for s in normalized)


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp value to [low, high] range."""
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Dimension 1: Revenue Acceleration (二阶导)
# ---------------------------------------------------------------------------


def _score_revenue_acceleration(financials: dict) -> dict:
    """Score: -5 to +5. Detects growth rate acceleration/deceleration."""
    income = financials.get("income_statement", {})
    revenue_series = income.get("revenue") or income.get("total_revenue")

    raw_values = _extract(revenue_series)
    if len(raw_values) < 6:
        return {
            "score": None,
            "direction": None,
            "detail": f"Insufficient revenue data ({len(raw_values)} periods, need >= 6)",
            "quarterly_growth_rates": [],
            "acceleration_series": [],
            "note": "Minimum 6 quarterly data points required for acceleration analysis",
        }

    # Ensure chronological order (oldest first) — fetch_financials typically has newest first
    # Check if first period is more recent than last
    revenue_with_periods = _extract_with_periods(revenue_series)
    if revenue_with_periods and len(revenue_with_periods) >= 2:
        first_period = revenue_with_periods[0][0]
        last_period = revenue_with_periods[-1][0]
        if first_period > last_period:
            raw_values = list(reversed(raw_values))

    # Compute YoY growth rates (quarterly)
    growth_rates = _compute_yoy_growth(raw_values, periods_per_year=4)
    if len(growth_rates) < 3:
        # Try sequential growth if not enough for YoY
        growth_rates = []
        for i in range(1, len(raw_values)):
            prev = raw_values[i - 1]
            if prev and prev != 0:
                growth_rates.append((raw_values[i] - prev) / abs(prev))

    if len(growth_rates) < 3:
        return {
            "score": None,
            "direction": None,
            "detail": "Insufficient growth rate data for acceleration computation",
            "quarterly_growth_rates": [_r(g) for g in growth_rates],
            "acceleration_series": [],
            "note": "Need at least 3 growth rate observations",
        }

    # Compute acceleration and jerk
    acceleration = _compute_acceleration(growth_rates)
    jerk = _compute_jerk(acceleration)

    # Scoring logic
    score = 0.0
    direction = "stable"
    detail_parts = []

    if len(acceleration) >= 2:
        recent_accel = acceleration[-min(3, len(acceleration)) :]
        avg_recent_accel = _mean(recent_accel)

        # Check for sign change (inflection)
        if len(acceleration) >= 3:
            older_accel = acceleration[:-2]
            recent_sign = 1 if avg_recent_accel > 0 else -1
            older_sign = 1 if _mean(older_accel) > 0 else -1

            if recent_sign != older_sign:
                detail_parts.append("acceleration sign change detected")

        # Count consecutive positive/negative acceleration
        consecutive_positive = 0
        consecutive_negative = 0
        for a in reversed(acceleration):
            if a > 0:
                consecutive_positive += 1
                if consecutive_negative > 0:
                    break
            elif a < 0:
                consecutive_negative += 1
                if consecutive_positive > 0:
                    break
            else:
                break

        # Score based on magnitude and consistency
        if avg_recent_accel is not None:
            # Convert to percentage points for scoring
            accel_pp = avg_recent_accel * 100

            if accel_pp > 5:
                score = min(5.0, 2.0 + accel_pp / 5.0)
                direction = "accelerating"
            elif accel_pp > 2:
                score = 1.5 + accel_pp / 5.0
                direction = "accelerating"
            elif accel_pp > 0:
                score = accel_pp / 3.0
                direction = "mildly_accelerating"
            elif accel_pp > -2:
                score = accel_pp / 3.0
                direction = "mildly_decelerating"
            elif accel_pp > -5:
                score = -1.5 + accel_pp / 5.0
                direction = "decelerating"
            else:
                score = max(-5.0, -2.0 + accel_pp / 5.0)
                direction = "decelerating"

            # Bonus for consistency
            if consecutive_positive >= 3:
                score = min(5.0, score + 1.0)
                detail_parts.append(
                    f"{consecutive_positive} consecutive quarters of positive acceleration"
                )
            elif consecutive_negative >= 3:
                score = max(-5.0, score - 1.0)
                detail_parts.append(
                    f"{consecutive_negative} consecutive quarters of negative acceleration"
                )

            accel_values_str = ", ".join(f"{a*100:+.1f}pp" for a in recent_accel)
            detail_parts.append(f"recent acceleration: {accel_values_str}")

    score = _clamp(score, -5.0, 5.0)
    detail = (
        "; ".join(detail_parts)
        if detail_parts
        else "No significant acceleration signal"
    )

    return {
        "score": _r(score, 2),
        "direction": direction,
        "detail": detail,
        "quarterly_growth_rates": [_r(g) for g in growth_rates],
        "acceleration_series": [_r(a) for a in acceleration],
    }


# ---------------------------------------------------------------------------
# Dimension 2: Segment Mix Shift (新业务占比突变)
# ---------------------------------------------------------------------------


def _score_segment_shift(segments_data: dict | None) -> dict:
    """Score: 0 to 10. Detects new business emergence via segment mix change."""
    if not segments_data or not segments_data.get("segments"):
        return {
            "score": None,
            "direction": None,
            "detail": "No segment data available",
            "segments": [],
            "note": "Provide --segments-json for segment mix analysis",
        }

    segments = segments_data["segments"]
    if not segments or len(segments) < 2:
        return {
            "score": None,
            "direction": None,
            "detail": "Need at least 2 segments for mix analysis",
            "segments": [],
            "note": "Insufficient segment diversity",
        }

    # Compute current vs historical share for each segment
    segment_results = []
    max_share_change = 0.0
    fastest_growth_rate = 0.0
    company_avg_growth = 0.0

    # Compute total revenue at current and past periods
    total_now = 0.0
    total_past = 0.0

    for seg in segments:
        rev_series = _extract(seg.get("revenue"))
        if len(rev_series) < 2:
            continue

        # Ensure chronological order (oldest first)
        periods = _extract_with_periods(seg.get("revenue"))
        if periods and len(periods) >= 2:
            if periods[0][0] > periods[-1][0]:
                rev_series = list(reversed(rev_series))

        total_now += rev_series[-1]
        # Use value from ~4 quarters ago or earliest available
        past_idx = max(0, len(rev_series) - 5)
        total_past += rev_series[past_idx]

    if total_now == 0:
        return {
            "score": None,
            "direction": None,
            "detail": "Zero total revenue — cannot compute mix",
            "segments": [],
            "note": "Revenue data appears invalid",
        }

    # Compute company average growth
    if total_past > 0:
        company_avg_growth = (total_now - total_past) / total_past

    for seg in segments:
        name = seg.get("name", "Unknown")
        rev_series = _extract(seg.get("revenue"))
        if len(rev_series) < 2:
            segment_results.append(
                {"name": name, "pct_now": None, "pct_1y_ago": None, "growth": None}
            )
            continue

        # Ensure chronological
        periods = _extract_with_periods(seg.get("revenue"))
        if periods and len(periods) >= 2:
            if periods[0][0] > periods[-1][0]:
                rev_series = list(reversed(rev_series))

        current_rev = rev_series[-1]
        past_idx = max(0, len(rev_series) - 5)
        past_rev = rev_series[past_idx]

        pct_now = (current_rev / total_now * 100) if total_now else 0
        pct_past = (past_rev / total_past * 100) if total_past else 0

        seg_growth = (
            _safe_div(current_rev - past_rev, abs(past_rev)) if past_rev else None
        )

        share_change = pct_now - pct_past
        max_share_change = max(max_share_change, abs(share_change))
        if seg_growth is not None:
            fastest_growth_rate = max(fastest_growth_rate, seg_growth)

        segment_results.append(
            {
                "name": name,
                "pct_now": _r(pct_now, 1),
                "pct_1y_ago": _r(pct_past, 1),
                "growth": _r(seg_growth),
            }
        )

    # Scoring
    score = 0.0
    direction = "stable"
    detail_parts = []

    # Criterion 1: Segment growing from <10% to >20% (worth up to 4 points)
    for sr in segment_results:
        if sr["pct_1y_ago"] is not None and sr["pct_now"] is not None:
            if sr["pct_1y_ago"] < 10 and sr["pct_now"] > 20:
                score += 4.0
                detail_parts.append(
                    f"{sr['name']} grew from {sr['pct_1y_ago']:.0f}% to {sr['pct_now']:.0f}% of revenue"
                )
                direction = "new_business_emerging"
                break
            elif sr["pct_1y_ago"] < 15 and sr["pct_now"] > 25:
                score += 3.0
                detail_parts.append(
                    f"{sr['name']} grew from {sr['pct_1y_ago']:.0f}% to {sr['pct_now']:.0f}% of revenue"
                )
                direction = "new_business_emerging"
                break

    # Criterion 2: Fastest segment > 2x company avg (worth up to 3 points)
    if company_avg_growth > 0 and fastest_growth_rate > 2 * company_avg_growth:
        multiplier = fastest_growth_rate / company_avg_growth
        score += min(3.0, multiplier - 1.0)
        detail_parts.append(
            f"fastest segment growing {multiplier:.1f}x company average"
        )
        if direction == "stable":
            direction = "segment_divergence"

    # Criterion 3: Mix shift magnitude (worth up to 3 points)
    if max_share_change > 15:
        score += 3.0
        detail_parts.append(f"max share change: {max_share_change:.1f}pp")
    elif max_share_change > 10:
        score += 2.0
        detail_parts.append(f"max share change: {max_share_change:.1f}pp")
    elif max_share_change > 5:
        score += 1.0

    score = _clamp(score, 0.0, 10.0)
    detail = (
        "; ".join(detail_parts) if detail_parts else "No significant segment mix shift"
    )

    return {
        "score": _r(score, 2),
        "direction": direction,
        "detail": detail,
        "segments": segment_results,
    }


# ---------------------------------------------------------------------------
# Dimension 3: Margin Regime Change (毛利率结构性拐点)
# ---------------------------------------------------------------------------


def _score_margin_regime(financials: dict) -> dict:
    """Score: -5 to +5. Detects structural margin inflection."""
    income = financials.get("income_statement", {})

    revenue_raw = _extract(income.get("revenue") or income.get("total_revenue"))
    gross_profit_raw = _extract(income.get("gross_profit"))
    operating_income_raw = _extract(income.get("operating_income"))
    opex_raw = _extract(
        income.get("operating_expenses") or income.get("total_operating_expenses")
    )

    # Reverse if needed (newest-first to chronological)
    revenue_periods = _extract_with_periods(
        income.get("revenue") or income.get("total_revenue")
    )
    is_reversed = False
    if revenue_periods and len(revenue_periods) >= 2:
        if revenue_periods[0][0] > revenue_periods[-1][0]:
            is_reversed = True
            revenue_raw = list(reversed(revenue_raw))
            gross_profit_raw = list(reversed(gross_profit_raw))
            operating_income_raw = list(reversed(operating_income_raw))
            opex_raw = list(reversed(opex_raw))

    # Compute margin series
    gross_margins = []
    for i in range(min(len(gross_profit_raw), len(revenue_raw))):
        gm = _safe_div(gross_profit_raw[i], revenue_raw[i])
        if gm is not None:
            gross_margins.append(gm)

    op_margins = []
    for i in range(min(len(operating_income_raw), len(revenue_raw))):
        om = _safe_div(operating_income_raw[i], revenue_raw[i])
        if om is not None:
            op_margins.append(om)

    if len(gross_margins) < 4 and len(op_margins) < 4:
        return {
            "score": None,
            "direction": None,
            "detail": "Insufficient margin data for regime analysis",
            "margin_series": {"gross_margins": [], "op_margins": []},
            "note": "Need at least 4 quarters of margin data",
        }

    score = 0.0
    direction = "stable"
    detail_parts = []

    # Analyze gross margin trend (trailing 8 quarters or available)
    gm_window = gross_margins[-8:] if len(gross_margins) >= 8 else gross_margins
    gm_slope = _linear_regression_slope(gm_window)

    if gm_slope is not None:
        # Check for slope sign change (split series in half)
        if len(gm_window) >= 6:
            mid = len(gm_window) // 2
            first_half_slope = _linear_regression_slope(gm_window[: mid + 1])
            second_half_slope = _linear_regression_slope(gm_window[mid:])

            if first_half_slope is not None and second_half_slope is not None:
                if first_half_slope < -0.001 and second_half_slope > 0.001:
                    score += 2.5
                    detail_parts.append(
                        "gross margin slope turned positive after compression"
                    )
                    direction = "expanding"
                elif first_half_slope > 0.001 and second_half_slope < -0.001:
                    score -= 2.5
                    detail_parts.append(
                        "gross margin slope turned negative after expansion"
                    )
                    direction = "compressing"

        # Threshold crossing: > 40% gross margin = software economics
        if gm_window and gm_window[-1] > 0.40:
            if len(gm_window) >= 4 and gm_window[-4] <= 0.40:
                score += 1.0
                detail_parts.append(
                    "gross margin crossed 40% threshold (software-like)"
                )

    # Analyze operating margin
    om_window = op_margins[-8:] if len(op_margins) >= 8 else op_margins
    om_slope = _linear_regression_slope(om_window)

    if om_slope is not None:
        if om_slope > 0.005:
            score += 1.5
            if direction == "stable":
                direction = "expanding"
            detail_parts.append(
                f"operating margin trending up (slope: {om_slope*100:.2f}pp/Q)"
            )
        elif om_slope < -0.005:
            score -= 1.5
            if direction == "stable":
                direction = "compressing"
            detail_parts.append(
                f"operating margin trending down (slope: {om_slope*100:.2f}pp/Q)"
            )

    # Operating leverage: revenue growing faster than opex for 3+ quarters
    if len(revenue_raw) >= 5 and len(opex_raw) >= 5:
        rev_growth = _compute_yoy_growth(revenue_raw, 4)
        opex_growth = _compute_yoy_growth(opex_raw, 4)

        # Use sequential growth if not enough for YoY
        if len(rev_growth) < 3:
            rev_growth = [
                (revenue_raw[i] - revenue_raw[i - 1]) / abs(revenue_raw[i - 1])
                for i in range(1, len(revenue_raw))
                if revenue_raw[i - 1] != 0
            ]
            opex_growth = [
                (opex_raw[i] - opex_raw[i - 1]) / abs(opex_raw[i - 1])
                for i in range(1, len(opex_raw))
                if opex_raw[i - 1] != 0
            ]

        min_len = min(len(rev_growth), len(opex_growth))
        if min_len >= 3:
            leverage_quarters = sum(
                1
                for i in range(max(0, min_len - 4), min_len)
                if rev_growth[i] > opex_growth[i]
            )
            if leverage_quarters >= 3:
                score += 1.0
                detail_parts.append(
                    f"operating leverage: rev > opex growth for {leverage_quarters} quarters"
                )
                if direction == "stable":
                    direction = "expanding"

    score = _clamp(score, -5.0, 5.0)
    detail = (
        "; ".join(detail_parts) if detail_parts else "No margin regime change detected"
    )

    return {
        "score": _r(score, 2),
        "direction": direction,
        "detail": detail,
        "margin_series": {
            "gross_margins": [_r(m) for m in gross_margins],
            "op_margins": [_r(m) for m in op_margins],
        },
    }


# ---------------------------------------------------------------------------
# Dimension 4: R&D-to-Revenue Transmission (研发→收入转化)
# ---------------------------------------------------------------------------


def _score_rnd_transmission(financials: dict) -> dict:
    """Score: 0 to 10. Detects R&D investment payoff signals."""
    income = financials.get("income_statement", {})

    revenue_raw = _extract(income.get("revenue") or income.get("total_revenue"))
    rnd_raw = _extract(
        income.get("research_and_development")
        or income.get("research_development")
        or income.get("rnd")
        or income.get("r_and_d")
    )
    gross_profit_raw = _extract(income.get("gross_profit"))

    # Reverse if needed
    revenue_periods = _extract_with_periods(
        income.get("revenue") or income.get("total_revenue")
    )
    if revenue_periods and len(revenue_periods) >= 2:
        if revenue_periods[0][0] > revenue_periods[-1][0]:
            revenue_raw = list(reversed(revenue_raw))
            rnd_raw = list(reversed(rnd_raw))
            gross_profit_raw = list(reversed(gross_profit_raw))

    if not rnd_raw or len(rnd_raw) < 4:
        return {
            "score": None,
            "direction": None,
            "detail": "R&D data unavailable or insufficient",
            "rnd_pct_series": [],
            "note": "No research_and_development field in income statement",
        }

    # Compute R&D as % of revenue
    min_len = min(len(rnd_raw), len(revenue_raw))
    rnd_pct = []
    for i in range(min_len):
        pct = _safe_div(rnd_raw[i], revenue_raw[i])
        if pct is not None:
            rnd_pct.append(pct)

    if len(rnd_pct) < 4:
        return {
            "score": None,
            "direction": None,
            "detail": "Insufficient R&D/Revenue ratio data",
            "rnd_pct_series": [_r(p) for p in rnd_pct],
            "note": "Need at least 4 periods of R&D % data",
        }

    score = 0.0
    direction = "investing"
    detail_parts = []

    # Signal 1: R&D % declining WHILE revenue accelerating
    rnd_slope = _linear_regression_slope(rnd_pct[-6:] if len(rnd_pct) >= 6 else rnd_pct)
    rev_growth = _compute_yoy_growth(revenue_raw, 4)
    if not rev_growth:
        rev_growth = [
            (revenue_raw[i] - revenue_raw[i - 1]) / abs(revenue_raw[i - 1])
            for i in range(1, len(revenue_raw))
            if revenue_raw[i - 1] != 0
        ]

    rev_acceleration = _compute_acceleration(rev_growth) if len(rev_growth) >= 2 else []

    if rnd_slope is not None and rnd_slope < -0.002:
        # R&D % is declining
        if rev_growth and _mean(rev_growth[-3:]) and _mean(rev_growth[-3:]) > 0.05:
            score += 4.0
            direction = "transmitting"
            rnd_change = (rnd_pct[-1] - rnd_pct[0]) * 100
            detail_parts.append(
                f"R&D/Rev declining ({rnd_pct[0]*100:.1f}% → {rnd_pct[-1]*100:.1f}%) "
                f"while revenue growing"
            )

    # Signal 2: Revenue growth > R&D growth for 3+ consecutive quarters
    rnd_growth = _compute_yoy_growth(rnd_raw, 4)
    if not rnd_growth:
        rnd_growth = [
            (rnd_raw[i] - rnd_raw[i - 1]) / abs(rnd_raw[i - 1])
            for i in range(1, len(rnd_raw))
            if rnd_raw[i - 1] != 0
        ]

    if rev_growth and rnd_growth:
        min_gr_len = min(len(rev_growth), len(rnd_growth))
        if min_gr_len >= 3:
            recent_rev = rev_growth[-min(4, min_gr_len) :]
            recent_rnd = rnd_growth[-min(4, min_gr_len) :]
            outperform_count = sum(1 for r, d in zip(recent_rev, recent_rnd) if r > d)
            if outperform_count >= 3:
                score += 3.0
                direction = "transmitting"
                detail_parts.append(
                    f"Revenue growth > R&D growth for {outperform_count} consecutive quarters"
                )

    # Signal 3: Gross margin expanding simultaneously (product maturity)
    if gross_profit_raw and revenue_raw:
        gm_series = []
        for i in range(min(len(gross_profit_raw), len(revenue_raw))):
            gm = _safe_div(gross_profit_raw[i], revenue_raw[i])
            if gm is not None:
                gm_series.append(gm)
        if len(gm_series) >= 4:
            gm_slope = _linear_regression_slope(
                gm_series[-6:] if len(gm_series) >= 6 else gm_series
            )
            if gm_slope is not None and gm_slope > 0.003:
                score += 3.0
                detail_parts.append("gross margin expanding (product maturity signal)")
                if direction == "investing":
                    direction = "early_transmission"

    score = _clamp(score, 0.0, 10.0)
    detail = (
        "; ".join(detail_parts)
        if detail_parts
        else "No R&D transmission signal detected"
    )

    return {
        "score": _r(score, 2),
        "direction": direction,
        "detail": detail,
        "rnd_pct_series": [_r(p) for p in rnd_pct],
    }


# ---------------------------------------------------------------------------
# Dimension 5: Customer/Revenue Concentration Change (客户集中度骤变)
# ---------------------------------------------------------------------------


def _score_concentration(financials: dict, segments_data: dict | None) -> dict:
    """Score: -5 to +5. Detects concentration/diversification shifts."""
    # Try geographic segments first
    geo_data = None
    if segments_data:
        geo_data = segments_data.get("geographic") or segments_data.get("geography")

    # Also look in financials for geographic breakdown
    if not geo_data:
        geo_data = financials.get("geographic_revenue") or financials.get("geography")

    if not geo_data and not segments_data:
        return {
            "score": None,
            "direction": None,
            "detail": "Insufficient segment/geographic data",
            "note": "No customer concentration data available",
        }

    # Use segment data as proxy for concentration
    segments = []
    if segments_data and segments_data.get("segments"):
        segments = segments_data["segments"]
    elif geo_data and isinstance(geo_data, list):
        segments = geo_data

    if len(segments) < 2:
        return {
            "score": None,
            "direction": None,
            "detail": "Insufficient segment diversity for concentration analysis",
            "note": "Need at least 2 segments/regions",
        }

    # Compute HHI at current and historical points
    current_shares = []
    past_shares = []

    for seg in segments:
        rev_series = _extract(seg.get("revenue") or seg.get("value"))
        if not rev_series:
            # Try direct value
            val = seg.get("revenue") or seg.get("value")
            if isinstance(val, (int, float)):
                current_shares.append(float(val))
            continue

        # Ensure chronological
        periods = _extract_with_periods(seg.get("revenue") or [])
        if periods and len(periods) >= 2:
            if periods[0][0] > periods[-1][0]:
                rev_series = list(reversed(rev_series))

        current_shares.append(rev_series[-1])
        past_idx = max(0, len(rev_series) - 5)
        if len(rev_series) > 1:
            past_shares.append(rev_series[past_idx])

    if not current_shares:
        return {
            "score": None,
            "direction": None,
            "detail": "Could not extract revenue shares from segments",
            "note": "Segment data format not recognized",
        }

    hhi_current = _compute_hhi(current_shares)
    hhi_past = _compute_hhi(past_shares) if past_shares else None

    score = 0.0
    direction = "stable"
    detail_parts = []

    if hhi_current is not None and hhi_past is not None:
        hhi_change = hhi_current - hhi_past

        # Significant HHI drop = diversification (positive)
        if hhi_change < -500:
            score = min(5.0, abs(hhi_change) / 500.0)
            direction = "diversifying"
            detail_parts.append(
                f"HHI dropped from {hhi_past:.0f} to {hhi_current:.0f} (diversification)"
            )
        elif hhi_change < -200:
            score = abs(hhi_change) / 500.0
            direction = "mildly_diversifying"
            detail_parts.append(f"HHI declining: {hhi_past:.0f} → {hhi_current:.0f}")
        elif hhi_change > 500:
            score = -min(5.0, hhi_change / 500.0)
            direction = "concentrating"
            detail_parts.append(
                f"HHI spiked from {hhi_past:.0f} to {hhi_current:.0f} (concentration risk)"
            )
        elif hhi_change > 200:
            score = -hhi_change / 500.0
            direction = "mildly_concentrating"
            detail_parts.append(f"HHI rising: {hhi_past:.0f} → {hhi_current:.0f}")
        else:
            detail_parts.append(f"HHI stable ({hhi_current:.0f})")

    elif hhi_current is not None:
        # Only current snapshot available
        if hhi_current < 2000:
            score = 2.0
            direction = "well_diversified"
            detail_parts.append(f"HHI = {hhi_current:.0f} (well diversified)")
        elif hhi_current > 4000:
            score = -2.0
            direction = "highly_concentrated"
            detail_parts.append(f"HHI = {hhi_current:.0f} (highly concentrated)")
        else:
            detail_parts.append(f"HHI = {hhi_current:.0f} (moderate concentration)")

    score = _clamp(score, -5.0, 5.0)
    detail = (
        "; ".join(detail_parts) if detail_parts else "No concentration change detected"
    )

    return {
        "score": _r(score, 2),
        "direction": direction,
        "detail": detail,
        "hhi_current": _r(hhi_current, 0) if hhi_current else None,
        "hhi_past": _r(hhi_past, 0) if hhi_past else None,
    }


# ---------------------------------------------------------------------------
# Composite scoring & verdict
# ---------------------------------------------------------------------------

_DIMENSION_WEIGHTS = {
    "revenue_acceleration": 0.30,
    "segment_shift": 0.20,
    "margin_regime": 0.25,
    "rnd_transmission": 0.15,
    "concentration": 0.10,
}

_DIMENSION_RANGES = {
    "revenue_acceleration": (-5, 5),
    "segment_shift": (0, 10),
    "margin_regime": (-5, 5),
    "rnd_transmission": (0, 10),
    "concentration": (-5, 5),
}


def _normalize_score(score: float, dim_range: tuple[float, float]) -> float:
    """Normalize a dimension score to -1..+1 range for composite calculation."""
    low, high = dim_range
    mid = (low + high) / 2.0
    half_range = (high - low) / 2.0
    if half_range == 0:
        return 0.0
    return (score - mid) / half_range


def _compute_composite(dimensions: dict) -> dict:
    """Compute weighted composite inflection score."""
    available = {}
    for dim_key, dim_result in dimensions.items():
        if dim_result.get("score") is not None:
            available[dim_key] = dim_result["score"]

    if not available:
        return {
            "score": 0.0,
            "verdict": "NO_INFLECTION",
            "inflection_type": "none",
            "confidence": 0.0,
            "weights_used": {},
        }

    # Re-normalize weights for available dimensions
    total_weight = sum(_DIMENSION_WEIGHTS[k] for k in available)
    weights_used = {
        k: round(_DIMENSION_WEIGHTS[k] / total_weight, 2) for k in available
    }

    # Compute weighted normalized score
    composite_normalized = 0.0
    for dim_key, raw_score in available.items():
        normalized = _normalize_score(raw_score, _DIMENSION_RANGES[dim_key])
        weight = _DIMENSION_WEIGHTS[dim_key] / total_weight
        composite_normalized += normalized * weight

    # Scale to -10..+10
    composite_score = composite_normalized * 10.0
    composite_score = _clamp(composite_score, -10.0, 10.0)

    # Determine verdict
    if composite_score >= 7:
        verdict = "STRONG_POSITIVE_INFLECTION"
    elif composite_score >= 3:
        verdict = "MODERATE_POSITIVE_INFLECTION"
    elif composite_score >= -2:
        verdict = "NO_INFLECTION"
    elif composite_score >= -6:
        verdict = "MODERATE_NEGATIVE_INFLECTION"
    else:
        verdict = "STRONG_NEGATIVE_INFLECTION"

    # Determine inflection type from dominant signal
    inflection_type = "none"
    if composite_score > 2:
        # Find which positive dimension is strongest
        max_dim = max(
            available,
            key=lambda k: _normalize_score(available[k], _DIMENSION_RANGES[k]),
        )
        type_map = {
            "revenue_acceleration": "acceleration",
            "segment_shift": "model_shift",
            "margin_regime": "margin_expansion",
            "rnd_transmission": "acceleration",
            "concentration": "acceleration",
        }
        inflection_type = type_map.get(max_dim, "acceleration")
    elif composite_score < -2:
        inflection_type = "deceleration"

    # Confidence based on data completeness
    confidence = len(available) / len(_DIMENSION_WEIGHTS)
    # Bonus for having more quarters
    confidence = min(1.0, confidence)

    return {
        "score": _r(composite_score, 2),
        "verdict": verdict,
        "inflection_type": inflection_type,
        "confidence": _r(confidence, 2),
        "weights_used": weights_used,
    }


def _estimate_time_to_inflection(dimensions: dict, composite: dict) -> int | None:
    """Estimate quarters until inflection fully manifests (if early signal)."""
    score = composite.get("score", 0)
    if abs(score) < 2:
        return None  # No inflection detected

    # Early signal: moderate inflection with acceleration building
    rev_accel = dimensions.get("revenue_acceleration", {})
    accel_series = rev_accel.get("acceleration_series", [])

    if not accel_series:
        return None

    # If acceleration is building but not yet strong
    if 2 <= abs(score) <= 6:
        # Estimate based on acceleration magnitude
        recent_accel = (
            _mean(accel_series[-3:]) if len(accel_series) >= 3 else _mean(accel_series)
        )
        if recent_accel is not None and abs(recent_accel) > 0:
            # Rough estimate: how many more quarters at current rate to reach full inflection
            remaining = (10 - abs(score)) / max(abs(score), 1)
            return max(1, min(8, int(remaining + 1)))

    return 1  # Strong inflection already manifesting


def _assess_peer_relative(
    composite_score: float, peer_growth_data: dict | None
) -> str | None:
    """Assess whether this company is inflecting ahead of or behind peers."""
    if not peer_growth_data or not peer_growth_data.get("peers"):
        return None

    peers = peer_growth_data["peers"]
    peer_accelerations = []

    for peer in peers:
        growth_rates = peer.get("yoy_growth_rates", [])
        if len(growth_rates) >= 3:
            accel = _compute_acceleration(growth_rates)
            if accel:
                peer_accelerations.append(_mean(accel[-3:]))

    peer_accelerations = [a for a in peer_accelerations if a is not None]
    if not peer_accelerations:
        return None

    avg_peer_accel = _mean(peer_accelerations)
    if avg_peer_accel is None:
        return None

    # Compare company inflection to peer average
    if composite_score > 3 and avg_peer_accel < 0.02:
        return "AHEAD"
    elif composite_score < -3 and avg_peer_accel > -0.02:
        return "BEHIND"
    elif composite_score > 0 and avg_peer_accel < 0:
        return "AHEAD"
    elif composite_score < 0 and avg_peer_accel > 0:
        return "BEHIND"
    else:
        return "IN_LINE"


def _generate_key_evidence(dimensions: dict, composite: dict) -> list[str]:
    """Generate 3-5 bullet points explaining the inflection thesis."""
    evidence = []

    for dim_key in [
        "revenue_acceleration",
        "margin_regime",
        "segment_shift",
        "rnd_transmission",
        "concentration",
    ]:
        dim = dimensions.get(dim_key, {})
        if dim.get("score") is not None and dim.get("detail"):
            detail = dim["detail"]
            if detail and "No " not in detail and "Insufficient" not in detail:
                evidence.append(detail)

    # Cap at 5, minimum 1
    if not evidence:
        evidence.append("No significant inflection signals detected in available data")

    return evidence[:5]


def _generate_risk_to_thesis(dimensions: dict, composite: dict) -> list[str]:
    """Generate falsification risks for the inflection thesis."""
    risks = []
    score = composite.get("score", 0)

    if score > 2:
        # Positive inflection risks
        rev = dimensions.get("revenue_acceleration", {})
        if rev.get("direction") == "accelerating":
            risks.append(
                "Revenue acceleration may be one-time/seasonal rather than structural"
            )

        seg = dimensions.get("segment_shift", {})
        if seg.get("direction") == "new_business_emerging":
            risks.append(
                "New segment growth may not sustain if total addressable market is limited"
            )

        margin = dimensions.get("margin_regime", {})
        if margin.get("direction") == "expanding":
            risks.append(
                "Margin expansion may reverse under competitive pricing pressure"
            )

        rnd = dimensions.get("rnd_transmission", {})
        if rnd.get("direction") == "transmitting":
            risks.append("R&D payoff may plateau as initial product cycle matures")

    elif score < -2:
        # Negative inflection risks (risk that thesis is wrong = things improve)
        risks.append(
            "Deceleration may be temporary due to macro headwinds, not structural"
        )
        risks.append(
            "Management may execute a successful pivot not yet visible in data"
        )
        risks.append("Industry cyclicality may cause mean reversion in growth rates")

    if not risks:
        risks.append(
            "Stable trajectory may mask underlying structural shifts not yet in financials"
        )
        risks.append(
            "External catalyst (M&A, regulation, technology) could override current trend"
        )

    return risks[:4]


# ---------------------------------------------------------------------------
# Input normalization
# ---------------------------------------------------------------------------


def _normalize_input(raw_data: dict) -> tuple[str, dict]:
    """Normalize input JSON to (ticker, financials_dict).
    Handles both single-ticker and multi-ticker formats from fetch_financials.py.
    """
    # Direct format: {financials: {...}}
    if "financials" in raw_data:
        ticker = raw_data.get("ticker", raw_data.get("symbol", "UNKNOWN"))
        return ticker, raw_data.get("financials", {})

    # Multi-ticker format: {TICKER: {financials: {...}}}
    for key, value in raw_data.items():
        if isinstance(value, dict) and "financials" in value:
            return key, value.get("financials", {})

    # Fallback: treat entire dict as financials
    ticker = raw_data.get("ticker", raw_data.get("symbol", "UNKNOWN"))
    return ticker, raw_data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Detect business growth inflection points (5-dimension signal analysis)"
    )
    parser.add_argument(
        "input", help="Path to raw financials JSON (from fetch_financials.py)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--segments-json",
        help="Optional path to segment breakdown data (JSON with revenue by segment over time)",
    )
    parser.add_argument(
        "--peer-growth-json", help="Optional peer growth rates for relative comparison"
    )
    args = parser.parse_args()

    # Load primary input
    try:
        with open(args.input) as fh:
            raw_data = json.load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"Error: File not found: {args.input}\n")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"Error: Invalid JSON in {args.input}: {exc}\n")
        sys.exit(1)

    # Load optional segment data
    segments_data = None
    if args.segments_json:
        try:
            with open(args.segments_json) as fh:
                segments_data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"Warning: Could not load segments data: {exc}\n")

    # Load optional peer growth data
    peer_growth_data = None
    if args.peer_growth_json:
        try:
            with open(args.peer_growth_json) as fh:
                peer_growth_data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"Warning: Could not load peer growth data: {exc}\n")

    # Normalize input
    ticker, financials = _normalize_input(raw_data)

    # Count available quarters for confidence
    income = financials.get("income_statement", {})
    revenue_series = income.get("revenue") or income.get("total_revenue") or []
    quarters_available = len(_extract(revenue_series))

    # Run 5 dimension analyses
    dim_revenue = _score_revenue_acceleration(financials)
    dim_segment = _score_segment_shift(segments_data)
    dim_margin = _score_margin_regime(financials)
    dim_rnd = _score_rnd_transmission(financials)
    dim_concentration = _score_concentration(financials, segments_data)

    dimensions = {
        "revenue_acceleration": dim_revenue,
        "segment_shift": dim_segment,
        "margin_regime": dim_margin,
        "rnd_transmission": dim_rnd,
        "concentration": dim_concentration,
    }

    # Compute composite
    composite = _compute_composite(dimensions)

    # Adjust confidence based on data depth
    data_confidence = min(1.0, quarters_available / 12.0)
    composite["confidence"] = _r(
        min(1.0, (composite["confidence"] + data_confidence) / 2.0), 2
    )

    # Estimate time to inflection
    time_to_inflection = _estimate_time_to_inflection(dimensions, composite)

    # Assess peer-relative position
    peer_relative = _assess_peer_relative(composite["score"] or 0, peer_growth_data)

    # Generate evidence and risks
    key_evidence = _generate_key_evidence(dimensions, composite)
    risk_to_thesis = _generate_risk_to_thesis(dimensions, composite)

    # Data coverage summary
    has_segments = segments_data is not None and bool(segments_data.get("segments"))
    has_rnd = dim_rnd.get("score") is not None
    has_geographic = (
        dim_concentration.get("score") is not None
        and dim_concentration.get("direction") != "stable"
    )

    # Build output
    result = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "Growth inflection detection via 5-dimension signal analysis",
        "data_coverage": {
            "quarters_available": quarters_available,
            "has_segments": has_segments,
            "has_rnd": has_rnd,
            "has_geographic": has_geographic,
            "confidence": composite["confidence"],
        },
        "dimensions": dimensions,
        "composite": composite,
        "time_to_inflection_quarters": time_to_inflection,
        "peer_relative": peer_relative,
        "key_evidence": key_evidence,
        "risk_to_thesis": risk_to_thesis,
    }

    # Output
    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        sys.stderr.write(f"Output written to: {args.output}\n")
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
