#!/usr/bin/env python3
"""Management Capital Allocation Audit — practitioner-grade scorecard (A-F).

Sources for design:
  - @InvestmentTalk, @bluegrasscap (FinTwit) — buyback IRR + capex efficiency
  - Mauboussin Capital Allocation Scorecard (Counterpoint Global)
  - Buffett's "$1 retained → $1 market value" retention test
  - docs/research/fintwit-reddit-practitioner-insights-2026-05.md (P0.1)

Inputs:
  raw-data.json      — fetch_financials.py output (income/cf/balance-sheet history)
  capital_structure  — fetch_capital_structure.py output (already computes buyback ROI, SBC dilution)

Outputs (json):
  {
    "buyback":   {grade, irr_pct, sbc_dilution_pct, value_created_usd, flags},
    "capex":     {grade, capex_efficiency, capex_intensity_trend, flags},
    "dividend":  {grade, payout_ratio, payout_trend, sustainable, flags},
    "m_and_a":   {grade, goodwill_growth_pct, organic_vs_acquired, flags},
    "retention": {grade, buffett_test_pct, flags},
    "composite": {grade_letter, score_0_100, top_strengths, top_red_flags}
  }

Deterministic only. Missing data → null + note. Never invent figures.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _r(value: float | None, places: int = 4) -> float | None:
    return round(value, places) if value is not None else None


def _extract(series: list[dict]) -> list[float]:
    """Pull non-None values from [{period, value}, ...], most-recent first."""
    return [e["value"] for e in series if e.get("value") is not None]


def _cagr(start: float | None, end: float | None, years: int) -> float | None:
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def _grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# 1. Buyback grading (uses pre-computed capital_structure.json)
# ---------------------------------------------------------------------------


def grade_buyback(capital_structure: dict | None) -> dict:
    if not capital_structure:
        return {
            "grade": "N/A",
            "score": None,
            "note": "capital_structure.json not provided",
            "flags": [],
        }

    flags: list[str] = []
    score = 50

    irr = None
    roi_obj = capital_structure.get("buyback_analysis", {}).get("buyback_roi") or {}
    irr_pct = roi_obj.get("roi_pct")
    if irr_pct is not None:
        irr = irr_pct / 100.0
        if irr > 0.12:
            score = 90
        elif irr > 0.08:
            score = 78
        elif irr > 0.04:
            score = 65
        elif irr > 0:
            score = 50
        else:
            score = 25
            flags.append(f"Negative buyback IRR ({irr_pct:.1f}%) — destroying shareholder value")

    sbc_obj = capital_structure.get("sbc_dilution", {}) or {}
    sbc_dilution_pct = sbc_obj.get("sbc_pct_revenue")
    if sbc_dilution_pct is not None:
        if sbc_dilution_pct > 8:
            score = max(score - 25, 10)
            flags.append(f"SBC dilution {sbc_dilution_pct:.1f}% of revenue — heavy dilution offsets buybacks")
        elif sbc_dilution_pct > 5:
            score = max(score - 10, 15)
            flags.append(f"SBC dilution {sbc_dilution_pct:.1f}% — moderate dilution drag")

    return {
        "grade": _grade(score),
        "score": score,
        "irr_pct": irr_pct,
        "sbc_dilution_pct": sbc_dilution_pct,
        "methodology": "Buyback IRR from fetch_capital_structure.py; deduct points for SBC dilution >5% of revenue.",
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# 2. Capex efficiency
# ---------------------------------------------------------------------------


def grade_capex(financials: dict) -> dict:
    """Capex efficiency = Δrevenue (5yr) / cumulative capex (5yr).

    Higher = $1 of capex generates more incremental revenue.
    Top-quartile asset-light: >5x. Capital-heavy A: >2x. C: ~1x. F: <0.3x.
    """
    flags: list[str] = []

    revenue_series = _extract(financials.get("revenue", []))
    capex_series_signed = _extract(financials.get("capital_expenditure", []))
    capex_series = [abs(v) for v in capex_series_signed]

    if len(revenue_series) < 5 or len(capex_series) < 5:
        return {
            "grade": "N/A",
            "score": None,
            "note": "Need ≥5yr revenue and capex history",
            "flags": flags,
        }

    rev_recent = revenue_series[0]
    rev_5yr_ago = revenue_series[4]
    delta_revenue = rev_recent - rev_5yr_ago
    cumulative_capex = sum(capex_series[:5])

    capex_efficiency = _safe_div(delta_revenue, cumulative_capex)

    intensity_recent = _safe_div(capex_series[0], revenue_series[0])
    intensity_5yr_avg = _safe_div(
        sum(capex_series[:5]) / 5, sum(revenue_series[:5]) / 5
    )

    intensity_trend = "stable"
    if intensity_recent and intensity_5yr_avg:
        if intensity_recent > intensity_5yr_avg * 1.25:
            intensity_trend = "rising — entering capacity cycle peak (caution)"
            flags.append("Capex intensity rising 25%+ above 5yr avg — possible overinvestment risk")
        elif intensity_recent < intensity_5yr_avg * 0.75:
            intensity_trend = "falling — harvesting (bullish if FCF rising)"

    if capex_efficiency is None:
        score = None
        grade = "N/A"
    elif capex_efficiency > 5:
        score = 92
        grade = "A"
    elif capex_efficiency > 2:
        score = 78
        grade = "B"
    elif capex_efficiency > 1:
        score = 62
        grade = "C"
    elif capex_efficiency > 0.3:
        score = 45
        grade = "D"
        flags.append(f"Low capex efficiency ({capex_efficiency:.2f}x) — every $1 capex returns <$0.30 incremental revenue")
    else:
        score = 25
        grade = "F"
        flags.append(f"Capex destroying value: {capex_efficiency:.2f}x — likely value trap")

    return {
        "grade": grade,
        "score": score,
        "capex_efficiency_5yr": _r(capex_efficiency, 3),
        "capex_intensity_recent_pct": _r(intensity_recent * 100, 2) if intensity_recent else None,
        "capex_intensity_5yr_avg_pct": _r(intensity_5yr_avg * 100, 2) if intensity_5yr_avg else None,
        "intensity_trend": intensity_trend,
        "methodology": "Capex efficiency = (Revenue_t - Revenue_t-5) / Σ(capex_t-4..t). Higher = better unit revenue per $ of capital.",
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# 3. Dividend
# ---------------------------------------------------------------------------


def grade_dividend(financials: dict, capital_structure: dict | None) -> dict:
    flags: list[str] = []
    score = 50

    div_series = _extract(financials.get("dividends_paid", [])) or []
    eps_series = _extract(financials.get("eps", [])) or []
    fcf_series = _extract(financials.get("free_cash_flow", [])) or []
    net_income = _extract(financials.get("net_income", [])) or []

    if not div_series or all(d == 0 for d in div_series[:3]):
        return {
            "grade": "N/A",
            "score": None,
            "note": "No dividend program — not applicable",
            "payout_ratio_pct": 0,
            "flags": flags,
        }

    dividends_recent = abs(div_series[0])
    payout_ratio = None
    if net_income and net_income[0] > 0:
        payout_ratio = dividends_recent / net_income[0]

    fcf_payout = None
    if fcf_series and fcf_series[0] > 0:
        fcf_payout = dividends_recent / fcf_series[0]

    if payout_ratio is None:
        score = None
    elif payout_ratio > 1.0:
        score = 20
        flags.append(f"Payout > 100% of net income ({payout_ratio*100:.0f}%) — dividend funded by debt or asset sales")
    elif payout_ratio > 0.85:
        score = 40
        flags.append(f"Payout {payout_ratio*100:.0f}% leaves little reinvestment runway")
    elif payout_ratio > 0.6:
        score = 65
    elif payout_ratio > 0.3:
        score = 82
    else:
        score = 78

    if fcf_payout is not None and fcf_payout > 1.0:
        flags.append(f"FCF payout {fcf_payout*100:.0f}% — dividend not covered by free cash flow")
        if score:
            score = max(score - 20, 15)

    trend = "stable"
    if len(div_series) >= 5:
        d_recent = abs(div_series[0])
        d_5yr = abs(div_series[4])
        if d_5yr > 0:
            div_cagr = _cagr(d_5yr, d_recent, 5)
            if div_cagr is not None:
                if div_cagr > 0.05:
                    trend = f"growing {div_cagr*100:.1f}% CAGR (5yr)"
                elif div_cagr > 0:
                    trend = f"stable {div_cagr*100:.1f}% CAGR (5yr)"
                else:
                    trend = f"declining {div_cagr*100:.1f}% CAGR (5yr)"
                    flags.append("Dividend declining over 5yr — capital allocation concern")
                    if score:
                        score = max(score - 15, 20)

    return {
        "grade": _grade(score) if score else "N/A",
        "score": score,
        "payout_ratio_pct": _r(payout_ratio * 100, 2) if payout_ratio else None,
        "fcf_payout_ratio_pct": _r(fcf_payout * 100, 2) if fcf_payout else None,
        "trend": trend,
        "methodology": "Payout = dividends / net income. Bonus if FCF-covered. Penalty if >85% or declining.",
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# 4. M&A audit (proxy via goodwill growth)
# ---------------------------------------------------------------------------


def grade_m_and_a(financials: dict) -> dict:
    flags: list[str] = []
    score = 60  # neutral default — assume no material M&A unless data says otherwise

    goodwill_series = _extract(financials.get("goodwill", [])) or []
    revenue_series = _extract(financials.get("revenue", [])) or []
    intangibles_series = _extract(financials.get("intangible_assets", [])) or []

    if not goodwill_series or len(goodwill_series) < 3:
        return {
            "grade": "N/A",
            "score": None,
            "note": "Insufficient goodwill data",
            "flags": flags,
        }

    gw_recent = goodwill_series[0]
    gw_3yr_ago = goodwill_series[2] if len(goodwill_series) >= 3 else None
    gw_growth_pct = None
    if gw_3yr_ago and gw_3yr_ago > 0:
        gw_growth_pct = (gw_recent / gw_3yr_ago - 1) * 100

    rev_3yr_ago = revenue_series[2] if len(revenue_series) >= 3 else None
    rev_growth_pct = None
    if rev_3yr_ago and rev_3yr_ago > 0 and revenue_series:
        rev_growth_pct = (revenue_series[0] / rev_3yr_ago - 1) * 100

    organic_vs_acquired = "primarily organic"
    if gw_growth_pct is not None and rev_growth_pct is not None:
        if gw_growth_pct > rev_growth_pct + 30 and gw_growth_pct > 50:
            organic_vs_acquired = "heavy M&A — goodwill growing 30%+ faster than revenue"
            score = 40
            flags.append("Goodwill growth far outpacing revenue — M&A may be destroying value (overpayment risk)")
        elif gw_growth_pct > rev_growth_pct + 10:
            organic_vs_acquired = "M&A-supplemented growth"
            score = 55
        elif gw_growth_pct < -10:
            organic_vs_acquired = "goodwill writedowns — past M&A failures"
            score = 30
            flags.append("Goodwill impairment evident — prior acquisitions impaired (capital destruction)")

    return {
        "grade": _grade(score),
        "score": score,
        "goodwill_growth_3yr_pct": _r(gw_growth_pct, 2) if gw_growth_pct is not None else None,
        "revenue_growth_3yr_pct": _r(rev_growth_pct, 2) if rev_growth_pct is not None else None,
        "organic_vs_acquired": organic_vs_acquired,
        "methodology": "Compare 3yr goodwill growth vs 3yr revenue growth; flag if goodwill growth >> revenue growth (overpayment) or negative (impairment).",
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# 5. Buffett retention test ($1 retained → $X market value created)
# ---------------------------------------------------------------------------


def grade_retention(financials: dict, capital_structure: dict | None) -> dict:
    flags: list[str] = []

    net_income = _extract(financials.get("net_income", [])) or []
    div_series = _extract(financials.get("dividends_paid", [])) or []

    if len(net_income) < 5:
        return {
            "grade": "N/A",
            "score": None,
            "note": "Need ≥5yr net income history",
            "flags": flags,
        }

    cumulative_ni = sum(net_income[:5])
    cumulative_div = sum(abs(d) for d in div_series[:5]) if div_series else 0
    retained = cumulative_ni - cumulative_div

    market_cap_recent = None
    market_cap_5yr_ago = None
    if capital_structure:
        cap_obj = capital_structure.get("optimal_structure", {}) or {}
        market_cap_recent = cap_obj.get("market_cap")

    if retained <= 0 or not market_cap_recent:
        return {
            "grade": "N/A",
            "score": None,
            "note": "Cannot compute Buffett retention test (need market cap history + positive retained earnings)",
            "retained_5yr_usd": retained if retained > 0 else None,
            "flags": flags,
        }

    return {
        "grade": "N/A",
        "score": None,
        "note": "Full Buffett retention test requires 5yr-ago market cap (not yet wired). Reporting retained earnings only.",
        "retained_earnings_5yr_usd": _r(retained, 0),
        "methodology": "Buffett: $1 retained should create ≥$1 market cap. Need 5yr-ago market cap delta to score.",
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def composite(buyback: dict, capex: dict, dividend: dict, m_and_a: dict, retention: dict) -> dict:
    weights = {"buyback": 0.30, "capex": 0.30, "dividend": 0.15, "m_and_a": 0.20, "retention": 0.05}

    components = {"buyback": buyback, "capex": capex, "dividend": dividend, "m_and_a": m_and_a, "retention": retention}

    weighted_sum = 0.0
    weight_used = 0.0
    for name, data in components.items():
        score = data.get("score")
        if score is not None:
            weighted_sum += score * weights[name]
            weight_used += weights[name]

    if weight_used == 0:
        return {
            "grade_letter": "N/A",
            "score_0_100": None,
            "note": "Insufficient data to grade any dimension",
            "top_strengths": [],
            "top_red_flags": [],
        }

    composite_score = round(weighted_sum / weight_used, 1)
    composite_grade = _grade(int(composite_score))

    strengths = []
    red_flags = []
    for name, data in components.items():
        if data.get("grade") in ("A", "B"):
            strengths.append(f"{name}: {data['grade']}")
        red_flags.extend(data.get("flags", []))

    return {
        "grade_letter": composite_grade,
        "score_0_100": composite_score,
        "weights": weights,
        "coverage_pct": round(weight_used * 100, 1),
        "top_strengths": strengths,
        "top_red_flags": red_flags[:5],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Management Capital Allocation Audit — A-F scorecard (P0.1)"
    )
    parser.add_argument("raw_data", help="Path to raw-data.json (fetch_financials.py output)")
    parser.add_argument(
        "--capital-structure",
        help="Path to capital_structure.json (fetch_capital_structure.py output)",
    )
    parser.add_argument("--ticker", help="Ticker symbol (informational only)")
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    try:
        with open(args.raw_data) as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"Error: raw_data not found: {args.raw_data}\n")
        sys.exit(1)

    capital_structure = None
    if args.capital_structure:
        try:
            with open(args.capital_structure) as fh:
                capital_structure = json.load(fh)
        except FileNotFoundError:
            sys.stderr.write(f"Warning: capital_structure not found at {args.capital_structure}; buyback grading limited\n")

    financials = raw.get("financials", raw)

    buyback = grade_buyback(capital_structure)
    capex = grade_capex(financials)
    dividend = grade_dividend(financials, capital_structure)
    m_and_a = grade_m_and_a(financials)
    retention = grade_retention(financials, capital_structure)
    overall = composite(buyback, capex, dividend, m_and_a, retention)

    output = {
        "ticker": args.ticker or raw.get("ticker"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "framework": "Management Capital Allocation Audit (P0.1)",
        "framework_sources": [
            "@InvestmentTalk, @bluegrasscap (FinTwit) — capex efficiency + buyback IRR",
            "Mauboussin Capital Allocation Scorecard",
            "Buffett $1-retained retention test",
        ],
        "buyback": buyback,
        "capex": capex,
        "dividend": dividend,
        "m_and_a": m_and_a,
        "retention": retention,
        "composite": overall,
    }

    if args.output:
        with open(args.output, "w") as fh:
            json.dump(output, fh, indent=2)
        sys.stderr.write(f"Wrote {args.output}\n")
    else:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
