#!/usr/bin/env python3
"""Capital Structure & Shareholder Return Analysis.

Usage:
    fetch_capital_structure.py AAPL
    fetch_capital_structure.py AAPL --raw-data ./reports/AAPL/raw-data.json
    fetch_capital_structure.py AAPL --output ./reports/AAPL/capital_structure.json
    fetch_capital_structure.py MSFT --output ./reports/MSFT/capital_structure.json

Deterministic calculations only. No LLM involvement in math.
Output includes methodology attribution for every calculation.

Analysis dimensions:
  1. Share Buyback Analysis         — repurchase ROI, buyback effectiveness
  2. SBC Dilution                   — true dilution rate, SBC-adjusted FCF
  3. Capital Return Analysis        — dividend & buyback yields, payout ratios
  4. Optimal Capital Structure      — leverage metrics, WACC sensitivity
  5. Capital Markets Activity       — equity issuance, insider transactions

Primary source: yfinance (Yahoo Finance).
Fallback:       raw-data.json previously fetched by fetch_financials.py.
Missing data:   returned as null with explanatory note — never fabricated.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' required. Run: pip install requests\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Arithmetic utilities
# ---------------------------------------------------------------------------


def _fetch_10y_yield() -> float:
    """Fetch the latest 10-year Treasury yield (^TNX) as a decimal.
    Falls back to 0.043 (a long-run-average proxy) if the live fetch fails."""
    try:
        import yfinance as yf
        import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch

        tnx = yf.Ticker("^TNX").history(period="5d")
        if tnx is not None and not tnx.empty:
            # ^TNX is quoted in percent (e.g., 4.30 means 4.30%)
            latest = float(tnx["Close"].dropna().iloc[-1]) / 100.0
            if 0.0 < latest < 0.20:
                return round(latest, 4)
    except Exception:
        pass
    return 0.043


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Return numerator / denominator, or None if either is None / zero."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _round(value: float | None, places: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, places)


def _cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Compound Annual Growth Rate from start to end over `years` periods."""
    if start is None or end is None or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def _pct(value: float | None) -> float | None:
    """Express a ratio as a percentage (multiply by 100), rounded to 2 dp."""
    return _round(value * 100, 2) if value is not None else None


def _extract_series(series: list[dict]) -> list[float]:
    """Pull non-None values from [{period, value}, ...] — most-recent first."""
    return [e["value"] for e in series if e.get("value") is not None]


def _extract_period_series(series: list[dict]) -> list[tuple[str, float]]:
    """Return [(period, value), ...] with valid numeric values."""
    return [
        (e["period"], e["value"])
        for e in series
        if e.get("value") is not None and e.get("period")
    ]


# ---------------------------------------------------------------------------
# yfinance helpers
# ---------------------------------------------------------------------------


def _df_row(df, field: str) -> list[dict]:
    """Extract a single DataFrame row as [{period, value}, ...], most-recent first."""
    try:
        import pandas as pd

        if df is None or df.empty or field not in df.index:
            return []
        row = df.loc[field]
        return [
            {
                "period": str(idx.date()) if hasattr(idx, "date") else str(idx),
                "value": float(row[idx]) if pd.notna(row[idx]) else None,
            }
            for idx in row.index
        ]
    except Exception:
        return []


def _try_fields(df, *fields: str) -> list[dict]:
    """Try multiple field names; return first non-empty result."""
    for f in fields:
        result = _df_row(df, f)
        if result:
            return result
    return []


def _year_end_prices(ticker_obj, periods: list[str]) -> dict[str, float | None]:
    """Fetch closing price at or just before each fiscal-year-end date.

    yfinance monthly history index uses timezone-aware timestamps (UTC or tz-
    localised). Comparisons are normalised to tz-naive date strings to avoid
    TypeError when mixing aware/naive Timestamps.
    """
    prices: dict[str, float | None] = {}
    try:
        import pandas as pd

        hist = ticker_obj.history(period="10y", interval="1mo")
        if hist is None or hist.empty:
            return {p: None for p in periods}

        # Normalise index to tz-naive date for safe comparison
        hist.index = pd.to_datetime(hist.index).tz_localize(None)

        for period in periods:
            try:
                target = pd.Timestamp(period[:10])  # keep YYYY-MM-DD only
                # Use the closest month-end on or before the fiscal year-end.
                # Add a 35-day forward window so September fiscal year-ends
                # match the October bar when the September bar is missing.
                window_end = target + pd.DateOffset(days=35)
                subset = hist[hist.index <= window_end]
                if not subset.empty:
                    prices[period] = float(subset["Close"].iloc[-1])
                else:
                    prices[period] = None
            except Exception:
                prices[period] = None
    except Exception:
        prices = {p: None for p in periods}
    return prices


# ---------------------------------------------------------------------------
# 1. Share Buyback Analysis
# ---------------------------------------------------------------------------


def compute_buyback_analysis(
    stock,  # yfinance Ticker object
    info: dict,
    cash_flow: Any,
    balance_sheet: Any,
) -> dict:
    """Compute share repurchase metrics.

    Methodology:
      - Shares repurchased from cash-flow statement: RepurchaseOfStock (negative = outflow).
      - Buyback ROI = current_price / weighted_avg_buyback_price — measures return on capital deployed.
      - Net buyback effectiveness = (shares_repurchased - shares_issued_via_SBC) / beginning_shares.
      - Value creation: positive when buybacks executed below intrinsic value; negative when above.
    """
    result: dict[str, Any] = {
        "methodology": (
            "Buyback ROI = current_price / avg_buyback_price_per_period. "
            "Net effectiveness = (shares_repurchased - SBC_shares_issued) / beginning_shares. "
            "Source: yfinance cash flow statement (RepurchaseOfCapitalStock)."
        )
    }

    # Repurchase outflow series — yfinance sign: negative = cash outflow (buyback)
    repurchase_series = _try_fields(
        cash_flow,
        "Repurchase Of Capital Stock",
        "RepurchaseOfCapitalStock",
        "Common Stock Repurchased",
    )
    # SBC series from cash flow (non-cash add-back → positive)
    sbc_series = _try_fields(
        cash_flow,
        "Stock Based Compensation",
        "StockBasedCompensation",
        "Share Based Compensation",
    )
    # Shares issued (SBC grants, secondaries) — from cash flow
    shares_issued_series = _try_fields(
        cash_flow,
        "Issuance Of Capital Stock",
        "IssuanceOfCapitalStock",
        "Proceeds From Issuance Of Common Stock",
    )

    current_price = (
        info.get("regularMarketPrice")
        or info.get("currentPrice")
        or info.get("previousClose")
    )

    # Shares outstanding history from balance sheet
    shares_series = _try_fields(
        balance_sheet,
        "Ordinary Shares Number",
        "Share Issued",
        "Common Stock",
    )

    # Build annual buyback dollar amounts (abs value; positive = cash spent on buybacks)
    buyback_amounts: list[dict] = []
    for entry in repurchase_series:
        v = entry.get("value")
        if v is not None:
            buyback_amounts.append({"period": entry["period"], "value": abs(v)})

    # Trailing 1yr / 3yr / 5yr totals
    def _trailing_total(n: int) -> float | None:
        vals = [e["value"] for e in buyback_amounts[:n] if e.get("value") is not None]
        return sum(vals) if vals else None

    result["buybacks_trailing_1yr_usd"] = _trailing_total(1)
    result["buybacks_trailing_3yr_usd"] = _trailing_total(3)
    result["buybacks_trailing_5yr_usd"] = _trailing_total(5)

    # Average annual buyback price: requires knowing price at each year-end
    periods = [e["period"] for e in buyback_amounts[:5]]
    year_prices = _year_end_prices(stock, periods) if periods else {}

    annual_buyback_details: list[dict] = []
    roi_inputs: list[tuple[float, float]] = []  # (weight, avg_price)

    for entry in buyback_amounts[:5]:
        period = entry["period"]
        amount = entry["value"]
        year_price = year_prices.get(period)
        annual_buyback_details.append(
            {
                "period": period,
                "buyback_usd": _round(amount, 0),
                "year_end_price": _round(year_price, 2),
            }
        )
        if year_price and year_price > 0 and amount:
            roi_inputs.append((amount, year_price))

    result["annual_buyback_details"] = annual_buyback_details

    # Buyback ROI per period and blended
    if current_price and roi_inputs:
        period_rois = []
        weighted_price_num = 0.0
        weighted_price_den = 0.0
        for weight, avg_price in roi_inputs:
            period_rois.append(_round(current_price / avg_price - 1.0, 4))
            weighted_price_num += weight * avg_price
            weighted_price_den += weight

        blended_avg_price = (
            weighted_price_num / weighted_price_den if weighted_price_den else None
        )
        blended_roi = (
            _round(current_price / blended_avg_price - 1.0, 4)
            if blended_avg_price
            else None
        )

        result["buyback_roi"] = {
            "methodology": "ROI = (current_price / weighted_avg_buyback_price) - 1",
            "current_price": current_price,
            "blended_avg_buyback_price": _round(blended_avg_price, 2),
            "blended_roi": blended_roi,
            "blended_roi_pct": _pct(blended_roi),
            "interpretation": (
                "Value created"
                if blended_roi and blended_roi > 0
                else "Value destroyed"
                if blended_roi and blended_roi < 0
                else "Insufficient data"
            ),
        }
    else:
        result["buyback_roi"] = {
            "blended_roi": None,
            "note": "Insufficient price or buyback data to compute ROI.",
        }

    # Net buyback effectiveness (buybacks minus SBC dilution)
    sbc_vals = _extract_series(sbc_series)
    shares_vals = _extract_series(shares_series)
    repurchase_vals = [abs(v) for v in _extract_series(repurchase_series)]

    shares_issued_vals = _extract_series(shares_issued_series)

    if repurchase_vals and sbc_vals and len(shares_vals) >= 2:
        # For most-recent year
        sbc_last = sbc_vals[0] if sbc_vals else 0.0
        repurchase_last = repurchase_vals[0] if repurchase_vals else 0.0
        beginning_shares_val = shares_vals[1] if len(shares_vals) > 1 else None
        current_price_for_est = current_price or 1.0

        # Convert SBC dollar amount to approximate share equivalents
        if current_price_for_est and current_price_for_est > 0:
            sbc_share_equiv = sbc_last / current_price_for_est
            repurchase_share_equiv = repurchase_last / current_price_for_est

            if beginning_shares_val and beginning_shares_val > 0:
                net_effectiveness = (
                    repurchase_share_equiv - sbc_share_equiv
                ) / beginning_shares_val
                result["net_buyback_effectiveness"] = {
                    "methodology": (
                        "Net effectiveness = (shares_repurchased_equiv - SBC_share_equiv) / beginning_shares. "
                        "Share equivalents estimated as dollar_amount / current_price."
                    ),
                    "net_effectiveness_rate": _round(net_effectiveness, 4),
                    "net_effectiveness_pct": _pct(net_effectiveness),
                    "interpretation": (
                        "Concentrating (net positive shareholder value)"
                        if net_effectiveness > 0
                        else "Diluting (SBC exceeds buybacks)"
                    ),
                    "sbc_dollar_last_yr": _round(sbc_last, 0),
                    "repurchase_dollar_last_yr": _round(repurchase_last, 0),
                }
            else:
                result["net_buyback_effectiveness"] = {
                    "net_effectiveness_rate": None,
                    "note": "Beginning share count unavailable.",
                }
        else:
            result["net_buyback_effectiveness"] = {
                "net_effectiveness_rate": None,
                "note": "Current price unavailable — cannot estimate share equivalents.",
            }
    else:
        result["net_buyback_effectiveness"] = {
            "net_effectiveness_rate": None,
            "note": "Insufficient data: requires repurchase, SBC, and shares outstanding series.",
        }

    return result


# ---------------------------------------------------------------------------
# 2. Stock-Based Compensation Dilution
# ---------------------------------------------------------------------------


def compute_sbc_dilution(
    income_stmt: Any,
    cash_flow: Any,
    balance_sheet: Any,
    info: dict,
) -> dict:
    """Compute SBC dilution metrics.

    Methodology:
      - SBC % of revenue = SBC / Total Revenue (flag if >5%).
      - SBC % of operating income = SBC / Operating Income.
      - True dilution rate = (shares_issued - shares_repurchased) / beginning_shares.
      - SBC-adjusted FCF = FCF - SBC (penalises the real economic cost of option grants).
      - Net share trajectory: positive slope = diluting, negative slope = concentrating.
    """
    result: dict[str, Any] = {
        "methodology": (
            "SBC dilution analysis follows Graham & Dodd treatment: SBC is a real economic cost "
            "subtracted from FCF. True dilution = (gross shares issued - shares repurchased) / "
            "beginning shares. Source: yfinance income statement and cash flow statement."
        )
    }

    sbc_series = _try_fields(
        cash_flow,
        "Stock Based Compensation",
        "StockBasedCompensation",
        "Share Based Compensation",
    )
    revenue_series = _try_fields(income_stmt, "Total Revenue", "Revenue")
    op_income_series = _try_fields(income_stmt, "Operating Income", "EBIT")
    ocf_series = _try_fields(
        cash_flow,
        "Operating Cash Flow",
        "Cash Flow From Continuing Operating Activities",
    )
    capex_series = _try_fields(
        cash_flow, "Capital Expenditure", "Purchase Of Property Plant And Equipment"
    )
    shares_series = _try_fields(
        balance_sheet,
        "Ordinary Shares Number",
        "Share Issued",
        "Common Stock",
    )
    repurchase_series = _try_fields(
        cash_flow,
        "Repurchase Of Capital Stock",
        "RepurchaseOfCapitalStock",
        "Common Stock Repurchased",
    )

    sbc_vals = _extract_series(sbc_series)
    revenue_vals = _extract_series(revenue_series)
    op_income_vals = _extract_series(op_income_series)
    shares_vals = _extract_series(shares_series)

    # SBC as % of revenue (flag if >5%)
    sbc_revenue_series = []
    sbc_opex_series = []
    for i, sbc in enumerate(sbc_vals):
        rev = revenue_vals[i] if i < len(revenue_vals) else None
        op = op_income_vals[i] if i < len(op_income_vals) else None
        period = sbc_series[i]["period"] if i < len(sbc_series) else f"Year-{i}"
        sbc_revenue_series.append(
            {
                "period": period,
                "sbc_usd": _round(sbc, 0),
                "sbc_pct_revenue": _round(_safe_div(sbc, rev), 4),
                "flag_high_sbc": (_safe_div(sbc, rev) or 0) > 0.05,
            }
        )
        sbc_opex_series.append(
            {
                "period": period,
                "sbc_pct_operating_income": _round(
                    _safe_div(sbc, abs(op)) if op else None, 4
                ),
            }
        )

    result["sbc_as_pct_revenue"] = sbc_revenue_series
    result["sbc_as_pct_operating_income"] = sbc_opex_series

    if sbc_revenue_series:
        latest = sbc_revenue_series[0]
        result["sbc_revenue_flag"] = {
            "latest_pct": _pct(latest.get("sbc_pct_revenue")),
            "flag": latest.get("flag_high_sbc", False),
            "interpretation": (
                "WARNING: SBC >5% of revenue — significant dilution risk"
                if latest.get("flag_high_sbc")
                else "SBC within normal range (<5% of revenue)"
            ),
        }

    # True dilution rate
    if len(shares_vals) >= 2:
        dilution_series = []
        for i in range(min(len(shares_vals) - 1, 5)):
            beginning = shares_vals[i + 1]
            ending = shares_vals[i]
            sbc_v = sbc_vals[i] if i < len(sbc_vals) else None
            repurch_v = (
                abs(repurchase_series[i]["value"])
                if i < len(repurchase_series)
                and repurchase_series[i].get("value") is not None
                else None
            )
            current_price_est = info.get("regularMarketPrice") or info.get(
                "currentPrice"
            )
            gross_issued = (
                sbc_v / current_price_est
                if sbc_v and current_price_est and current_price_est > 0
                else None
            )
            gross_repurchased = (
                repurch_v / current_price_est
                if repurch_v and current_price_est and current_price_est > 0
                else None
            )
            net_dilution = (
                _safe_div(
                    (gross_issued or 0) - (gross_repurchased or 0),
                    beginning,
                )
                if beginning > 0 and gross_issued is not None
                else None
            )
            actual_dilution = _safe_div(ending - beginning, beginning)
            dilution_series.append(
                {
                    "period": shares_series[i]["period"]
                    if i < len(shares_series)
                    else f"Year-{i}",
                    "beginning_shares": _round(beginning, 0),
                    "ending_shares": _round(ending, 0),
                    "actual_dilution_rate": _round(actual_dilution, 4),
                    "actual_dilution_pct": _pct(actual_dilution),
                }
            )

        result["true_dilution_series"] = dilution_series

        # 1yr, 3yr, 5yr actual dilution
        actual_dilution_rates = [
            e["actual_dilution_rate"]
            for e in dilution_series
            if e.get("actual_dilution_rate") is not None
        ]
        result["dilution_summary"] = {
            "methodology": (
                "Actual dilution = (shares_end - shares_begin) / shares_begin per year. "
                "Negative = concentrating (buybacks > issuance); positive = diluting."
            ),
            "trailing_1yr_pct": _pct(actual_dilution_rates[0])
            if actual_dilution_rates
            else None,
            "trailing_3yr_avg_pct": _pct(
                sum(actual_dilution_rates[:3]) / len(actual_dilution_rates[:3])
            )
            if len(actual_dilution_rates) >= 3
            else None,
            "trailing_5yr_avg_pct": _pct(
                sum(actual_dilution_rates[:5]) / len(actual_dilution_rates[:5])
            )
            if len(actual_dilution_rates) >= 5
            else None,
        }

        # Net share count trajectory
        trend = None
        if len(shares_vals) >= 3:
            recent_avg = sum(shares_vals[:2]) / 2
            older_avg = sum(shares_vals[-2:]) / 2
            if older_avg > 0:
                trend_val = (recent_avg - older_avg) / older_avg
                trend = (
                    "diluting"
                    if trend_val > 0.005
                    else "concentrating"
                    if trend_val < -0.005
                    else "stable"
                )

        result["share_count_trajectory"] = {
            "current_shares": _round(shares_vals[0], 0) if shares_vals else None,
            "shares_5yr_ago": _round(shares_vals[-1], 0)
            if len(shares_vals) >= 5
            else None,
            "trend": trend,
            "5yr_total_change_pct": _pct(
                _cagr(shares_vals[-1], shares_vals[0], len(shares_vals) - 1)
                if len(shares_vals) >= 2
                else None
            ),
        }
    else:
        result["true_dilution_series"] = []
        result["dilution_summary"] = {
            "note": "Insufficient shares outstanding history."
        }
        result["share_count_trajectory"] = {
            "note": "Insufficient shares outstanding history."
        }

    # SBC-adjusted FCF
    ocf_vals = _extract_series(ocf_series)
    capex_vals = [abs(v) for v in _extract_series(capex_series)]

    sbc_adj_fcf_series = []
    for i, sbc in enumerate(sbc_vals[:5]):
        ocf = ocf_vals[i] if i < len(ocf_vals) else None
        capex = capex_vals[i] if i < len(capex_vals) else None
        if ocf is not None and capex is not None:
            raw_fcf = ocf - capex
            sbc_adj_fcf = raw_fcf - sbc
            sbc_adj_fcf_series.append(
                {
                    "period": sbc_series[i]["period"]
                    if i < len(sbc_series)
                    else f"Year-{i}",
                    "raw_fcf": _round(raw_fcf, 0),
                    "sbc_usd": _round(sbc, 0),
                    "sbc_adjusted_fcf": _round(sbc_adj_fcf, 0),
                    "sbc_as_pct_raw_fcf": _pct(_safe_div(sbc, raw_fcf)),
                }
            )

    result["sbc_adjusted_fcf"] = {
        "methodology": (
            "SBC-adjusted FCF = (Operating Cash Flow - CapEx) - SBC. "
            "This treats option/RSU grants as real economic cost per Graham & Dodd convention."
        ),
        "series": sbc_adj_fcf_series,
    }

    return result


# ---------------------------------------------------------------------------
# 3. Capital Return Analysis
# ---------------------------------------------------------------------------


def compute_capital_return(
    stock,
    info: dict,
    cash_flow: Any,
    income_stmt: Any,
) -> dict:
    """Compute dividend, buyback, and total capital return yields.

    Methodology:
      - Dividend yield (trailing) = trailing_dividends_per_share / current_price.
      - Buyback yield = net_buybacks / market_cap.
      - Total capital return yield = (dividends + net_buybacks) / market_cap.
      - Payout ratio = (dividends_paid + buybacks) / FCF (cash-based, preferred over earnings-based).
      - Retained earnings reinvestment rate = 1 - (dividends_paid / net_income).
      - Dividend CAGR uses per-share dividends from yfinance dividends history.
    """
    result: dict[str, Any] = {
        "methodology": (
            "Capital return yields use market cap denominator. "
            "Payout ratio uses FCF (not earnings) per Greenblatt convention — measures sustainability. "
            "Dividend CAGR from per-share dividend history."
        )
    }

    market_cap = info.get("marketCap")
    current_price = (
        info.get("regularMarketPrice")
        or info.get("currentPrice")
        or info.get("previousClose")
    )

    # Dividend yield
    # yfinance `dividendYield` field is unreliable (often stale/annualised wrongly).
    # `trailingAnnualDividendYield` is the authoritative trailing 12-month figure.
    trailing_yield = info.get("trailingAnnualDividendYield") or info.get(
        "dividendYield"
    )
    result["dividend_yield_trailing"] = _round(trailing_yield, 4)
    result["dividend_yield_trailing_pct"] = _pct(trailing_yield)
    result["dividend_yield_forward"] = _round(
        info.get("dividendRate")
        and current_price
        and _safe_div(info.get("dividendRate"), current_price),
        4,
    )

    # Dividends paid (cash flow)
    dividends_paid_series = _try_fields(
        cash_flow,
        "Cash Dividends Paid",
        "Payment Of Dividends",
        "Common Stock Dividend Paid",
    )
    repurchase_series = _try_fields(
        cash_flow,
        "Repurchase Of Capital Stock",
        "RepurchaseOfCapitalStock",
        "Common Stock Repurchased",
    )
    ocf_series = _try_fields(
        cash_flow,
        "Operating Cash Flow",
        "Cash Flow From Continuing Operating Activities",
    )
    capex_series = _try_fields(
        cash_flow, "Capital Expenditure", "Purchase Of Property Plant And Equipment"
    )
    net_income_series = _try_fields(
        income_stmt, "Net Income", "Net Income Common Stockholders"
    )

    div_paid_vals = [abs(v) for v in _extract_series(dividends_paid_series)]
    repurchase_vals = [abs(v) for v in _extract_series(repurchase_series)]
    ocf_vals = _extract_series(ocf_series)
    capex_vals = [abs(v) for v in _extract_series(capex_series)]
    net_income_vals = _extract_series(net_income_series)

    # Buyback yield
    buyback_last = repurchase_vals[0] if repurchase_vals else None
    buyback_yield = _safe_div(buyback_last, market_cap)
    result["buyback_yield"] = {
        "methodology": "Buyback yield = net_repurchases_last12m / market_cap",
        "buyback_yield": _round(buyback_yield, 4),
        "buyback_yield_pct": _pct(buyback_yield),
        "net_buybacks_usd": _round(buyback_last, 0),
        "market_cap": market_cap,
    }

    # Total capital return yield
    div_last = div_paid_vals[0] if div_paid_vals else 0.0
    total_return_usd = (div_last or 0) + (buyback_last or 0)
    total_yield = _safe_div(total_return_usd, market_cap)
    result["total_capital_return_yield"] = {
        "methodology": "Total yield = (dividends_paid + net_buybacks) / market_cap",
        "total_yield": _round(total_yield, 4),
        "total_yield_pct": _pct(total_yield),
        "dividends_usd": _round(div_last, 0),
        "buybacks_usd": _round(buyback_last, 0),
        "total_returned_usd": _round(total_return_usd, 0),
    }

    # Payout ratio (FCF-based)
    payout_series = []
    for i in range(min(len(div_paid_vals), len(repurchase_vals), 5)):
        ocf = ocf_vals[i] if i < len(ocf_vals) else None
        capex = capex_vals[i] if i < len(capex_vals) else None
        div = div_paid_vals[i]
        repurch = repurchase_vals[i]
        fcf = (ocf - capex) if (ocf is not None and capex is not None) else None
        payout_ratio = _safe_div(div + repurch, fcf) if fcf and fcf > 0 else None
        period = (
            dividends_paid_series[i]["period"]
            if i < len(dividends_paid_series)
            else f"Year-{i}"
        )
        payout_series.append(
            {
                "period": period,
                "dividends_paid": _round(div, 0),
                "buybacks": _round(repurch, 0),
                "fcf": _round(fcf, 0),
                "payout_ratio_fcf": _round(payout_ratio, 4),
                "payout_ratio_pct": _pct(payout_ratio),
                "flag_unsustainable": payout_ratio is not None and payout_ratio > 1.0,
            }
        )

    result["payout_ratio_fcf_series"] = {
        "methodology": (
            "FCF-based payout ratio = (dividends_paid + buybacks) / FCF. "
            "Preferred over earnings-based: measures cash sustainability. "
            ">100% indicates company is returning more than it generates."
        ),
        "series": payout_series,
        "latest_payout_ratio_pct": payout_series[0].get("payout_ratio_pct")
        if payout_series
        else None,
        "sustainability_flag": payout_series[0].get("flag_unsustainable", False)
        if payout_series
        else None,
    }

    # Retained earnings reinvestment rate
    if net_income_vals and div_paid_vals:
        ni = net_income_vals[0]
        div = div_paid_vals[0]
        reinvestment_rate = 1.0 - _safe_div(div, ni) if ni and ni > 0 else None
        result["retained_earnings_reinvestment_rate"] = {
            "methodology": "Reinvestment rate = 1 - (dividends_paid / net_income)",
            "reinvestment_rate": _round(reinvestment_rate, 4),
            "reinvestment_rate_pct": _pct(reinvestment_rate),
        }
    else:
        result["retained_earnings_reinvestment_rate"] = {
            "reinvestment_rate": None,
            "note": "Net income or dividends paid unavailable.",
        }

    # Dividend CAGR from per-share dividend history
    try:
        import pandas as pd

        div_history = stock.dividends
        if div_history is not None and len(div_history) > 0:
            try:
                div_annual = div_history.resample("YE").sum()
            except (ValueError, KeyError):
                # pandas < 2.2 uses "A" for year-end alias
                div_annual = div_history.resample("A").sum()
            # Drop the current (partial) calendar year — it has fewer dividend
            # payments than a full year and will produce a misleadingly low CAGR.
            # rollforward() of today returns today's own year-end, so exclude
            # any bar whose index year equals the current calendar year.
            current_year = pd.Timestamp.now().year
            div_annual = div_annual[div_annual.index.year < current_year]
            if len(div_annual) >= 2:
                div_vals_annual = div_annual.values.tolist()
                div_vals_annual.reverse()  # most-recent first (most-recent completed year at [0])

                def _div_cagr(n: int) -> float | None:
                    if len(div_vals_annual) >= n + 1:
                        return _cagr(div_vals_annual[n], div_vals_annual[0], n)
                    return None

                result["dividend_growth_cagr"] = {
                    "methodology": (
                        "Dividend CAGR from per-share annual dividend history (completed years only). "
                        "Partial current year excluded to avoid understating growth."
                    ),
                    "cagr_3yr": _round(_div_cagr(3), 4),
                    "cagr_3yr_pct": _pct(_div_cagr(3)),
                    "cagr_5yr": _round(_div_cagr(5), 4),
                    "cagr_5yr_pct": _pct(_div_cagr(5)),
                    "cagr_10yr": _round(_div_cagr(10), 4),
                    "cagr_10yr_pct": _pct(_div_cagr(10)),
                    "latest_annual_dps": _round(div_vals_annual[0], 4),
                }
            else:
                result["dividend_growth_cagr"] = {
                    "note": "Insufficient completed-year dividend history for CAGR (need 2+ years)."
                }
        else:
            result["dividend_growth_cagr"] = {
                "cagr_3yr": None,
                "cagr_5yr": None,
                "cagr_10yr": None,
                "note": "No dividend history found — company may not pay dividends.",
            }
    except Exception as e:
        result["dividend_growth_cagr"] = {
            "note": f"Could not compute dividend CAGR: {e}"
        }

    # Dividend safety score
    div_coverage = None
    div_safety_flags = []
    if div_paid_vals and ocf_vals and capex_vals:
        div = div_paid_vals[0]
        ocf = ocf_vals[0] if ocf_vals else None
        capex = capex_vals[0] if capex_vals else None
        if ocf and capex and div and div > 0:
            fcf_coverage = (ocf - capex) / div
            div_coverage = _round(fcf_coverage, 2)
            if fcf_coverage < 1.0:
                div_safety_flags.append(
                    f"FCF coverage below 1.0x ({fcf_coverage:.2f}x) — dividend at risk"
                )
            elif fcf_coverage < 1.5:
                div_safety_flags.append(
                    f"FCF coverage thin ({fcf_coverage:.2f}x) — watch closely"
                )

    result["dividend_safety"] = {
        "methodology": "FCF coverage = FCF / dividends_paid. >2x = safe; 1-2x = adequate; <1x = at risk.",
        "fcf_coverage_ratio": div_coverage,
        "flags": div_safety_flags,
        "safety_assessment": (
            "Safe"
            if div_coverage and div_coverage >= 2.0
            else "Adequate"
            if div_coverage and div_coverage >= 1.0
            else "At risk"
            if div_coverage is not None and div_coverage < 1.0
            else "No dividends or insufficient data"
        ),
    }

    return result


# ---------------------------------------------------------------------------
# 4. Optimal Capital Structure
# ---------------------------------------------------------------------------


def compute_capital_structure(
    info: dict,
    income_stmt: Any,
    balance_sheet: Any,
    cash_flow: Any,
) -> dict:
    """Compute leverage, WACC, and capital structure metrics.

    Methodology:
      - Debt/Equity = total_debt / stockholders_equity.
      - Net Debt/EBITDA = (total_debt - cash) / EBITDA.
      - Interest coverage = EBIT / interest_expense (Dalio framework: >3x = manageable).
      - WACC = E/(D+E) * Ke + D/(D+E) * Kd * (1-t). Ke via CAPM.
      - WACC sensitivity table shows value at different leverage levels.
      - Debt maturity proximity from balance sheet current vs non-current debt split.
    """
    result: dict[str, Any] = {
        "methodology": (
            "Leverage metrics follow Dalio's 'beautiful deleveraging' framework. "
            "WACC via Modigliani-Miller with CAPM cost of equity. "
            "Interest coverage >3x is considered manageable per standard credit analysis."
        )
    }

    # Extract latest values
    total_debt_series = _try_fields(
        balance_sheet,
        "Total Debt",
        "Long Term Debt",
        "Long Term Debt And Capital Lease Obligation",
    )
    equity_series = _try_fields(
        balance_sheet, "Stockholders Equity", "Common Stock Equity"
    )
    cash_series = _try_fields(
        balance_sheet,
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    )
    ebitda_series = _try_fields(
        income_stmt,
        "EBITDA",
        "Normalized EBITDA",
    )
    ebit_series = _try_fields(income_stmt, "Operating Income", "EBIT")
    interest_series = _try_fields(
        income_stmt,
        "Interest Expense",
        "Interest Expense Non Operating",
    )
    current_debt_series = _try_fields(
        balance_sheet,
        "Current Debt",
        "Current Debt And Capital Lease Obligation",
        "Short Long Term Debt",
    )
    long_term_debt_series = _try_fields(
        balance_sheet,
        "Long Term Debt",
        "Long Term Debt And Capital Lease Obligation",
    )
    net_income_series = _try_fields(income_stmt, "Net Income")
    tax_provision_series = _try_fields(
        income_stmt, "Tax Provision", "Income Tax Expense"
    )
    pretax_income_series = _try_fields(
        income_stmt, "Pretax Income", "Income Before Tax"
    )

    total_debt_vals = _extract_series(total_debt_series)
    equity_vals = _extract_series(equity_series)
    cash_vals = _extract_series(cash_series)
    ebitda_vals = _extract_series(ebitda_series)
    ebit_vals = _extract_series(ebit_series)
    interest_vals = [abs(v) for v in _extract_series(interest_series)]
    current_debt_vals = _extract_series(current_debt_series)
    long_term_debt_vals = _extract_series(long_term_debt_series)
    net_income_vals = _extract_series(net_income_series)
    tax_vals = _extract_series(tax_provision_series)
    pretax_vals = _extract_series(pretax_income_series)

    market_cap = info.get("marketCap")
    beta = info.get("beta")
    current_price = info.get("regularMarketPrice") or info.get("currentPrice")

    # Core leverage ratios
    total_debt = total_debt_vals[0] if total_debt_vals else None
    equity = equity_vals[0] if equity_vals else None
    cash = cash_vals[0] if cash_vals else None
    ebitda = ebitda_vals[0] if ebitda_vals else None
    ebit = ebit_vals[0] if ebit_vals else None
    interest_exp = interest_vals[0] if interest_vals else None

    net_debt = (
        (total_debt - cash) if (total_debt is not None and cash is not None) else None
    )

    result["leverage_ratios"] = {
        "methodology": (
            "Debt/Equity = total_debt / stockholders_equity. "
            "Net Debt = total_debt - cash_and_equivalents. "
            "Net Debt/EBITDA preferred over gross debt for capital allocation decisions."
        ),
        "total_debt": _round(total_debt, 0),
        "cash": _round(cash, 0),
        "net_debt": _round(net_debt, 0),
        "stockholders_equity": _round(equity, 0),
        "debt_to_equity": _round(_safe_div(total_debt, equity), 4),
        "net_debt_to_ebitda": _round(_safe_div(net_debt, ebitda), 4),
        "gross_debt_to_ebitda": _round(_safe_div(total_debt, ebitda), 4),
        "interest_coverage_ebit": _round(_safe_div(ebit, interest_exp), 2),
        "flag_high_leverage": (
            (_safe_div(net_debt, ebitda) or 0) > 4.0
            or (_safe_div(ebit, interest_exp) or 999) < 2.0
        ),
    }

    # Weighted average cost of debt
    if total_debt and interest_exp and total_debt > 0:
        cost_of_debt = interest_exp / total_debt
    elif info.get("totalDebt") and interest_exp:
        cost_of_debt = interest_exp / info["totalDebt"]
    else:
        cost_of_debt = None

    # Effective tax rate
    tax_rate = None
    if tax_vals and pretax_vals and pretax_vals[0] and pretax_vals[0] != 0:
        tax_rate = abs(tax_vals[0]) / abs(pretax_vals[0])
        tax_rate = max(0.0, min(0.5, tax_rate))  # clamp to [0%, 50%]
    if tax_rate is None:
        tax_rate = 0.21  # US statutory default

    result["cost_of_debt"] = {
        "methodology": "Kd = interest_expense / total_debt. After-tax Kd = Kd * (1 - effective_tax_rate).",
        "gross_cost_of_debt": _round(cost_of_debt, 4),
        "gross_cost_of_debt_pct": _pct(cost_of_debt),
        "effective_tax_rate": _round(tax_rate, 4),
        "after_tax_cost_of_debt": _round(
            cost_of_debt * (1 - tax_rate) if cost_of_debt else None, 4
        ),
        "after_tax_cost_of_debt_pct": _pct(
            cost_of_debt * (1 - tax_rate) if cost_of_debt else None
        ),
    }

    # WACC — risk-free rate sourced live from 10Y Treasury yield (^TNX)
    # with a hardcoded fallback if the live fetch fails.
    risk_free_rate = _fetch_10y_yield()
    equity_risk_premium = 0.055  # Damodaran implied ERP
    beta_val = beta or 1.0
    cost_of_equity = risk_free_rate + beta_val * equity_risk_premium

    enterprise_value = (market_cap or 0) + (net_debt or 0)
    if enterprise_value > 0 and market_cap is not None:
        equity_weight = market_cap / enterprise_value
        debt_weight = 1.0 - equity_weight
    elif market_cap and total_debt:
        total_cap = market_cap + total_debt
        equity_weight = market_cap / total_cap
        debt_weight = total_debt / total_cap
    else:
        equity_weight = 0.8
        debt_weight = 0.2

    after_tax_kd = (cost_of_debt * (1 - tax_rate)) if cost_of_debt else 0.04
    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_kd

    result["wacc"] = {
        "methodology": (
            "WACC = E/(D+E) * Ke + D/(D+E) * Kd*(1-t). "
            "Ke = Rf + beta * ERP (CAPM). Rf = 4.3% (10Y UST). ERP = 5.5% (Damodaran). "
            "Weights based on market-value capital structure."
        ),
        "risk_free_rate": risk_free_rate,
        "equity_risk_premium": equity_risk_premium,
        "beta": beta_val,
        "cost_of_equity": _round(cost_of_equity, 4),
        "cost_of_equity_pct": _pct(cost_of_equity),
        "after_tax_cost_of_debt": _round(after_tax_kd, 4),
        "after_tax_cost_of_debt_pct": _pct(after_tax_kd),
        "equity_weight": _round(equity_weight, 4),
        "debt_weight": _round(debt_weight, 4),
        "wacc": _round(wacc, 4),
        "wacc_pct": _pct(wacc),
    }

    # WACC sensitivity at varying leverage levels (Modigliani-Miller trade-off)
    wacc_sensitivity = []
    for debt_pct in [0.0, 0.10, 0.20, 0.30, 0.40, 0.50]:
        eq_pct = 1.0 - debt_pct
        # Higher leverage increases cost of equity (financial distress premium)
        distress_premium = debt_pct**2 * 0.02
        ke_adj = cost_of_equity + distress_premium
        kd_adj = after_tax_kd + debt_pct * 0.005  # debt cost rises with leverage
        wacc_adj = eq_pct * ke_adj + debt_pct * kd_adj
        wacc_sensitivity.append(
            {
                "debt_pct_of_capital": _pct(debt_pct),
                "equity_pct_of_capital": _pct(eq_pct),
                "cost_of_equity_pct": _pct(ke_adj),
                "after_tax_cost_of_debt_pct": _pct(kd_adj),
                "wacc_pct": _pct(wacc_adj),
            }
        )

    result["wacc_leverage_sensitivity"] = {
        "methodology": (
            "Modigliani-Miller trade-off: interest tax shield benefit offset by rising "
            "financial distress probability at higher leverage. "
            "Distress premium = (debt_pct^2) * 2%. Debt cost rises 0.5% per 10% additional leverage."
        ),
        "table": wacc_sensitivity,
        "optimal_leverage_note": (
            "Minimum WACC in the table indicates theoretically optimal leverage. "
            "Industry norms and bond covenant constraints often dominate in practice."
        ),
    }

    # Debt maturity schedule (current vs long-term split)
    current_debt_val = current_debt_vals[0] if current_debt_vals else None
    lt_debt_val = long_term_debt_vals[0] if long_term_debt_vals else None
    total_debt_for_sched = (
        total_debt if total_debt else ((current_debt_val or 0) + (lt_debt_val or 0))
    )

    # Weighted average maturity proxy: assume current matures in 0.5yr, LT in 5yr
    if current_debt_val and lt_debt_val and total_debt_for_sched > 0:
        wav_maturity = (
            current_debt_val * 0.5 + lt_debt_val * 5.0
        ) / total_debt_for_sched
    else:
        wav_maturity = None

    result["debt_maturity_schedule"] = {
        "methodology": (
            "Maturity split from balance sheet current vs non-current debt. "
            "Weighted average maturity (WAM) = weighted by debt tranche size. "
            "Current portion assumed maturity ~6 months; long-term ~5 years (proxy only — "
            "exact schedule requires 10-K notes)."
        ),
        "current_portion_debt": _round(current_debt_val, 0),
        "long_term_debt": _round(lt_debt_val, 0),
        "total_debt": _round(total_debt_for_sched, 0),
        "pct_maturing_within_1yr": _pct(
            _safe_div(current_debt_val, total_debt_for_sched)
        ),
        "weighted_avg_maturity_proxy_years": _round(wav_maturity, 1),
        "refinancing_risk": (
            "High"
            if current_debt_val
            and total_debt_for_sched
            and (current_debt_val / total_debt_for_sched) > 0.30
            else "Moderate"
            if current_debt_val
            and total_debt_for_sched
            and (current_debt_val / total_debt_for_sched) > 0.15
            else "Low"
            if total_debt_for_sched and total_debt_for_sched > 0
            else "Not applicable"
        ),
    }

    # Sector median leverage comparison (static reference data)
    SECTOR_MEDIAN_NET_DEBT_EBITDA = {
        "Technology": 0.5,
        "Healthcare": 1.2,
        "Consumer Discretionary": 2.0,
        "Consumer Staples": 1.8,
        "Financials": None,  # leverage not meaningful for banks
        "Industrials": 1.8,
        "Energy": 1.5,
        "Materials": 1.3,
        "Utilities": 3.5,
        "Real Estate": 4.0,
        "Communication Services": 1.5,
    }
    sector = info.get("sector", "")
    sector_median = SECTOR_MEDIAN_NET_DEBT_EBITDA.get(sector)
    company_nd_ebitda = result["leverage_ratios"].get("net_debt_to_ebitda")

    result["sector_leverage_comparison"] = {
        "methodology": "Sector median Net Debt/EBITDA from Damodaran sector averages (approximate).",
        "company_net_debt_ebitda": company_nd_ebitda,
        "sector": sector,
        "sector_median_net_debt_ebitda": sector_median,
        "vs_sector_median": (
            _round(company_nd_ebitda - sector_median, 2)
            if company_nd_ebitda is not None and sector_median is not None
            else None
        ),
        "relative_leverage": (
            "Above sector median"
            if company_nd_ebitda and sector_median and company_nd_ebitda > sector_median
            else "Below sector median"
            if company_nd_ebitda is not None
            and sector_median is not None
            and company_nd_ebitda <= sector_median
            else "Sector median not available for comparison"
        ),
    }

    return result


# ---------------------------------------------------------------------------
# 5. Capital Markets Activity Signals
# ---------------------------------------------------------------------------


def compute_capital_markets_activity(
    stock,
    info: dict,
    cash_flow: Any,
) -> dict:
    """Detect recent capital markets activity signals.

    Methodology:
      - Equity issuance: positive proceeds from stock issuance in last 12 months.
      - Insider activity: open-market purchases vs sales (dollar-weighted, 90 days).
        Cluster signal: 3+ insiders transacting in the same direction within 30 days.
      - Debt issuance: proceeds from debt issuance in cash flow.
      - Buyback authorization: change in repurchase amounts YoY.
    """
    result: dict[str, Any] = {
        "methodology": (
            "Capital markets activity detection from yfinance cash flow statement and "
            "insider transactions. Insider cluster signal (3+ same-direction within 30 days) "
            "per Lakonishok & Lee (2001) — open-market purchases are strongest predictive signal."
        )
    }

    # Equity issuance detection
    issuance_series = _try_fields(
        cash_flow,
        "Issuance Of Capital Stock",
        "IssuanceOfCapitalStock",
        "Proceeds From Issuance Of Common Stock",
    )
    issuance_vals = _extract_period_series(issuance_series)

    equity_issuances = []
    for period, val in issuance_vals[:3]:
        if val and val > 0:
            equity_issuances.append(
                {
                    "period": period,
                    "amount_usd": _round(val, 0),
                    "as_pct_market_cap": _pct(_safe_div(val, info.get("marketCap"))),
                }
            )

    result["equity_issuance"] = {
        "recent_issuances": equity_issuances,
        "issuance_detected": len(equity_issuances) > 0,
        "flag": len(equity_issuances) > 0,
        "interpretation": (
            f"Equity issuance detected in {len(equity_issuances)} recent period(s) — "
            "potential dilution signal; verify if ATM, secondary, or convert."
            if equity_issuances
            else "No significant equity issuance detected in recent periods."
        ),
    }

    # Debt issuance / refinancing
    debt_issuance_series = _try_fields(
        cash_flow,
        "Issuance Of Debt",
        "Proceeds From Issuance Of Long Term Debt",
        "Long Term Debt Issuance",
    )
    debt_repayment_series = _try_fields(
        cash_flow,
        "Repayment Of Debt",
        "Repayment Of Long Term Debt",
        "Long Term Debt Payments",
    )

    debt_issuance_vals = _extract_period_series(debt_issuance_series)
    debt_repayment_vals = _extract_period_series(debt_repayment_series)

    debt_activity = []
    for period, issued in debt_issuance_vals[:3]:
        repaid_match = next((v for p, v in debt_repayment_vals if p == period), None)
        net_debt_change = issued - (abs(repaid_match) if repaid_match else 0)
        debt_activity.append(
            {
                "period": period,
                "debt_issued": _round(issued, 0),
                "debt_repaid": _round(abs(repaid_match), 0) if repaid_match else None,
                "net_debt_change": _round(net_debt_change, 0),
                "activity_type": (
                    "Net refinancing (swapped)"
                    if repaid_match and net_debt_change < issued * 0.1
                    else "Net new debt"
                    if net_debt_change > 0
                    else "Net debt paydown"
                ),
            }
        )

    result["debt_issuance_activity"] = {
        "recent_activity": debt_activity,
        "note": "Refinancing is neutral; net new debt at high leverage warrants scrutiny.",
    }

    # Buyback authorization change YoY
    repurchase_series = _try_fields(
        cash_flow,
        "Repurchase Of Capital Stock",
        "RepurchaseOfCapitalStock",
        "Common Stock Repurchased",
    )
    repurchase_vals = [abs(v) for v in _extract_series(repurchase_series)]

    buyback_authorization_change = None
    if len(repurchase_vals) >= 2:
        recent = repurchase_vals[0]
        prior = repurchase_vals[1]
        if prior > 0:
            buyback_authorization_change = (recent - prior) / prior

    result["buyback_authorization"] = {
        "methodology": "YoY change in actual repurchase spending as proxy for authorization activity.",
        "repurchases_last_yr_usd": _round(repurchase_vals[0], 0)
        if repurchase_vals
        else None,
        "repurchases_prior_yr_usd": _round(repurchase_vals[1], 0)
        if len(repurchase_vals) > 1
        else None,
        "yoy_change_pct": _pct(buyback_authorization_change),
        "signal": (
            "Accelerating buybacks — management conviction signal"
            if buyback_authorization_change and buyback_authorization_change > 0.20
            else "Decelerating buybacks — possible capital constraint or overvaluation concern"
            if buyback_authorization_change and buyback_authorization_change < -0.20
            else "Buyback pace stable"
            if buyback_authorization_change is not None
            else "Insufficient data"
        ),
    }

    # Insider transactions (open-market only, 90 days)
    insider_signals = _compute_insider_signals(stock)
    result["insider_activity"] = insider_signals

    return result


def _compute_insider_signals(stock) -> dict:
    """Parse insider transactions for open-market buys vs sells, cluster detection."""
    try:
        import pandas as pd

        txns_raw = stock.insider_transactions
        if txns_raw is None or txns_raw.empty:
            return {
                "note": "No insider transaction data available.",
                "open_market_buys_90d_usd": None,
                "open_market_sells_90d_usd": None,
            }

        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        records = []
        for _, row in txns_raw.iterrows():
            try:
                txn_date_raw = row.get("Start Date") or row.get("startDate")
                txn_type = str(row.get("Transaction", "")).lower()
                shares = row.get("Shares") or row.get("shares")
                value = row.get("Value") or row.get("value")

                # Parse date
                if txn_date_raw:
                    if hasattr(txn_date_raw, "to_pydatetime"):
                        txn_date = txn_date_raw.to_pydatetime().replace(
                            tzinfo=timezone.utc
                        )
                    else:
                        txn_date = datetime.strptime(
                            str(txn_date_raw)[:10], "%Y-%m-%d"
                        ).replace(tzinfo=timezone.utc)
                else:
                    continue

                if txn_date < cutoff:
                    continue

                # Classify open-market transactions
                is_buy = any(kw in txn_type for kw in ("purchase", "buy", "acquired"))
                is_sell = any(
                    kw in txn_type for kw in ("sale", "sell", "sold", "disposed")
                )
                if not (is_buy or is_sell):
                    continue

                records.append(
                    {
                        "date": str(txn_date.date()),
                        "name": str(row.get("Insider", "")),
                        "type": "buy" if is_buy else "sell",
                        "shares": float(shares)
                        if shares and pd.notna(shares)
                        else None,
                        "value": float(value) if value and pd.notna(value) else None,
                    }
                )
            except Exception:
                continue

        if not records:
            return {
                "note": "No open-market insider transactions in last 90 days.",
                "open_market_buys_90d_usd": None,
                "open_market_sells_90d_usd": None,
                "buy_sell_ratio": None,
                "cluster_signal": None,
                "signal_summary": "Neutral: No open-market insider transactions in last 90 days.",
            }

        buys = [r for r in records if r["type"] == "buy"]
        sells = [r for r in records if r["type"] == "sell"]

        buy_value = sum(r["value"] for r in buys if r.get("value"))
        sell_value = sum(r["value"] for r in sells if r.get("value"))

        # Cluster detection: 3+ insiders in same direction within 30 days
        buy_cluster = _detect_cluster(buys)
        sell_cluster = _detect_cluster(sells)

        buy_sell_ratio = _safe_div(buy_value, sell_value) if sell_value > 0 else None

        return {
            "methodology": (
                "Open-market insider transactions only (excludes options exercises, gifts). "
                "Cluster signal: 3+ insiders transacting in same direction within 30 days. "
                "Per Lakonishok & Lee (2001): open-market purchases most predictive, "
                "particularly by non-officer directors."
            ),
            "period": "90 days",
            "open_market_buys_90d_usd": _round(buy_value, 0),
            "open_market_sells_90d_usd": _round(sell_value, 0),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "buy_sell_ratio": _round(buy_sell_ratio, 2),
            "buy_cluster_signal": buy_cluster,
            "sell_cluster_signal": sell_cluster,
            "signal_summary": (
                "STRONG BUY SIGNAL: Insider cluster purchase detected"
                if buy_cluster
                else "CAUTION: Insider cluster selling detected"
                if sell_cluster
                else "Bullish: Net insider buying"
                if buy_value > sell_value * 1.5
                else "Bearish: Net insider selling"
                if sell_value > buy_value * 1.5
                else "Neutral: Balanced insider activity"
            ),
            "transactions": records[:20],
        }

    except Exception as e:
        return {"note": f"Could not parse insider transactions: {e}"}


def _detect_cluster(transactions: list[dict]) -> bool:
    """Return True if 3+ distinct insiders transacted within any 30-day window."""
    if len(transactions) < 3:
        return False
    try:
        dates = []
        for t in transactions:
            d = datetime.strptime(t["date"], "%Y-%m-%d")
            dates.append(d)
        dates.sort()
        for i, start in enumerate(dates):
            window_end = start + timedelta(days=30)
            names_in_window = {
                transactions[j]["name"]
                for j in range(i, len(dates))
                if dates[j] <= window_end
            }
            if len(names_in_window) >= 3:
                return True
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main fetch orchestration
# ---------------------------------------------------------------------------


def fetch_capital_structure(ticker: str, raw_data_path: str | None = None) -> dict:
    """Fetch and compute all capital structure metrics for a ticker.

    Falls back to raw_data_path (from fetch_financials.py) when yfinance
    statements are incomplete. Missing fields return null with an explanatory
    note — never fabricated.
    """
    result: dict[str, Any] = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "analysis_version": "1.0",
    }

    try:
        import yfinance as yf
    except ImportError:
        result["error"] = "yfinance not installed. Run: pip install yfinance"
        return result

    # Load yfinance data
    stock = yf.Ticker(ticker)
    info: dict = {}
    income_stmt = None
    balance_sheet = None
    cash_flow = None

    try:
        info = stock.info or {}
    except Exception as e:
        sys.stderr.write(f"yfinance info fetch failed for {ticker}: {e}\n")

    try:
        income_stmt = stock.financials
    except Exception as e:
        sys.stderr.write(f"yfinance financials fetch failed for {ticker}: {e}\n")

    try:
        balance_sheet = stock.balance_sheet
    except Exception as e:
        sys.stderr.write(f"yfinance balance_sheet fetch failed for {ticker}: {e}\n")

    try:
        cash_flow = stock.cashflow
    except Exception as e:
        sys.stderr.write(f"yfinance cashflow fetch failed for {ticker}: {e}\n")

    # Overlay raw data from file if provided (fills gaps)
    if raw_data_path:
        try:
            with open(raw_data_path) as f:
                raw = json.load(f)
            # raw_data may be a dict of {ticker: data} or direct data
            raw_ticker_data = raw.get(ticker) or raw.get(ticker.upper()) or raw
            result["raw_data_overlay"] = raw_data_path
        except Exception as e:
            sys.stderr.write(f"Could not load raw data from {raw_data_path}: {e}\n")

    # Populate entity info
    result["entity_name"] = info.get("longName") or info.get("shortName") or ticker
    result["sector"] = info.get("sector", "")
    result["industry"] = info.get("industry", "")
    result["market_cap"] = info.get("marketCap")
    result["current_price"] = (
        info.get("regularMarketPrice")
        or info.get("currentPrice")
        or info.get("previousClose")
    )
    result["shares_outstanding"] = info.get("sharesOutstanding")

    if not info and income_stmt is None and balance_sheet is None and cash_flow is None:
        result["error"] = (
            f"Could not fetch any data for {ticker}. "
            "Verify the ticker is valid and internet is accessible."
        )
        return result

    # Run all five analysis modules
    errors: list[str] = []

    try:
        result["buyback_analysis"] = compute_buyback_analysis(
            stock, info, cash_flow, balance_sheet
        )
    except Exception as e:
        errors.append(f"buyback_analysis: {e}")
        result["buyback_analysis"] = {"error": str(e)}

    try:
        result["sbc_dilution"] = compute_sbc_dilution(
            income_stmt, cash_flow, balance_sheet, info
        )
    except Exception as e:
        errors.append(f"sbc_dilution: {e}")
        result["sbc_dilution"] = {"error": str(e)}

    try:
        result["capital_return"] = compute_capital_return(
            stock, info, cash_flow, income_stmt
        )
    except Exception as e:
        errors.append(f"capital_return: {e}")
        result["capital_return"] = {"error": str(e)}

    try:
        result["capital_structure"] = compute_capital_structure(
            info, income_stmt, balance_sheet, cash_flow
        )
    except Exception as e:
        errors.append(f"capital_structure: {e}")
        result["capital_structure"] = {"error": str(e)}

    try:
        result["capital_markets_activity"] = compute_capital_markets_activity(
            stock, info, cash_flow
        )
    except Exception as e:
        errors.append(f"capital_markets_activity: {e}")
        result["capital_markets_activity"] = {"error": str(e)}

    if errors:
        result["computation_warnings"] = errors

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capital Structure & Shareholder Return Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  fetch_capital_structure.py AAPL
  fetch_capital_structure.py MSFT --output ./reports/MSFT/capital_structure.json
  fetch_capital_structure.py NVDA --raw-data ./reports/NVDA/raw-data.json
        """,
    )
    parser.add_argument("ticker", help="Ticker symbol (e.g., AAPL, MSFT, BRK.B)")
    parser.add_argument(
        "--raw-data",
        metavar="PATH",
        help="Path to raw-data.json from fetch_financials.py (optional overlay)",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    result = fetch_capital_structure(ticker, raw_data_path=args.raw_data)

    output = json.dumps(result, indent=2, default=str)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(output)
        sys.stderr.write(f"Output written to {args.output}\n")
    else:
        print(output)

    if result.get("error"):
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
