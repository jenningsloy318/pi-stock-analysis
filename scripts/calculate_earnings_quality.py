#!/usr/bin/env python3
"""Analyze earnings quality across 6 dimensions to produce a composite 0-100 score.

Usage:
    calculate_earnings_quality.py ./reports/AAPL/raw-data.json
    calculate_earnings_quality.py ./reports/MSFT/raw-data.json --output ./reports/MSFT/earnings_quality.json

Deterministic calculations only. No LLM involvement in math.
Every conclusion is traceable to a specific methodology.

Dimensions analyzed:
  1. Accruals Quality         (0-20 pts) — cash vs. accrual earnings gap
  2. Cash Conversion          (0-20 pts) — OCF/Net Income and FCF/Net Income ratios
  3. Revenue Quality          (0-20 pts) — receivables growth vs revenue growth, deferred revenue trend
  4. Expense Manipulation     (0-15 pts) — SG&A trend, depreciation/capex ratio
  5. Earnings Persistence     (0-15 pts) — ROE stability, revenue CAGR std deviation
  6. Tax Rate Signal          (0-10 pts) — effective tax rate vs statutory, tax rate stability

Missing data: returned as null with explanatory note — never fabricated.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Arithmetic utilities
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


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _cagr(start: float | None, end: float | None, years: int) -> float | None:
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


# ---------------------------------------------------------------------------
# Dimension 1: Accruals Quality (0-20 pts)
# ---------------------------------------------------------------------------

STATUTORY_TAX_RATE = 0.21  # US federal statutory rate


def _score_accruals(accruals_ratio: float | None) -> int:
    """Map accruals ratio to 0-20 score. Lower ratio = higher quality."""
    if accruals_ratio is None:
        return 10  # neutral when data is unavailable
    r = accruals_ratio
    if r < -0.05:
        return 20
    if r < 0.0:
        return 15
    if r < 0.05:
        return 10
    if r < 0.10:
        return 5
    return 0


def compute_accruals_quality(financials: dict) -> dict:
    """Compute balance-sheet accruals ratio.

    Total Accruals = (ΔCurrent Assets - ΔCash) - (ΔCurrent Liabilities - ΔSTD) - Depreciation
    Accruals Ratio = Total Accruals / Average Total Assets

    Because current_assets/current_liabilities may be absent from raw-data.json,
    we fall back to a simplified proxy:
      Simplified Accruals = Net Income - Operating Cash Flow
      Simplified Ratio    = Simplified Accruals / Average Total Assets
    """
    income = financials.get("income_statement", {})
    balance = financials.get("balance_sheet", {})
    cash_flow = financials.get("cash_flow", {})

    ni_vals = _extract(income.get("net_income", []))
    ocf_vals = _extract(cash_flow.get("operating_cash_flow", []))
    assets_vals = _extract(balance.get("total_assets", []))

    # Need at least 2 asset observations for average
    if len(assets_vals) < 2 or not ni_vals or not ocf_vals:
        return {
            "methodology": (
                "Accruals Ratio = (Net Income - OCF) / Average Total Assets. "
                "Positive ratio = accrual-based earnings, negative = cash-backed earnings."
            ),
            "accruals_ratio": None,
            "simplified_accruals": None,
            "avg_total_assets": None,
            "score": 10,
            "note": "Insufficient data for accruals calculation.",
        }

    n = min(len(ni_vals), len(ocf_vals), len(assets_vals) - 1)
    ratios = []
    for i in range(n):
        ni = ni_vals[i]
        ocf = ocf_vals[i]
        avg_assets = (assets_vals[i] + assets_vals[i + 1]) / 2
        if avg_assets and avg_assets != 0:
            simplified_accruals = ni - ocf
            ratios.append(_safe_div(simplified_accruals, avg_assets))

    valid_ratios = [r for r in ratios if r is not None]
    if not valid_ratios:
        return {
            "methodology": (
                "Accruals Ratio = (Net Income - OCF) / Average Total Assets."
            ),
            "accruals_ratio": None,
            "score": 10,
            "note": "Could not compute ratio; zero or missing asset data.",
        }

    avg_ratio = _mean(valid_ratios)
    score = _score_accruals(avg_ratio)
    most_recent = valid_ratios[0]

    return {
        "methodology": (
            "Accruals Ratio (simplified) = (Net Income - OCF) / Avg Total Assets. "
            "Full balance-sheet method requires current_assets/current_liabilities data. "
            "High positive ratio = earnings driven by accruals, not cash (lower quality)."
        ),
        "accruals_ratio_latest": _r(most_recent),
        "accruals_ratio_avg": _r(avg_ratio),
        "years_computed": len(valid_ratios),
        "score": score,
        "interpretation": (
            "Cash-backed earnings (high quality)"
            if avg_ratio < 0
            else "Moderate accruals"
            if avg_ratio < 0.05
            else "High accruals — earnings may be inflated"
        ),
    }


# ---------------------------------------------------------------------------
# Dimension 2: Cash Conversion (0-20 pts)
# ---------------------------------------------------------------------------


def _score_ocf_ni(ratio: float | None) -> int:
    if ratio is None:
        return 10
    if ratio > 1.2:
        return 20
    if ratio >= 1.0:
        return 15
    if ratio >= 0.8:
        return 10
    if ratio >= 0.5:
        return 5
    return 0


def compute_cash_conversion(financials: dict) -> dict:
    """OCF/Net Income and FCF/Net Income ratios (3yr average)."""
    income = financials.get("income_statement", {})
    cash_flow = financials.get("cash_flow", {})

    ni_vals = _extract(income.get("net_income", []))
    ocf_vals = _extract(cash_flow.get("operating_cash_flow", []))
    fcf_vals = _extract(cash_flow.get("free_cash_flow", []))

    n = min(len(ni_vals), len(ocf_vals), 3)
    if n == 0 or not ni_vals:
        return {
            "methodology": "Cash Conversion = OCF / Net Income (3yr avg).",
            "ocf_ni_ratio_avg": None,
            "fcf_ni_ratio_avg": None,
            "score": 10,
            "note": "Insufficient data.",
        }

    ocf_ni_ratios = [
        _safe_div(ocf_vals[i], ni_vals[i])
        for i in range(n)
        if ni_vals[i] and ni_vals[i] != 0
    ]
    ocf_ni_avg = _mean([r for r in ocf_ni_ratios if r is not None])

    fcf_ni_avg = None
    if fcf_vals and ni_vals:
        nf = min(len(fcf_vals), len(ni_vals), 3)
        fcf_ni_ratios = [
            _safe_div(fcf_vals[i], ni_vals[i])
            for i in range(nf)
            if ni_vals[i] and ni_vals[i] != 0
        ]
        fcf_ni_avg = _mean([r for r in fcf_ni_ratios if r is not None])

    score = _score_ocf_ni(ocf_ni_avg)

    return {
        "methodology": (
            "Cash Conversion = OCF / Net Income (3yr average). "
            "Ratio > 1.0 means operating cash flow exceeds reported earnings — high quality signal. "
            "FCF / Net Income supplementary; FCF = OCF - CapEx."
        ),
        "ocf_ni_ratio_avg": _r(ocf_ni_avg),
        "fcf_ni_ratio_avg": _r(fcf_ni_avg),
        "years_averaged": n,
        "score": score,
        "interpretation": (
            "Excellent: Cash generation exceeds reported earnings"
            if (ocf_ni_avg or 0) > 1.2
            else "Good: Cash closely tracks earnings"
            if (ocf_ni_avg or 0) >= 1.0
            else "Moderate: Some earnings not converting to cash"
            if (ocf_ni_avg or 0) >= 0.8
            else "Weak: Significant earnings-to-cash gap"
        ),
    }


# ---------------------------------------------------------------------------
# Dimension 3: Revenue Quality (0-20 pts)
# ---------------------------------------------------------------------------


def _score_revenue_quality(
    recv_growth_excess: float | None, deferred_trend: str
) -> int:
    """Score based on receivables growth vs revenue growth and deferred revenue trend."""
    base = 10  # neutral

    if recv_growth_excess is not None:
        # Receivables growing faster than revenue = revenue pulling forward
        if recv_growth_excess < -0.05:
            base += 8  # receivables growing slower → conservative recognition
        elif recv_growth_excess < 0.05:
            base += 4
        elif recv_growth_excess < 0.15:
            base -= 2
        else:
            base -= 5

    if deferred_trend == "growing":
        base += 2  # growing deferred = conservative recognition
    elif deferred_trend == "shrinking":
        base -= 2

    return max(0, min(20, base))


def compute_revenue_quality(financials: dict) -> dict:
    """Revenue quality via receivables growth vs revenue growth."""
    income = financials.get("income_statement", {})
    balance = financials.get("balance_sheet", {})

    rev_vals = _extract(income.get("revenue", []))

    # accounts_receivable may be absent in minimal raw-data.json
    ar_vals = _extract(balance.get("accounts_receivable", []))
    deferred_vals = _extract(balance.get("deferred_revenue", []))

    # Revenue growth (most recent year)
    rev_growth = None
    if len(rev_vals) >= 2 and rev_vals[1] and rev_vals[1] != 0:
        rev_growth = _safe_div(rev_vals[0] - rev_vals[1], abs(rev_vals[1]))

    # Receivables days change proxy (AR growth vs revenue growth)
    recv_growth_excess = None
    ar_growth = None
    if len(ar_vals) >= 2 and ar_vals[1] and ar_vals[1] != 0:
        ar_growth = _safe_div(ar_vals[0] - ar_vals[1], abs(ar_vals[1]))
        if rev_growth is not None and ar_growth is not None:
            recv_growth_excess = ar_growth - rev_growth

    # Deferred revenue trend
    deferred_trend = "unknown"
    if len(deferred_vals) >= 2:
        if deferred_vals[0] > deferred_vals[1] * 1.02:
            deferred_trend = "growing"
        elif deferred_vals[0] < deferred_vals[1] * 0.98:
            deferred_trend = "shrinking"
        else:
            deferred_trend = "stable"

    score = _score_revenue_quality(recv_growth_excess, deferred_trend)

    flags = []
    if recv_growth_excess is not None and recv_growth_excess > 0.15:
        flags.append(
            "Receivables growing significantly faster than revenue — potential revenue pull-forward"
        )
    if deferred_trend == "shrinking":
        flags.append("Deferred revenue declining — possible aggressive recognition")

    return {
        "methodology": (
            "Revenue Quality: compare AR growth rate vs Revenue growth rate. "
            "AR growing faster than revenue implies potential revenue pull-forward or collection risk. "
            "Growing deferred revenue = conservative recognition (quality signal)."
        ),
        "revenue_growth_latest": _r(rev_growth),
        "ar_growth_latest": _r(ar_growth) if ar_vals else None,
        "recv_growth_excess_vs_revenue": _r(recv_growth_excess),
        "deferred_revenue_trend": deferred_trend,
        "score": score,
        "flags": flags,
        "data_availability": {
            "accounts_receivable": len(ar_vals) > 0,
            "deferred_revenue": len(deferred_vals) > 0,
        },
    }


# ---------------------------------------------------------------------------
# Dimension 4: Expense Manipulation Signals (0-15 pts)
# ---------------------------------------------------------------------------


def _score_expense_signals(sga_trend: str, depr_capex_ratio: float | None) -> int:
    base = 8  # neutral

    if sga_trend == "declining_while_growing":
        base -= 4  # potentially under-investing in sales infrastructure
    elif sga_trend == "stable":
        base += 3
    elif sga_trend == "growing_proportionally":
        base += 2

    if depr_capex_ratio is not None:
        # Very low D/CapEx = aggressive depreciation (extends asset life to boost earnings)
        if depr_capex_ratio < 0.3:
            base -= 3
        elif depr_capex_ratio < 0.6:
            base += 0
        elif depr_capex_ratio <= 1.2:
            base += 4  # healthy reinvestment cycle
        else:
            base += 1  # high ratio may mean capex-light or aging assets

    return max(0, min(15, base))


def compute_expense_signals(financials: dict) -> dict:
    """SG&A trend and depreciation/capex ratio analysis."""
    income = financials.get("income_statement", {})
    cash_flow = financials.get("cash_flow", {})

    rev_vals = _extract(income.get("revenue", []))
    sga_vals = _extract(income.get("sga", []))
    depr_vals = _extract(income.get("depreciation_amortization", []))
    capex_vals = _extract(cash_flow.get("capex", []))
    # capex in raw-data may be negative (cash outflow); normalize to positive
    capex_vals = [abs(v) for v in capex_vals]

    # SG&A as % of revenue trend
    sga_trend = "unknown"
    sga_pct_series = []
    if sga_vals and rev_vals:
        n = min(len(sga_vals), len(rev_vals), 4)
        sga_pct_series = [
            _safe_div(abs(sga_vals[i]), rev_vals[i]) for i in range(n) if rev_vals[i]
        ]
        valid_pcts = [p for p in sga_pct_series if p is not None]
        if len(valid_pcts) >= 2:
            # Compare most recent vs prior year
            latest_pct = valid_pcts[0]
            prior_pct = valid_pcts[1]
            rev_growing = len(rev_vals) >= 2 and rev_vals[0] > rev_vals[1]
            if rev_growing and latest_pct < prior_pct * 0.95:
                sga_trend = "declining_while_growing"
            elif latest_pct < prior_pct * 1.05:
                sga_trend = "stable"
            else:
                sga_trend = "growing_proportionally"

    # Depreciation / CapEx ratio (proxy for depreciation aggressiveness)
    depr_capex_ratio = None
    depr_capex_series = []
    if depr_vals and capex_vals:
        n = min(len(depr_vals), len(capex_vals), 3)
        depr_capex_series = [
            _safe_div(depr_vals[i], capex_vals[i])
            for i in range(n)
            if capex_vals[i] and capex_vals[i] != 0
        ]
        valid = [r for r in depr_capex_series if r is not None]
        depr_capex_ratio = _mean(valid)

    score = _score_expense_signals(sga_trend, depr_capex_ratio)

    flags = []
    if sga_trend == "declining_while_growing":
        flags.append(
            "SG&A shrinking as % of revenue while revenue grows — potential under-investment signal"
        )
    if depr_capex_ratio is not None and depr_capex_ratio < 0.3:
        flags.append(
            "Low depreciation/capex ratio — potentially aggressive (extended) depreciation policy"
        )

    return {
        "methodology": (
            "Expense Signals: (1) SG&A % of revenue trend — declining during growth may indicate "
            "under-investment or cost deferral. (2) Depreciation/CapEx ratio — low ratio suggests "
            "aggressive depreciation policy boosting near-term earnings artificially."
        ),
        "sga_pct_revenue_trend": sga_trend,
        "sga_pct_latest": _r(sga_pct_series[0] if sga_pct_series else None),
        "depreciation_capex_ratio_avg": _r(depr_capex_ratio),
        "score": score,
        "flags": flags,
        "data_availability": {
            "sga": len(sga_vals) > 0,
            "depreciation_amortization": len(depr_vals) > 0,
        },
    }


# ---------------------------------------------------------------------------
# Dimension 5: Earnings Persistence (0-15 pts)
# ---------------------------------------------------------------------------


def _score_persistence(roe_cv: float | None, rev_cagr_stdev: float | None) -> int:
    base = 8

    if roe_cv is not None:
        # Coefficient of variation of ROE — lower = more persistent
        if roe_cv < 0.15:
            base += 5
        elif roe_cv < 0.30:
            base += 2
        elif roe_cv < 0.50:
            base += 0
        else:
            base -= 3

    if rev_cagr_stdev is not None:
        # Annual revenue growth std dev — lower = more predictable
        if rev_cagr_stdev < 0.05:
            base += 2
        elif rev_cagr_stdev < 0.10:
            base += 1
        elif rev_cagr_stdev > 0.20:
            base -= 1

    return max(0, min(15, base))


def compute_earnings_persistence(financials: dict) -> dict:
    """ROE stability and revenue growth consistency over 5 years."""
    income = financials.get("income_statement", {})
    balance = financials.get("balance_sheet", {})

    ni_vals = _extract(income.get("net_income", []))
    equity_vals = _extract(balance.get("stockholders_equity", []))
    rev_vals = _extract(income.get("revenue", []))

    # ROE series
    n_roe = min(len(ni_vals), len(equity_vals), 5)
    roe_series = [
        _safe_div(ni_vals[i], equity_vals[i])
        for i in range(n_roe)
        if equity_vals[i] and equity_vals[i] != 0
    ]
    roe_series = [r for r in roe_series if r is not None]

    roe_mean = _mean(roe_series)
    roe_stdev = _stdev(roe_series)
    roe_cv = _safe_div(roe_stdev, abs(roe_mean)) if roe_mean else None

    # Revenue year-over-year growth rates
    rev_growth_rates = []
    for i in range(min(len(rev_vals) - 1, 4)):
        if rev_vals[i + 1] and rev_vals[i + 1] != 0:
            g = _safe_div(rev_vals[i] - rev_vals[i + 1], abs(rev_vals[i + 1]))
            if g is not None:
                rev_growth_rates.append(g)

    rev_cagr_stdev = _stdev(rev_growth_rates)

    score = _score_persistence(roe_cv, rev_cagr_stdev)

    return {
        "methodology": (
            "Earnings Persistence: (1) ROE coefficient of variation over 5 years — "
            "lower CV = more consistent profitability. (2) Revenue annual growth std deviation — "
            "lower = more predictable revenue trajectory."
        ),
        "roe_series": [_r(r) for r in roe_series],
        "roe_mean": _r(roe_mean),
        "roe_stdev": _r(roe_stdev),
        "roe_coefficient_of_variation": _r(roe_cv),
        "revenue_growth_rates": [_r(g) for g in rev_growth_rates],
        "revenue_growth_stdev": _r(rev_cagr_stdev),
        "score": score,
        "interpretation": (
            "Highly persistent earnings"
            if (roe_cv or 1) < 0.15
            else "Moderately persistent"
            if (roe_cv or 1) < 0.30
            else "Volatile earnings history"
        ),
    }


# ---------------------------------------------------------------------------
# Dimension 6: Tax Rate Signal (0-10 pts)
# ---------------------------------------------------------------------------


def _score_tax_signal(avg_effective_rate: float | None, tax_stdev: float | None) -> int:
    base = 5

    if avg_effective_rate is not None:
        gap = avg_effective_rate - STATUTORY_TAX_RATE
        if -0.05 <= gap <= 0.05:
            base += 3  # close to statutory — sustainable
        elif gap < -0.10:
            base -= 2  # very low ETR — likely unsustainable tax structure
        elif gap < -0.05:
            base += 1
        else:
            base += 0  # higher than statutory — conservative

    if tax_stdev is not None:
        if tax_stdev < 0.02:
            base += 2  # very stable
        elif tax_stdev < 0.05:
            base += 1
        elif tax_stdev > 0.10:
            base -= 2  # highly volatile — earnings management signal

    return max(0, min(10, base))


def compute_tax_signal(financials: dict) -> dict:
    """Effective tax rate vs statutory and tax rate stability."""
    income = financials.get("income_statement", {})

    tax_vals = _extract(income.get("income_tax_expense", []))
    pretax_vals = _extract(income.get("pretax_income", []))

    # Fallback: derive pretax from net income and tax expense
    ni_vals = _extract(income.get("net_income", []))
    if not pretax_vals and tax_vals and ni_vals:
        pretax_vals = [
            ni_vals[i] + tax_vals[i] for i in range(min(len(ni_vals), len(tax_vals)))
        ]

    etr_series = []
    n = min(len(tax_vals), len(pretax_vals), 5)
    for i in range(n):
        if pretax_vals[i] and pretax_vals[i] > 0:
            etr = _safe_div(tax_vals[i], pretax_vals[i])
            if etr is not None and 0 < etr < 1:
                etr_series.append(etr)

    if not etr_series:
        return {
            "methodology": (
                "Tax Rate Signal: Effective Tax Rate = Tax Expense / Pretax Income. "
                "Compares ETR to US statutory rate (21%). Low/volatile ETR = potential earnings management."
            ),
            "effective_tax_rates": [],
            "avg_effective_tax_rate": None,
            "statutory_tax_rate": STATUTORY_TAX_RATE,
            "etr_vs_statutory_gap": None,
            "etr_stdev": None,
            "score": 5,
            "note": "Tax expense or pretax income data not available in raw-data.json.",
        }

    avg_etr = _mean(etr_series)
    etr_stdev = _stdev(etr_series)
    score = _score_tax_signal(avg_etr, etr_stdev)

    flags = []
    if avg_etr is not None and avg_etr < STATUTORY_TAX_RATE - 0.10:
        flags.append(
            f"Effective tax rate ({avg_etr:.1%}) significantly below statutory ({STATUTORY_TAX_RATE:.0%}) — "
            "may rely on unsustainable tax structures (offshore shelters, deferred tax assets)"
        )
    if etr_stdev is not None and etr_stdev > 0.08:
        flags.append(
            "Highly volatile effective tax rate — potential indicator of earnings smoothing via tax line"
        )

    return {
        "methodology": (
            "Tax Rate Signal: Effective Tax Rate = Tax Expense / Pretax Income. "
            f"Benchmarked against US statutory rate ({STATUTORY_TAX_RATE:.0%}). "
            "Very low ETR (<11%) or high volatility signals aggressive tax accounting."
        ),
        "effective_tax_rates": [_r(e) for e in etr_series],
        "avg_effective_tax_rate": _r(avg_etr),
        "statutory_tax_rate": STATUTORY_TAX_RATE,
        "etr_vs_statutory_gap": _r((avg_etr - STATUTORY_TAX_RATE) if avg_etr else None),
        "etr_stdev": _r(etr_stdev),
        "score": score,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Rating and red flag aggregation
# ---------------------------------------------------------------------------


def _rating(score: int) -> str:
    if score > 75:
        return "High Quality"
    if score >= 50:
        return "Moderate Quality"
    if score >= 25:
        return "Low Quality"
    return "Very Low Quality"


def _collect_red_flags(*dimension_results: dict) -> list[str]:
    flags: list[str] = []
    for dim in dimension_results:
        flags.extend(dim.get("flags", []))
    return flags


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze earnings quality across 6 dimensions (0-100 composite score)"
    )
    parser.add_argument("input", help="Path to raw-data.json from fetch_financials.py")
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    try:
        with open(args.input) as fh:
            raw_data = json.load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"Error: File not found: {args.input}\n")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"Error: Invalid JSON in {args.input}: {exc}\n")
        sys.exit(1)

    if "financials" not in raw_data and raw_data:
        first_key = list(raw_data.keys())[0]
        if isinstance(raw_data[first_key], dict) and "financials" in raw_data[first_key]:
            raw_data = raw_data[first_key]

    ticker: str = raw_data.get("ticker", "UNKNOWN")
    financials: dict = raw_data.get("financials", {})

    if not financials:
        sys.stderr.write(f"Warning: No 'financials' key found in {args.input}\n")

    accruals = compute_accruals_quality(financials)
    cash_conv = compute_cash_conversion(financials)
    rev_quality = compute_revenue_quality(financials)
    expense_sig = compute_expense_signals(financials)
    persistence = compute_earnings_persistence(financials)
    tax_sig = compute_tax_signal(financials)

    total_score = (
        accruals["score"]
        + cash_conv["score"]
        + rev_quality["score"]
        + expense_sig["score"]
        + persistence["score"]
        + tax_sig["score"]
    )

    red_flags = _collect_red_flags(
        rev_quality, expense_sig, tax_sig, accruals, cash_conv
    )

    result = {
        "ticker": ticker,
        "analysis_date": datetime.now(timezone.utc).date().isoformat(),
        "earnings_quality_score": total_score,
        "rating": _rating(total_score),
        "score_breakdown": {
            "accruals_quality": f"{accruals['score']}/20",
            "cash_conversion": f"{cash_conv['score']}/20",
            "revenue_quality": f"{rev_quality['score']}/20",
            "expense_signals": f"{expense_sig['score']}/15",
            "earnings_persistence": f"{persistence['score']}/15",
            "tax_signal": f"{tax_sig['score']}/10",
        },
        "dimensions": {
            "accruals_quality": accruals,
            "cash_conversion": cash_conv,
            "revenue_quality": rev_quality,
            "expense_signals": expense_sig,
            "earnings_persistence": persistence,
            "tax_signal": tax_sig,
        },
        "red_flags": red_flags,
        "methodology": (
            "Earnings Quality composite score (0-100) across 6 dimensions: "
            "Accruals Quality (0-20): cash vs. accrual earnings gap via OCF-NI divergence. "
            "Cash Conversion (0-20): OCF/NI and FCF/NI 3yr averages. "
            "Revenue Quality (0-20): AR growth vs revenue growth and deferred revenue trend. "
            "Expense Signals (0-15): SG&A % of revenue trend and Depreciation/CapEx ratio. "
            "Earnings Persistence (0-15): ROE coefficient of variation and revenue growth std dev. "
            "Tax Rate Signal (0-10): Effective tax rate vs US statutory (21%) and ETR stability. "
            "Ratings: >75 High Quality, 50-75 Moderate, 25-50 Low, <25 Very Low."
        ),
        "data_source": raw_data.get("source", "unknown"),
        "data_retrieved_at": raw_data.get("retrieved_at", "unknown"),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(output)
        sys.stderr.write(f"Earnings quality analysis written to {args.output}\n")
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
