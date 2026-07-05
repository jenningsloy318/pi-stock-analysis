#!/usr/bin/env python3
"""Fetch global macroeconomic indicators for non-US economies.

Usage:
    fetch_global_macro.py --regions EU,CN,JP,UK --output ./reports/global-macro.json
    fetch_global_macro.py --regions EU --indicators GDP,CPI,RATE,PMI
    fetch_global_macro.py --all

Covers: Eurozone (ECB SDW), China (PBOC/NBS via akshare), Japan (BOJ/e-stat),
United Kingdom (ONS/BoE), and international aggregates (IMF/OECD via World Bank API).

Data categories per region:
  - GDP: Real GDP growth (YoY), GDP level
  - CPI: Consumer price inflation (headline, core)
  - RATE: Policy rate, 10-year government bond yield
  - PMI: Manufacturing PMI, Services PMI
  - EMPLOY: Unemployment rate
  - TRADE: Current account balance, exports/imports growth
  - FX: Exchange rate vs USD

All sources are free/public APIs. No API key required.
Explicitly state data freshness and source for every data point.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' package required. Run: pip install requests\n")
    sys.exit(1)

# ---------------------------------------------------------------------------
# World Bank API (GDP, CPI, unemployment, trade for all countries)
# ---------------------------------------------------------------------------

WB_BASE = "https://api.worldbank.org/v2"

# World Bank indicator codes
WB_INDICATORS = {
    # --- Core macro (default category) ---
    "GDP": "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
    "GDP_USD": "NY.GDP.MKTP.CD",  # GDP (current US$)
    "CPI": "FP.CPI.TOTL.ZG",  # Inflation, consumer prices (annual %)
    "UNEMPLOY": "SL.UEM.TOTL.ZS",  # Unemployment, total (% of labor force)
    "CURRENT_ACCOUNT": "BN.CAB.XOKA.GD.ZS",  # Current account balance (% of GDP)
    "EXPORTS_GROWTH": "NE.EXP.GNFS.ZS",  # Exports of goods and services (annual % growth)
    "IMPORTS_GROWTH": "NE.IMP.GNFS.ZS",  # Imports of goods and services (annual % growth)
    "FDI": "BX.KLT.DINV.WD.GD.ZS",  # Foreign direct investment, net inflows (% of GDP)
    # --- Demographics (Japan-thesis flip detection; long-term TAM) ---
    "POP_GROWTH": "SP.POP.GROW",  # Population growth (annual %)
    "WORKING_AGE_PCT": "SP.POP.1564.TO.ZS",  # Population ages 15-64 (% of total)
    "URBAN_PCT": "SP.URB.TOTL.IN.ZS",  # Urban population (% of total)
    # --- Innovation / human capital (country-level moat proxy) ---
    "RD_PCT_GDP": "GB.XPD.RSDV.GD.ZS",  # R&D expenditure (% of GDP)
    "TERTIARY_ENROLL": "SE.TER.ENRR",  # Tertiary enrollment (% gross)
    # --- Trade openness (tariff exposure / supply-chain risk) ---
    "TRADE_PCT_GDP": "NE.TRD.GNFS.ZS",  # Trade (% of GDP)
    "HIGH_TECH_EXPORTS": "TX.VAL.TECH.MF.ZS",  # High-tech exports (% of manufactured exports)
    # --- Infrastructure / digital saturation (TAM ceiling for SaaS / digital) ---
    "INTERNET_USERS_PCT": "IT.NET.USER.ZS",  # Individuals using the Internet (% of population)
    "MOBILE_PER_100": "IT.CEL.SETS.P2",  # Mobile cellular subscriptions (per 100 people)
    "ELECTRICITY_PER_CAPITA": "EG.USE.ELEC.KH.PC",  # Electric power consumption (kWh per capita)
    # --- Energy / commodities (supply-chain / carbon-pricing risk) ---
    "ENERGY_PER_GDP": "EG.USE.COMM.GD.PP.KD",  # Energy use per $1,000 GDP (PPP, kg of oil eq)
    "CO2_PER_GDP": "EN.GHG.CO2.RT.GDP.PP",  # CO2 emissions per GDP (PPP)
    # --- Financial depth (liquidity floor; per-country Buffett ratio) ---
    "PRIVATE_CREDIT_PCT_GDP": "FS.AST.PRVT.GD.ZS",  # Domestic credit to private sector (% of GDP)
    "MARKET_CAP_PCT_GDP": "CM.MKT.LCAP.GD.ZS",  # Market cap of listed domestic companies (% GDP)
    # --- Sovereign / fiscal risk ---
    "GOV_DEBT_PCT_GDP": "GC.DOD.TOTL.GD.ZS",  # Central gov debt, total (% of GDP)
}

# Category groupings — used by --categories CLI flag to keep token cost low
WB_INDICATOR_CATEGORIES: dict[str, list[str]] = {
    "core": [
        "GDP",
        "GDP_USD",
        "CPI",
        "UNEMPLOY",
        "CURRENT_ACCOUNT",
        "EXPORTS_GROWTH",
        "IMPORTS_GROWTH",
        "FDI",
    ],
    "demographics": ["POP_GROWTH", "WORKING_AGE_PCT", "URBAN_PCT"],
    "innovation": ["RD_PCT_GDP", "TERTIARY_ENROLL"],
    "trade": ["TRADE_PCT_GDP", "HIGH_TECH_EXPORTS"],
    "infrastructure": [
        "INTERNET_USERS_PCT",
        "MOBILE_PER_100",
        "ELECTRICITY_PER_CAPITA",
    ],
    "energy": ["ENERGY_PER_GDP", "CO2_PER_GDP"],
    "financial": ["PRIVATE_CREDIT_PCT_GDP", "MARKET_CAP_PCT_GDP"],
    "sovereign": ["GOV_DEBT_PCT_GDP"],
}

# ISO3 country codes
REGION_COUNTRIES = {
    "EU": ["DEU", "FRA", "ITA", "ESP", "NLD", "BEL", "AUT"],  # Eurozone majors
    "CN": ["CHN"],
    "JP": ["JPN"],
    "UK": ["GBR"],
    "KR": ["KOR"],
    "IN": ["IND"],
    "BR": ["BRA"],
    "CA": ["CAN"],
    "AU": ["AUS"],
    "CH": ["CHE"],
}


def fetch_world_bank(
    indicator: str, country: str, date_range: str = "2018:2026"
) -> dict | None:
    """Fetch a World Bank indicator for a country."""
    url = f"{WB_BASE}/country/{country}/indicator/{indicator}"
    params = {"format": "json", "date": date_range, "per_page": 20}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) >= 2 and data[1]:
                values = []
                for entry in data[1]:
                    if entry.get("value") is not None:
                        values.append(
                            {
                                "year": entry["year"],
                                "value": round(float(entry["value"]), 3),
                            }
                        )
                if values:
                    return {
                        "indicator_name": data[1][0]
                        .get("indicator", {})
                        .get("value", indicator),
                        "country": country,
                        "values": sorted(values, key=lambda x: x["year"], reverse=True),
                    }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# ECB SDW (Statistical Data Warehouse) — Eurozone
# ---------------------------------------------------------------------------

ECB_BASE = "https://sdw-wsrest.ecb.europa.eu/service"

ECB_SERIES = {
    "GDP_Q": "MNA.Q.Y.I8.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N",  # Eurozone GDP (chain-linked)
    "HICP": "ICP.M.U2.N.000000.4.INX",  # Eurozone HICP (headline)
    "HICP_CORE": "ICP.M.U2.N.0000X0.4.INX",  # Eurozone HICP (core)
    "UNEMPLOY": "STS.M.I8.S.UNEH.RTT000.4.000",  # Eurozone unemployment rate
    "PMI_MFG": None,  # PMI is from Markit, not ECB — use web search
    "PMI_SVC": None,
}


def fetch_ecb_series(series_key: str, last_n: int = 12) -> dict | None:
    """Fetch a time series from the ECB SDW REST API."""
    if ECB_SERIES.get(series_key) is None:
        return None

    url = f"{ECB_BASE}/data/{ECB_SERIES[series_key]}"
    params = {
        "format": "jsondata",
        "detail": "dataonly",
        "startPeriod": f"{datetime.now().year - 3}",
        "endPeriod": f"{datetime.now().year}",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            observations = []
            dims = (
                data.get("structure", {}).get("dimensions", {}).get("observation", [])
            )
            time_dim = next((d for d in dims if d.get("id") == "TIME_PERIOD"), None)
            time_values = time_dim.get("values", []) if time_dim else []

            # ECB SDW observation keys are dimension-index strings like "0:0:0".
            # The trailing index is the TIME_PERIOD position. Parse it explicitly
            # rather than relying on dict-iteration order.
            obs_dict = data.get("dataSets", [{}])[0].get("observations", {})
            parsed_obs = []
            for key, val in obs_dict.items():
                if not (isinstance(val, list) and val and val[0] is not None):
                    continue
                try:
                    time_idx = int(str(key).split(":")[-1])
                except (ValueError, IndexError):
                    continue
                if 0 <= time_idx < len(time_values):
                    period = time_values[time_idx].get("id", "")
                else:
                    period = ""
                parsed_obs.append(
                    (time_idx, {"period": period, "value": round(float(val[0]), 3)})
                )

            parsed_obs.sort(key=lambda p: p[0])
            observations = [obs for _, obs in parsed_obs]

            if observations:
                return {
                    "series": series_key,
                    "source": "ECB SDW",
                    "observations": observations[-last_n:],
                }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Eurostat API — European statistics
# ---------------------------------------------------------------------------

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

EUROSTAT_DATASETS = {
    "GDP_GROWTH": "nama_10_gdp",  # GDP and main components
    "CPI": "prc_hicp_manr",  # HICP - monthly data (annual rate of change)
    "UNEMPLOY": "une_rt_m",  # Unemployment by sex and age - monthly average
    "INDUSTRIAL_PROD": "sts_inpr_m",  # Industrial production
    "RETAIL_TRADE": "sts_trtu_m",  # Retail trade turnover
}


def fetch_eurostat(dataset: str, params: dict | None = None) -> dict | None:
    """Fetch data from Eurostat JSON API."""
    url = f"{EUROSTAT_BASE}/{dataset}"
    p = {"format": "JSON", "lang": "en"}
    if params:
        p.update(params)
    try:
        resp = requests.get(url, params=p, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# OECD API — advanced economies
# ---------------------------------------------------------------------------

OECD_BASE = "https://stats.oecd.org/SDMX-JSON/data"

OECD_DATASETS = {
    "LEI": "MEI_CLI",  # Composite Leading Indicators
    "GDP_GROWTH": "QNA",  # Quarterly National Accounts
    "CPI": "MEI_PRICES",  # Consumer prices
    "UNEMPLOY": "MEI_LABOUR",  # Labour market statistics
}


def fetch_oecd(dataset: str, country: str, indicator: str) -> dict | None:
    """Fetch data from OECD SDMX-JSON API."""
    url = f"{OECD_BASE}/{dataset}/{indicator}.{country}.all"
    params = {
        "startTime": f"{datetime.now().year - 3}",
        "endTime": f"{datetime.now().year}",
        "format": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Central bank policy rates (manual, updated periodically)
# ---------------------------------------------------------------------------


def get_policy_rates() -> dict:
    """Return current policy rates for major central banks.

    These are approximate and should be verified against web search for precision.
    """
    return {
        "ecb_main_refinancing_rate": {
            "source": "ECB",
            "rate": None,  # Requires web scrape or live API
            "note": "Retrieve from ECB press release or web search for exact current rate.",
        },
        "pboc_1y_mlf": {
            "source": "PBOC",
            "rate": None,
            "note": "PBOC Medium-term Lending Facility (MLF) 1-year rate.",
        },
        "boj_policy_rate": {
            "source": "BOJ",
            "rate": None,
            "note": "BOJ short-term policy interest rate.",
        },
        "boe_bank_rate": {
            "source": "BoE",
            "rate": None,
            "note": "Bank of England Bank Rate.",
        },
    }


# ---------------------------------------------------------------------------
# Regional macro aggregation
# ---------------------------------------------------------------------------


def fetch_region_data(region: str, indicator_keys: list[str] | None = None) -> dict:
    """Fetch macro indicators for a region.

    indicator_keys: subset of WB_INDICATORS keys to fetch. Default = all.
    Use WB_INDICATOR_CATEGORIES to scope (e.g., ["core","demographics"]).
    """
    result = {
        "region": region,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "indicators": {},
        "sources_used": [],
    }

    countries = REGION_COUNTRIES.get(region, [])

    selected = indicator_keys if indicator_keys else list(WB_INDICATORS.keys())

    # World Bank data for each indicator
    for indicator_name in selected:
        indicator_code = WB_INDICATORS.get(indicator_name)
        if not indicator_code:
            continue
        region_values = {}
        for country in countries:
            wb_data = fetch_world_bank(indicator_code, country)
            if wb_data:
                latest = wb_data["values"][0] if wb_data["values"] else None
                if latest:
                    region_values[country] = latest

        if region_values:
            result["indicators"][indicator_name.lower()] = region_values
            result["sources_used"].append("World Bank API")

    # ECB/Eurostat for Eurozone
    if region == "EU":
        for series_key in ["GDP_Q", "HICP", "UNEMPLOY"]:
            ecb_data = fetch_ecb_series(series_key)
            if ecb_data:
                result["indicators"][f"ecb_{series_key.lower()}"] = ecb_data
                result["sources_used"].append("ECB SDW")

    # Policy rates
    rates = get_policy_rates()
    region_rates = {}
    mapping = {
        "EU": "ecb_main_refinancing_rate",
        "CN": "pboc_1y_mlf",
        "JP": "boj_policy_rate",
        "UK": "boe_bank_rate",
    }
    rate_key = mapping.get(region)
    if rate_key:
        region_rates[rate_key] = rates.get(rate_key, {})
    if region_rates:
        result["indicators"]["policy_rates"] = region_rates

    # Data freshness summary
    result["data_freshness"] = {
        "world_bank": "Annual (lag: 3-12 months depending on indicator)",
        "ecb_sdw": "Monthly/Quarterly (lag: 1-2 months)",
        "eurostat": "Monthly (lag: 1-3 months)",
        "policy_rates": "Real-time (central bank announcements)",
    }

    return result


# ---------------------------------------------------------------------------
# Cross-region comparison table
# ---------------------------------------------------------------------------


def generate_comparison(all_data: dict) -> dict:
    """Generate a cross-region comparison of key macro indicators."""
    comparison = {}

    gdp_map = {}
    cpi_map = {}
    unemployment_map = {}

    for region, data in all_data.items():
        indicators = data.get("indicators", {})
        # GDP from World Bank
        gdp_data = indicators.get("gdp", {})
        cpi_data = indicators.get("cpi", {})
        unemp_data = indicators.get("unemploy", {})

        for country, vals in gdp_data.items():
            gdp_map[f"{region}/{country}"] = vals

        for country, vals in cpi_data.items():
            cpi_map[f"{region}/{country}"] = vals

        for country, vals in unemp_data.items():
            unemployment_map[f"{region}/{country}"] = vals

    comparison = {
        "gdp_growth": gdp_map,
        "inflation": cpi_map,
        "unemployment": unemployment_map,
    }

    return comparison


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fetch global macroeconomic indicators from free/public APIs"
    )
    parser.add_argument(
        "--regions",
        default="EU,CN,JP,UK",
        help="Comma-separated region codes: EU,CN,JP,UK,KR,IN,BR,CA,AU,CH",
    )
    parser.add_argument(
        "--all", action="store_true", help="Fetch all available regions"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--comparison",
        action="store_true",
        help="Also generate cross-region comparison table",
    )
    parser.add_argument(
        "--categories",
        default="core,demographics,trade",
        help=(
            "Comma-separated WB indicator categories to fetch. Default keeps token "
            "cost low. Available: "
            + ",".join(WB_INDICATOR_CATEGORIES.keys())
            + ". Use 'all' for every indicator."
        ),
    )
    args = parser.parse_args()

    if args.all:
        regions = list(REGION_COUNTRIES.keys())
    else:
        regions = [
            r.strip().upper()
            for r in args.regions.split(",")
            if r.strip().upper() in REGION_COUNTRIES
        ]

    if not regions:
        print("Error: No valid regions specified.", file=sys.stderr)
        print(f"Available: {', '.join(REGION_COUNTRIES.keys())}", file=sys.stderr)
        sys.exit(1)

    # Resolve --categories to a flat list of indicator keys
    if args.categories.strip().lower() == "all":
        indicator_keys: list[str] = list(WB_INDICATORS.keys())
    else:
        requested = [c.strip().lower() for c in args.categories.split(",") if c.strip()]
        indicator_keys = []
        for cat in requested:
            keys = WB_INDICATOR_CATEGORIES.get(cat)
            if keys is None:
                print(
                    f"Warning: unknown category '{cat}'. Available: "
                    f"{', '.join(WB_INDICATOR_CATEGORIES.keys())}",
                    file=sys.stderr,
                )
                continue
            indicator_keys.extend(keys)

    result = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "regions": regions,
        "wb_categories": (
            "all" if args.categories.strip().lower() == "all" else args.categories
        ),
        "wb_indicators_fetched": indicator_keys,
        "data": {},
    }

    for region in regions:
        result["data"][region] = fetch_region_data(region, indicator_keys)

    if args.comparison:
        result["cross_region_comparison"] = generate_comparison(result["data"])

    result["notes"] = {
        "data_freshness": {
            "world_bank": "Annual data, lag 3-12 months. Suitable for long-term analysis.",
            "ecb_sdw": "Monthly/quarterly, lag 1-2 months. Suitable for mid-term macro assessment.",
            "policy_rates": "Real-time from central bank announcements. Requires web search for exact current value.",
        },
        "limitations": [
            "PMI data requires Markit/S&P Global subscription — use web search fallback.",
            "China data from World Bank has longer lag than NBS releases — cross-reference with akshare.",
            "Policy rates shown as None — fetch from central bank press releases via web search.",
            "Not a substitute for Bloomberg/Refinitiv terminal. Directional indicator for non-US macro regime.",
        ],
        "usage": "Feed this data to the macro-analyst agent for non-US company analysis.",
    }

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
