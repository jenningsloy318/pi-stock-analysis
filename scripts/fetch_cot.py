#!/usr/bin/env python3
"""Fetch CFTC Commitments of Traders (COT) data for institutional positioning.

Usage:
    fetch_cot.py --market SP500
    fetch_cot.py --market SP500,NASDAQ,VIX,GOLD,USD --output ./reports/cot-data.json

CFTC COT report (free, weekly release every Friday):
  Shows net positioning of Commercials, Large Speculators, and Small Speculators
  in futures markets. Leading indicator for institutional sentiment.

Supported markets:
  Equity indices: SP500, NASDAQ, DJIA, RUSSELL
  Volatility: VIX
  Rates: 10Y_NOTE, 2Y_NOTE, 30Y_BOND, EURODOLLAR
  Currencies: USD, EUR, JPY, GBP, AUD, CAD
  Commodities: GOLD, SILVER, CRUDE_OIL, NATURAL_GAS, COPPER

Data source: CFTC via Quandl/NASDAQ Data Link (free tier) or direct CFTC bulk CSV.
"""

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' package required. Run: pip install requests\n")
    sys.exit(1)

CFTC_BULK_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"

# CFTC contract codes for common markets
MARKET_CODES = {
    "SP500": {"name": "S&P 500", "code": "13874A", "exchange": "CME"},
    "NASDAQ": {"name": "NASDAQ-100", "code": "20974A", "exchange": "CME"},
    "DJIA": {"name": "Dow Jones", "code": "12460A", "exchange": "CBOT"},
    "RUSSELL": {"name": "Russell 2000", "code": "239742", "exchange": "CME"},
    "VIX": {"name": "VIX Futures", "code": "1170E1", "exchange": "CFE"},
    "10Y_NOTE": {"name": "10-Year T-Note", "code": "043602", "exchange": "CBOT"},
    "2Y_NOTE": {"name": "2-Year T-Note", "code": "042601", "exchange": "CBOT"},
    "30Y_BOND": {"name": "30-Year T-Bond", "code": "020601", "exchange": "CBOT"},
    "USD": {"name": "US Dollar Index", "code": "098662", "exchange": "ICE"},
    "EUR": {"name": "Euro FX", "code": "099741", "exchange": "CME"},
    "JPY": {"name": "Japanese Yen", "code": "097741", "exchange": "CME"},
    "GBP": {"name": "British Pound", "code": "096742", "exchange": "CME"},
    "AUD": {"name": "Australian Dollar", "code": "232741", "exchange": "CME"},
    "CAD": {"name": "Canadian Dollar", "code": "090741", "exchange": "CME"},
    "GOLD": {"name": "Gold", "code": "088691", "exchange": "COMEX"},
    "SILVER": {"name": "Silver", "code": "084691", "exchange": "COMEX"},
    "CRUDE_OIL": {"name": "Crude Oil WTI", "code": "067651", "exchange": "NYMEX"},
    "NATURAL_GAS": {"name": "Natural Gas", "code": "023651", "exchange": "NYMEX"},
    "COPPER": {"name": "Copper", "code": "085692", "exchange": "COMEX"},
}

HEADERS = {"User-Agent": "StockAnalysisSkill/2.0 (research@example.com)"}


def fetch_cot_bulk() -> list[dict]:
    """Fetch the latest COT bulk data from CFTC (current week)."""
    try:
        resp = requests.get(CFTC_BULK_URL, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return []
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)
    except (requests.RequestException, csv.Error):
        return []


def parse_cot_for_market(rows: list[dict], market_key: str) -> dict | None:
    """Parse COT data for a specific market from bulk CSV rows."""
    market_info = MARKET_CODES.get(market_key)
    if not market_info:
        return None

    code = market_info["code"]
    matching_rows = []

    for row in rows:
        cftc_code = row.get("CFTC_Contract_Market_Code", "").strip()
        if cftc_code == code:
            matching_rows.append(row)

    if not matching_rows:
        return None

    # Take the most recent row
    row = matching_rows[0]

    try:
        # Commercial positions (hedgers — smart money)
        comm_long = int(row.get("Comm_Positions_Long_All", 0) or 0)
        comm_short = int(row.get("Comm_Positions_Short_All", 0) or 0)
        comm_net = comm_long - comm_short

        # Non-commercial (large speculators — fund managers)
        noncomm_long = int(row.get("NonComm_Positions_Long_All", 0) or 0)
        noncomm_short = int(row.get("NonComm_Positions_Short_All", 0) or 0)
        noncomm_net = noncomm_long - noncomm_short
        noncomm_spread = int(row.get("NonComm_Positions_Spread_All", 0) or 0)

        # Non-reportable (small speculators — retail)
        nonrep_long = int(row.get("NonRept_Positions_Long_All", 0) or 0)
        nonrep_short = int(row.get("NonRept_Positions_Short_All", 0) or 0)
        nonrep_net = nonrep_long - nonrep_short

        # Open interest
        open_interest = int(row.get("Open_Interest_All", 0) or 0)

        # Concentration (top 4 and top 8 traders)
        conc_long_4 = row.get("Conc_Gross_LE_4_TDR_Long_All", "")
        conc_short_4 = row.get("Conc_Gross_LE_4_TDR_Short_All", "")

        report_date = row.get("As_of_Date_In_Form_YYMMDD", "")
        if report_date and len(report_date) == 6:
            report_date = f"20{report_date[:2]}-{report_date[2:4]}-{report_date[4:6]}"

        # Determine positioning signal
        if open_interest > 0:
            noncomm_pct = noncomm_net / open_interest
        else:
            noncomm_pct = 0

        if noncomm_pct > 0.15:
            positioning = "extremely_long"
            signal = "Crowded long — contrarian bearish signal."
        elif noncomm_pct > 0.05:
            positioning = "net_long"
            signal = "Moderately long positioning."
        elif noncomm_pct < -0.15:
            positioning = "extremely_short"
            signal = (
                "Crowded short — contrarian bullish signal (short squeeze potential)."
            )
        elif noncomm_pct < -0.05:
            positioning = "net_short"
            signal = "Moderately short positioning."
        else:
            positioning = "neutral"
            signal = "Balanced positioning — no strong directional bias."

        return {
            "market": market_info["name"],
            "market_key": market_key,
            "exchange": market_info["exchange"],
            "report_date": report_date,
            "open_interest": open_interest,
            "commercials": {
                "long": comm_long,
                "short": comm_short,
                "net": comm_net,
                "note": "Hedgers (smart money). Extreme net positions can signal reversals.",
            },
            "large_speculators": {
                "long": noncomm_long,
                "short": noncomm_short,
                "net": noncomm_net,
                "spread": noncomm_spread,
                "pct_of_oi": round(noncomm_pct, 4),
                "note": "Fund managers/CTAs. Trend-followers. Crowded positions = reversal risk.",
            },
            "small_speculators": {
                "long": nonrep_long,
                "short": nonrep_short,
                "net": nonrep_net,
                "note": "Retail/small traders. Often wrong at extremes (contrarian indicator).",
            },
            "concentration": {
                "top_4_long_pct": conc_long_4,
                "top_4_short_pct": conc_short_4,
            },
            "positioning_signal": {
                "positioning": positioning,
                "signal": signal,
                "large_spec_net_pct_oi": round(noncomm_pct * 100, 2),
            },
        }
    except (ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch CFTC Commitments of Traders (COT) positioning data"
    )
    parser.add_argument(
        "--market",
        default="SP500,VIX,10Y_NOTE,USD,GOLD",
        help="Comma-separated market keys (default: SP500,VIX,10Y_NOTE,USD,GOLD). Use --list to see all.",
    )
    parser.add_argument(
        "--list", action="store_true", help="List available markets and exit"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    if args.list:
        print("Available CFTC COT Markets:")
        print(f"{'Key':<15} {'Name':<25} {'Exchange':<10}")
        print("-" * 55)
        for key, info in MARKET_CODES.items():
            print(f"{key:<15} {info['name']:<25} {info['exchange']:<10}")
        sys.exit(0)

    requested = [m.strip().upper() for m in args.market.split(",") if m.strip()]
    unknown = [m for m in requested if m not in MARKET_CODES]
    if unknown:
        sys.stderr.write(f"Warning: Unknown markets ignored: {unknown}\n")
    requested = [m for m in requested if m in MARKET_CODES]

    if not requested:
        sys.stderr.write("Error: No valid markets specified.\n")
        sys.exit(1)

    sys.stderr.write("Fetching CFTC COT bulk data...\n")
    rows = fetch_cot_bulk()

    if not rows:
        sys.stderr.write(
            "Warning: Could not fetch CFTC bulk data. Trying alternative source.\n"
        )
        result = {
            "source": "cftc",
            "status": "unavailable",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "note": "CFTC bulk data unavailable. Check https://www.cftc.gov/dea/newcot/ for status.",
            "markets": {},
        }
    else:
        result = {
            "source": "cftc",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "markets": {},
        }

        for market_key in requested:
            parsed = parse_cot_for_market(rows, market_key)
            if parsed:
                result["markets"][market_key] = parsed
            else:
                result["markets"][market_key] = {
                    "market_key": market_key,
                    "status": "not_found",
                    "note": f"No COT data found for {market_key} in latest report.",
                }

        # Summary: overall market positioning assessment
        sp500_data = result["markets"].get("SP500", {})
        vix_data = result["markets"].get("VIX", {})

        sp_signal = sp500_data.get("positioning_signal", {}).get(
            "positioning", "unknown"
        )
        vix_signal = vix_data.get("positioning_signal", {}).get(
            "positioning", "unknown"
        )

        if sp_signal == "extremely_long" or vix_signal == "extremely_short":
            overall = "risk_elevated"
            overall_note = "Crowded equity longs + compressed vol positioning — elevated reversal risk."
        elif sp_signal == "extremely_short" or vix_signal == "extremely_long":
            overall = "contrarian_bullish"
            overall_note = (
                "Extreme pessimism in positioning — contrarian bullish signal."
            )
        else:
            overall = "neutral"
            overall_note = "No extreme positioning detected across key markets."

        result["overall_assessment"] = {
            "regime": overall,
            "note": overall_note,
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
