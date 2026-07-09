#!/usr/bin/env python3
"""Short interest dynamics and squeeze potential analysis.

Usage:
    fetch_short_interest.py --ticker AAPL
    fetch_short_interest.py --ticker AAPL --output ./reports/AAPL/short_interest.json
    fetch_short_interest.py --ticker GME --output ./reports/GME/short_interest.json

Deterministic calculations only. No LLM involvement in math.

Analysis dimensions:
  1. Short Interest Metrics      — shares short, days to cover, % float, % outstanding
  2. Squeeze Score (1-10)        — weighted composite: short % float (40%), days to cover (30%),
                                   momentum divergence (20%), catalyst proximity (10%)
  3. Positioning Decomposition   — institutional, insider, effective free float, crowding score
  4. Catalyst Proximity Flags    — earnings within 30d, ex-dividend within 30d

Primary source: yfinance (Yahoo Finance).
Missing data:   returned as null with warning — never fabricated.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: yfinance required. Run: pip install yfinance\n")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: numpy required. Run: pip install numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Arithmetic utilities
# ---------------------------------------------------------------------------


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Return numerator / denominator, or None if either is None / zero."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _round(value: float | None, places: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, places)


def _pct(value: float | None, places: int = 2) -> float | None:
    """Express a ratio as a percentage (multiply by 100)."""
    return _round(value * 100, places) if value is not None else None


def _clamp(score: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, round(score, 1)))


# ---------------------------------------------------------------------------
# Raw data fetch
# ---------------------------------------------------------------------------


def _fetch_info(ticker: str, warnings: list[str]) -> dict:
    """Fetch yfinance info dict with graceful degradation."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        return info
    except Exception as exc:
        warnings.append(f"yfinance info fetch failed: {exc}")
        return {}


def _fetch_history(ticker: str, period: str, warnings: list[str]):
    """Fetch price history DataFrame; return None on failure."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist is None or hist.empty:
            warnings.append(f"No price history returned for period={period}")
            return None
        return hist
    except Exception as exc:
        warnings.append(f"Price history fetch failed (period={period}): {exc}")
        return None


def _fetch_calendar(ticker: str, warnings: list[str]) -> dict:
    """Fetch yfinance earnings/dividend calendar; return empty dict on failure."""
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar
        if cal is None:
            return {}
        # yfinance returns a dict or a DataFrame depending on version
        if hasattr(cal, "to_dict"):
            return cal.to_dict()
        return cal if isinstance(cal, dict) else {}
    except Exception as exc:
        warnings.append(f"Calendar fetch failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Short interest section
# ---------------------------------------------------------------------------


def build_short_interest(info: dict, warnings: list[str]) -> dict:
    """Extract and derive short interest metrics from yfinance info."""
    shares_short = info.get("sharesShort")
    shares_short_prior = info.get("sharesShortPriorMonth")
    short_ratio = info.get("shortRatio")  # days to cover
    float_shares = info.get("floatShares")
    shares_outstanding = info.get("sharesOutstanding")
    short_pct_float_raw = info.get("shortPercentOfFloat")

    # yfinance returns shortPercentOfFloat as a decimal (e.g. 0.0234 = 2.34%)
    short_pct_float: float | None = None
    if short_pct_float_raw is not None:
        short_pct_float = (
            short_pct_float_raw * 100
            if short_pct_float_raw < 1.0
            else short_pct_float_raw
        )

    # Derive short % of shares outstanding
    short_pct_outstanding: float | None = None
    if shares_short is not None and shares_outstanding:
        short_pct_outstanding = _pct(_safe_div(shares_short, shares_outstanding))

    # Derive short % float when yfinance field absent
    if short_pct_float is None and shares_short is not None and float_shares:
        short_pct_float = _pct(_safe_div(shares_short, float_shares))

    # Change % vs prior period
    short_interest_change_pct: float | None = None
    if shares_short is not None and shares_short_prior and shares_short_prior != 0:
        short_interest_change_pct = _pct(
            _safe_div(shares_short - shares_short_prior, shares_short_prior)
        )

    # Warn on any missing Tier-1 field
    missing = []
    if shares_short is None:
        missing.append("sharesShort")
    if short_ratio is None:
        missing.append("shortRatio (days to cover)")
    if float_shares is None:
        missing.append("floatShares")
    if missing:
        warnings.append(
            f"Short interest fields unavailable from yfinance: {', '.join(missing)}"
        )

    return {
        "shares_short": shares_short,
        "short_ratio_days_to_cover": _round(short_ratio, 2),
        "short_pct_float": _round(short_pct_float, 2),
        "short_pct_outstanding": _round(short_pct_outstanding, 2),
        "prior_period_shares_short": shares_short_prior,
        "short_interest_change_pct": _round(short_interest_change_pct, 2),
    }


# ---------------------------------------------------------------------------
# Momentum divergence
# ---------------------------------------------------------------------------


def _compute_momentum_vs_short(
    ticker: str,
    short_interest_change_pct: float | None,
    warnings: list[str],
) -> str:
    """Determine convergence/divergence between price momentum and short trend.

    Divergent: price is rising while short interest is also increasing
               (shorts building into strength — squeeze setup).
    Convergent: both moving in same direction (momentum confirms shorts).
    """
    hist = _fetch_history(ticker, "3mo", warnings)
    if hist is None or len(hist) < 10:
        warnings.append(
            "Insufficient price history to compute momentum vs short divergence"
        )
        return "unknown"

    prices = hist["Close"].dropna().values
    if len(prices) < 2:
        return "unknown"

    # Simple 3-month price return
    price_return_pct = (prices[-1] - prices[0]) / prices[0] * 100

    if short_interest_change_pct is None:
        return "unknown"

    price_rising = price_return_pct > 2.0  # >2% threshold to avoid noise
    price_falling = price_return_pct < -2.0
    short_increasing = short_interest_change_pct > 3.0  # >3% threshold
    short_decreasing = short_interest_change_pct < -3.0

    # Divergent: price up + short increasing (shorts fighting uptrend)
    # OR price down + short decreasing (covering into downtrend)
    if (price_rising and short_increasing) or (price_falling and short_decreasing):
        return "divergent"
    return "convergent"


# ---------------------------------------------------------------------------
# Catalyst proximity
# ---------------------------------------------------------------------------


def _days_until(target_date_str: str | None) -> int | None:
    """Return calendar days until target_date_str (YYYY-MM-DD), or None."""
    if not target_date_str:
        return None
    try:
        target = datetime.strptime(str(target_date_str)[:10], "%Y-%m-%d").date()
        delta = (target - date.today()).days
        return delta if delta >= 0 else None
    except (ValueError, TypeError):
        return None


def build_catalyst_flags(info: dict, calendar: dict, warnings: list[str]) -> list[str]:
    """Identify near-term catalyst events within 30 days."""
    flags: list[str] = []

    # Earnings date — check multiple yfinance paths
    earnings_date_str: str | None = None

    # Path 1: calendar dict (newer yfinance)
    if isinstance(calendar, dict):
        for key in ("Earnings Date", "earningsDate"):
            val = calendar.get(key)
            if val is not None:
                if isinstance(val, (list, tuple)) and val:
                    earnings_date_str = str(val[0])[:10]
                else:
                    earnings_date_str = str(val)[:10]
                break

    # Path 2: info dict
    if earnings_date_str is None:
        for key in ("earningsDate", "nextEarningsDate"):
            val = info.get(key)
            if val is not None:
                earnings_date_str = str(val)[:10]
                break

    days_earnings = _days_until(earnings_date_str)
    if days_earnings is not None and days_earnings <= 30:
        flags.append(f"earnings_in_{days_earnings}d")

    # Ex-dividend date
    ex_div_str: str | None = info.get("exDividendDate")
    if ex_div_str is None and isinstance(calendar, dict):
        ex_div_str = calendar.get("Ex-Dividend Date") or calendar.get("exDividendDate")

    if ex_div_str is not None:
        # yfinance sometimes returns a Unix timestamp int
        if isinstance(ex_div_str, (int, float)):
            try:
                ex_div_str = datetime.fromtimestamp(
                    ex_div_str, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except (OSError, ValueError, OverflowError):
                ex_div_str = None

    days_ex_div = _days_until(ex_div_str)
    if days_ex_div is not None and days_ex_div <= 30:
        flags.append(f"ex_div_in_{days_ex_div}d")

    return flags


# ---------------------------------------------------------------------------
# Squeeze score
# ---------------------------------------------------------------------------

# Thresholds for short % of float scoring sub-component (out of 10)
# Based on common squeeze literature:
#   <5%  → low short interest (score 1-2)
#   5-15% → moderate (score 3-5)
#   15-25% → elevated (score 6-7)
#   25-40% → high (score 8-9)
#   >40%  → extreme (score 10)
_SHORT_PCT_FLOAT_THRESHOLDS = [
    (5.0, 1.5),
    (10.0, 3.0),
    (15.0, 5.0),
    (20.0, 6.5),
    (25.0, 7.5),
    (35.0, 8.5),
    (40.0, 9.5),
]

# Thresholds for days-to-cover scoring sub-component
#   <1d  → very liquid (score 1)
#   1-2d → score 2-3
#   2-5d → score 4-6
#   5-10d → score 7-8
#   >10d → extreme (score 9-10)
_DAYS_TO_COVER_THRESHOLDS = [
    (1.0, 1.5),
    (2.0, 3.0),
    (3.5, 5.0),
    (5.0, 6.5),
    (7.0, 7.5),
    (10.0, 8.5),
    (15.0, 9.5),
]


def _interpolate_score(value: float, thresholds: list[tuple[float, float]]) -> float:
    """Linear interpolation across a monotone threshold table -> score 1-10."""
    if value <= thresholds[0][0]:
        return thresholds[0][1]
    for i in range(1, len(thresholds)):
        lo_val, lo_score = thresholds[i - 1]
        hi_val, hi_score = thresholds[i]
        if value <= hi_val:
            frac = (value - lo_val) / (hi_val - lo_val)
            return lo_score + frac * (hi_score - lo_score)
    # Above highest threshold
    return min(10.0, thresholds[-1][1] + 0.5)


def compute_squeeze_score(
    short_pct_float: float | None,
    days_to_cover: float | None,
    momentum_vs_short: str,
    catalyst_flags: list[str],
    warnings: list[str],
) -> dict:
    """Compute weighted short squeeze score (1-10).

    Weights:
      short_pct_float   40%
      days_to_cover     30%
      momentum_diverge  20%
      catalyst_proxim   10%
    """
    component_scores: dict[str, float | None] = {
        "short_pct_float_score": None,
        "days_to_cover_score": None,
        "momentum_score": None,
        "catalyst_score": None,
    }

    # Sub-component: short % float (40%)
    if short_pct_float is not None:
        component_scores["short_pct_float_score"] = _clamp(
            _interpolate_score(short_pct_float, _SHORT_PCT_FLOAT_THRESHOLDS)
        )

    # Sub-component: days to cover (30%)
    if days_to_cover is not None:
        component_scores["days_to_cover_score"] = _clamp(
            _interpolate_score(days_to_cover, _DAYS_TO_COVER_THRESHOLDS)
        )

    # Sub-component: momentum divergence (20%)
    # divergent = shorts fighting price momentum (higher squeeze risk)
    if momentum_vs_short == "divergent":
        component_scores["momentum_score"] = 7.5
    elif momentum_vs_short == "convergent":
        component_scores["momentum_score"] = 2.5
    else:
        component_scores["momentum_score"] = 5.0  # neutral / unknown

    # Sub-component: catalyst proximity (10%)
    # More upcoming catalysts within 30d → higher score
    component_scores["catalyst_score"] = min(10.0, 1.0 + len(catalyst_flags) * 4.5)

    # Weighted average — skip None components and rescale weights
    weights = {
        "short_pct_float_score": 0.40,
        "days_to_cover_score": 0.30,
        "momentum_score": 0.20,
        "catalyst_score": 0.10,
    }

    available_weight = 0.0
    weighted_sum = 0.0
    missing_components: list[str] = []

    for key, w in weights.items():
        val = component_scores[key]
        if val is not None:
            weighted_sum += val * w
            available_weight += w
        else:
            missing_components.append(key)

    if available_weight == 0:
        warnings.append(
            "No squeeze sub-components could be scored; squeeze_score set to null"
        )
        final_score = None
    else:
        # Rescale so weights still sum to 1
        final_score = _clamp(weighted_sum / available_weight)

    if missing_components:
        warnings.append(
            f"Squeeze sub-components defaulted to neutral (data missing): "
            f"{', '.join(missing_components)}"
        )

    # Risk level classification
    risk_level: str | None = None
    if final_score is not None:
        if final_score < 3.5:
            risk_level = "Low"
        elif final_score < 5.5:
            risk_level = "Moderate"
        elif final_score < 7.5:
            risk_level = "High"
        else:
            risk_level = "Extreme"

    return {
        "squeeze_score": final_score,
        "squeeze_risk_level": risk_level,
        "component_scores": component_scores,
    }


# ---------------------------------------------------------------------------
# Positioning section
# ---------------------------------------------------------------------------


def build_positioning(
    info: dict,
    float_shares: float | None,
    shares_outstanding: float | None,
    short_pct_float: float | None,
    warnings: list[str],
) -> dict:
    """Derive float decomposition and crowding score."""
    institutional_pct: float | None = None
    insider_pct: float | None = None
    effective_free_float_pct: float | None = None

    inst_raw = info.get("heldPercentInstitutions")
    if inst_raw is not None:
        institutional_pct = _pct(inst_raw if inst_raw > 1 else inst_raw)
        # yfinance returns as decimal
        if inst_raw <= 1.0:
            institutional_pct = _round(inst_raw * 100, 2)
        else:
            institutional_pct = _round(inst_raw, 2)

    insider_raw = info.get("heldPercentInsiders")
    if insider_raw is not None:
        insider_pct = (
            _round(insider_raw * 100, 2)
            if insider_raw <= 1.0
            else _round(insider_raw, 2)
        )

    # Effective free float = 100% - institutional - insider (approximate)
    if institutional_pct is not None and insider_pct is not None:
        effective_free_float_pct = _round(
            max(0.0, 100.0 - institutional_pct - insider_pct), 2
        )
    elif institutional_pct is not None:
        effective_free_float_pct = _round(max(0.0, 100.0 - institutional_pct), 2)

    # Utilization proxy = short interest / effective free float (as share count)
    # Approximated as: short_pct_float / (effective_free_float_pct / 100 * 100)
    # i.e., how much of the truly tradeable float is already short
    utilization_proxy: float | None = None
    if (
        short_pct_float is not None
        and effective_free_float_pct
        and effective_free_float_pct > 0
    ):
        utilization_proxy = _round(
            min(100.0, short_pct_float / effective_free_float_pct * 100), 2
        )

    # Crowding score (1-10): combines utilization and institutional ownership
    # High institutional + high short = crowded trade (higher risk of synchronized exit)
    crowding_score: float | None = None
    if institutional_pct is not None and utilization_proxy is not None:
        inst_score = _clamp(
            _interpolate_score(
                institutional_pct,
                [
                    (40.0, 2.0),
                    (55.0, 4.0),
                    (65.0, 6.0),
                    (75.0, 8.0),
                    (85.0, 9.5),
                ],
            )
        )
        util_score = _clamp(
            _interpolate_score(
                utilization_proxy,
                [
                    (10.0, 2.0),
                    (25.0, 4.0),
                    (40.0, 6.0),
                    (60.0, 8.0),
                    (80.0, 9.5),
                ],
            )
        )
        crowding_score = _round(inst_score * 0.45 + util_score * 0.55, 1)

    if institutional_pct is None:
        warnings.append("heldPercentInstitutions unavailable from yfinance")
    if insider_pct is None:
        warnings.append("heldPercentInsiders unavailable from yfinance")

    return {
        "institutional_pct": institutional_pct,
        "insider_pct": insider_pct,
        "effective_free_float_pct": effective_free_float_pct,
        "utilization_proxy": utilization_proxy,
        "crowding_score": crowding_score,
    }


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------


def analyze_short_interest(ticker: str) -> dict:
    """Fetch data and compute all short interest metrics for a ticker."""
    warnings: list[str] = []
    ticker = ticker.strip().upper()

    info = _fetch_info(ticker, warnings)
    if not info:
        warnings.append("yfinance returned empty info dict — all metrics null")

    calendar = _fetch_calendar(ticker, warnings)

    # --- Short Interest section ---
    short_data = build_short_interest(info, warnings)

    shares_short = short_data["shares_short"]
    short_pct_float = short_data["short_pct_float"]
    days_to_cover = short_data["short_ratio_days_to_cover"]
    short_interest_change_pct = short_data["short_interest_change_pct"]

    # --- Catalyst proximity ---
    catalyst_flags = build_catalyst_flags(info, calendar, warnings)

    # --- Momentum divergence ---
    momentum_vs_short = _compute_momentum_vs_short(
        ticker, short_interest_change_pct, warnings
    )

    # --- Squeeze score ---
    squeeze_result = compute_squeeze_score(
        short_pct_float=short_pct_float,
        days_to_cover=days_to_cover,
        momentum_vs_short=momentum_vs_short,
        catalyst_flags=catalyst_flags,
        warnings=warnings,
    )

    # --- Positioning decomposition ---
    float_shares = info.get("floatShares")
    shares_outstanding = info.get("sharesOutstanding")
    positioning = build_positioning(
        info=info,
        float_shares=float_shares,
        shares_outstanding=shares_outstanding,
        short_pct_float=short_pct_float,
        warnings=warnings,
    )

    return {
        "ticker": ticker,
        "retrieved": date.today().isoformat(),
        "short_interest": short_data,
        "squeeze_analysis": {
            "squeeze_score": squeeze_result["squeeze_score"],
            "squeeze_risk_level": squeeze_result["squeeze_risk_level"],
            "days_to_cover": days_to_cover,
            "utilization_proxy": positioning["utilization_proxy"],
            "momentum_vs_short": momentum_vs_short,
            "catalyst_proximity": catalyst_flags,
            "component_scores": squeeze_result["component_scores"],
        },
        "positioning": {
            "institutional_pct": positioning["institutional_pct"],
            "insider_pct": positioning["insider_pct"],
            "effective_free_float_pct": positioning["effective_free_float_pct"],
            "crowding_score": positioning["crowding_score"],
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Short interest dynamics and squeeze potential analysis"
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help="Ticker symbol (e.g. AAPL). Positional, matches other fetch scripts.",
    )
    parser.add_argument(
        "--ticker",
        dest="ticker_flag",
        help="Alternative named form of the ticker argument (kept for back-compat).",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker or args.ticker_flag
    if not ticker:
        parser.error("ticker required (positional or --ticker)")

    result = analyze_short_interest(ticker)

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
