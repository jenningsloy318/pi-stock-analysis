#!/usr/bin/env python3
"""Fetch macroeconomic indicators from FRED (Federal Reserve Economic Data).

Usage:
    fetch_macro.py
    fetch_macro.py --indicators CPI,GDP,UNRATE
    fetch_macro.py --output ./reports/macro.json

FRED API is free — register for a key at: https://fred.stlouisfed.org/docs/api/api_key.html
Set environment variable: FRED_API_KEY

Key indicators covered:
  - GDP, Real GDP, GDP growth rate
  - CPI, Core CPI, PCE, Core PCE (inflation)
  - Unemployment rate, labor force participation, initial claims
  - Federal Funds Rate, 10Y Treasury yield, 2Y Treasury yield, yield spread
  - ISM Manufacturing PMI, Industrial Production
  - Retail sales, housing starts, consumer sentiment
  - M2 Money Supply, Federal Debt/GDP
  - Trade-weighted USD index

Output: JSON to stdout or --output file.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' package required. Run: pip install requests\n")
    sys.exit(1)

FRED_BASE = "https://api.stlouisfed.org/fred"

# Indicator definitions: series_id → {label, unit, frequency, description}
INDICATORS = {
    # ---- GDP & Growth ----
    "GDP": {
        "series_id": "GDP",
        "label": "Gross Domestic Product",
        "unit": "Billions of Dollars",
        "frequency": "Quarterly",
        "category": "growth",
        "description": "Nominal GDP, seasonally adjusted annual rate.",
    },
    "GDPC1": {
        "series_id": "GDPC1",
        "label": "Real GDP",
        "unit": "Billions of Chained 2017 Dollars",
        "frequency": "Quarterly",
        "category": "growth",
        "description": "Real GDP, inflation-adjusted, seasonally adjusted annual rate.",
    },
    "GDPPOT": {
        "series_id": "GDPPOT",
        "label": "Potential Real GDP",
        "unit": "Billions of Chained 2017 Dollars",
        "frequency": "Quarterly",
        "category": "growth",
        "description": "CBO estimate of potential GDP — the output gap is Real GDP minus Potential GDP.",
    },
    # ---- Inflation ----
    "CPIAUCSL": {
        "series_id": "CPIAUCSL",
        "label": "CPI (All Urban Consumers)",
        "unit": "Index 1982-84=100",
        "frequency": "Monthly",
        "category": "inflation",
        "description": "Consumer Price Index for All Urban Consumers, seasonally adjusted.",
    },
    "CPILFESL": {
        "series_id": "CPILFESL",
        "label": "Core CPI (ex Food & Energy)",
        "unit": "Index 1982-84=100",
        "frequency": "Monthly",
        "category": "inflation",
        "description": "Core CPI excluding food and energy, seasonally adjusted.",
    },
    "PCEPI": {
        "series_id": "PCEPI",
        "label": "PCE Price Index",
        "unit": "Index 2017=100",
        "frequency": "Monthly",
        "category": "inflation",
        "description": "Personal Consumption Expenditures Price Index (Fed's preferred inflation measure).",
    },
    "PCEPILFE": {
        "series_id": "PCEPILFE",
        "label": "Core PCE (ex Food & Energy)",
        "unit": "Index 2017=100",
        "frequency": "Monthly",
        "category": "inflation",
        "description": "Core PCE Price Index excluding food and energy.",
    },
    "T5YIFR": {
        "series_id": "T5YIFR",
        "label": "5-Year Breakeven Inflation Rate",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "inflation",
        "description": "Market-based 5-year inflation expectation (TIPS spread).",
    },
    "T10YIE": {
        "series_id": "T10YIE",
        "label": "10-Year Breakeven Inflation Rate",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "inflation",
        "description": "Market-based 10-year inflation expectation.",
    },
    # ---- Employment ----
    "UNRATE": {
        "series_id": "UNRATE",
        "label": "Unemployment Rate",
        "unit": "Percent",
        "frequency": "Monthly",
        "category": "employment",
        "description": "Civilian unemployment rate, seasonally adjusted.",
    },
    "CIVPART": {
        "series_id": "CIVPART",
        "label": "Labor Force Participation Rate",
        "unit": "Percent",
        "frequency": "Monthly",
        "category": "employment",
        "description": "Civilian labor force participation rate.",
    },
    "ICSA": {
        "series_id": "ICSA",
        "label": "Initial Jobless Claims",
        "unit": "Number",
        "frequency": "Weekly",
        "category": "employment",
        "description": "Initial claims for unemployment insurance.",
    },
    "PAYEMS": {
        "series_id": "PAYEMS",
        "label": "Nonfarm Payrolls",
        "unit": "Thousands of Persons",
        "frequency": "Monthly",
        "category": "employment",
        "description": "Total nonfarm payroll employees, seasonally adjusted.",
    },
    # ---- Interest Rates ----
    "DFF": {
        "series_id": "DFF",
        "label": "Effective Federal Funds Rate",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "rates",
        "description": "Effective federal funds rate — the Fed's primary policy rate.",
    },
    "DGS10": {
        "series_id": "DGS10",
        "label": "10-Year Treasury Yield",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "rates",
        "description": "Market yield on U.S. Treasury securities at 10-year constant maturity.",
    },
    "DGS2": {
        "series_id": "DGS2",
        "label": "2-Year Treasury Yield",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "rates",
        "description": "Market yield on U.S. Treasury securities at 2-year constant maturity.",
    },
    "T10Y2Y": {
        "series_id": "T10Y2Y",
        "label": "10Y-2Y Treasury Spread",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "rates",
        "description": "10-year minus 2-year Treasury constant maturity spread. Negative = inversion (recession signal).",
    },
    "T10YFF": {
        "series_id": "T10YFF",
        "label": "10Y-FF Treasury Spread",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "rates",
        "description": "10-year Treasury minus Federal Funds rate spread.",
    },
    "BAA10Y": {
        "series_id": "BAA10Y",
        "label": "Moody's Baa - 10Y Treasury Spread",
        "unit": "Percent",
        "frequency": "Daily",
        "category": "rates",
        "description": "Corporate credit spread: Moody's Baa corporate bond yield minus 10Y Treasury.",
    },
    # ---- Industrial Activity ----
    "INDPRO": {
        "series_id": "INDPRO",
        "label": "Industrial Production Index",
        "unit": "Index 2017=100",
        "frequency": "Monthly",
        "category": "activity",
        "description": "Industrial production index, seasonally adjusted.",
    },
    "TCU": {
        "series_id": "TCU",
        "label": "Capacity Utilization",
        "unit": "Percent of Capacity",
        "frequency": "Monthly",
        "category": "activity",
        "description": "Total industry capacity utilization.",
    },
    "RSAFS": {
        "series_id": "RSAFS",
        "label": "Retail Sales (Total, incl. Food Services)",
        "unit": "Millions of Dollars",
        "frequency": "Monthly",
        "category": "activity",
        "description": "Advance retail sales, total (RSXFS was discontinued in 2022; RSAFS is the current series).",
    },
    "HOUST": {
        "series_id": "HOUST",
        "label": "Housing Starts",
        "unit": "Thousands of Units",
        "frequency": "Monthly",
        "category": "activity",
        "description": "New privately-owned housing units started.",
    },
    "BUSINV": {
        "series_id": "BUSINV",
        "label": "Business Inventories",
        "unit": "Millions of Dollars",
        "frequency": "Monthly",
        "category": "activity",
        "description": "Total business inventories, seasonally adjusted.",
    },
    # ---- Money & Credit ----
    "M2SL": {
        "series_id": "M2SL",
        "label": "M2 Money Supply",
        "unit": "Billions of Dollars",
        "frequency": "Monthly",
        "category": "money",
        "description": "M2 money stock, seasonally adjusted.",
    },
    "TOTRESNS": {
        "series_id": "TOTRESNS",
        "label": "Total Bank Reserves",
        "unit": "Billions of Dollars",
        "frequency": "Monthly",
        "category": "money",
        "description": "Total reserves of depository institutions.",
    },
    "GFDEBTN": {
        "series_id": "GFDEBTN",
        "label": "Federal Debt (Total Public)",
        "unit": "Millions of Dollars",
        "frequency": "Quarterly",
        "category": "fiscal",
        "description": "Total public federal debt.",
    },
    # ---- Consumer & Sentiment ----
    "UMCSENT": {
        "series_id": "UMCSENT",
        "label": "U. of Michigan Consumer Sentiment",
        "unit": "Index 1966:Q1=100",
        "frequency": "Monthly",
        "category": "sentiment",
        "description": "University of Michigan Consumer Sentiment Index.",
    },
    "USEPUINDXD": {
        "series_id": "USEPUINDXD",
        "label": "Economic Policy Uncertainty Index",
        "unit": "Index",
        "frequency": "Daily",
        "category": "sentiment",
        "description": "U.S. Economic Policy Uncertainty Index (Baker, Bloom, Davis).",
    },
    # ---- Currency & Trade ----
    "DTWEXBGS": {
        "series_id": "DTWEXBGS",
        "label": "Trade-Weighted U.S. Dollar Index (Broad)",
        "unit": "Index Jan 2006=100",
        "frequency": "Daily",
        "category": "currency",
        "description": "Broad trade-weighted U.S. dollar index (major trading partners).",
    },
    # ---- ISM PMI (from FRED) ----
    "NAPM": {
        "series_id": "NAPM",
        "label": "ISM Manufacturing PMI",
        "unit": "Index",
        "frequency": "Monthly",
        "category": "activity",
        "description": "ISM Manufacturing PMI Composite Index. >50 = expansion, <50 = contraction.",
    },
    "NMFCI": {
        "series_id": "NMFCI",
        "label": "Chicago Fed Adjusted NFCI: Nonfinancial Leverage",
        "unit": "Index",
        "frequency": "Weekly",
        "category": "credit",
        "description": "Chicago Fed Adjusted NFCI Nonfinancial Leverage Subindex. Note: this is a financial-conditions series, NOT the ISM Services PMI (which is proprietary and not on FRED).",
    },
    # ---- JOLTS (Job Openings & Labor Turnover) ----
    "JTSJOL": {
        "series_id": "JTSJOL",
        "label": "Job Openings (JOLTS)",
        "unit": "Thousands",
        "frequency": "Monthly",
        "category": "employment",
        "description": "Total nonfarm job openings from BLS JOLTS. Leading indicator for labor demand.",
    },
    "JTSQUL": {
        "series_id": "JTSQUL",
        "label": "Quits Rate (JOLTS)",
        "unit": "Percent",
        "frequency": "Monthly",
        "category": "employment",
        "description": "Quits rate from BLS JOLTS. High quits = worker confidence; low quits = fear. Leading indicator for wage inflation.",
    },
    # ---- Leading Economic Index ----
    "USSLIND": {
        "series_id": "USSLIND",
        "label": "Conference Board Leading Economic Index",
        "unit": "Index 2016=100",
        "frequency": "Monthly",
        "category": "activity",
        "description": "Composite of 10 leading indicators (claims, orders, building permits, S&P 500, etc.). 6+ months of decline signals recession.",
    },
    # ---- Bank Lending (H.8 proxy via FRED) ----
    "TOTCI": {
        "series_id": "TOTCI",
        "label": "Commercial & Industrial Loans (All Banks)",
        "unit": "Billions of Dollars",
        "frequency": "Weekly",
        "category": "money",
        "description": "Total C&I loans at all commercial banks (H.8). Rising = credit expansion; falling = tightening.",
    },
}


def fetch_series(api_key: str, series_id: str, limit: int = 12) -> list[dict]:
    """Fetch observations for a single FRED series.

    Returns list of {date, value} dicts, most recent first.
    """
    url = f"{FRED_BASE}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        observations = data.get("observations", [])
        result = []
        for obs in observations:
            val = obs.get("value", "")
            if val in ("", "."):
                continue
            try:
                num_val = float(val)
            except ValueError:
                num_val = None
            result.append({"date": obs.get("date"), "value": num_val})
        return result
    except requests.RequestException:
        return []


def compute_change(values: list[dict]) -> dict:
    """Compute period-over-period and YoY changes from sorted values (most recent first)."""
    if len(values) < 2:
        return {}
    latest = values[0]["value"]
    prior = values[1]["value"]
    if latest is not None and prior is not None and prior != 0:
        mom = (latest - prior) / abs(prior)
    else:
        mom = None

    # YoY: find value 12 months ago for monthly, 4 quarters for quarterly
    yoy = None
    if len(values) >= 12:
        yv = values[11]["value"]
        if latest is not None and yv is not None and yv != 0:
            yoy = (latest - yv) / abs(yv)
    elif len(values) >= 4:
        yv = values[3]["value"]
        if latest is not None and yv is not None and yv != 0:
            yoy = (latest - yv) / abs(yv)

    return {
        "mom_change": round(mom, 6) if mom is not None else None,
        "yoy_change": round(yoy, 6) if yoy is not None else None,
    }


def compute_macro_summary(results: dict) -> dict:
    """Derive a macro regime classification from the indicators.

    Classifies into one of Dalio's four-box quadrants:
      - Goldilocks: rising growth + falling/stable inflation
      - Reflation: rising growth + rising inflation
      - Stagflation: falling growth + rising inflation
      - Deflation: falling growth + falling inflation

    Returns regime classification and key signals.
    """
    keys = results.get("indicators", {})

    # Extract latest values
    gdp = next((d for d in keys.get("GDPC1", {}).get("data", [])), None)
    cpi = next((d for d in keys.get("CPIAUCSL", {}).get("data", [])), None)
    unrate = next((d for d in keys.get("UNRATE", {}).get("data", [])), None)
    fedfunds = next((d for d in keys.get("DFF", {}).get("data", [])), None)
    dgs10 = next((d for d in keys.get("DGS10", {}).get("data", [])), None)
    spread = next((d for d in keys.get("T10Y2Y", {}).get("data", [])), None)
    pmi = next((d for d in keys.get("NAPM", {}).get("data", [])), None)

    gdp_val = gdp["value"] if gdp else None
    cpi_val = cpi["value"] if cpi else None
    unrate_val = unrate["value"] if unrate else None
    ff_val = fedfunds["value"] if fedfunds else None
    yield10_val = dgs10["value"] if dgs10 else None
    spread_val = spread["value"] if spread else None
    pmi_val = pmi["value"] if pmi else None

    # Growth assessment
    gdp_mom = keys.get("GDPC1", {}).get("mom_change")
    growth_rising = gdp_mom is not None and gdp_mom > 0

    # Inflation assessment
    cpi_yoy = keys.get("CPIAUCSL", {}).get("yoy_change")
    inflation_rising = (
        cpi_yoy is not None and cpi_yoy > 0.02
    )  # >2% YoY is rising concern
    inflation_falling = cpi_yoy is not None and cpi_yoy < 0

    # Regime determination
    if growth_rising and not inflation_rising:
        regime = "goldilocks"
        label = "Goldilocks (Rising Growth + Stable/Low Inflation)"
    elif growth_rising and inflation_rising:
        regime = "reflation"
        label = "Reflation (Rising Growth + Rising Inflation)"
    elif not growth_rising and inflation_rising:
        regime = "stagflation"
        label = "Stagflation (Falling Growth + Rising Inflation)"
    else:
        regime = "deflation"
        label = "Deflationary (Falling Growth + Falling/Low Inflation)"

    # Recession signal
    yield_inverted = spread_val is not None and spread_val < 0
    pmi_contraction = pmi_val is not None and pmi_val < 50
    recession_risk = (
        "high"
        if (yield_inverted and pmi_contraction)
        else "elevated"
        if (yield_inverted or pmi_contraction)
        else "low"
    )

    # Services PMI not available on FRED for free; field intentionally unset to
    # avoid mislabeling another series as Services PMI. Manufacturing PMI (NAPM)
    # remains the activity proxy.
    services_pmi_val = None
    services_contraction = False

    # JOLTS indicators
    jolts_openings = next((d for d in keys.get("JTSJOL", {}).get("data", [])), None)
    jolts_quits = next((d for d in keys.get("JTSQUL", {}).get("data", [])), None)
    jolts_openings_val = jolts_openings["value"] if jolts_openings else None
    jolts_quits_val = jolts_quits["value"] if jolts_quits else None
    labor_market_tight = jolts_quits_val is not None and jolts_quits_val > 2.5

    # Leading Economic Index
    lei = next((d for d in keys.get("USSLIND", {}).get("data", [])), None)
    lei_val = lei["value"] if lei else None
    lei_mom = keys.get("USSLIND", {}).get("mom_change")
    lei_declining = lei_mom is not None and lei_mom < 0

    # C&I Loans (credit expansion/contraction)
    ci_loans = next((d for d in keys.get("TOTCI", {}).get("data", [])), None)
    ci_loans_val = ci_loans["value"] if ci_loans else None
    ci_loans_yoy = keys.get("TOTCI", {}).get("yoy_change")
    credit_contracting = ci_loans_yoy is not None and ci_loans_yoy < 0

    return {
        "macro_regime": regime,
        "macro_regime_label": label,
        "dalio_quadrant": {
            "growth_rising": growth_rising,
            "inflation_rising": inflation_rising,
            "quadrant": regime,
        },
        "key_levels": {
            "gdp_real": gdp_val,
            "cpi": cpi_val,
            "unemployment_rate": unrate_val,
            "fed_funds_rate": ff_val,
            "ten_year_yield": yield10_val,
            "ten_two_spread": spread_val,
            "yield_curve_inverted": yield_inverted,
            "ism_manufacturing_pmi": pmi_val,
            "ism_services_pmi": services_pmi_val,
            "pmi_contraction": pmi_contraction,
            "services_contraction": services_contraction,
        },
        "labor_market": {
            "unemployment_rate": unrate_val,
            "jolts_openings_thousands": jolts_openings_val,
            "jolts_quits_rate": jolts_quits_val,
            "labor_market_tight": labor_market_tight,
            "wage_pressure_signal": labor_market_tight,
        },
        "leading_indicators": {
            "lei_value": lei_val,
            "lei_declining": lei_declining,
            "lei_note": "6+ consecutive monthly declines historically precede recession.",
            "ci_loans_billions": ci_loans_val,
            "credit_contracting": credit_contracting,
        },
        "recession_risk": recession_risk,
        "recession_signals": {
            "yield_curve_inverted": yield_inverted,
            "manufacturing_pmi_below_50": pmi_contraction,
            "services_pmi_below_50": services_contraction,
            "lei_declining": lei_declining,
            "credit_contracting": credit_contracting,
            "unemployment_rising": unrate_val is not None
            and keys.get("UNRATE", {}).get("mom_change", 0) > 0.003,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch macroeconomic indicators from FRED"
    )
    parser.add_argument(
        "--indicators",
        help="Comma-separated indicator keys to fetch (default: all). Use --list to see available.",
        default=",".join(INDICATORS.keys()),
    )
    parser.add_argument(
        "--list", action="store_true", help="List available indicators and exit"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--api-key-env",
        default="FRED_API_KEY",
        help="Environment variable name for FRED API key (default: FRED_API_KEY)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=24,
        help="Number of observations per series (default: 24)",
    )
    args = parser.parse_args()

    if args.list:
        print("Available FRED Indicators:")
        print(f"{'Key':<20} {'Label':<50} {'Freq':<12}")
        print("-" * 85)
        for key, info in INDICATORS.items():
            print(f"{key:<20} {info['label']:<50} {info['frequency']:<12}")
        sys.exit(0)

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        sys.stderr.write(
            f"Error: FRED API key not found in ${args.api_key_env}.\n"
            "Register for a free key at: https://fred.stlouisfed.org/docs/api/api_key.html\n"
            f"Then set: export {args.api_key_env}=your_key_here\n"
        )
        sys.exit(1)

    requested = [
        k.strip() for k in args.indicators.split(",") if k.strip() in INDICATORS
    ]
    unknown = [
        k.strip()
        for k in args.indicators.split(",")
        if k.strip() and k.strip() not in INDICATORS
    ]
    if unknown:
        sys.stderr.write(f"Warning: Unknown indicators ignored: {unknown}\n")

    if not requested:
        sys.stderr.write("Error: No valid indicators specified.\n")
        sys.exit(1)

    result = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "fred",
        "indicators": {},
    }

    for key in requested:
        info = INDICATORS[key]
        data = fetch_series(api_key, info["series_id"], args.limit)
        changes = compute_change(data)
        result["indicators"][key] = {
            "series_id": info["series_id"],
            "label": info["label"],
            "unit": info["unit"],
            "frequency": info["frequency"],
            "category": info["category"],
            "description": info["description"],
            "latest_value": data[0]["value"] if data else None,
            "latest_date": data[0]["date"] if data else None,
            "mom_change": changes.get("mom_change"),
            "yoy_change": changes.get("yoy_change"),
            "data": data[:12],  # keep last 12 observations for context
        }
        # FRED free tier: 120 req/min → ~0.5s between requests
        time.sleep(0.6)

    # Derive macro regime classification
    result["macro_summary"] = compute_macro_summary(result)

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
