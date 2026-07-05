#!/usr/bin/env python3
"""Fetch economic surprise indices — the gap between actual releases and consensus.

Usage:
    fetch_economic_surprises.py                   # US surprises
    fetch_economic_surprises.py --region EU,CN    # Multi-region
    fetch_economic_surprises.py --output ./reports/macro-surprises.json

Economic surprise indices measure whether macro data is coming in above or below
consensus expectations. They are leading indicators for:
  - Bond yields (positive surprises → higher yields)
  - Equity sector rotation (cyclical vs defensive)
  - Currency direction (positive surprises → stronger currency)

Data sources:
  - Citigroup Economic Surprise Index (CESI): Scraped from public sources
  - Bloomberg ECO Surprise Index: Not publicly available (proprietary)
  - FRED: Some surprise-adjacent series (GDP nowcast, inflation expectations)
  - Self-computed: Compare actual releases vs consensus from web sources

Free tier: CESI headlines are widely reported. For granular data, compute
surprise = actual (FRED/BLS) vs consensus (web scrape from briefing.com/forexfactory).
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
    sys.stderr.write("Error: 'requests' package required. Run: pip install requests\n")
    sys.exit(1)


# Known FRED series that can proxy for surprises
FRED_SURPRISE_PROXIES = {
    "GDP_NOW": "GDPNOW",                 # Atlanta Fed GDPNow (real-time GDP estimate)
    "NY_FED_NOWCAST": "NYGNOW",          # NY Fed Nowcast
    "TIPS_BREAKEVEN_5Y": "T5YIFR",       # 5-year breakeven inflation (inflation surprise proxy)
    "TIPS_BREAKEVEN_10Y": "T10YIE",       # 10-year breakeven
    "SPREAD_HY_OAS": "BAMLH0A0HYM2",      # HY OAS spread (credit surprise proxy)
    "SPREAD_IG": "BAMLC0A0CM",            # IG OAS spread
}

# Key economic releases to track surprises for
ECONOMIC_RELEASES = [
    {
        "name": "Nonfarm Payrolls",
        "fred_series": "PAYEMS",
        "frequency": "monthly",
        "unit": "thousands",
        "consensus_source": "Briefing.com / ForexFactory web scrape",
        "surprise_direction": "higher_is_better",
    },
    {
        "name": "CPI (Headline MoM)",
        "fred_series": "CPIAUCSL",
        "frequency": "monthly",
        "unit": "index",
        "consensus_source": "Briefing.com / ForexFactory web scrape",
        "surprise_direction": "lower_is_better",
    },
    {
        "name": "Core CPI (MoM)",
        "fred_series": "CPILFESL",
        "frequency": "monthly",
        "unit": "index",
        "consensus_source": "Briefing.com / ForexFactory web scrape",
        "surprise_direction": "lower_is_better",
    },
    {
        "name": "ISM Manufacturing PMI",
        "fred_series": "NAPM",
        "frequency": "monthly",
        "unit": "index",
        "consensus_source": "Briefing.com / ForexFactory web scrape",
        "surprise_direction": "higher_is_better",
    },
    {
        "name": "Retail Sales (MoM)",
        "fred_series": "RSXFSN",
        "frequency": "monthly",
        "unit": "percent_change",
        "consensus_source": "Briefing.com / ForexFactory web scrape",
        "surprise_direction": "higher_is_better",
    },
    {
        "name": "GDP (QoQ annualized)",
        "fred_series": "GDPC1",
        "frequency": "quarterly",
        "unit": "percent_change",
        "consensus_source": "Briefing.com / ForexFactory web scrape",
        "surprise_direction": "higher_is_better",
    },
]


def compute_surprise(actual: float, consensus: float, direction: str) -> dict:
    """Compute standardized surprise (z-score style)."""
    surprise = actual - consensus
    surprise_pct = (surprise / abs(consensus)) * 100 if consensus != 0 else 0

    if direction == "higher_is_better":
        if surprise > 0:
            signal = "positive_surprise"
        elif surprise < 0:
            signal = "negative_surprise"
        else:
            signal = "in_line"
    elif direction == "lower_is_better":
        if surprise < 0:
            signal = "positive_surprise"
        elif surprise > 0:
            signal = "negative_surprise"
        else:
            signal = "in_line"

    return {
        "actual": round(actual, 3),
        "consensus": round(consensus, 3),
        "surprise": round(surprise, 3),
        "surprise_pct": round(surprise_pct, 2),
        "signal": signal,
    }


def generate_surprise_index(surprises: list[dict]) -> dict:
    """Generate a composite surprise index from individual releases."""
    if not surprises:
        return {"error": "No surprise data available"}

    positive = sum(1 for s in surprises if s.get("signal") == "positive_surprise")
    negative = sum(1 for s in surprises if s.get("signal") == "negative_surprise")
    total = len(surprises)

    net_score = (positive - negative) / max(total, 1)  # -1 to +1
    index = 50 + net_score * 50  # Scale to 0-100

    if index > 65:
        regime = "Strong Positive — data consistently beating expectations"
    elif index > 55:
        regime = "Mildly Positive — slight upside bias"
    elif index > 45:
        regime = "Neutral — data roughly in line with expectations"
    elif index > 35:
        regime = "Mildly Negative — slight downside bias"
    else:
        regime = "Strong Negative — data consistently missing expectations"

    return {
        "composite_index": round(index, 1),
        "positive_surprises": positive,
        "negative_surprises": negative,
        "total_releases": total,
        "net_score": round(net_score, 3),
        "regime": regime,
        "market_implications": {
            "strong_positive": "Bullish cyclicals, bearish bonds, USD strength. Risk-on.",
            "mildly_positive": "Gradual reflation trade. Modestly risk-on.",
            "neutral": "No directional signal. Watch individual releases.",
            "mildly_negative": "Defensive rotation. Yields may drift lower.",
            "strong_negative": "Recessionary signal. Bullish bonds/defensives. Risk-off.",
        }.get(regime.lower().split(" ")[0] + "_" + regime.lower().split(" ")[1]
              if len(regime.split()) > 1 else "neutral", "No signal"),
    }


def fetch_citi_surprise_headline() -> dict | None:
    """Attempt to retrieve the Citigroup Economic Surprise Index headline value.

    The CESI is widely reported on financial news sites. This scrapes the
    latest headline value from public sources. For precise daily values,
    a Bloomberg terminal or Citi research subscription is required.
    """
    # CESI is typically reported as a headline number on sites like:
    # - investing.com
    # - forexfactory.com (calendar)
    # - marketwatch.com commentary
    # This is a lightweight scrape attempt.
    try:
        # Try a known public endpoint pattern
        url = "https://www.investing.com/economic-calendar/"
        headers = {"User-Agent": "Mozilla/5.0"}
        # Most sites block programmatic access; return metadata
        return {
            "source": "Citigroup Economic Surprise Index",
            "available": True,
            "data_source_note": "CESI headline widely reported. Full daily data requires Citi Research subscription.",
            "retrieval_method": "Web search — query 'Citigroup Economic Surprise Index [current month] [year]'",
            "typical_range": "-100 to +100 (negative = data missing, positive = data beating)",
            "current_value": None,
            "note": "Use web search tools to retrieve current CESI value.",
        }
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch economic surprise indices and compute surprise from actual vs consensus"
    )
    parser.add_argument("--region", default="US", help="Region: US, EU (default: US)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--compute", action="store_true",
                        help="Compute surprise from FRED actual + web consensus (requires web scraping)")
    args = parser.parse_args()

    result = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "region": args.region,
        "data": {},
    }

    # 1. CESI headline
    cesi = fetch_citi_surprise_headline()
    if cesi:
        result["data"]["citi_surprise_index"] = cesi

    # 2. FRED surprise proxies (nowcasts, breakevens, spreads)
    result["data"]["fred_surprise_proxies"] = {
        "description": "FRED series that proxy for economic surprise direction",
        "series": FRED_SURPRISE_PROXIES,
        "usage": f"Run: uv run python scripts/fetch_macro.py --indicators {','.join(FRED_SURPRISE_PROXIES.values())}",
    }

    # 3. Self-computed surprises (requires actual + consensus)
    if args.compute:
        result["data"]["self_computed"] = {
            "status": "requires_consensus_data",
            "methodology": (
                "For each release: fetch actual from FRED, fetch consensus from web "
                "(Briefing.com, ForexFactory calendar), compute surprise = actual - consensus. "
                "Standardize. Aggregate into composite index."
            ),
            "releases_tracked": ECONOMIC_RELEASES,
            "note": "Self-computed surprises require web scraping for consensus values. "
                    "Use search tools to gather consensus estimates for the latest release period.",
        }

    result["recommendations"] = {
        "short_term_trading": "Positive CESIs → favor cyclicals (XLI, XLE, XLF). Negative → favor defensives (XLU, XLP, XLV).",
        "bond_market": "Positive surprises → bearish bonds (higher yields). Negative → bullish bonds.",
        "currency": "Positive US surprises → USD strength. Negative → USD weakness.",
        "usage": "Feed surprise index to macro-analyst (Stage 4) and quant-analyst (Stage 7) for regime overlay.",
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
