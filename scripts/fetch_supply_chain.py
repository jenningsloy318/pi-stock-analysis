#!/usr/bin/env python3
"""Supply Chain Concentration Risk Assessment.

Usage:
    fetch_supply_chain.py NVDA
    fetch_supply_chain.py NVDA --sector 4530
    fetch_supply_chain.py NVDA --output ./reports/NVDA/supply_chain.json
    fetch_supply_chain.py AAPL --sector 4520 --output ./reports/AAPL/supply_chain.json

Assesses supply chain concentration risk using proxy signals derived from
yfinance data and sector heuristics. Deep supply chain mapping (Bloomberg
SPLC, FactSet) requires paid APIs; this script uses publicly available data.

Analysis dimensions:
  1. Geographic Revenue Concentration  — HHI from yfinance segments
  2. Customer Concentration Proxy      — 10%+ customer disclosure heuristic
  3. Sector Chokepoint Profile         — GICS-mapped known bottlenecks
  4. Input Cost Sensitivity            — COGS margin trend + commodity exposure
  5. Resilience Score (0-100)          — weighted composite of dimensions 1-4 + size

Missing data is returned as null with an explanatory note — never fabricated.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    import numpy as np
except ImportError:
    sys.stderr.write("Error: 'numpy' required. Run: pip install numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Sector chokepoint knowledge base (GICS sector/industry codes)
# ---------------------------------------------------------------------------

# Maps GICS industry group prefix (4 digits) or sector (2 digits) to chokepoints.
# Order: most-specific match wins.
SECTOR_CHOKEPOINTS: dict[str, dict] = {
    "4530": {  # Semiconductors & Semiconductor Equipment
        "label": "Semiconductors",
        "chokepoints": [
            "TSMC leading-edge foundry monopoly (advanced nodes <7nm)",
            "ASML EUV photolithography monopoly",
            "Synopsys/Cadence EDA tool duopoly",
            "Rare earth elements (neodymium, dysprosium) — China ~60% supply",
            "Advanced packaging (CoWoS, HBM) — TSMC/SK Hynix concentration",
        ],
        "risk_tier": "Critical",
        "primary_geography_risk": "Taiwan strait (TSMC), Netherlands (ASML)",
    },
    "4520": {  # Technology Hardware & Equipment
        "label": "Tech Hardware",
        "chokepoints": [
            "Contract manufacturing concentration (Foxconn/Hon Hai, Pegatron)",
            "Display panel duopoly (Samsung, LG Display / AUO)",
            "Printed circuit board supply (Asia-Pacific 90%+ share)",
            "Camera module supply (Sony image sensors dominant)",
            "Rare earth magnets for motors/speakers — China dependency",
        ],
        "risk_tier": "High",
        "primary_geography_risk": "China manufacturing concentration, Taiwan components",
    },
    "2510": {  # Automobiles & Components
        "label": "Automotive",
        "chokepoints": [
            "Automotive semiconductor shortage vulnerability (TSMC, NXP, Renesas)",
            "Battery materials: lithium (Australia/Chile), cobalt (DRC ~70%)",
            "Rare earth for EV motors — China ~85% processing capacity",
            "Single-source suppliers for safety-critical components",
            "Tier-2/3 supplier visibility gap (opaque sub-tiers)",
        ],
        "risk_tier": "High",
        "primary_geography_risk": "China EV battery materials, Taiwan semiconductors",
    },
    "3520": {  # Pharmaceuticals, Biotechnology & Life Sciences
        "label": "Pharma/Biotech",
        "chokepoints": [
            "Active Pharmaceutical Ingredient (API) sourcing — India/China 80%+ global supply",
            "Fermentation capacity for biologics (limited global CDMOs)",
            "Cold-chain logistics dependency (2-8°C, ultra-cold -70°C)",
            "FDA/EMA regulatory single-source approval risk",
            "Glass vial & syringe supply (Gerresheimer, Schott concentration)",
        ],
        "risk_tier": "High",
        "primary_geography_risk": "India/China API dominance, cold-chain disruption",
    },
    "1010": {  # Energy
        "label": "Energy",
        "chokepoints": [
            "Pipeline and midstream access (regulated natural monopolies)",
            "OPEC+ production quota influence on crude pricing",
            "Refining capacity concentration (regional bottlenecks)",
            "Offshore equipment lead times (drillships, FPSOs)",
            "LNG liquefaction train capacity (long-lead capital)",
        ],
        "risk_tier": "Medium",
        "primary_geography_risk": "OPEC geopolitics, pipeline route dependencies",
    },
    "2550": {  # Retailing
        "label": "Retail",
        "chokepoints": [
            "Container shipping capacity (top 10 carriers control ~85%)",
            "Port congestion and drayage (LA/Long Beach, Rotterdam)",
            "Last-mile delivery duopoly (FedEx, UPS) or Amazon self-supply",
            "China-sourced merchandise concentration (tariff exposure)",
            "Cold-chain for grocery (limited 3PL options)",
        ],
        "risk_tier": "Medium",
        "primary_geography_risk": "Trans-Pacific shipping lanes, China sourcing",
    },
    "2010": {  # Capital Goods (defense sub-sector)
        "label": "Capital Goods / Defense",
        "chokepoints": [
            "Government (DoD/NATO) as dominant single customer",
            "Sole-source contract dependency on program continuation",
            "Specialty alloys and titanium (Russia/China historical supply)",
            "Security-cleared workforce scarcity (clearance backlog)",
            "Long-cycle program: cancellation or sequestration risk",
        ],
        "risk_tier": "High",
        "primary_geography_risk": "US government budget dependency, specialty materials",
    },
    "3510": {  # Health Care Equipment & Services
        "label": "Healthcare Equipment",
        "chokepoints": [
            "Semiconductor components for medical devices (Class II/III lead times)",
            "Contract sterilization capacity (EtO sterilization concentration)",
            "Single-source raw materials for implantables (UHMWPE, Ti-6Al-4V)",
            "FDA 510(k)/PMA regulatory single-source approval",
            "Hospital group purchasing organization (GPO) pricing leverage",
        ],
        "risk_tier": "Medium",
        "primary_geography_risk": "Asia-Pacific component sourcing, regulatory concentration",
    },
    "20": {  # Industrials (fallback sector)
        "label": "Industrials",
        "chokepoints": [
            "Steel and aluminum (trade policy / tariff exposure)",
            "Freight rail and trucking capacity (cyclical tightness)",
            "Skilled trades labor shortage (welders, electricians)",
            "Single-source castings or forgings (long lead times)",
        ],
        "risk_tier": "Medium",
        "primary_geography_risk": "Steel/aluminum trade policy, logistics capacity",
    },
    "default": {
        "label": "General",
        "chokepoints": [
            "Data insufficient to map sector-specific chokepoints",
            "Review 10-K Item 1A Risk Factors for supply chain disclosures",
        ],
        "risk_tier": "Unknown",
        "primary_geography_risk": "Not determined",
    },
}

# GICS codes where high government/single-customer concentration is expected
GOV_CONCENTRATION_GICS = {"2010", "2020", "1010"}
# GICS codes typical of B2C / fragmented customer base
B2C_GICS = {"2550", "2520", "3010", "3020", "3030", "4510"}


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _round(v: float | None, places: int = 4) -> float | None:
    return round(v, places) if v is not None else None


def _pct(v: float | None) -> float | None:
    return _round(v * 100, 2) if v is not None else None


def _hhi(shares: list[float]) -> float:
    """Herfindahl-Hirschman Index from a list of revenue shares (0-1 scale).

    Returns value in 0-10000 range. >2500 = highly concentrated.
    """
    total = sum(shares)
    if total == 0:
        return 0.0
    normalised = [s / total for s in shares]
    return float(np.sum(np.square(normalised)) * 10000)


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
    for f in fields:
        r = _df_row(df, f)
        if r:
            return r
    return []


def _valid_values(series: list[dict]) -> list[float]:
    return [e["value"] for e in series if e.get("value") is not None]


# ---------------------------------------------------------------------------
# Chokepoint lookup
# ---------------------------------------------------------------------------


def lookup_chokepoints(gics_code: str | None) -> dict:
    """Return chokepoint profile for the given GICS code.

    Tries 4-digit industry group, then 2-digit sector, then default.
    """
    if not gics_code:
        return SECTOR_CHOKEPOINTS["default"]
    code = str(gics_code).strip()
    if code in SECTOR_CHOKEPOINTS:
        return SECTOR_CHOKEPOINTS[code]
    sector_prefix = code[:2]
    if sector_prefix in SECTOR_CHOKEPOINTS:
        return SECTOR_CHOKEPOINTS[sector_prefix]
    return SECTOR_CHOKEPOINTS["default"]


# ---------------------------------------------------------------------------
# 1. Geographic Revenue Concentration
# ---------------------------------------------------------------------------


def compute_geographic_concentration(info: dict) -> dict:
    """Derive geographic revenue HHI from yfinance info segments if available.

    yfinance exposes geographic segment data inconsistently. We extract whatever
    is available and fall back to domicile-based heuristics.
    """
    result: dict[str, Any] = {
        "methodology": (
            "HHI computed from yfinance geographic revenue segments where disclosed. "
            "HHI >2500 = highly concentrated; 1500-2500 = moderate; <1500 = diversified. "
            "Single-region >50% triggers a concentration flag. "
            "Fallback: country-of-domicile proxy when segments unavailable."
        )
    }

    country = info.get("country", "Unknown")
    total_revenue = info.get("totalRevenue")

    # yfinance sometimes surfaces geographic breakdown via revenueByGeography
    segments: dict[str, float] = {}
    rev_by_geo = info.get("revenueByGeography") or {}
    if isinstance(rev_by_geo, dict):
        for region, val in rev_by_geo.items():
            try:
                segments[str(region)] = float(val)
            except (TypeError, ValueError):
                pass

    if segments:
        total = sum(segments.values())
        shares = {k: v / total for k, v in segments.items() if total > 0}
        hhi = _hhi(list(segments.values()))
        dominant = max(shares, key=lambda k: shares[k]) if shares else None
        dominant_pct = _pct(shares.get(dominant)) if dominant else None
        result.update(
            {
                "source": "yfinance_segments",
                "segments": {k: _pct(v) for k, v in shares.items()},
                "hhi": _round(hhi, 1),
                "dominant_region": dominant,
                "dominant_region_pct": dominant_pct,
                "flag_single_region_gt50": (dominant_pct or 0) > 50,
                "concentration_level": (
                    "High" if hhi > 2500 else "Medium" if hhi > 1500 else "Low"
                ),
            }
        )
    else:
        # Heuristic fallback: assume home-country concentration from domicile
        us_domicile = country in ("United States", "USA", "US")
        result.update(
            {
                "source": "domicile_heuristic",
                "segments": None,
                "hhi": None,
                "dominant_region": country,
                "dominant_region_pct": None,
                "flag_single_region_gt50": None,
                "concentration_level": "Unknown",
                "note": (
                    "Geographic revenue segments not disclosed via yfinance. "
                    "Review 10-K Note on Segment Information for actual breakdown."
                ),
            }
        )

    return result


# ---------------------------------------------------------------------------
# 2. Customer Concentration Proxy
# ---------------------------------------------------------------------------


def compute_customer_concentration(info: dict, gics_code: str | None) -> dict:
    """Estimate customer concentration risk from sector heuristics and description.

    True 10%+ customer disclosures require 10-K parsing. This function provides
    a GICS-based prior and flags known high-concentration sectors.
    """
    result: dict[str, Any] = {
        "methodology": (
            "Customer concentration estimated via GICS sector prior + keyword scan "
            "of yfinance longBusinessSummary. Defense/Gov (GICS 2010) = high concentration. "
            "B2C sectors (GICS 2550, 25xx, 30xx, 45xx) = low concentration. "
            "10%+ customer keyword detection triggers a disclosure flag. "
            "True concentration requires 10-K Item 1 / Note on Segments."
        )
    }

    code = str(gics_code or "").strip()
    description = (info.get("longBusinessSummary") or "").lower()

    # Keyword signals in business description
    concentration_keywords = [
        "10% or more",
        "10 percent or more",
        "single customer",
        "major customer",
        "significant customer",
        "concentrated customer",
        "government contracts",
        "department of defense",
        "u.s. government",
    ]
    diversification_keywords = [
        "diversified customer",
        "no single customer",
        "broad customer base",
        "thousands of customers",
        "millions of customers",
    ]

    concentration_hits = [kw for kw in concentration_keywords if kw in description]
    diversification_hits = [kw for kw in diversification_keywords if kw in description]

    # GICS sector prior
    if code[:4] in GOV_CONCENTRATION_GICS or code[:2] in GOV_CONCENTRATION_GICS:
        sector_prior = "High"
        sector_note = "Defense/government sector: government procurement typically 40-80%+ of revenue"
    elif code[:4] in B2C_GICS or code[:2] in B2C_GICS:
        sector_prior = "Low"
        sector_note = "B2C sector: fragmented end-customer base typical"
    else:
        sector_prior = "Medium"
        sector_note = "B2B sector: moderate customer concentration typical; review 10-K for 10%+ customers"

    keyword_signal = (
        "High"
        if concentration_hits and not diversification_hits
        else "Low"
        if diversification_hits and not concentration_hits
        else "Unknown"
    )

    # Combine: keyword > sector prior when available
    estimate = keyword_signal if keyword_signal != "Unknown" else sector_prior

    result.update(
        {
            "estimated_concentration": estimate,
            "sector_prior": sector_prior,
            "sector_note": sector_note,
            "keyword_signals_concentration": concentration_hits,
            "keyword_signals_diversification": diversification_hits,
            "note": (
                "Proxy estimate only. Verify against 10-K Item 1 'Major Customers' "
                "and Note on Segment Information for regulatory disclosures."
            ),
        }
    )
    return result


# ---------------------------------------------------------------------------
# 3. Sector Chokepoints
# ---------------------------------------------------------------------------


def compute_sector_chokepoints(info: dict, gics_code: str | None) -> dict:
    """Return known supply chain chokepoints for the company's GICS sector."""
    profile = lookup_chokepoints(gics_code)
    industry_key = info.get("industry", "N/A")
    sector_key = info.get("sector", "N/A")

    return {
        "gics_code_used": gics_code,
        "sector_label": profile["label"],
        "yfinance_sector": sector_key,
        "yfinance_industry": industry_key,
        "risk_tier": profile["risk_tier"],
        "primary_geography_risk": profile["primary_geography_risk"],
        "known_chokepoints": profile["chokepoints"],
        "methodology": (
            "Chokepoints derived from GICS industry group / sector mapping. "
            "Sources: industry reports, SEC risk factor aggregation, "
            "Congressional Research Service supply chain studies. "
            "Tier: Critical = systemic single-point failures with no near-term substitute; "
            "High = significant concentration with costly workarounds; "
            "Medium = manageable with 6-18 month mitigation; Low = diversified."
        ),
    }


# ---------------------------------------------------------------------------
# 4. Input Cost Sensitivity
# ---------------------------------------------------------------------------


def compute_input_cost_analysis(
    income_stmt: Any,
    info: dict,
    gics_code: str | None,
) -> dict:
    """Assess input cost sensitivity from COGS margin trend and sector exposure."""
    result: dict[str, Any] = {
        "methodology": (
            "COGS/Revenue (gross margin inverse) extracted from yfinance income statement. "
            "Trend computed as recent COGS ratio minus 3-year average COGS ratio — "
            "positive trend = cost pressures rising. "
            "Operating leverage proxy = (1 - gross_margin) as upper bound on variable cost share. "
            "Commodity exposure mapped from GICS sector knowledge base."
        )
    }

    # COGS series
    cogs_series = _try_fields(
        income_stmt,
        "Cost Of Revenue",
        "CostOfRevenue",
        "Cost Of Goods Sold",
        "CostOfGoodsSold",
    )
    rev_series = _try_fields(
        income_stmt,
        "Total Revenue",
        "TotalRevenue",
    )

    cogs_vals = _valid_values(cogs_series)
    rev_vals = _valid_values(rev_series)

    cogs_ratios: list[float] = []
    for c, r in zip(cogs_vals, rev_vals):
        ratio = _safe_div(c, r)
        if ratio is not None:
            cogs_ratios.append(ratio)

    if cogs_ratios:
        recent_cogs_ratio = cogs_ratios[0]
        avg_cogs_ratio = float(np.mean(cogs_ratios))
        cogs_trend = recent_cogs_ratio - avg_cogs_ratio  # positive = rising costs
        gross_margin_recent = 1.0 - recent_cogs_ratio
        result.update(
            {
                "cogs_to_revenue_recent": _pct(recent_cogs_ratio),
                "cogs_to_revenue_avg": _pct(avg_cogs_ratio),
                "cogs_trend_pct_pts": _round(cogs_trend * 100, 2),
                "gross_margin_pct": _pct(gross_margin_recent),
                "cost_pressure_signal": (
                    "Rising"
                    if cogs_trend > 0.02
                    else "Falling"
                    if cogs_trend < -0.02
                    else "Stable"
                ),
            }
        )
    else:
        result.update(
            {
                "cogs_to_revenue_recent": None,
                "cogs_to_revenue_avg": None,
                "cogs_trend_pct_pts": None,
                "gross_margin_pct": _pct(_safe_div(info.get("grossMargins"), 1.0)),
                "cost_pressure_signal": "Unknown",
                "note": "Income statement not available via yfinance; gross margin from info dict.",
            }
        )

    # Sector commodity exposure map
    code = str(gics_code or "")
    commodity_map: dict[str, list[str]] = {
        "4530": ["silicon wafers", "specialty gases (NF3, WF6)", "rare earth metals"],
        "4520": ["copper", "aluminum", "lithium", "display glass", "rare earths"],
        "2510": ["steel", "aluminum", "lithium", "cobalt", "palladium", "natural gas"],
        "3520": [
            "active pharmaceutical ingredients",
            "solvents",
            "glass vials",
            "natural gas",
        ],
        "1010": ["crude oil", "natural gas", "steel tubulars", "electricity"],
        "2550": [
            "cotton",
            "polyester",
            "cardboard/paper",
            "diesel (logistics)",
            "natural gas",
        ],
        "2010": ["titanium", "specialty alloys", "composites", "electronics"],
        "3510": [
            "medical-grade polymers",
            "titanium",
            "specialty gases",
            "electronics",
        ],
    }
    result["key_input_commodities"] = (
        commodity_map.get(code[:4])
        or commodity_map.get(code[:2])
        or ["Not mapped — review 10-K cost of revenues disclosures"]
    )

    return result


# ---------------------------------------------------------------------------
# 5. Resilience Score
# ---------------------------------------------------------------------------


def compute_resilience_score(
    geo: dict,
    customer: dict,
    chokepoints: dict,
    input_cost: dict,
    info: dict,
) -> dict:
    """Compute composite supply chain resilience score (0-100, higher = more resilient).

    Scoring weights:
      Geographic concentration  25 pts
      Customer concentration    20 pts
      Chokepoint exposure       25 pts
      Input cost stability      15 pts
      Company size              15 pts
    """
    scores: dict[str, dict] = {}

    # --- Geographic (25 pts) ---
    hhi = geo.get("hhi")
    geo_flag = geo.get("flag_single_region_gt50")
    conc_level = geo.get("concentration_level", "Unknown")
    if hhi is not None:
        if hhi > 5000 or geo_flag:
            geo_pts = 5.0
        elif hhi > 2500:
            geo_pts = 12.0
        elif hhi > 1500:
            geo_pts = 19.0
        else:
            geo_pts = 25.0
    elif conc_level == "Unknown":
        geo_pts = 12.5  # neutral when no data
    else:
        level_map = {"Low": 25.0, "Medium": 15.0, "High": 7.0}
        geo_pts = level_map.get(conc_level, 12.5)
    scores["geographic_concentration"] = {
        "points": _round(geo_pts, 1),
        "max": 25,
        "basis": f"HHI={hhi}, concentration={conc_level}",
    }

    # --- Customer (20 pts) ---
    cust_est = customer.get("estimated_concentration", "Unknown")
    cust_map = {"Low": 20.0, "Medium": 12.0, "High": 4.0, "Unknown": 10.0}
    cust_pts = cust_map.get(cust_est, 10.0)
    scores["customer_concentration"] = {
        "points": cust_pts,
        "max": 20,
        "basis": f"estimated={cust_est}",
    }

    # --- Chokepoint (25 pts) ---
    tier_map = {
        "Low": 25.0,
        "Medium": 17.0,
        "High": 8.0,
        "Critical": 2.0,
        "Unknown": 12.5,
    }
    choke_pts = tier_map.get(chokepoints.get("risk_tier", "Unknown"), 12.5)
    scores["chokepoint_exposure"] = {
        "points": choke_pts,
        "max": 25,
        "basis": f"risk_tier={chokepoints.get('risk_tier')}",
    }

    # --- Input cost stability (15 pts) ---
    cost_signal = input_cost.get("cost_pressure_signal", "Unknown")
    cost_map = {"Falling": 15.0, "Stable": 12.0, "Rising": 4.0, "Unknown": 7.5}
    cost_pts = cost_map.get(cost_signal, 7.5)
    scores["input_cost_stability"] = {
        "points": cost_pts,
        "max": 15,
        "basis": f"cost_pressure={cost_signal}",
    }

    # --- Company size (15 pts): larger firms have more supply chain optionality ---
    market_cap = info.get("marketCap") or 0
    if market_cap >= 200e9:
        size_pts = 15.0
        size_label = "Mega-cap (>$200B)"
    elif market_cap >= 10e9:
        size_pts = 12.0
        size_label = "Large-cap ($10B-$200B)"
    elif market_cap >= 2e9:
        size_pts = 8.0
        size_label = "Mid-cap ($2B-$10B)"
    elif market_cap > 0:
        size_pts = 4.0
        size_label = "Small-cap (<$2B)"
    else:
        size_pts = 7.5
        size_label = "Unknown"
    scores["company_size"] = {
        "points": size_pts,
        "max": 15,
        "basis": f"market_cap={market_cap:.0f}, {size_label}",
    }

    total = sum(s["points"] for s in scores.values())
    if total >= 80:
        tier = "Resilient"
    elif total >= 60:
        tier = "Moderate"
    elif total >= 35:
        tier = "Vulnerable"
    else:
        tier = "Critical"

    return {
        "total": _round(total, 1),
        "max": 100,
        "tier": tier,
        "components": scores,
        "methodology": (
            "Resilience score = weighted sum of 5 components. "
            "Geographic (25): HHI-based; Customer (20): GICS/keyword prior; "
            "Chokepoint (25): GICS risk tier; Input cost (15): COGS trend signal; "
            "Size (15): market cap proxy for supply chain diversification capacity. "
            "Tiers: Resilient ≥80, Moderate 60-79, Vulnerable 35-59, Critical <35."
        ),
    }


# ---------------------------------------------------------------------------
# Key risks synthesis
# ---------------------------------------------------------------------------


def synthesise_key_risks(
    geo: dict,
    customer: dict,
    chokepoints: dict,
    input_cost: dict,
    resilience: dict,
) -> list[str]:
    """Return a ranked list of supply chain risk statements."""
    risks: list[str] = []

    if geo.get("flag_single_region_gt50"):
        region = geo.get("dominant_region", "unknown region")
        pct = geo.get("dominant_region_pct")
        risks.append(
            f"Geographic concentration: {pct}% revenue from {region} — "
            "tariff, FX, or geopolitical disruption could materially impair revenue."
        )

    if customer.get("estimated_concentration") == "High":
        risks.append(
            "Customer concentration: high dependence on single/few customers — "
            "contract non-renewal or budget cuts represent significant revenue risk."
        )

    tier = chokepoints.get("risk_tier")
    if tier in ("Critical", "High"):
        top_choke = (chokepoints.get("known_chokepoints") or ["N/A"])[0]
        risks.append(
            f"Sector chokepoint ({tier}): {top_choke}. "
            "Disruption could trigger production halts or extended lead-time blowouts."
        )

    geo_risk = chokepoints.get("primary_geography_risk")
    if geo_risk and geo_risk != "Not determined":
        risks.append(f"Geopolitical supply exposure: {geo_risk}.")

    if input_cost.get("cost_pressure_signal") == "Rising":
        trend = input_cost.get("cogs_trend_pct_pts")
        risks.append(
            f"Input cost pressure: COGS/revenue rising by ~{trend} ppt vs. historical avg — "
            "margin compression risk if pricing power insufficient."
        )

    if not risks:
        risks.append(
            "No dominant supply chain risks identified from available proxy data. "
            "Conduct 10-K Item 1A review for company-specific disclosures."
        )

    return risks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supply chain concentration risk assessment (proxy signals)"
    )
    parser.add_argument("ticker", help="Ticker symbol (e.g. NVDA)")
    parser.add_argument(
        "--sector",
        dest="gics_code",
        default=None,
        help="GICS industry group or sector code (e.g. 4530). "
        "Overrides yfinance sector lookup.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    try:
        import yfinance as yf
    except ImportError:
        sys.stderr.write("Error: 'yfinance' required. Run: pip install yfinance\n")
        sys.exit(1)

    stock = yf.Ticker(ticker)
    try:
        info: dict = stock.info or {}
    except Exception:
        info = {}

    income_stmt = None
    try:
        income_stmt = stock.financials  # annual income statement
    except Exception:
        pass

    # Resolve GICS code: CLI arg > yfinance sectorKey mapping
    gics_code = args.gics_code
    if not gics_code:
        # yfinance does not expose raw GICS codes directly; use sector/industry
        # heuristic mapping for the most common cases
        sector_to_gics: dict[str, str] = {
            "Technology": "4530",
            "Communication Services": "5010",
            "Consumer Cyclical": "2550",
            "Consumer Defensive": "3010",
            "Healthcare": "3520",
            "Industrials": "2010",
            "Basic Materials": "1510",
            "Energy": "1010",
            "Financial Services": "4010",
            "Real Estate": "6010",
            "Utilities": "5510",
        }
        yf_sector = info.get("sector", "")
        yf_industry = info.get("industry", "")
        # Narrow tech industries → hardware vs semis
        if yf_industry in (
            "Semiconductors",
            "Semiconductor Equipment & Materials",
            "Semiconductor Equipment",
        ):
            gics_code = "4530"
        elif yf_industry in (
            "Consumer Electronics",
            "Electronic Components",
            "Computer Hardware",
            "Communication Equipment",
        ):
            gics_code = "4520"
        elif yf_industry in ("Auto Manufacturers", "Auto Parts"):
            gics_code = "2510"
        elif yf_industry in (
            "Drug Manufacturers—General",
            "Biotechnology",
            "Pharmaceuticals",
        ):
            gics_code = "3520"
        elif yf_industry in ("Medical Devices", "Medical Instruments & Supplies"):
            gics_code = "3510"
        elif yf_industry in ("Specialty Retail", "Discount Stores", "Internet Retail"):
            gics_code = "2550"
        elif yf_industry in ("Aerospace & Defense",):
            gics_code = "2010"
        else:
            gics_code = sector_to_gics.get(yf_sector)

    geo = compute_geographic_concentration(info)
    customer = compute_customer_concentration(info, gics_code)
    chokepoints = compute_sector_chokepoints(info, gics_code)
    input_cost = compute_input_cost_analysis(income_stmt, info, gics_code)
    resilience = compute_resilience_score(geo, customer, chokepoints, input_cost, info)
    key_risks = synthesise_key_risks(geo, customer, chokepoints, input_cost, resilience)

    result = {
        "ticker": ticker,
        "sector_gics": gics_code,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "geographic_concentration": geo,
        "customer_concentration": customer,
        "sector_chokepoints": chokepoints,
        "input_cost_analysis": input_cost,
        "resilience_score": resilience,
        "key_risks": key_risks,
        "methodology": (
            "Supply chain concentration risk assessed via proxy signals: "
            "(1) geographic HHI from yfinance revenue segments where disclosed; "
            "(2) customer concentration from GICS sector prior + business description NLP; "
            "(3) sector chokepoints from GICS-mapped knowledge base (industry reports, CRS studies); "
            "(4) input cost sensitivity from COGS/revenue trend (yfinance income statement); "
            "(5) resilience score = weighted composite (geo 25%, customer 20%, "
            "chokepoints 25%, cost stability 15%, size 15%). "
            "Deep supply chain mapping requires Bloomberg SPLC or FactSet Supply Chain. "
            "All estimates are proxies — validate against 10-K Item 1A Risk Factors."
        ),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        sys.stderr.write(f"Written to {args.output}\n")
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
