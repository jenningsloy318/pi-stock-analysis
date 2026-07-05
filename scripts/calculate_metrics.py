#!/usr/bin/env python3
"""Compute financial metrics and valuation from raw financial data.

Usage:
    calculate_metrics.py ./reports/AAPL/raw-data.json [--output ./reports/[TICKER]/metrics.json]
    calculate_metrics.py raw-data.json --wacc 0.09 --growth 0.03 --market-cap 3000000000000

Deterministic calculations only. No LLM involvement in math.
Output includes methodology attribution for every calculation.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0 or denominator is None or numerator is None:
        return None
    return numerator / denominator


def extract_values(series: list) -> list[float]:
    """Extract numeric values from a time-series list.

    Handles both formats:
    - List of dicts: [{period: "2024", value: 123}, ...]
    - List of raw numbers: [123, 456, ...]
    """
    if not series:
        return []
    # Handle raw numeric lists
    if isinstance(series[0], (int, float)):
        return [float(v) for v in series if v is not None]
    # Handle dict format
    return [
        float(entry["value"])
        for entry in series
        if isinstance(entry, dict) and entry.get("value") is not None
    ]


def compute_cagr(values: list[float]) -> float | None:
    """Compute CAGR from a list of annual values (most recent first)."""
    if len(values) < 2:
        return None
    start = values[-1]
    end = values[0]
    years = len(values) - 1
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def compute_eva(
    roic: float | None, wacc: float, invested_capital: float | None
) -> dict:
    """Compute Economic Value Added (EVA) and ROIC vs WACC spread."""
    if roic is None or invested_capital is None:
        return {"error": "ROIC and Invested Capital required for EVA."}

    spread = roic - wacc
    eva = spread * invested_capital
    return {
        "methodology": "Economic Value Added (EVA) = (ROIC - WACC) * Invested Capital",
        "roic": round(roic, 4),
        "wacc": wacc,
        "spread": round(spread, 4),
        "invested_capital": round(invested_capital, 2),
        "eva": round(eva, 2),
        "interpretation": "Value-creating (Moat expanding)"
        if spread > 0
        else "Value-destroying (Moat shrinking)",
    }


def generate_mermaid_charts(
    ticker: str, rev_series: list[float], fcf_series: list[float]
) -> dict:
    """Generate Mermaid syntax charts for the markdown reports."""
    charts = {}

    # Ensure we have data and matching lengths, limit to 5 years
    if rev_series and fcf_series:
        min_len = min(len(rev_series), len(fcf_series), 5)
        revs = [round(r, 2) for r in reversed(rev_series[:min_len])]
        fcfs = [round(f, 2) for f in reversed(fcf_series[:min_len])]
        years = [f"Y-{i}" for i in reversed(range(1, min_len))] + ["Current"]

        xy_chart = f'```mermaid\nxychart-beta\n    title "{ticker} Revenue vs FCF"\n    x-axis {json.dumps(years)}\n    y-axis "Value"\n    bar {json.dumps(revs)}\n    line {json.dumps(fcfs)}\n```'
        charts["revenue_fcf_trend"] = xy_chart

    return charts


def compute_dupont(
    net_income: float,
    revenue: float,
    assets: float,
    equity: float,
    ebit: float | None = None,
    ebt: float | None = None,
) -> dict:
    """DuPont 5-factor decomposition of ROE.

    ROE = Tax Burden × Interest Burden × Operating Margin × Asset Turnover × Equity Multiplier
    Where: Tax Burden = NI/EBT, Interest Burden = EBT/EBIT
    Falls back to 3-factor if EBIT/EBT unavailable.
    Handles negative equity (buyback-heavy companies) by flagging and computing ROIC instead.
    """
    net_margin = safe_div(net_income, revenue)
    asset_turnover = safe_div(revenue, assets)

    # Handle negative equity (common for buyback-heavy companies like SBUX, MCD, PM)
    negative_equity = equity is not None and equity <= 0

    if negative_equity:
        equity_multiplier = None
        roe = None
        # Compute ROIC as alternative: NOPAT / Invested Capital
        # Invested Capital ≈ Total Assets - non-interest-bearing current liabilities
        # Simplified: use assets as invested capital proxy
        roic_alternative = (
            safe_div(net_income, assets) if assets and assets > 0 else None
        )
    else:
        equity_multiplier = safe_div(assets, equity)
        roe = safe_div(net_income, equity)
        roic_alternative = None

    result = {
        "roe": round(roe, 4) if roe else None,
        "net_profit_margin": round(net_margin, 4) if net_margin else None,
        "asset_turnover": round(asset_turnover, 4) if asset_turnover else None,
        "equity_multiplier": round(equity_multiplier, 4) if equity_multiplier else None,
        "negative_equity": negative_equity,
        "interpretation": {
            "margin_driven": net_margin is not None and net_margin > 0.15,
            "turnover_driven": asset_turnover is not None and asset_turnover > 1.0,
            "leverage_driven": equity_multiplier is not None
            and equity_multiplier > 3.0,
        },
    }

    if negative_equity:
        result["roic_alternative"] = (
            round(roic_alternative, 4) if roic_alternative else None
        )
        result["negative_equity_note"] = (
            "Negative equity from buybacks — use ROIC instead of ROE"
        )

    if ebit and ebt and ebit != 0 and ebt != 0:
        tax_burden = safe_div(net_income, ebt)
        interest_burden = safe_div(ebt, ebit)
        operating_margin = safe_div(ebit, revenue)
        result["methodology"] = (
            "DuPont 5-Factor: ROE = Tax Burden × Interest Burden × "
            "Op Margin × Turnover × Leverage"
        )
        result["tax_burden"] = round(tax_burden, 4) if tax_burden else None
        result["interest_burden"] = (
            round(interest_burden, 4) if interest_burden else None
        )
        result["operating_margin"] = (
            round(operating_margin, 4) if operating_margin else None
        )
        result["interpretation"]["tax_efficient"] = (
            tax_burden is not None and tax_burden > 0.75
        )
        result["interpretation"]["low_interest_drag"] = (
            interest_burden is not None and interest_burden > 0.85
        )
    else:
        result["methodology"] = (
            "DuPont 3-Factor: ROE = Margin × Turnover × Leverage "
            "(EBIT/EBT unavailable for 5-factor)"
        )

    if negative_equity:
        result["methodology"] += (
            " | NOTE: Equity ≤ 0 — DuPont decomposition not meaningful, ROIC substituted"
        )

    return result


def compute_beneish_mscore(
    dsri: float | None,
    gmi: float | None,
    aqi: float | None,
    sgi: float | None,
    depi: float | None,
    sgai: float | None,
    tata: float | None,
    lvgi: float | None,
) -> dict:
    """Compute Beneish M-Score from 8 financial variables.

    M-Score = -4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
              + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI

    M-Score > -1.78 suggests earnings manipulation probability.
    """
    components = [dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi]
    if any(c is None for c in components):
        return {
            "methodology": "Beneish M-Score (8-variable model). M > -1.78 = manipulation probability.",
            "mscore": None,
            "interpretation": "Insufficient data. Requires 2 consecutive years of financials.",
            "variables": {
                "DSRI": dsri,
                "GMI": gmi,
                "AQI": aqi,
                "SGI": sgi,
                "DEPI": depi,
                "SGAI": sgai,
                "LVGI": lvgi,
                "TATA": tata,
            },
        }

    mscore = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )

    if mscore > -1.78:
        interp = "WARNING: M-Score > -1.78 indicates probable earnings manipulation."
    else:
        interp = "M-Score within normal range. No manipulation signal."

    return {
        "methodology": "Beneish M-Score (8-variable model). M > -1.78 = manipulation probability.",
        "mscore": round(mscore, 4),
        "threshold": -1.78,
        "flag": mscore > -1.78,
        "interpretation": interp,
        "variables": {
            "DSRI": round(dsri, 4),
            "GMI": round(gmi, 4),
            "AQI": round(aqi, 4),
            "SGI": round(sgi, 4),
            "DEPI": round(depi, 4),
            "SGAI": round(sgai, 4),
            "LVGI": round(lvgi, 4),
            "TATA": round(tata, 4),
        },
    }


def compute_beneish_from_financials(years_data: dict) -> dict:
    """Attempt to compute Beneish variables from multi-year financials.

    Implements all 8 variables where data permits. Uses 1.0 (neutral) for
    variables that cannot be computed due to missing data. If fewer than 5
    variables have real data, marks M-Score as INCOMPLETE.
    """
    income = years_data.get("income_statement", {})
    balance = years_data.get("balance_sheet", {})
    cash_flow_data = years_data.get("cash_flow", {})

    rev = extract_values(income.get("revenue", []))
    ni = extract_values(income.get("net_income", []))
    assets = extract_values(balance.get("total_assets", []))
    gross_profit = extract_values(income.get("gross_profit", []))
    receivables = extract_values(balance.get("accounts_receivable", []))
    current_assets = extract_values(balance.get("current_assets", []))
    current_liabilities = extract_values(balance.get("current_liabilities", []))
    total_liabilities = extract_values(balance.get("total_liabilities", []))
    total_debt = extract_values(balance.get("total_debt", []))
    ocf = extract_values(cash_flow_data.get("operating_cash_flow", []))

    if len(rev) < 2 or len(assets) < 2:
        return compute_beneish_mscore(None, None, None, None, None, None, None, None)

    computed_vars: list[str] = []

    # SGI (Sales Growth Index) = Revenue[t] / Revenue[t-1]
    sgi = safe_div(rev[0], rev[1])
    if sgi is not None:
        computed_vars.append("SGI")
    else:
        sgi = 1.0

    # DSRI (Days Sales Receivable Index)
    # = (Receivables_t / Revenue_t) / (Receivables_t-1 / Revenue_t-1)
    dsri = None
    if len(receivables) >= 2 and len(rev) >= 2:
        ratio_t = safe_div(receivables[0], rev[0])
        ratio_t1 = safe_div(receivables[1], rev[1])
        if ratio_t is not None and ratio_t1 is not None:
            dsri = safe_div(ratio_t, ratio_t1)
    if dsri is not None:
        computed_vars.append("DSRI")
    else:
        dsri = 1.0

    # GMI (Gross Margin Index) = GM_t-1 / GM_t (inverted — higher if declining)
    gmi = None
    if len(gross_profit) >= 2 and len(rev) >= 2:
        gm_t = safe_div(gross_profit[0], rev[0])
        gm_t1 = safe_div(gross_profit[1], rev[1])
        if gm_t is not None and gm_t1 is not None and gm_t > 0:
            gmi = gm_t1 / gm_t
    if gmi is not None:
        computed_vars.append("GMI")
    else:
        gmi = 1.0

    # AQI (Asset Quality Index) = 1 - (PPE_t + CA_t) / TA_t
    # Since PPE is not directly available, approximate using:
    # AQI = 1 - (current_assets_t + (TA_t - total_liabilities_t - current_assets_t)) / TA_t
    # Simplified: AQI measures intangible asset growth. Without PPE, use
    # (1 - current_assets / total_assets) as proxy for non-current non-tangible portion
    aqi = None
    if len(current_assets) >= 1 and len(assets) >= 1 and assets[0] > 0:
        # Approximate: assume tangible = current_assets (conservative)
        # AQI_t = 1 - CA_t / TA_t (higher = more intangibles)
        aqi_t = 1.0 - (current_assets[0] / assets[0])
        if len(current_assets) >= 2 and len(assets) >= 2 and assets[1] > 0:
            aqi_t1 = 1.0 - (current_assets[1] / assets[1])
            if aqi_t1 > 0:
                aqi = aqi_t / aqi_t1
                computed_vars.append("AQI")
    if aqi is None:
        aqi = 1.0

    # DEPI (Depreciation Index) — requires depreciation and PPE data
    # Not available in standard fetch_financials output. Use neutral default.
    depi = 1.0

    # SGAI (SGA Expense Index) — SGA not directly available
    # Approximate SGA as: Gross Profit - Operating Income (if both available)
    sgai = None
    operating_income = extract_values(income.get("operating_income", []))
    if len(gross_profit) >= 2 and len(operating_income) >= 2 and len(rev) >= 2:
        sga_t = (
            gross_profit[0] - operating_income[0]
            if gross_profit[0] and operating_income[0]
            else None
        )
        sga_t1 = (
            gross_profit[1] - operating_income[1]
            if gross_profit[1] and operating_income[1]
            else None
        )
        if sga_t is not None and sga_t1 is not None and sga_t >= 0 and sga_t1 >= 0:
            ratio_t = safe_div(sga_t, rev[0])
            ratio_t1 = safe_div(sga_t1, rev[1])
            if ratio_t is not None and ratio_t1 is not None:
                sgai = safe_div(ratio_t, ratio_t1)
    if sgai is not None:
        computed_vars.append("SGAI")
    else:
        sgai = 1.0

    # TATA (Total Accruals to Total Assets) = (NI_t - CFO_t) / TA_t
    tata = None
    if len(ni) >= 1 and len(ocf) >= 1 and len(assets) >= 1 and assets[0] > 0:
        tata = (ni[0] - ocf[0]) / assets[0]
        computed_vars.append("TATA")
    if tata is None:
        tata = 0.0  # Neutral for TATA is 0 (no accruals)

    # LVGI (Leverage Index) = ((LTD_t + CL_t) / TA_t) / ((LTD_t-1 + CL_t-1) / TA_t-1)
    lvgi = None
    if len(assets) >= 2:
        # Use total_debt + current_liabilities, or total_liabilities as fallback
        if len(total_debt) >= 2 and len(current_liabilities) >= 2:
            lev_t = safe_div(total_debt[0] + current_liabilities[0], assets[0])
            lev_t1 = safe_div(total_debt[1] + current_liabilities[1], assets[1])
            if lev_t is not None and lev_t1 is not None:
                lvgi = safe_div(lev_t, lev_t1)
        elif len(total_liabilities) >= 2:
            lev_t = safe_div(total_liabilities[0], assets[0])
            lev_t1 = safe_div(total_liabilities[1], assets[1])
            if lev_t is not None and lev_t1 is not None:
                lvgi = safe_div(lev_t, lev_t1)
    if lvgi is not None:
        computed_vars.append("LVGI")
    else:
        lvgi = 1.0

    # Check completeness — need at least 5 real variables for meaningful M-Score
    result = compute_beneish_mscore(
        dsri=dsri,
        gmi=gmi,
        aqi=aqi,
        sgi=sgi,
        depi=depi,
        sgai=sgai,
        tata=tata,
        lvgi=lvgi,
    )

    # Add metadata about which variables were computed vs defaulted
    result["variables_computed"] = computed_vars
    result["variables_defaulted"] = [
        v
        for v in ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "TATA", "LVGI"]
        if v not in computed_vars
    ]
    result["completeness"] = len(computed_vars)

    if len(computed_vars) < 5:
        result["confidence"] = "INCOMPLETE"
        result["confidence_note"] = (
            f"Only {len(computed_vars)}/8 variables computed from available data. "
            f"M-Score reliability is low. Computed: {', '.join(computed_vars)}."
        )
    else:
        result["confidence"] = "ADEQUATE"
        result["confidence_note"] = (
            f"{len(computed_vars)}/8 variables computed. "
            f"Defaulted (neutral): {', '.join(result['variables_defaulted'])}."
        )

    return result


def compute_altman_zscore(
    working_capital: float | None,
    retained_earnings: float | None,
    ebit: float | None,
    market_cap: float | None,
    total_liabilities: float | None,
    revenue: float | None,
    total_assets: float | None,
) -> dict:
    """Compute Altman Z-Score.

    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
    A = Working Capital / Total Assets
    B = Retained Earnings / Total Assets
    C = EBIT / Total Assets
    D = Market Value of Equity / Total Liabilities
    E = Sales / Total Assets

    Z > 2.99: Safe. 1.81 < Z < 2.99: Grey. Z < 1.81: Distress.
    """
    if total_assets is None or total_assets == 0:
        return {
            "methodology": "Altman Z-Score (5-factor model). Z < 1.81 = distress risk.",
            "zscore": None,
            "interpretation": "Insufficient data (total_assets required).",
        }

    a = safe_div(working_capital, total_assets) or 0
    b = safe_div(retained_earnings, total_assets) or 0
    c = safe_div(ebit, total_assets) or 0
    d = (
        safe_div(market_cap, total_liabilities)
        if market_cap and total_liabilities
        else 0
    )
    e = safe_div(revenue, total_assets) or 0

    zscore = 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e

    if zscore > 2.99:
        zone = "Safe"
        interp = "Low bankruptcy probability."
    elif zscore > 1.81:
        zone = "Grey"
        interp = "Uncertain — warrants closer monitoring."
    else:
        zone = "Distress"
        interp = "WARNING: Elevated bankruptcy probability."

    return {
        "methodology": "Altman Z-Score (5-factor model). Z < 1.81 = distress risk.",
        "zscore": round(zscore, 4),
        "zone": zone,
        "interpretation": interp,
        "components": {
            "A": round(a, 4),
            "B": round(b, 4),
            "C": round(c, 4),
            "D": round(d, 4),
            "E": round(e, 4),
        },
    }


def compute_piotroski_fscore(financials: dict) -> dict:
    """Compute Piotroski F-Score (0-9 binary scoring for financial strength).

    Categories:
      Profitability (4 points): ROA>0, OCF>0, ROA improving, OCF>NI
      Leverage/Liquidity (3 points): Leverage decreasing, Current ratio improving, No dilution
      Operating Efficiency (2 points): Gross margin improving, Asset turnover improving
    """
    income = financials.get("income_statement", {})
    balance = financials.get("balance_sheet", {})
    cashflow = financials.get("cash_flow", {})

    ni_series = extract_values(income.get("net_income", []))
    rev_series = extract_values(income.get("revenue", []))
    assets_series = extract_values(balance.get("total_assets", []))
    equity_series = extract_values(balance.get("stockholders_equity", []))
    debt_series = extract_values(balance.get("total_debt", []))
    ocf_series = extract_values(cashflow.get("operating_cash_flow", []))
    shares_series = extract_values(balance.get("shares_outstanding", []))
    current_assets_series = extract_values(balance.get("current_assets", []))
    current_liabilities_series = extract_values(balance.get("current_liabilities", []))

    score = 0
    details = {}

    # --- Profitability (4 points) ---
    # F1: ROA > 0
    roa_current = (
        safe_div(ni_series[0], assets_series[0])
        if ni_series and assets_series
        else None
    )
    f1 = roa_current is not None and roa_current > 0
    details["f1_positive_roa"] = {"value": roa_current, "pass": f1}
    if f1:
        score += 1

    # F2: OCF > 0
    ocf_current = ocf_series[0] if ocf_series else None
    f2 = ocf_current is not None and ocf_current > 0
    details["f2_positive_ocf"] = {"value": ocf_current, "pass": f2}
    if f2:
        score += 1

    # F3: ROA improving (current > prior year)
    roa_prior = (
        safe_div(ni_series[1], assets_series[1])
        if len(ni_series) > 1 and len(assets_series) > 1
        else None
    )
    f3 = roa_current is not None and roa_prior is not None and roa_current > roa_prior
    details["f3_roa_improving"] = {
        "current": roa_current,
        "prior": roa_prior,
        "pass": f3,
    }
    if f3:
        score += 1

    # F4: OCF > Net Income (accruals quality)
    ni_current = ni_series[0] if ni_series else None
    f4 = ocf_current is not None and ni_current is not None and ocf_current > ni_current
    details["f4_ocf_exceeds_ni"] = {"ocf": ocf_current, "ni": ni_current, "pass": f4}
    if f4:
        score += 1

    # --- Leverage / Liquidity (3 points) ---
    # F5: Leverage decreasing (debt/assets current < prior)
    lev_current = (
        safe_div(debt_series[0], assets_series[0])
        if debt_series and assets_series
        else None
    )
    lev_prior = (
        safe_div(debt_series[1], assets_series[1])
        if len(debt_series) > 1 and len(assets_series) > 1
        else None
    )
    f5 = lev_current is not None and lev_prior is not None and lev_current < lev_prior
    details["f5_leverage_decreasing"] = {
        "current": lev_current,
        "prior": lev_prior,
        "pass": f5,
    }
    if f5:
        score += 1

    # F6: Current ratio improving (current assets / current liabilities)
    cr_current = (
        safe_div(current_assets_series[0], current_liabilities_series[0])
        if current_assets_series and current_liabilities_series
        else None
    )
    cr_prior = (
        safe_div(current_assets_series[1], current_liabilities_series[1])
        if len(current_assets_series) > 1 and len(current_liabilities_series) > 1
        else None
    )
    f6 = cr_current is not None and cr_prior is not None and cr_current > cr_prior
    details["f6_liquidity_improving"] = {
        "current": cr_current,
        "prior": cr_prior,
        "pass": f6,
    }
    if f6:
        score += 1

    # F7: No share dilution (shares outstanding not increasing)
    # When data is unavailable, leave F7 unscored rather than gifting a free point
    f7 = False
    if len(shares_series) >= 2:
        f7 = shares_series[0] <= shares_series[1]
    details["f7_no_dilution"] = {
        "current_shares": shares_series[0] if shares_series else None,
        "pass": f7,
        "data_available": len(shares_series) >= 2,
    }
    if f7:
        score += 1

    # --- Operating Efficiency (2 points) ---
    # F8: Gross margin improving
    gm_current = None
    gm_prior = None
    cogs_series = extract_values(income.get("cost_of_revenue", []))
    if rev_series and cogs_series:
        gm_current = (
            safe_div(rev_series[0] - cogs_series[0], rev_series[0])
            if len(cogs_series) > 0
            else None
        )
        gm_prior = (
            safe_div(rev_series[1] - cogs_series[1], rev_series[1])
            if len(rev_series) > 1 and len(cogs_series) > 1
            else None
        )
    f8 = gm_current is not None and gm_prior is not None and gm_current > gm_prior
    details["f8_gross_margin_improving"] = {
        "current": gm_current,
        "prior": gm_prior,
        "pass": f8,
    }
    if f8:
        score += 1

    # F9: Asset turnover improving (revenue/assets current > prior)
    at_current = (
        safe_div(rev_series[0], assets_series[0])
        if rev_series and assets_series
        else None
    )
    at_prior = (
        safe_div(rev_series[1], assets_series[1])
        if len(rev_series) > 1 and len(assets_series) > 1
        else None
    )
    f9 = at_current is not None and at_prior is not None and at_current > at_prior
    details["f9_asset_turnover_improving"] = {
        "current": at_current,
        "prior": at_prior,
        "pass": f9,
    }
    if f9:
        score += 1

    # Interpretation
    if score >= 8:
        interp = "Strong financial health. High-quality value candidate."
        zone = "Strong"
    elif score >= 5:
        interp = "Average financial health. Mixed signals."
        zone = "Average"
    else:
        interp = "Weak financial health. Potential value trap."
        zone = "Weak"

    return {
        "methodology": "Piotroski F-Score (9-point binary model). >=8 = strong, 5-7 = average, <=4 = weak.",
        "fscore": score,
        "max_score": 9,
        "zone": zone,
        "interpretation": interp,
        "components": {
            "profitability": sum(
                1
                for k in [
                    "f1_positive_roa",
                    "f2_positive_ocf",
                    "f3_roa_improving",
                    "f4_ocf_exceeds_ni",
                ]
                if details[k]["pass"]
            ),
            "leverage_liquidity": sum(
                1
                for k in [
                    "f5_leverage_decreasing",
                    "f6_liquidity_improving",
                    "f7_no_dilution",
                ]
                if details[k]["pass"]
            ),
            "operating_efficiency": sum(
                1
                for k in ["f8_gross_margin_improving", "f9_asset_turnover_improving"]
                if details[k]["pass"]
            ),
        },
        "details": details,
    }


def compute_residual_income_model(
    book_value: float | None,
    roe: float | None,
    cost_of_equity: float,
    growth_rate: float = 0.03,
    years: int = 5,
    shares_outstanding: float | None = None,
) -> dict:
    """Residual Income Model (RIM): Intrinsic Value = Book Value + PV(Excess Returns).

    More appropriate than DCF for financial companies where FCF is meaningless.
    Intrinsic Value = BV + Sum(Residual Income_t / (1+r)^t) + Terminal RI / (r - g)
    Where Residual Income = (ROE - Cost of Equity) × Book Value
    """
    if book_value is None or book_value <= 0 or roe is None:
        return {
            "methodology": "Residual Income Model (RIM)",
            "value": None,
            "error": "Book value and ROE required.",
        }

    if cost_of_equity <= growth_rate:
        return {
            "methodology": "Residual Income Model (RIM)",
            "value": None,
            "error": "Cost of equity must exceed growth rate.",
        }

    excess_return = roe - cost_of_equity
    bv = book_value
    pv_residual_income = 0

    for t in range(1, years + 1):
        residual_income = excess_return * bv
        pv_residual_income += residual_income / ((1 + cost_of_equity) ** t)
        bv = bv * (1 + growth_rate)

    terminal_ri = (excess_return * bv) / (cost_of_equity - growth_rate)
    pv_terminal = terminal_ri / ((1 + cost_of_equity) ** years)

    intrinsic_value = book_value + pv_residual_income + pv_terminal

    result = {
        "methodology": "Residual Income Model: IV = Book Value + PV(Excess Returns). Ideal for financials.",
        "inputs": {
            "book_value": book_value,
            "roe": round(roe, 4),
            "cost_of_equity": cost_of_equity,
            "growth_rate": growth_rate,
            "years": years,
        },
        "intrinsic_value": round(intrinsic_value, 2),
        "book_value_component": round(book_value, 2),
        "pv_excess_returns": round(pv_residual_income, 2),
        "pv_terminal": round(pv_terminal, 2),
        "excess_return_spread": round(excess_return, 4),
        "interpretation": (
            f"ROE ({roe:.1%}) {'exceeds' if excess_return > 0 else 'below'} cost of equity ({cost_of_equity:.1%}). "
            f"{'Value-creating' if excess_return > 0 else 'Value-destroying'} — "
            f"stock {'deserves premium to' if excess_return > 0 else 'should trade at discount to'} book value."
        ),
    }

    if shares_outstanding and shares_outstanding > 0:
        result["per_share_value"] = round(intrinsic_value / shares_outstanding, 2)

    return result


def compute_dividend_discount_model(
    dividend_per_share: float | None,
    dividend_growth_rate: float,
    cost_of_equity: float,
    payout_ratio: float | None = None,
    years_high_growth: int = 5,
    terminal_growth: float = 0.03,
) -> dict:
    """Dividend Discount Model (DDM) — two-stage Gordon Growth.

    For mature dividend-paying companies (utilities, REITs, consumer staples).
    Stage 1: High-growth phase (years_high_growth at dividend_growth_rate)
    Stage 2: Terminal perpetuity at terminal_growth rate
    """
    if dividend_per_share is None or dividend_per_share <= 0:
        return {
            "methodology": "Dividend Discount Model (DDM)",
            "value": None,
            "error": "Positive dividend per share required.",
        }

    if cost_of_equity <= terminal_growth:
        return {
            "methodology": "Dividend Discount Model (DDM)",
            "value": None,
            "error": "Cost of equity must exceed terminal growth rate.",
        }

    # Stage 1: PV of high-growth dividends
    pv_stage1 = 0
    div = dividend_per_share
    for t in range(1, years_high_growth + 1):
        div = div * (1 + dividend_growth_rate)
        pv_stage1 += div / ((1 + cost_of_equity) ** t)

    # Stage 2: Terminal value (Gordon Growth Model)
    terminal_div = div * (1 + terminal_growth)
    terminal_value = terminal_div / (cost_of_equity - terminal_growth)
    pv_terminal = terminal_value / ((1 + cost_of_equity) ** years_high_growth)

    intrinsic_value = pv_stage1 + pv_terminal

    # Sensitivity to growth rate
    sensitivity = {}
    for g in [
        terminal_growth - 0.01,
        terminal_growth,
        terminal_growth + 0.01,
        terminal_growth + 0.02,
    ]:
        if cost_of_equity > g > -0.05:
            tv = div * (1 + g) / (cost_of_equity - g)
            pv_tv = tv / ((1 + cost_of_equity) ** years_high_growth)
            sensitivity[f"tg_{g:.1%}"] = round(pv_stage1 + pv_tv, 2)

    return {
        "methodology": "Two-Stage DDM (Gordon Growth). Ideal for mature dividend payers.",
        "inputs": {
            "dividend_per_share": dividend_per_share,
            "high_growth_rate": round(dividend_growth_rate, 4),
            "terminal_growth": terminal_growth,
            "cost_of_equity": cost_of_equity,
            "years_high_growth": years_high_growth,
            "payout_ratio": payout_ratio,
        },
        "intrinsic_value_per_share": round(intrinsic_value, 2),
        "pv_high_growth_dividends": round(pv_stage1, 2),
        "pv_terminal_value": round(pv_terminal, 2),
        "terminal_pct_of_total": round(pv_terminal / intrinsic_value * 100, 1)
        if intrinsic_value > 0
        else None,
        "dividend_yield_at_iv": round(dividend_per_share / intrinsic_value * 100, 2)
        if intrinsic_value > 0
        else None,
        "sensitivity": sensitivity,
    }


def compute_dcf(
    fcf_current: float,
    growth_rate: float,
    wacc: float,
    terminal_growth: float = 0.025,
    years: int = 5,
    shares_outstanding: float | None = None,
) -> dict:
    """Compute DCF valuation with sensitivity table."""
    if fcf_current <= 0 or wacc <= 0:
        return {
            "methodology": "DCF",
            "dcf_value": None,
            "error": "FCF and WACC must be positive.",
            "note": "Consider using EV/Revenue or milestone-based valuation for pre-profit companies",
        }

    fcf_projections = []
    fcf = fcf_current
    for _ in range(years):
        fcf = fcf * (1 + growth_rate)
        fcf_projections.append(fcf)

    if wacc <= terminal_growth:
        return {
            "methodology": "DCF",
            "dcf_value": None,
            "error": "WACC must exceed terminal growth rate.",
        }

    terminal_value = (
        fcf_projections[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    )

    pv_fcfs = sum(f / ((1 + wacc) ** y) for y, f in enumerate(fcf_projections, 1))
    pv_terminal = terminal_value / ((1 + wacc) ** years)
    enterprise_value = pv_fcfs + pv_terminal

    # Sensitivity table
    wacc_range = [
        w for w in [wacc - 0.02, wacc - 0.01, wacc, wacc + 0.01, wacc + 0.02] if w > 0
    ]
    tg_range = [terminal_growth - 0.01, terminal_growth, terminal_growth + 0.01]
    sensitivity = {}
    for w in wacc_range:
        key = f"WACC_{w:.1%}"
        sensitivity[key] = {}
        for tg in tg_range:
            tg_key = f"TG_{tg:.1%}"
            if tg >= w:
                sensitivity[key][tg_key] = None
                continue
            tv = fcf_projections[-1] * (1 + tg) / (w - tg)
            pv_tv = tv / ((1 + w) ** years)
            pv_f = sum(f_ / ((1 + w) ** y) for y, f_ in enumerate(fcf_projections, 1))
            sensitivity[key][tg_key] = round(pv_f + pv_tv, 2)

    result = {
        "methodology": f"DCF ({years}-year projection, perpetuity growth terminal value)",
        "inputs": {
            "fcf_current": fcf_current,
            "growth_rate": growth_rate,
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "years": years,
        },
        "enterprise_value": round(enterprise_value, 2),
        "pv_of_fcfs": round(pv_fcfs, 2),
        "pv_of_terminal": round(pv_terminal, 2),
        "terminal_pct_of_total": round(pv_terminal / enterprise_value * 100, 1),
        "sensitivity_table": sensitivity,
    }

    if shares_outstanding and shares_outstanding > 0:
        result["per_share_value"] = round(enterprise_value / shares_outstanding, 2)

    # Damodaran-aligned terminal value assessment
    # High TV% is NORMAL for growth companies — flag for transparency, not defect
    tv_pct = result["terminal_pct_of_total"]
    if tv_pct > 85:
        result["tv_sensitivity"] = "HIGH"
        result["tv_note"] = (
            "Terminal value dominates (>85%). This is normal for growth companies "
            "(Damodaran: 'you should not be surprised to see bulk of value in terminal value'). "
            "Key risk: small changes in terminal growth (±1%) create large valuation swings. "
            "Focus on growth-period assumptions and narrative coherence."
        )
        result["confidence"] = "MODERATE"
    elif tv_pct > 75:
        result["tv_sensitivity"] = "MODERATE"
        result["tv_note"] = (
            "Terminal value significant (>75%). Standard for growth companies. "
            "Review sensitivity table for assumption impact."
        )
        result["confidence"] = "STANDARD"
    else:
        result["tv_sensitivity"] = "LOW"
        result["confidence"] = "HIGH"

    return result


def compute_reverse_dcf(
    market_cap: float,
    fcf_current: float,
    wacc: float,
    terminal_growth: float = 0.025,
    years: int = 5,
) -> dict:
    """Reverse DCF: what growth rate is implied by the current market price?"""
    if fcf_current <= 0 or market_cap <= 0 or wacc <= terminal_growth:
        return {"implied_growth": None, "error": "Invalid inputs for reverse DCF."}

    # Binary search for implied growth rate
    low, high = -0.20, 1.0
    for _ in range(50):
        mid = (low + high) / 2
        fcf_projections = []
        fcf = fcf_current
        for _ in range(years):
            fcf = fcf * (1 + mid)
            fcf_projections.append(fcf)
        tv = fcf_projections[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
        ev = sum(f / ((1 + wacc) ** y) for y, f in enumerate(fcf_projections, 1))
        ev += tv / ((1 + wacc) ** years)
        if ev < market_cap:
            low = mid
        else:
            high = mid

    implied = (low + high) / 2
    return {
        "methodology": "Reverse DCF — implied FCF growth rate to justify current market cap.",
        "implied_growth_rate": round(implied, 4),
        "implied_growth_pct": f"{implied:.1%}",
        "interpretation": (
            f"Market is pricing in {implied:.1%} annual FCF growth over {years} years. "
            f"Compare to historical growth and analyst estimates to assess if this is realistic."
        ),
    }


def compute_ratios(
    financials: dict,
    market_cap: float | None = None,
    shares_outstanding: float | None = None,
    profile: dict | None = None,
) -> dict:
    """Compute standard financial ratios from structured financial data."""
    income = financials.get("income_statement", {})
    balance = financials.get("balance_sheet", {})
    cashflow = financials.get("cash_flow", {})

    rev_series = extract_values(income.get("revenue", []))
    ni_series = extract_values(income.get("net_income", []))
    oi_series = extract_values(income.get("operating_income", []))
    assets_series = extract_values(balance.get("total_assets", []))
    equity_series = extract_values(balance.get("stockholders_equity", []))
    debt_series = extract_values(balance.get("total_debt", []))
    cash_series = extract_values(balance.get("cash", []))
    ocf_series = extract_values(cashflow.get("operating_cash_flow", []))
    fcf_series = extract_values(cashflow.get("free_cash_flow", []))
    pretax_series = extract_values(income.get("pretax_income", []))
    tax_series = extract_values(income.get("tax_provision", []))

    # Most recent values
    rev = rev_series[0] if rev_series else None
    ni = ni_series[0] if ni_series else None
    oi = oi_series[0] if oi_series else None
    assets = assets_series[0] if assets_series else None
    equity = equity_series[0] if equity_series else None
    debt = debt_series[0] if debt_series else None
    cash = cash_series[0] if cash_series else None
    ocf = ocf_series[0] if ocf_series else None
    fcf = fcf_series[0] if fcf_series else None

    # Effective tax rate from actual income statement; fall back to 21% if unavailable
    pretax = pretax_series[0] if pretax_series else None
    tax = tax_series[0] if tax_series else None
    if pretax and pretax > 0 and tax is not None:
        effective_tax_rate = max(0.0, min(0.5, tax / pretax))
    else:
        effective_tax_rate = 0.21

    # P/E ratio: from profile if available, else compute from market_cap / NI
    pe_ratio = None
    if profile and profile.get("pe_ratio"):
        pe_ratio = profile["pe_ratio"]
    elif market_cap and ni and ni > 0:
        pe_ratio = market_cap / ni

    # EPS = NI / shares_outstanding
    eps = safe_div(ni, shares_outstanding) if ni and shares_outstanding else None

    # PEG = P/E / (EPS Growth Rate × 100)
    peg_ratio = None
    eps_growth = compute_cagr(ni_series) if ni_series else None
    if profile and profile.get("peg_ratio"):
        peg_ratio = profile["peg_ratio"]
    elif pe_ratio and eps_growth and eps_growth > 0:
        peg_ratio = pe_ratio / (eps_growth * 100)

    # EV/EBITDA: EV = market_cap + net_debt, EBITDA ≈ operating_income + D&A
    # D&A approximated from (OCF - NI) if OCF > NI
    ev = None
    ev_ebitda = None
    if market_cap and debt is not None and cash is not None:
        ev = market_cap + (debt - cash)
    if ev and oi and oi > 0:
        ev_ebitda = safe_div(ev, oi)

    # Greenblatt earnings yield: EBIT / EV (inverse of EV/EBIT)
    earnings_yield = safe_div(oi, ev) if ev and oi else None

    # P/B: Price / Book value per share
    pb_ratio = None
    if market_cap and equity and equity > 0:
        pb_ratio = market_cap / equity

    # P/S: Price / Sales
    ps_ratio = None
    if market_cap and rev and rev > 0:
        ps_ratio = market_cap / rev

    # Gross margin from cost_of_revenue
    cogs_series_r = extract_values(income.get("cost_of_revenue", []))
    gp_series = extract_values(income.get("gross_profit", []))
    gross_margin = None
    if gp_series and rev:
        gross_margin = round(safe_div(gp_series[0], rev), 4)
    elif cogs_series_r and rev:
        gross_margin = round((rev - cogs_series_r[0]) / rev, 4) if rev > 0 else None

    # Margin trajectory (multi-year trend)
    margin_trajectory = None
    if len(rev_series) >= 3 and (len(gp_series) >= 3 or len(cogs_series_r) >= 3):
        gm_history = []
        for i in range(min(len(rev_series), max(len(gp_series), len(cogs_series_r)))):
            r = rev_series[i]
            if r and r > 0:
                if i < len(gp_series) and gp_series[i]:
                    gm_history.append(round(gp_series[i] / r, 4))
                elif i < len(cogs_series_r) and cogs_series_r[i]:
                    gm_history.append(round((r - cogs_series_r[i]) / r, 4))
        if len(gm_history) >= 3:
            recent_avg = (
                sum(gm_history[:2]) / 2 if len(gm_history) >= 2 else gm_history[0]
            )
            older_avg = sum(gm_history[-2:]) / 2
            delta = recent_avg - older_avg
            margin_trajectory = {
                "history": gm_history,
                "trend": "expanding"
                if delta > 0.01
                else "contracting"
                if delta < -0.01
                else "stable",
                "delta_bps": round(delta * 10000),
            }

    ratios = {
        "gross_margin": gross_margin,
        "margin_trajectory": margin_trajectory,
        "operating_margin": round(safe_div(oi, rev), 4) if oi and rev else None,
        "net_margin": round(safe_div(ni, rev), 4) if ni and rev else None,
        "roa": round(safe_div(ni, assets), 4) if ni and assets else None,
        "roe": round(safe_div(ni, equity), 4) if ni and equity else None,
        "roic": round(safe_div(oi * (1 - effective_tax_rate), equity + debt - cash), 4)
        if oi
        and equity
        and debt is not None
        and cash is not None
        and (equity + debt - cash) != 0
        else None,
        "incremental_roic": None,
        "effective_tax_rate": round(effective_tax_rate, 4),
        "debt_to_equity": round(safe_div(debt, equity), 4) if debt and equity else None,
        "current_ratio": (
            round(
                safe_div(
                    extract_values(balance.get("current_assets", []))[0],
                    extract_values(balance.get("current_liabilities", []))[0],
                ),
                4,
            )
            if extract_values(balance.get("current_assets", []))
            and extract_values(balance.get("current_liabilities", []))
            else None
        ),
        "net_debt": round(debt - cash, 2)
        if debt is not None and cash is not None
        else None,
        "fcf_yield": round(safe_div(fcf, market_cap), 4)
        if fcf and market_cap
        else None,
        "ocf_to_ni": round(safe_div(ocf, ni), 4) if ocf and ni else None,
        "revenue_cagr_5yr": round(rc, 4)
        if (rc := compute_cagr(rev_series)) is not None
        else None,
        "ni_cagr_5yr": round(nc, 4)
        if (nc := compute_cagr(ni_series)) is not None
        else None,
        "fcf_cagr_5yr": round(fc, 4)
        if (fc := compute_cagr(fcf_series)) is not None
        else None,
        # Valuation multiples
        "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
        "peg_ratio": round(peg_ratio, 4) if peg_ratio else None,
        "eps": round(eps, 2) if eps else None,
        "ev": round(ev, 2) if ev else None,
        "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda else None,
        "earnings_yield": round(earnings_yield, 4) if earnings_yield else None,
        "pb_ratio": round(pb_ratio, 4) if pb_ratio else None,
        "ps_ratio": round(ps_ratio, 4) if ps_ratio else None,
        "eps_growth": round(eps_growth, 4) if eps_growth else None,
        "methodology": {
            "pe": "P/E = Market Cap / Net Income (or from profile if available)",
            "peg": "PEG = P/E / (EPS Growth × 100). Lynch: <1 attractive, 1-2 fair, >2 expensive.",
            "ev_ebitda": "EV/EBITDA ≈ (Market Cap + Net Debt) / Operating Income",
            "earnings_yield": "EBIT / EV (Greenblatt Magic Formula). >10% attractive, compare to sector median.",
            "pb": "P/B = Market Cap / Stockholders Equity",
            "ps": "P/S = Market Cap / Revenue",
        },
    }

    # Cash Conversion Cycle (DIO + DSO - DPO)
    inv_series = extract_values(balance.get("inventory", []))
    ar_series = extract_values(balance.get("accounts_receivable", []))
    ap_series = extract_values(balance.get("accounts_payable", []))
    cogs_series = extract_values(income.get("cost_of_revenue", []))
    inv_val = inv_series[0] if inv_series else None
    ar_val = ar_series[0] if ar_series else None
    ap_val = ap_series[0] if ap_series else None
    cogs_val = cogs_series[0] if cogs_series else None

    if cogs_val and cogs_val > 0:
        dio = round((inv_val / cogs_val) * 365, 1) if inv_val else None
        dpo = round((ap_val / cogs_val) * 365, 1) if ap_val else None
    else:
        dio = None
        dpo = None
    dso = round((ar_val / rev) * 365, 1) if ar_val and rev and rev > 0 else None

    ccc = None
    if dio is not None and dso is not None and dpo is not None:
        ccc = round(dio + dso - dpo, 1)

    ratios["cash_conversion_cycle"] = {
        "dio_days": dio,
        "dso_days": dso,
        "dpo_days": dpo,
        "ccc_days": ccc,
        "interpretation": (
            "Negative CCC = company gets paid before paying suppliers (capital efficient)"
            if ccc is not None and ccc < 0
            else "Lower CCC = faster cash conversion (more efficient working capital)"
            if ccc is not None
            else "Insufficient data for CCC computation"
        ),
    }

    # Current ratio from balance sheet
    ca_vals_r = extract_values(balance.get("current_assets", []))
    cl_vals_r = extract_values(balance.get("current_liabilities", []))
    if ca_vals_r and cl_vals_r and cl_vals_r[0] and cl_vals_r[0] > 0:
        ratios["current_ratio"] = round(ca_vals_r[0] / cl_vals_r[0], 4)

    # Incremental ROIC: Δ NOPAT / Δ Invested Capital (year-over-year)
    if (
        len(oi_series) >= 2
        and len(equity_series) >= 2
        and len(debt_series) >= 2
        and len(cash_series) >= 2
    ):
        nopat_curr = oi_series[0] * (1 - effective_tax_rate) if oi_series[0] else None
        nopat_prior = oi_series[1] * (1 - effective_tax_rate) if oi_series[1] else None
        ic_curr = (
            (equity_series[0] or 0) + (debt_series[0] or 0) - (cash_series[0] or 0)
        )
        ic_prior = (
            (equity_series[1] or 0) + (debt_series[1] or 0) - (cash_series[1] or 0)
        )
        delta_ic = ic_curr - ic_prior
        if (
            nopat_curr is not None
            and nopat_prior is not None
            and delta_ic
            and abs(delta_ic) > 0
        ):
            ratios["incremental_roic"] = round((nopat_curr - nopat_prior) / delta_ic, 4)

    # DuPont
    if ni and rev and assets and equity:
        ebt_series = extract_values(income.get("pretax_income", []))
        ebt = ebt_series[0] if ebt_series else None
        ratios["dupont"] = compute_dupont(ni, rev, assets, equity, ebit=oi, ebt=ebt)

    return ratios


def compute_peer_comparison(ticker_data: dict, peer_data: dict) -> dict:
    """Compare this ticker's key multiples against a peer set.

    peer_data should be {ticker: {...ratios...}, ...} from compute_ratios output.
    Note: No GICS validation is performed here by design — peers are pre-selected
    by the upstream agent (fetch_peer_universe.py) which handles GICS matching.
    """
    own = ticker_data.get("ratios", {})
    peers = {t: p.get("ratios", {}) for t, p in peer_data.items()}

    # Metrics where lower values are better (cheaper valuation, less leverage)
    lower_is_better = {
        "pe_ratio",
        "ev_ebitda",
        "price_to_book",
        "debt_to_equity",
        "pb_ratio",
        "ps_ratio",
    }

    comparison = {}
    for metric in [
        "pe_ratio",
        "peg_ratio",
        "ev_ebitda",
        "pb_ratio",
        "ps_ratio",
        "operating_margin",
        "net_margin",
        "roe",
        "roic",
        "fcf_yield",
        "debt_to_equity",
        "revenue_cagr_5yr",
        "ni_cagr_5yr",
    ]:
        own_val = own.get(metric)
        peer_vals = [p.get(metric) for p in peers.values() if p.get(metric) is not None]
        if own_val is None or not peer_vals:
            comparison[metric] = {
                "value": own_val,
                "peer_median": None,
                "peer_mean": None,
                "peer_count": len(peer_vals),
                "percentile": None,
            }
            continue

        peer_mean = sum(peer_vals) / len(peer_vals)
        peer_sorted = sorted(peer_vals)
        peer_median = peer_sorted[len(peer_sorted) // 2]
        below = sum(1 for v in peer_vals if v <= own_val)
        percentile = round(below / len(peer_vals) * 100, 1)

        # For lower-is-better metrics, flip interpretation
        if metric in lower_is_better:
            interpretation = (
                f"Cheaper than {100 - percentile}% of peers"
                if percentile < 50
                else f"More expensive than {percentile}% of peers"
            )
        else:
            interpretation = (
                f"Higher than {percentile}% of peers"
                if percentile > 50
                else f"Lower than {100 - percentile}% of peers"
            )

        comparison[metric] = {
            "value": own_val,
            "peer_median": round(peer_median, 4),
            "peer_mean": round(peer_mean, 4),
            "peer_min": round(min(peer_vals), 4),
            "peer_max": round(max(peer_vals), 4),
            "peer_count": len(peer_vals),
            "percentile": percentile,
            "lower_is_better": metric in lower_is_better,
            "interpretation": interpretation,
        }

    return {
        "methodology": "Peer comparison against tickers in peer data file",
        "tickers_compared": [ticker_data.get("ticker", "")] + list(peers.keys()),
        "comparison": comparison,
        "note": "Percentile interpretation: if value=30 and percentile=80, the company is more expensive (or has higher margins) than 80% of peers. Direction depends on metric context.",
    }


# ---------------------------------------------------------------------------
# Monte Carlo simulation for valuation (10K runs)
# ---------------------------------------------------------------------------


def compute_monte_carlo(
    fcf_current: float,
    growth_mu: float,
    growth_sigma: float,
    wacc: float,
    terminal_growth: float = 0.025,
    years: int = 5,
    shares_outstanding: float | None = None,
    simulations: int = 10000,
    seed: int = 42,
) -> dict:
    """Run Monte Carlo simulation for DCF valuation.

    Args:
        fcf_current: Current free cash flow
        growth_mu: Mean annual growth rate (from forecast.py ensemble)
        growth_sigma: Standard deviation of growth rate (from forecast residuals)
        wacc: Weighted average cost of capital
        terminal_growth: Terminal perpetuity growth rate
        years: Projection years
        shares_outstanding: For per-share value
        simulations: Number of Monte Carlo runs (default 10,000)
        seed: Random seed for reproducibility

    Returns distribution of enterprise values with confidence intervals.
    """
    import math

    if fcf_current <= 0 or wacc <= 0 or wacc <= terminal_growth:
        return {"methodology": "Monte Carlo DCF", "error": "Invalid inputs"}

    numpy = __import__("numpy")
    rng = numpy.random.default_rng(seed)

    ev_results = []
    per_share_results = []

    for _ in range(simulations):
        try:
            # Draw growth rate from log-normal (positive mu) or normal (negative mu)
            if growth_mu > 0:
                sigma_log = max(0.01, growth_sigma / max(growth_mu, 0.01))
                sigma_log = min(sigma_log, 2.0)
                growth = rng.lognormal(
                    mean=math.log(max(growth_mu, 0.001)) - sigma_log**2 / 2,
                    sigma=sigma_log,
                )
                growth = max(-0.50, min(2.0, growth))
            else:
                # Negative or zero growth: use normal distribution allowing negative draws
                growth = rng.normal(growth_mu, max(growth_sigma, 0.01))
                growth = max(-0.50, min(0.50, growth))

            # Project FCF with annual variation
            fcf_projections = []
            fcf = fcf_current
            for _ in range(years):
                annual_growth = rng.normal(growth, max(growth_sigma * 0.7, 0.01))
                annual_growth = max(-0.30, min(1.0, annual_growth))
                fcf = fcf * (1 + annual_growth)
                fcf_projections.append(
                    fcf
                )  # Allow negative FCF (realistic for capex-heavy companies)

            # WACC variation
            wacc_varied = max(
                wacc * 0.85, min(wacc * 1.15, rng.normal(wacc, wacc * 0.15))
            )
            if wacc_varied <= terminal_growth:
                wacc_varied = terminal_growth + 0.01

            # Terminal value: skip if final-year FCF is negative (no perpetuity on losses)
            final_fcf = fcf_projections[-1]
            if final_fcf > 0:
                terminal_value = (
                    final_fcf * (1 + terminal_growth) / (wacc_varied - terminal_growth)
                )
            else:
                terminal_value = 0  # No terminal value for negative FCF trajectories

            pv_fcfs = sum(
                f / ((1 + wacc_varied) ** y) for y, f in enumerate(fcf_projections, 1)
            )
            pv_terminal = terminal_value / ((1 + wacc_varied) ** years)
            ev = pv_fcfs + pv_terminal

            if ev > 0 and not math.isnan(ev) and not math.isinf(ev):
                ev_results.append(ev)
                if shares_outstanding and shares_outstanding > 0:
                    per_share_results.append(ev / shares_outstanding)
        except Exception:
            continue

    if not ev_results:
        return {"methodology": "Monte Carlo DCF", "error": "All simulations failed"}

    ev_sorted = sorted(ev_results)
    n = len(ev_sorted)

    percentiles = {}
    for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        idx = int(n * pct / 100)
        percentiles[f"p{pct}"] = round(ev_sorted[min(idx, n - 1)], 2)

    mean_ev = sum(ev_results) / n
    std_ev = (sum((x - mean_ev) ** 2 for x in ev_results) / n) ** 0.5

    var_95 = percentiles.get("p5", 0)
    cvar_95_entries = [x for x in ev_results if x <= var_95]
    cvar_95 = sum(cvar_95_entries) / len(cvar_95_entries) if cvar_95_entries else var_95

    result = {
        "methodology": f"Monte Carlo DCF ({n} simulations, {years}-year projection)",
        "simulations_run": n,
        "simulations_planned": simulations,
        "inputs": {
            "fcf_current": fcf_current,
            "growth_mu": round(growth_mu, 4),
            "growth_sigma": round(growth_sigma, 4),
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "years": years,
        },
        "enterprise_value": {
            "mean": round(mean_ev, 2),
            "median": round(percentiles["p50"], 2),
            "std_dev": round(std_ev, 2),
            "p10_p90_range": [percentiles["p10"], percentiles["p90"]],
            "p5_p95_range": [percentiles["p5"], percentiles["p95"]],
            "percentiles": percentiles,
        },
        "risk_metrics": {
            "var_95": round(var_95, 2),
            "cvar_95": round(cvar_95, 2),
            "probability_above_mean": round(
                sum(1 for x in ev_results if x > mean_ev) / n, 3
            ),
        },
    }

    if shares_outstanding and shares_outstanding > 0:
        ps_sorted = sorted(per_share_results)
        pn = len(ps_sorted)
        ps_pct = {}
        for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
            idx = int(pn * pct / 100)
            ps_pct[f"p{pct}"] = round(ps_sorted[min(idx, pn - 1)], 2)
        result["per_share_value"] = {
            "mean": round(sum(per_share_results) / pn, 2),
            "median": round(ps_pct["p50"], 2),
            "percentiles": ps_pct,
        }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compute financial metrics from raw data"
    )
    parser.add_argument("input", help="Path to raw financial data JSON")
    parser.add_argument("--wacc", type=float, default=0.10, help="WACC (default: 0.10)")
    parser.add_argument(
        "--growth", type=float, default=0.05, help="FCF growth rate (default: 0.05)"
    )
    parser.add_argument(
        "--terminal-growth",
        type=float,
        default=0.025,
        help="Terminal growth rate (default: 0.025)",
    )
    parser.add_argument(
        "--market-cap",
        type=float,
        help="Market cap for valuation multiples, reverse DCF, and FCF yield",
    )
    parser.add_argument(
        "--shares", type=float, help="Shares outstanding for per-share DCF and EPS"
    )
    parser.add_argument(
        "--peers",
        help="Path to peer financial data JSON (same format as input, for relative valuation comparison)",
    )
    parser.add_argument(
        "--monte-carlo",
        action="store_true",
        help="Run Monte Carlo simulation (10K runs)",
    )
    parser.add_argument(
        "--mc-growth-mu", type=float, default=0.05, help="Monte Carlo mean growth rate"
    )
    parser.add_argument(
        "--mc-growth-sigma",
        type=float,
        default=0.08,
        help="Monte Carlo growth rate std dev",
    )
    parser.add_argument(
        "--mc-simulations", type=int, default=10000, help="Monte Carlo simulation count"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--macro",
        help="Path to macro.json for dynamic WACC estimation (reads DGS10 for risk-free rate)",
    )
    parser.add_argument(
        "--beta", type=float, help="Company beta for CAPM WACC estimation"
    )
    args = parser.parse_args()

    # Dynamic WACC estimation from macro data + beta
    if args.macro and args.wacc == 0.10:
        try:
            with open(args.macro) as mf:
                macro_data = json.load(mf)
            indicators = macro_data.get("indicators", {})
            dgs10 = indicators.get("DGS10", {}).get("latest_value")
            if dgs10 is not None:
                risk_free = float(dgs10) / 100.0
                erp = 0.055  # Long-run equity risk premium (~5.5%)
                beta = args.beta if args.beta else 1.0
                cost_of_equity = risk_free + beta * erp
                args.wacc = round(cost_of_equity, 4)
                sys.stderr.write(
                    f"Dynamic WACC: Rf={risk_free:.2%} + β({beta:.2f})×ERP({erp:.1%}) = {args.wacc:.2%}\n"
                )
        except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
            pass

    with open(args.input) as f:
        raw_data = json.load(f)

    ticker = list(raw_data.keys())[0] if raw_data else "UNKNOWN"
    data = raw_data.get(ticker, {})
    financials = data.get("financials", {})
    profile = data.get("profile", {})

    # Extract latest FCF
    fcf_entries = financials.get("cash_flow", {}).get("free_cash_flow", [])
    fcf_values = extract_values(fcf_entries) if isinstance(fcf_entries, list) else []
    fcf = fcf_values[0] if fcf_values else 0

    # Extract balance sheet values for Altman Z
    assets_entries = financials.get("balance_sheet", {}).get("total_assets", [])
    liab_entries = financials.get("balance_sheet", {}).get("total_liabilities", [])
    equity_entries = financials.get("balance_sheet", {}).get("stockholders_equity", [])
    rev_entries = financials.get("income_statement", {}).get("revenue", [])
    oi_entries = financials.get("income_statement", {}).get("operating_income", [])

    assets_vals = (
        extract_values(assets_entries) if isinstance(assets_entries, list) else []
    )
    liab_vals = extract_values(liab_entries) if isinstance(liab_entries, list) else []
    equity_vals = (
        extract_values(equity_entries) if isinstance(equity_entries, list) else []
    )
    rev_vals = extract_values(rev_entries) if isinstance(rev_entries, list) else []
    oi_vals = extract_values(oi_entries) if isinstance(oi_entries, list) else []

    total_assets = assets_vals[0] if assets_vals else None
    total_liabilities = liab_vals[0] if liab_vals else None
    equity = equity_vals[0] if equity_vals else None
    revenue = rev_vals[0] if rev_vals else None
    ebit = oi_vals[0] if oi_vals else None

    # Working capital: prefer current_assets - current_liabilities over total approximation
    ca_entries = financials.get("balance_sheet", {}).get("current_assets", [])
    cl_entries = financials.get("balance_sheet", {}).get("current_liabilities", [])
    re_entries = financials.get("balance_sheet", {}).get("retained_earnings", [])
    ca_vals = extract_values(ca_entries) if isinstance(ca_entries, list) else []
    cl_vals = extract_values(cl_entries) if isinstance(cl_entries, list) else []
    re_vals = extract_values(re_entries) if isinstance(re_entries, list) else []

    if ca_vals and cl_vals:
        working_capital = ca_vals[0] - cl_vals[0]
    elif total_assets and total_liabilities:
        working_capital = total_assets - total_liabilities
    else:
        working_capital = None

    retained_earnings = re_vals[0] if re_vals else None

    # Shares outstanding: from profile if not given
    shares = args.shares
    if shares is None and profile:
        shares = profile.get("shares_outstanding")

    metrics = {
        "ticker": ticker,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "input_data_source": data.get("source", "unknown"),
        "input_data_retrieved": data.get("retrieved_at", "unknown"),
        "ratios": compute_ratios(financials, args.market_cap, shares, profile),
        "piotroski_fscore": compute_piotroski_fscore(financials),
        "beneish_mscore": compute_beneish_from_financials(financials),
        "altman_zscore": compute_altman_zscore(
            working_capital=working_capital,
            retained_earnings=retained_earnings,
            ebit=ebit,
            market_cap=args.market_cap,
            total_liabilities=total_liabilities,
            revenue=revenue,
            total_assets=total_assets,
        ),
        "dcf_valuation": compute_dcf(
            fcf_current=fcf,
            growth_rate=args.growth,
            wacc=args.wacc,
            terminal_growth=args.terminal_growth,
            shares_outstanding=shares,
        )
        if fcf > 0
        else {
            "methodology": "DCF",
            "dcf_value": None,
            "error": "FCF <= 0, cannot run DCF.",
        },
    }

    # Add EVA
    debt_entries = financials.get("balance_sheet", {}).get("total_debt", [])
    cash_entries = financials.get("balance_sheet", {}).get("cash", [])
    debt_vals = extract_values(debt_entries) if isinstance(debt_entries, list) else []
    cash_vals = extract_values(cash_entries) if isinstance(cash_entries, list) else []
    debt = debt_vals[0] if debt_vals else None
    cash = cash_vals[0] if cash_vals else None
    roic_val = metrics["ratios"].get("roic")
    invested_capital = (
        (equity + debt - cash)
        if equity is not None and debt is not None and cash is not None
        else None
    )
    metrics["economic_value_added"] = compute_eva(roic_val, args.wacc, invested_capital)

    # Add Mermaid charts
    rev_entries = financials.get("income_statement", {}).get("revenue", [])
    fcf_entries = financials.get("cash_flow", {}).get("free_cash_flow", [])
    rev_vals = extract_values(rev_entries) if isinstance(rev_entries, list) else []
    fcf_vals = extract_values(fcf_entries) if isinstance(fcf_entries, list) else []
    metrics["visualizations"] = generate_mermaid_charts(ticker, rev_vals, fcf_vals)

    if args.market_cap and fcf > 0:
        metrics["reverse_dcf"] = compute_reverse_dcf(
            market_cap=args.market_cap,
            fcf_current=fcf,
            wacc=args.wacc,
            terminal_growth=args.terminal_growth,
        )

    # Residual Income Model (ideal for financials where FCF is meaningless)
    ni_entries = financials.get("income_statement", {}).get("net_income", [])
    ni_vals = extract_values(ni_entries) if isinstance(ni_entries, list) else []
    roe_val = (
        safe_div(ni_vals[0], equity) if ni_vals and equity and equity > 0 else None
    )
    if equity and equity > 0 and roe_val is not None:
        metrics["residual_income_model"] = compute_residual_income_model(
            book_value=equity,
            roe=roe_val,
            cost_of_equity=args.wacc,
            growth_rate=args.terminal_growth,
            shares_outstanding=shares,
        )

    # Dividend Discount Model (for dividend-paying companies)
    div_per_share = profile.get("dividend_per_share") or profile.get("dividendPerShare")
    if div_per_share and div_per_share > 0:
        div_growth = profile.get("dividend_growth_rate", 0.05)
        payout = (
            safe_div(div_per_share * shares, ni_vals[0]) if ni_vals and shares else None
        )
        metrics["dividend_discount_model"] = compute_dividend_discount_model(
            dividend_per_share=div_per_share,
            dividend_growth_rate=div_growth,
            cost_of_equity=args.wacc,
            payout_ratio=payout,
            terminal_growth=args.terminal_growth,
        )

    # Monte Carlo simulation
    if args.monte_carlo and fcf > 0:
        metrics["monte_carlo"] = compute_monte_carlo(
            fcf_current=fcf,
            growth_mu=args.mc_growth_mu,
            growth_sigma=args.mc_growth_sigma,
            wacc=args.wacc,
            terminal_growth=args.terminal_growth,
            shares_outstanding=shares,
            simulations=args.mc_simulations,
        )

    # Peer comparison
    if args.peers:
        try:
            with open(args.peers) as f:
                peer_raw = json.load(f)
            # Compute ratios for each peer using same parameters
            peer_metrics = {}
            for pticker, pdata in peer_raw.items():
                pfinancials = pdata.get("financials", {})
                pprofile = pdata.get("profile", {})
                peerv = compute_ratios(pfinancials, None, None, pprofile)
                peer_metrics[pticker] = {"ratios": peerv}
            metrics["peer_comparison"] = compute_peer_comparison(
                {"ticker": ticker, "ratios": metrics["ratios"]},
                peer_metrics,
            )
        except Exception as e:
            metrics["peer_comparison"] = {"error": str(e)}

    output = json.dumps(metrics, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
