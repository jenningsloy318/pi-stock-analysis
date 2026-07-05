#!/usr/bin/env python3
"""ESG Carbon Intensity & Climate Risk Analysis.

Usage:
    fetch_esg_carbon.py XOM
    fetch_esg_carbon.py XOM --sector 10
    fetch_esg_carbon.py XOM --sector 10 --output ./reports/XOM/esg_carbon.json
    fetch_esg_carbon.py AAPL --sector 45 --output ./reports/AAPL/esg_carbon.json
    fetch_esg_carbon.py NEE --sector 55 --output ./reports/NEE/esg_carbon.json

Computes:
  1. Carbon intensity assessment (Scope 1+2 estimates from sector averages)
  2. Carbon pricing scenario model (EBITDA impact at $50/$100/$150/$200 per tCO2)
  3. Stranded asset risk (Energy/Materials only)
  4. Transition risk score (0-100)
  5. ESG materiality score (0-100 across 5 components)

IMPORTANT: Company-level Scope 1/2 emissions require paid databases (CDP, MSCI,
Sustainalytics). This script provides sector-average estimates and clearly flags
all estimated values. The analyst should supplement with web research for company-
specific verified ESG disclosures.

Data sources:
  - yfinance: sector, industry, market cap, EBITDA, revenue, country, governance
  - Sector emission intensity benchmarks (IEA, CDP, MSCI ESG sector averages)
  - GICS sector heuristics for climate risk and governance scoring

Analytical frameworks:
  - TCFD (Task Force on Climate-related Financial Disclosures) scenario structure
  - IEA Net Zero by 2050 carbon price pathway ($50-$200 anchors)
  - SASB sector materiality mapping
  - Carbon Tracker Initiative stranded asset model
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    import numpy as np  # noqa: F401 — available for downstream callers
except ImportError:
    sys.stderr.write("Warning: 'numpy' not installed. Run: pip install numpy\n")


# ---------------------------------------------------------------------------
# Sector emission intensity benchmarks
# tCO2e per $M revenue — midpoint of published sector ranges
# Sources: CDP Global Supply Chain Report, IEA sectoral data, MSCI ESG Research
# ---------------------------------------------------------------------------

# GICS sector code (int) → (label, low_tco2e_per_mrev, high_tco2e_per_mrev)
SECTOR_EMISSION_BENCHMARKS: dict[int, tuple[str, float, float]] = {
    10: ("Energy", 400.0, 1200.0),
    15: ("Materials", 200.0, 800.0),
    20: ("Industrials", 50.0, 200.0),
    25: ("Consumer Discretionary", 15.0, 60.0),
    30: ("Consumer Staples", 20.0, 70.0),
    35: ("Health Care", 10.0, 50.0),
    40: ("Financials", 3.0, 15.0),
    45: ("Information Technology", 5.0, 30.0),
    50: ("Communication Services", 5.0, 25.0),
    55: ("Utilities", 300.0, 900.0),
    60: ("Real Estate", 20.0, 80.0),
}

# Transportation sub-industries within Industrials (20) — higher intensity
TRANSPORTATION_INDUSTRIES: frozenset[str] = frozenset(
    {
        "airlines",
        "trucking",
        "marine",
        "air freight",
        "railroads",
        "transportation infrastructure",
    }
)

# Sectors where carbon pricing scenario modelling is material
CARBON_INTENSIVE_SECTORS: frozenset[int] = frozenset({10, 15, 20, 55})

# Sectors where stranded asset analysis applies
STRANDED_ASSET_SECTORS: frozenset[int] = frozenset({10, 15})

# IEA NZE 2050 carbon price scenario anchors (USD/tCO2)
CARBON_PRICE_SCENARIOS: list[int] = [50, 100, 150, 200]

# Country-level physical risk multipliers (IPCC AR6 / ND-GAIN index proxy)
COUNTRY_PHYSICAL_RISK: dict[str, float] = {
    "United States": 0.65,
    "US": 0.65,
    "China": 0.80,
    "India": 0.85,
    "Bangladesh": 0.95,
    "Philippines": 0.90,
    "Vietnam": 0.88,
    "Indonesia": 0.87,
    "Brazil": 0.75,
    "Australia": 0.72,
    "Canada": 0.55,
    "Germany": 0.50,
    "France": 0.50,
    "United Kingdom": 0.52,
    "Japan": 0.70,
    "South Korea": 0.65,
    "Netherlands": 0.60,
    "Singapore": 0.68,
}
DEFAULT_COUNTRY_PHYSICAL_RISK: float = 0.60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Convert a value to float, returning default on failure."""
    if value is None:
        return default
    try:
        result = float(value)
        return result if result == result else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pct(val: float | None) -> float | None:
    return round(val * 100, 2) if val is not None else None


# ---------------------------------------------------------------------------
# yfinance DataFrame helpers
# ---------------------------------------------------------------------------


def _df_row(df: Any, field: str) -> list[dict]:
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


def _try_fields(df: Any, *fields: str) -> list[dict]:
    """Return first non-empty row from candidate field names."""
    for f in fields:
        result = _df_row(df, f)
        if result:
            return result
    return []


def _latest_val(series: list[dict]) -> float | None:
    for entry in series:
        if entry.get("value") is not None:
            return entry["value"]
    return None


# ---------------------------------------------------------------------------
# Sector resolution
# ---------------------------------------------------------------------------


def resolve_gics_sector(gics_arg: int | None, info: dict) -> int | None:
    """Resolve GICS sector code from CLI arg or yfinance sector string."""
    if gics_arg is not None:
        return gics_arg
    sector_map: dict[str, int] = {
        "Energy": 10,
        "Basic Materials": 15,
        "Materials": 15,
        "Industrials": 20,
        "Consumer Cyclical": 25,
        "Consumer Discretionary": 25,
        "Consumer Defensive": 30,
        "Consumer Staples": 30,
        "Healthcare": 35,
        "Health Care": 35,
        "Financial Services": 40,
        "Financials": 40,
        "Technology": 45,
        "Information Technology": 45,
        "Communication Services": 50,
        "Utilities": 55,
        "Real Estate": 60,
    }
    return sector_map.get(info.get("sector", ""))


# ---------------------------------------------------------------------------
# 1. Carbon Intensity Assessment
# ---------------------------------------------------------------------------


def assess_carbon_intensity(
    gics_sector: int | None,
    revenue_usd: float | None,
    industry: str,
) -> dict:
    """Estimate Scope 1+2 carbon intensity relative to GICS sector benchmarks.

    Methodology:
      - Company-level Scope 1+2 data requires paid providers (MSCI, Sustainalytics, CDP).
      - Sector-average tCO2e/$M revenue benchmarks from IEA and CDP industry reports.
      - Estimated annual emissions = revenue_usd * midpoint_intensity / 1,000,000.
      - Intensity classification: High / Medium / Low relative to cross-sector baseline.
      - Source: CDP Global Supply Chain Report, IEA World Energy Outlook sector data.
    """
    if gics_sector not in SECTOR_EMISSION_BENCHMARKS:
        sector_label = "Unknown"
        low_intensity, high_intensity = 30.0, 100.0
    else:
        sector_label, low_intensity, high_intensity = SECTOR_EMISSION_BENCHMARKS[
            gics_sector
        ]

    # Transportation sub-industry override within Industrials
    if gics_sector == 20 and any(
        t in industry.lower() for t in TRANSPORTATION_INDUSTRIES
    ):
        low_intensity, high_intensity = 100.0, 400.0
        sector_label = "Industrials (Transportation)"

    midpoint_intensity = (low_intensity + high_intensity) / 2.0

    estimated_emissions_tco2e: float | None = None
    if revenue_usd is not None and revenue_usd > 0:
        estimated_emissions_tco2e = midpoint_intensity * (revenue_usd / 1_000_000)

    # Cross-sector intensity classification thresholds
    if midpoint_intensity >= 200:
        intensity_classification = "High"
        carbon_risk_tier = "High"
        intensity_score_pts = 5  # high intensity → high materiality risk pts
    elif midpoint_intensity >= 30:
        intensity_classification = "Medium"
        carbon_risk_tier = "Medium"
        intensity_score_pts = 12
    else:
        intensity_classification = "Low"
        carbon_risk_tier = "Low"
        intensity_score_pts = 22  # low intensity → low materiality risk pts

    return {
        "methodology": (
            "Scope 1+2 intensity estimated from GICS sector average benchmarks "
            "(CDP Global Supply Chain Report, IEA sectoral data). "
            "These are SECTOR AVERAGES — not verified company disclosures. "
            "Use CDP, MSCI ESG, or Sustainalytics for company-specific data."
        ),
        "data_quality": "ESTIMATED_SECTOR_AVERAGE",
        "gics_sector": gics_sector,
        "sector_label": sector_label,
        "industry": industry,
        "sector_intensity_range_tco2e_per_mrev": {
            "low": low_intensity,
            "high": high_intensity,
            "midpoint": round(midpoint_intensity, 1),
            "unit": "tCO2e per $M revenue",
        },
        "estimated_scope1_2_intensity_tco2e_per_mrev": round(midpoint_intensity, 1),
        "estimated_absolute_emissions_tco2e": (
            round(estimated_emissions_tco2e)
            if estimated_emissions_tco2e is not None
            else None
        ),
        "intensity_classification": intensity_classification,
        "intensity_score_pts": intensity_score_pts,
        "max_pts": 25,
        "carbon_risk_tier": carbon_risk_tier,
        "note": (
            "Supplement with web search for company sustainability report, "
            "CDP disclosure score, or MSCI ESG rating for verified figures."
        ),
    }


# ---------------------------------------------------------------------------
# 2. Carbon Pricing Scenario Model
# ---------------------------------------------------------------------------


def model_carbon_pricing_scenarios(
    gics_sector: int | None,
    estimated_emissions_tco2e: float | None,
    ebitda_usd: float | None,
) -> dict:
    """Model EBITDA impact across IEA NZE carbon price scenarios ($50–$200/tCO2).

    Methodology (TCFD Scenario Analysis):
      - Applies to carbon-intensive sectors: Energy (10), Materials (15), Industrials (20), Utilities (55).
      - EBITDA_impact_pct = -(carbon_price × estimated_emissions) / EBITDA.
      - Breakeven carbon price = EBITDA / estimated_emissions (price where EBITDA = 0).
      - Sensitivity: EBITDA % erosion per $10 increase in carbon price.
      - Does not model: pass-through pricing, hedging, abatement capex, offsets, phase-in.
    """
    if gics_sector not in CARBON_INTENSIVE_SECTORS:
        return {
            "applicable": False,
            "reason": (
                f"GICS sector {gics_sector} is not carbon-intensive. "
                "Scenario modelling applies to Energy (10), Materials (15), "
                "Industrials (20), and Utilities (55)."
            ),
            "methodology": "N/A — sector not in scope for carbon pricing scenario analysis",
        }

    if estimated_emissions_tco2e is None:
        return {
            "applicable": True,
            "error": "Cannot model: estimated_emissions_tco2e unavailable (revenue missing).",
            "methodology": "EBITDA_impact_pct = -(carbon_price × emissions_tco2e) / EBITDA",
        }

    scenarios: list[dict] = []
    for price in CARBON_PRICE_SCENARIOS:
        carbon_cost = price * estimated_emissions_tco2e
        ebitda_impact_pct: float | None = None
        ebitda_impact_usd: float | None = None
        ebitda_after_carbon: float | None = None

        if ebitda_usd is not None and ebitda_usd != 0:
            ebitda_impact_pct = -carbon_cost / ebitda_usd
            ebitda_impact_usd = -carbon_cost
            ebitda_after_carbon = ebitda_usd + ebitda_impact_usd

        scenarios.append(
            {
                "carbon_price_usd_per_tco2": price,
                "carbon_cost_usd": round(carbon_cost),
                "ebitda_impact_usd": round(ebitda_impact_usd)
                if ebitda_impact_usd is not None
                else None,
                "ebitda_impact_pct": round(ebitda_impact_pct * 100, 1)
                if ebitda_impact_pct is not None
                else None,
                "ebitda_after_carbon_usd": round(ebitda_after_carbon)
                if ebitda_after_carbon is not None
                else None,
                "ebitda_positive_after_carbon": (
                    ebitda_after_carbon > 0 if ebitda_after_carbon is not None else None
                ),
            }
        )

    # Breakeven carbon price (EBITDA → 0)
    breakeven_price: float | None = None
    if ebitda_usd is not None and ebitda_usd > 0 and estimated_emissions_tco2e > 0:
        breakeven_price = ebitda_usd / estimated_emissions_tco2e

    # Sensitivity: EBITDA erosion % per $10 carbon price increase
    sensitivity_per_10_usd: float | None = None
    if ebitda_usd is not None and ebitda_usd != 0:
        sensitivity_per_10_usd = round(
            -(10 * estimated_emissions_tco2e / ebitda_usd) * 100, 2
        )

    # Risk assessment from $100 reference scenario
    ref = next((s for s in scenarios if s["carbon_price_usd_per_tco2"] == 100), None)
    if ref and ref.get("ebitda_impact_pct") is not None:
        impact = ref["ebitda_impact_pct"]
        if breakeven_price is not None and breakeven_price < 100:
            risk_assessment = f"Critical — EBITDA turns negative below $100/tCO2 (breakeven ~${breakeven_price:.0f})"
        elif impact < -50:
            risk_assessment = f"Severe — EBITDA erodes {abs(impact):.0f}% at $100/tCO2. Business model under threat."
        elif impact < -25:
            risk_assessment = f"High — EBITDA erodes {abs(impact):.0f}% at $100/tCO2. Material profitability impact."
        elif impact < -10:
            risk_assessment = f"Moderate — EBITDA erodes {abs(impact):.0f}% at $100/tCO2. Manageable near-term."
        else:
            risk_assessment = f"Low — EBITDA erodes only {abs(impact):.0f}% at $100/tCO2. Limited near-term impact."
    else:
        risk_assessment = "Insufficient data"

    return {
        "applicable": True,
        "data_quality": "ESTIMATED_SECTOR_AVERAGE — emissions are sector-average based",
        "scenarios": scenarios,
        "breakeven_carbon_price_usd_per_tco2": (
            round(breakeven_price, 1) if breakeven_price is not None else None
        ),
        "ebitda_erosion_per_10usd_carbon_price_pct": sensitivity_per_10_usd,
        "risk_assessment": risk_assessment,
        "methodology": (
            "EBITDA_impact_pct = -(carbon_price × estimated_scope1_2_emissions) / EBITDA. "
            "Breakeven = EBITDA / estimated_emissions. "
            "Emissions estimated from GICS sector midpoint intensity × revenue. "
            "Does not account for: carbon pass-through pricing, hedging, abatement capex, "
            "offsets, or regulatory phase-in periods. IEA NZE 2050 carbon price anchors."
        ),
    }


# ---------------------------------------------------------------------------
# 3. Stranded Asset Risk (Energy / Materials only)
# ---------------------------------------------------------------------------


def assess_stranded_asset_risk(
    gics_sector: int | None,
    info: dict,
) -> dict:
    """Estimate stranded asset risk for Energy and Materials sectors.

    Methodology:
      - Stranding condition: carbon_cost_per_boe > (realized_price_per_boe - production_cost_per_boe).
      - Carbon cost per BOE = carbon_price × 0.43 tCO2e/boe (IEA combustion factor).
      - Production cost = sector-average (IEA supply cost curve midpoint).
      - Reference oil price = $75/bbl long-run planning price.
      - Full analysis requires proved reserves from 10-K Item 2 and actual realized prices.
    """
    if gics_sector not in STRANDED_ASSET_SECTORS:
        return {
            "applicable": False,
            "reason": (
                "Stranded asset analysis applies to Energy (GICS 10) and "
                "Materials (GICS 15) sectors only."
            ),
            "methodology": "N/A",
        }

    industry = (info.get("industry") or "").lower()

    if gics_sector == 10:
        if "coal" in industry:
            avg_production_cost_boe = 45.0
            sector_type = "coal"
        elif "renewable" in industry or "solar" in industry or "wind" in industry:
            return {
                "applicable": True,
                "sector_type": "renewables",
                "stranded_asset_risk": "Minimal",
                "risk_score": 1,
                "assessment": (
                    "Renewable energy assets do not face fossil fuel stranded reserve risk. "
                    "May face physical climate risk (solar yield degradation, wind variability)."
                ),
                "methodology": "Renewables excluded from stranded fossil reserve framework",
            }
        elif "oil" in industry or "petroleum" in industry:
            avg_production_cost_boe = 25.0
            sector_type = "oil_and_gas"
        else:
            avg_production_cost_boe = 30.0
            sector_type = "generic_energy"
    else:
        # Materials: mining — different framework, qualitative only
        return {
            "applicable": True,
            "sector_type": "mining_materials",
            "stranded_asset_risk": "Moderate",
            "risk_score": 5,
            "assessment": (
                "Mining assets face stranded risk if carbon taxes increase extraction costs "
                "above commodity prices. Key variables: coal exposure, carbon-intensive smelting, "
                "regulatory mine closure mandates. "
                "Requires company-specific reserve/operations data for precise modelling."
            ),
            "data_quality": "HEURISTIC",
            "methodology": (
                "Qualitative assessment — precise stranded reserve modelling requires "
                "company 10-K reserve tables and regional carbon regulation schedules."
            ),
        }

    # Oil and gas reserve stranding model
    tco2e_per_boe = 0.43  # IEA combustion factor
    reference_oil_price = 75.0  # USD/bbl long-run planning price

    stranding_scenarios: list[dict] = []
    for carbon_price in CARBON_PRICE_SCENARIOS:
        carbon_cost_boe = carbon_price * tco2e_per_boe
        net_margin_boe = reference_oil_price - avg_production_cost_boe
        is_stranded = carbon_cost_boe > net_margin_boe
        pct_margin_erosion = min(
            100.0, carbon_cost_boe / max(net_margin_boe, 0.01) * 100
        )
        stranding_scenarios.append(
            {
                "carbon_price_usd_per_tco2": carbon_price,
                "carbon_cost_per_boe_usd": round(carbon_cost_boe, 2),
                "assumed_production_cost_per_boe_usd": avg_production_cost_boe,
                "reference_oil_price_boe_usd": reference_oil_price,
                "net_margin_per_boe_usd": round(net_margin_boe, 2),
                "economically_stranded": is_stranded,
                "margin_erosion_pct": round(pct_margin_erosion, 1),
            }
        )

    breakeven_oil_at_100 = avg_production_cost_boe + (100 * tco2e_per_boe)

    stranded_count = sum(1 for s in stranding_scenarios if s["economically_stranded"])
    if stranded_count >= 3:
        overall_risk = "High — assets become uneconomic even at moderate carbon prices"
    elif stranded_count == 2:
        overall_risk = (
            "Elevated — significant portion of reserve base at risk above $100/tCO2"
        )
    elif stranded_count == 1:
        overall_risk = (
            "Moderate — reserve base viable at current prices, stressed above $150/tCO2"
        )
    else:
        overall_risk = (
            "Low — reserve base remains economic across all modelled scenarios"
        )

    return {
        "applicable": True,
        "sector_type": sector_type,
        "data_quality": "ESTIMATED_SECTOR_AVERAGE",
        "assumed_avg_production_cost_per_boe_usd": avg_production_cost_boe,
        "tco2e_per_boe_combustion": tco2e_per_boe,
        "stranding_scenarios": stranding_scenarios,
        "breakeven_oil_price_at_100usd_carbon": round(breakeven_oil_at_100, 1),
        "overall_stranded_risk": overall_risk,
        "methodology": (
            "Stranding condition: carbon_cost_per_boe > (realized_price - production_cost). "
            "Carbon cost per BOE = carbon_price × 0.43 tCO2e/boe (IEA combustion factor). "
            "Production cost = sector-average per IEA supply cost curve midpoint. "
            "Reference oil price = $75/bbl long-run planning price. "
            "LIMITATIONS: Does not use company-specific proved reserves or actual realized prices."
        ),
        "note": (
            "High-cost producers (deepwater, oil sands, Arctic) face higher stranding risk. "
            "Use web search for '[TICKER] production cost per BOE' and '10-K proved reserves'."
        ),
    }


# ---------------------------------------------------------------------------
# 4. Transition Risk Score (0-100)
# ---------------------------------------------------------------------------


def compute_transition_risk(
    gics_sector: int | None,
    info: dict,
    income_stmt: Any,
    cash_flow: Any,
) -> dict:
    """Score transition risk on a 0-100 scale (100 = highest risk).

    Sub-components:
      A. Capital intensity (capex/revenue)            — 0-25 pts risk
      B. Carbon product revenue exposure (sector)     — 0-25 pts risk
      C. Green tech proxy (description keyword scan)  — 0-20 pts risk
      D. Regulatory/geographic exposure               — 0-15 pts risk
      E. Customer pressure (B2B vs B2C)               — 0-15 pts risk
    """
    sub_scores: dict[str, Any] = {}
    flags: list[str] = []

    # A. Capital intensity (capex / revenue)
    revenue_series = _try_fields(income_stmt, "Total Revenue", "Revenue")
    capex_series = _try_fields(
        cash_flow, "Capital Expenditure", "Purchase Of Property Plant And Equipment"
    )
    revenue_val = _latest_val(revenue_series)
    capex_val = _latest_val(capex_series)
    capex_abs = abs(capex_val) if capex_val is not None else None
    capex_intensity = _safe_div(capex_abs, revenue_val)

    if capex_intensity is None:
        cap_pts = 12  # uncertainty mid-point
    elif capex_intensity > 0.15:
        cap_pts = 22
        flags.append(
            f"High capital intensity (capex/revenue = {_pct(capex_intensity):.1f}%) "
            "— decarbonization retrofit expensive"
        )
    elif capex_intensity > 0.08:
        cap_pts = 14
    elif capex_intensity > 0.03:
        cap_pts = 8
    else:
        cap_pts = 4  # asset-light — easy to pivot

    sub_scores["capital_intensity"] = {
        "capex_revenue_ratio": round(capex_intensity, 4)
        if capex_intensity is not None
        else None,
        "capex_revenue_pct": _pct(capex_intensity),
        "risk_pts": cap_pts,
        "max_pts": 25,
    }

    # B. Carbon product revenue exposure (sector heuristic)
    sector_carbon_exposure: dict[int, int] = {
        10: 24,
        15: 20,
        55: 18,
        20: 14,
        60: 8,
        25: 10,
        30: 8,
        45: 4,
        35: 4,
        40: 3,
        50: 4,
    }
    carbon_exp_pts = sector_carbon_exposure.get(gics_sector or -1, 10)
    sub_scores["carbon_product_exposure"] = {
        "sector_gics": gics_sector,
        "risk_pts": carbon_exp_pts,
        "max_pts": 25,
        "note": "Sector-level heuristic. Company-specific product mix requires annual report review.",
    }

    # C. Green/transition technology proxy — scan business description
    description = (
        info.get("longBusinessSummary") or info.get("description") or ""
    ).lower()
    green_keywords = [
        "renewable",
        "solar",
        "wind",
        "hydrogen",
        "electric vehicle",
        " ev ",
        "carbon neutral",
        "net zero",
        "carbon capture",
        "clean energy",
        "decarboniz",
        "low carbon",
        "sustainability",
        "green energy",
        "battery",
        "electrif",
    ]
    matched_keywords = [kw for kw in green_keywords if kw in description]
    green_count = len(matched_keywords)

    if green_count >= 4:
        green_pts = 4
    elif green_count >= 2:
        green_pts = 10
    elif green_count >= 1:
        green_pts = 14
    elif gics_sector in CARBON_INTENSIVE_SECTORS:
        green_pts = 19
        flags.append(
            "No green/transition keywords in description for carbon-intensive sector — "
            "elevated transition risk"
        )
    else:
        green_pts = 8  # non-intensive sector, absence is neutral

    sub_scores["green_technology_proxy"] = {
        "matched_keywords": matched_keywords,
        "match_count": green_count,
        "risk_pts": green_pts,
        "max_pts": 20,
    }

    # D. Regulatory / geographic exposure
    country = info.get("country", "")
    regulatory_risk_map: dict[str, int] = {
        "United States": 10,
        "Germany": 14,
        "France": 14,
        "Netherlands": 14,
        "United Kingdom": 13,
        "China": 8,
        "Japan": 10,
        "Canada": 11,
        "Australia": 9,
    }
    reg_pts = regulatory_risk_map.get(country, 8)
    if gics_sector in CARBON_INTENSIVE_SECTORS:
        reg_pts = min(15, reg_pts + 3)

    sub_scores["regulatory_exposure"] = {
        "country": country,
        "risk_pts": reg_pts,
        "max_pts": 15,
        "note": (
            "Country-level heuristic. Sub-national regimes (EU ETS, CBAM, CA cap-and-trade) "
            "not individually modelled."
        ),
    }

    # E. Customer pressure (B2B vs B2C)
    b2c_sectors = {25, 30}
    regulated_sectors = {10, 15, 55}
    if gics_sector in b2c_sectors:
        cust_pts = 13
    elif gics_sector in regulated_sectors:
        cust_pts = 14
    elif gics_sector == 20:
        cust_pts = 10
    else:
        cust_pts = 7

    sub_scores["customer_pressure"] = {
        "sector_classification": (
            "B2C"
            if gics_sector in b2c_sectors
            else "Regulated utility / resource sector"
            if gics_sector in regulated_sectors
            else "Mixed B2B/B2C"
        ),
        "risk_pts": cust_pts,
        "max_pts": 15,
    }

    total_pts = int(
        _clamp(cap_pts + carbon_exp_pts + green_pts + reg_pts + cust_pts, 0, 100)
    )
    risk_label = (
        "Very High"
        if total_pts >= 75
        else "High"
        if total_pts >= 55
        else "Medium"
        if total_pts >= 35
        else "Low"
    )

    return {
        "methodology": (
            "TCFD Transition Risk framework — 5 sub-components: capital intensity, "
            "carbon product exposure (sector heuristic), green technology proxy (description NLP), "
            "regulatory/geographic exposure (country heuristic), customer pressure (sector B2B/B2C). "
            "Score 0-100: higher = greater transition risk."
        ),
        "transition_risk_score": total_pts,
        "risk_label": risk_label,
        "flags": flags,
        "sub_scores": sub_scores,
    }


# ---------------------------------------------------------------------------
# 5. ESG Materiality Score (0-100)
# ---------------------------------------------------------------------------


def compute_esg_materiality(
    gics_sector: int | None,
    info: dict,
    carbon_intensity: dict,
    transition_risk: dict,
    stranded_asset: dict,
) -> dict:
    """Compute a 0-100 ESG Materiality Score across 5 components.

    Higher score = greater ESG/climate materiality (more investment-relevant risk).

    Components:
      A. Carbon intensity         — 25 pts max (from carbon_intensity)
      B. Transition risk          — 25 pts max (rescaled from 0-100 transition_risk_score)
      C. Stranded asset exposure  — 20 pts max (from stranded_asset, or 5 neutral if N/A)
      D. Governance quality proxy — 15 pts max (yfinance governance fields)
      E. Social / controversy     — 15 pts max (description scan + sector heuristic)

    This is a MATERIALITY indicator — it flags where ESG factors are most likely
    to affect fundamental value, not whether the company is 'good' or 'bad'.
    """
    components: dict[str, Any] = {}

    # A. Carbon intensity (25 pts)
    ci_pts = carbon_intensity.get("intensity_score_pts", 12)
    components["carbon_intensity"] = {
        "score_pts": ci_pts,
        "max_pts": 25,
        "intensity_rating": carbon_intensity.get("intensity_classification"),
        "carbon_risk_tier": carbon_intensity.get("carbon_risk_tier"),
    }

    # B. Transition risk (25 pts — rescale from 0-100)
    tr_raw = transition_risk.get("transition_risk_score", 50)
    tr_pts = round(tr_raw * 25 / 100)
    components["transition_risk"] = {
        "score_pts": tr_pts,
        "max_pts": 25,
        "transition_risk_label": transition_risk.get("risk_label"),
        "source_score_0_100": tr_raw,
    }

    # C. Stranded asset (20 pts)
    if stranded_asset.get("applicable"):
        risk_str = stranded_asset.get("overall_stranded_risk", "")
        if "High" in risk_str:
            sa_pts = 16
        elif "Elevated" in risk_str:
            sa_pts = 12
        elif "Moderate" in risk_str:
            sa_pts = 8
        else:
            sa_pts = 4
    else:
        sa_pts = 5  # neutral — not applicable sector
    components["stranded_asset"] = {
        "score_pts": sa_pts,
        "max_pts": 20,
        "applicable": stranded_asset.get("applicable", False),
    }

    # D. Governance quality proxy (15 pts)
    gov_pts = 7.0  # neutral default
    gov_flags: list[str] = []

    # Yahoo Finance governance pillar scores (1-10 scale, lower = better governance)
    overall_risk = _safe_float(info.get("overallRisk"))
    board_risk = _safe_float(info.get("boardRisk"))
    audit_risk = _safe_float(info.get("auditRisk"))
    shareholder_risk = _safe_float(info.get("shareHolderRightsRisk"))
    compensation_risk = _safe_float(info.get("compensationRisk"))

    if overall_risk is not None:
        gov_pts += (overall_risk - 5.0) * 0.5  # >5 adds risk pts, <5 subtracts
        if overall_risk >= 8:
            gov_flags.append(f"Overall governance risk high ({overall_risk:.0f}/10)")
    if board_risk is not None:
        if board_risk >= 7:
            gov_pts += 2.0
            gov_flags.append(f"High board risk ({board_risk:.0f}/10)")
        elif board_risk <= 3:
            gov_pts -= 1.0
    if audit_risk is not None:
        if audit_risk >= 8:
            gov_pts += 2.5
            gov_flags.append(f"High audit risk ({audit_risk:.0f}/10)")
        elif audit_risk <= 3:
            gov_pts -= 1.0

    # Insider concentration
    insider_pct = _safe_float(info.get("heldPercentInsiders"))
    if insider_pct is not None:
        insider_scaled = insider_pct * 100 if insider_pct <= 1.0 else insider_pct
        if insider_scaled > 50:
            gov_pts += 3.0
            gov_flags.append(f"High insider concentration ({insider_scaled:.1f}%)")
        elif 5 <= insider_scaled <= 30:
            gov_pts -= 1.0  # healthy alignment

    gov_pts_int = int(_clamp(round(gov_pts), 0, 15))
    components["governance_quality"] = {
        "score_pts": gov_pts_int,
        "max_pts": 15,
        "insider_ownership_pct": _pct(insider_pct) if insider_pct is not None else None,
        "governance_risk_scores": {
            "overall": overall_risk,
            "board": board_risk,
            "audit": audit_risk,
            "shareholder_rights": shareholder_risk,
            "compensation": compensation_risk,
        },
        "flags": gov_flags,
        "note": "Governance quality proxy from Yahoo Finance pillar scores (1-10, lower = better).",
    }

    # E. Social / controversy signal (15 pts)
    description = (info.get("longBusinessSummary") or "").lower()
    controversy_keywords = [
        "lawsuit",
        "settlement",
        "regulatory fine",
        "investigation",
        "discrimination",
        "violation",
        "penalty",
    ]
    positive_social = [
        "diversity",
        "community",
        "employee benefit",
        "living wage",
        "safety record",
        "social impact",
    ]
    controversy_hits = sum(1 for kw in controversy_keywords if kw in description)
    positive_hits = sum(1 for kw in positive_social if kw in description)

    social_pts = 7.0
    if controversy_hits >= 2:
        social_pts = 12.0
    elif controversy_hits == 1:
        social_pts = 9.0
    if positive_hits >= 2:
        social_pts -= 2.0

    # Sector social risk premium
    if gics_sector in CARBON_INTENSIVE_SECTORS:
        social_pts = min(15.0, social_pts + 2.0)
    elif gics_sector == 35:  # Healthcare — drug pricing controversy
        social_pts = min(15.0, social_pts + 1.0)

    social_pts_int = int(_clamp(round(social_pts), 0, 15))
    components["social_controversy"] = {
        "score_pts": social_pts_int,
        "max_pts": 15,
        "controversy_keyword_hits": controversy_hits,
        "positive_social_keyword_hits": positive_hits,
        "note": "Keyword proxy only. Full controversy screening requires RepRisk or MSCI.",
    }

    total = ci_pts + tr_pts + sa_pts + gov_pts_int + social_pts_int
    total = int(_clamp(total, 0, 100))

    materiality_label = (
        "Very High Materiality"
        if total >= 70
        else "High Materiality"
        if total >= 50
        else "Medium Materiality"
        if total >= 30
        else "Low Materiality"
    )

    return {
        "methodology": (
            "SASB materiality + TCFD climate risk scoring. Score 0-100 (higher = greater materiality). "
            "Components: carbon intensity (25 pts), transition risk (25 pts, rescaled), "
            "stranded asset exposure (20 pts), governance proxy (15 pts, Yahoo Finance pillar scores), "
            "social signal (15 pts, description NLP + sector). "
            "This is a MATERIALITY indicator — flags where ESG factors affect fundamental value."
        ),
        "esg_materiality_score": total,
        "materiality_label": materiality_label,
        "components": components,
        "interpretation": (
            "Climate and ESG factors highly material — dedicated deep-dive and MSCI/Sustainalytics data required"
            if total >= 70
            else "ESG factors materially relevant — monitor regulatory and transition risk"
            if total >= 50
            else "ESG factors moderately relevant — sector norms apply"
            if total >= 30
            else "ESG factors low materiality for this sector and company profile"
        ),
        "data_sources_for_verification": [
            "Company sustainability report (IR website)",
            "CDP climate disclosure (cdp.net/en/companies)",
            "Sustainalytics ESG Risk Rating (sustainalytics.com)",
            "MSCI ESG Score (msci.com/esg-ratings)",
            "SBTi commitment status (sciencebasedtargets.org)",
        ],
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def compute_esg_summary(
    carbon_assessment: dict,
    carbon_pricing: dict,
    stranded_risk: dict,
    transition_risk: dict,
    esg_materiality: dict,
) -> dict:
    """Synthesize an overall ESG risk flag list and investment consideration."""
    flags: list[str] = []
    positives: list[str] = []

    if carbon_assessment.get("carbon_risk_tier") == "High":
        flags.append("High carbon intensity sector — material transition risk")

    if carbon_pricing.get("applicable"):
        scenarios = carbon_pricing.get("scenarios", [])
        ref = next(
            (s for s in scenarios if s.get("carbon_price_usd_per_tco2") == 100), None
        )
        if (
            ref
            and ref.get("ebitda_impact_pct") is not None
            and ref["ebitda_impact_pct"] < -25
        ):
            flags.append(
                f"Carbon pricing: EBITDA erodes {abs(ref['ebitda_impact_pct']):.0f}% at $100/tCO2"
            )
        breakeven = carbon_pricing.get("breakeven_carbon_price_usd_per_tco2")
        if breakeven is not None and breakeven < 150:
            flags.append(
                f"Breakeven carbon price ${breakeven:.0f}/tCO2 — within policy scenario range"
            )

    if stranded_risk.get("applicable") and "High" in str(
        stranded_risk.get("overall_stranded_risk", "")
    ):
        flags.append(
            "Stranded asset risk: reserves may be uneconomic at carbon policy trajectory"
        )

    tr_score = transition_risk.get("transition_risk_score", 0)
    if tr_score >= 70:
        flags.append(f"Very high transition risk score ({tr_score}/100)")
    elif tr_score >= 55:
        flags.append(f"High transition risk score ({tr_score}/100)")

    total_esg = esg_materiality.get("esg_materiality_score", 50)
    if total_esg >= 70:
        flags.append(
            f"High ESG materiality score ({total_esg}/100) — investor scrutiny likely"
        )
    elif total_esg < 30:
        positives.append(
            f"Low ESG materiality score ({total_esg}/100) — limited climate risk exposure"
        )

    tr_flags = transition_risk.get("flags", [])
    flags.extend(tr_flags)

    flag_count = len(flags)
    if flag_count == 0:
        overall = "Low ESG Risk"
    elif flag_count <= 2:
        overall = "Moderate ESG Risk"
    elif flag_count <= 4:
        overall = "Elevated ESG Risk"
    else:
        overall = "High ESG Risk"

    return {
        "overall_esg_risk_rating": overall,
        "flag_count": flag_count,
        "flags": flags,
        "positives": positives,
        "investment_consideration": (
            "ESG risks are increasingly priced by institutional investors (ESG AUM >$35T). "
            "High-risk companies face: rising cost of capital, ESG fund exclusion, "
            "regulatory carbon costs, and physical asset impairment. "
            "Supplement this heuristic with Sustainalytics ESG Risk Rating, "
            "MSCI ESG Score, and CDP Climate Disclosure Score for investment-grade diligence."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESG Carbon Intensity & Climate Risk Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  fetch_esg_carbon.py XOM\n"
            "  fetch_esg_carbon.py XOM --sector 10\n"
            "  fetch_esg_carbon.py XOM --sector 10 --output ./reports/XOM/esg_carbon.json\n"
            "  fetch_esg_carbon.py AAPL --sector 45 --output ./reports/AAPL/esg_carbon.json\n"
            "  fetch_esg_carbon.py NEE --sector 55 --output ./reports/NEE/esg_carbon.json\n\n"
            "GICS sector codes:\n"
            "  10=Energy | 15=Materials | 20=Industrials | 25=Consumer Discretionary\n"
            "  30=Consumer Staples | 35=Healthcare | 40=Financials | 45=Technology\n"
            "  50=Communication Services | 55=Utilities | 60=Real Estate"
        ),
    )
    parser.add_argument("ticker", help="Ticker symbol (e.g., XOM, AAPL, NEE)")
    parser.add_argument(
        "--sector",
        type=int,
        dest="gics_sector",
        metavar="GICS_CODE",
        help="GICS sector code override. Auto-inferred from yfinance if omitted.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Output file path (default: stdout). Parent directories created automatically.",
    )
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    # Fetch yfinance data
    try:
        import yfinance as yf
    except ImportError:
        sys.stderr.write("Error: yfinance not installed. Run: pip install yfinance\n")
        sys.exit(1)

    stock = yf.Ticker(ticker)
    info: dict = {}
    income_stmt = None
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
        cash_flow = stock.cashflow
    except Exception as e:
        sys.stderr.write(f"yfinance cashflow fetch failed for {ticker}: {e}\n")

    if not info and income_stmt is None:
        result: dict = {
            "ticker": ticker,
            "error": (
                f"Could not fetch any data for {ticker}. "
                "Verify the ticker is valid and internet is accessible."
            ),
        }
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Resolve GICS sector
    gics_sector = resolve_gics_sector(args.gics_sector, info)

    # Extract financial inputs
    revenue_usd = _safe_float(info.get("totalRevenue"))
    ebitda_usd = _safe_float(info.get("ebitda"))
    # Fallback: EBIT + D&A if direct EBITDA absent
    if ebitda_usd is None:
        ebit_series = _try_fields(income_stmt, "Operating Income", "EBIT")
        da_series = _try_fields(
            cash_flow,
            "Depreciation And Amortization",
            "Depreciation Amortization Depletion",
        )
        ebit = _latest_val(ebit_series)
        da = _latest_val(da_series)
        if ebit is not None and da is not None:
            ebitda_usd = ebit + abs(da)

    industry = info.get("industry") or ""

    # Run all modules
    errors: list[str] = []

    try:
        carbon_intensity = assess_carbon_intensity(gics_sector, revenue_usd, industry)
    except Exception as e:
        errors.append(f"carbon_intensity: {e}")
        carbon_intensity = {"error": str(e)}

    estimated_emissions = (
        carbon_intensity.get("estimated_absolute_emissions_tco2e")
        if "error" not in carbon_intensity
        else None
    )

    try:
        carbon_pricing_scenarios = model_carbon_pricing_scenarios(
            gics_sector, estimated_emissions, ebitda_usd
        )
    except Exception as e:
        errors.append(f"carbon_pricing_scenarios: {e}")
        carbon_pricing_scenarios = {"error": str(e)}

    try:
        stranded_asset_risk = assess_stranded_asset_risk(gics_sector, info)
    except Exception as e:
        errors.append(f"stranded_asset_risk: {e}")
        stranded_asset_risk = {"error": str(e)}

    try:
        transition_risk = compute_transition_risk(
            gics_sector, info, income_stmt, cash_flow
        )
    except Exception as e:
        errors.append(f"transition_risk: {e}")
        transition_risk = {"error": str(e)}

    try:
        esg_materiality_score = compute_esg_materiality(
            gics_sector, info, carbon_intensity, transition_risk, stranded_asset_risk
        )
    except Exception as e:
        errors.append(f"esg_materiality_score: {e}")
        esg_materiality_score = {"error": str(e)}

    try:
        esg_summary = compute_esg_summary(
            carbon_intensity,
            carbon_pricing_scenarios,
            stranded_asset_risk,
            transition_risk,
            esg_materiality_score,
        )
    except Exception as e:
        errors.append(f"esg_summary: {e}")
        esg_summary = {"error": str(e)}

    result = {
        "ticker": ticker,
        "sector_gics": gics_sector,
        "sector_gics_source": (
            "cli_override"
            if args.gics_sector is not None
            else "yfinance_sector_mapping"
        ),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "company_profile": {
            "name": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector"),
            "industry": industry,
            "country": info.get("country"),
            "market_cap_usd": _safe_float(info.get("marketCap")),
            "revenue_usd": revenue_usd,
            "ebitda_usd": ebitda_usd,
        },
        "carbon_intensity": carbon_intensity,
        "carbon_pricing_scenarios": carbon_pricing_scenarios,
        "stranded_asset_risk": stranded_asset_risk,
        "transition_risk": transition_risk,
        "esg_materiality_score": esg_materiality_score,
        "esg_summary": esg_summary,
        "methodology": (
            "ESG carbon risk analysis using sector-average emission intensity benchmarks. "
            "Frameworks: TCFD scenario analysis (carbon pricing), IEA NZE 2050 pathway "
            "($50-$200/tCO2 anchors), SASB sector materiality, Carbon Tracker Initiative "
            "(stranded asset). Company-level Scope 1+2 data unavailable without paid ESG providers. "
            "All intensity and emission figures are sector-average proxies — treat as directional. "
            "Data source: yfinance (Yahoo Finance). Math: deterministic, no LLM involvement."
        ),
        "global_disclaimer": (
            "ALL ESG AND CARBON DATA ARE ESTIMATED FROM SECTOR AVERAGES AND HEURISTICS "
            "UNLESS EXPLICITLY LABELED 'REPORTED'. Do not use as verified disclosures. "
            "Verify with CDP, MSCI ESG, Sustainalytics, or company sustainability reports."
        ),
    }

    if errors:
        result["computation_warnings"] = errors

    output = json.dumps(result, indent=2, default=str)

    if args.output:
        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(output)
        sys.stderr.write(f"Output written to {args.output}\n")
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
