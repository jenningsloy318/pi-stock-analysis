#!/usr/bin/env python3
"""Fetch currency/FX exposure and ADR status for international stock analysis.

Usage:
    fetch_currency_exposure.py AAPL --output ./reports/AAPL/currency_exposure.json
    fetch_currency_exposure.py TSM --raw-data ./reports/TSM/raw-data.json
    fetch_currency_exposure.py NVO --macro ./reports/global-macro.json

Detects ADR status, geographic revenue mix, FX sensitivity, and currency-
adjusted EPS impact. Critical for accurate valuation of multinationals and
ADRs whose financials are denominated in non-USD currencies.

Output:
  - is_adr: boolean ADR detection
  - reporting_currency: company's functional currency (e.g., TWD, DKK, EUR)
  - revenue_by_geography: percentage breakdown by region
  - fx_sensitivity: correlation of stock returns with DXY index
  - currency_headwind_tailwind: estimated EPS impact from FX moves
  - hedging_assessment: whether company hedges FX risk
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import numpy as np

try:
    import yfinance as yf

    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


ADR_EXCHANGES = {"PNK", "OTC", "PINK", "GREY"}
ADR_SUFFIXES = {
    ".L",
    ".HK",
    ".T",
    ".TW",
    ".KS",
    ".SA",
    ".DE",
    ".PA",
    ".AS",
    ".MI",
    ".MC",
    ".TO",
    ".AX",
    ".SI",
    ".NS",
    ".BO",
}

COUNTRY_CURRENCY_MAP = {
    "Taiwan": "TWD",
    "China": "CNY",
    "Japan": "JPY",
    "South Korea": "KRW",
    "United Kingdom": "GBP",
    "Germany": "EUR",
    "France": "EUR",
    "Netherlands": "EUR",
    "Italy": "EUR",
    "Spain": "EUR",
    "Denmark": "DKK",
    "Switzerland": "CHF",
    "Sweden": "SEK",
    "Norway": "NOK",
    "Brazil": "BRL",
    "India": "INR",
    "Australia": "AUD",
    "Canada": "CAD",
    "Israel": "ILS",
    "Ireland": "EUR",
    "Singapore": "SGD",
    "Hong Kong": "HKD",
}

MAJOR_CURRENCY_TICKERS = {
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "JPY": "JPY=X",
    "CNY": "CNY=X",
    "CHF": "CHFUSD=X",
    "CAD": "CADUSD=X",
    "AUD": "AUDUSD=X",
    "TWD": "TWD=X",
    "KRW": "KRW=X",
    "DKK": "DKK=X",
    "INR": "INR=X",
    "BRL": "BRL=X",
}


def detect_adr_status(info: dict) -> dict[str, Any]:
    """Detect if a ticker is an ADR based on yfinance info."""
    quote_type = info.get("quoteType", "")
    exchange = info.get("exchange", "")
    country = info.get("country", "")
    currency = info.get("currency", "USD")
    long_name = info.get("longName", "")
    short_name = info.get("shortName", "")

    is_adr = False
    adr_signals = []

    if "ADR" in long_name.upper() or "ADR" in short_name.upper():
        is_adr = True
        adr_signals.append("ADR in company name")

    if exchange in ADR_EXCHANGES:
        is_adr = True
        adr_signals.append(f"Trades on {exchange} (OTC/Pink Sheets)")

    if country and country != "United States" and currency == "USD":
        is_adr = True
        adr_signals.append(f"Foreign company ({country}) trading in USD")

    reporting_currency = info.get("financialCurrency", currency)
    home_currency = COUNTRY_CURRENCY_MAP.get(country, reporting_currency)

    return {
        "is_adr": is_adr,
        "adr_signals": adr_signals,
        "country_of_domicile": country,
        "exchange": exchange,
        "trading_currency": currency,
        "reporting_currency": reporting_currency,
        "home_currency": home_currency,
        "fx_translation_needed": reporting_currency != "USD",
    }


def extract_geographic_segments(info: dict, raw_data: dict | None = None) -> dict:
    """Extract geographic revenue breakdown from available data."""
    segments: dict[str, float] = {}

    if raw_data:
        ticker_key = next(iter(raw_data), None)
        if ticker_key and isinstance(raw_data.get(ticker_key), dict):
            financials = raw_data[ticker_key].get("financials", {})
        else:
            financials = raw_data.get("financials", {})

        geo_data = financials.get("geographic_segments", [])
        if geo_data and isinstance(geo_data, list):
            total = sum(s.get("revenue", 0) for s in geo_data if isinstance(s, dict))
            if total > 0:
                for seg in geo_data:
                    if isinstance(seg, dict) and seg.get("region"):
                        pct = seg.get("revenue", 0) / total * 100
                        segments[seg["region"]] = round(pct, 1)

    if not segments:
        country = info.get("country", "United States")
        sector = info.get("sector", "")
        if country == "United States":
            if sector in ("Technology", "Communication Services"):
                segments = {
                    "Americas": 45.0,
                    "Europe": 25.0,
                    "Greater China": 15.0,
                    "Rest of Asia Pacific": 10.0,
                    "Other": 5.0,
                }
            else:
                segments = {"United States": 70.0, "International": 30.0}
        else:
            segments = {
                country: 50.0,
                "United States": 25.0,
                "Other International": 25.0,
            }
        segments["_note"] = (
            "Estimated — actual geographic breakdown not available from API"
        )

    non_us_pct = sum(
        v
        for k, v in segments.items()
        if k not in ("United States", "Americas", "_note")
        and isinstance(v, (int, float))
    )

    return {
        "revenue_by_geography": segments,
        "international_revenue_pct": round(non_us_pct, 1),
        "fx_exposure_level": (
            "High" if non_us_pct > 50 else "Medium" if non_us_pct > 25 else "Low"
        ),
    }


def compute_fx_sensitivity(
    ticker: str, home_currency: str, lookback_days: int = 252
) -> dict[str, Any]:
    """Compute correlation between stock returns and USD strength (DXY proxy)."""
    if not YF_AVAILABLE:
        return {"error": "yfinance not available for FX sensitivity calculation"}

    try:
        stock = yf.download(ticker, period="1y", progress=False, auto_adjust=True)
        if stock.empty or len(stock) < 30:
            return {"error": "Insufficient stock price history"}

        stock_returns = stock["Close"].pct_change().dropna().values.flatten()

        dxy = yf.download("DX-Y.NYB", period="1y", progress=False, auto_adjust=True)
        if dxy.empty or len(dxy) < 30:
            dxy = yf.download("UUP", period="1y", progress=False, auto_adjust=True)

        if dxy.empty or len(dxy) < 30:
            return {"error": "Could not fetch DXY/USD index data"}

        dxy_returns = dxy["Close"].pct_change().dropna().values.flatten()

        min_len = min(len(stock_returns), len(dxy_returns))
        stock_returns = stock_returns[-min_len:]
        dxy_returns = dxy_returns[-min_len:]

        correlation = float(np.corrcoef(stock_returns, dxy_returns)[0, 1])

        fx_ticker = MAJOR_CURRENCY_TICKERS.get(home_currency)
        home_fx_corr = None
        if fx_ticker and home_currency != "USD":
            try:
                fx_data = yf.download(
                    fx_ticker, period="1y", progress=False, auto_adjust=True
                )
                if not fx_data.empty and len(fx_data) >= 30:
                    fx_returns = fx_data["Close"].pct_change().dropna().values.flatten()
                    fx_min = min(len(stock_returns), len(fx_returns))
                    home_fx_corr = float(
                        np.corrcoef(stock_returns[-fx_min:], fx_returns[-fx_min:])[0, 1]
                    )
            except Exception:
                pass

        return {
            "dxy_correlation": round(correlation, 4),
            "dxy_interpretation": (
                "Strong USD headwind"
                if correlation < -0.3
                else "Moderate USD headwind"
                if correlation < -0.15
                else "USD neutral"
                if abs(correlation) <= 0.15
                else "Moderate USD tailwind"
                if correlation < 0.3
                else "Strong USD tailwind"
            ),
            "home_currency_correlation": (
                round(home_fx_corr, 4) if home_fx_corr is not None else None
            ),
            "observations": min_len,
            "lookback_period": "1 year",
        }

    except Exception as e:
        return {"error": str(e)}


def estimate_eps_fx_impact(
    international_pct: float,
    reporting_currency: str,
    dxy_change_ytd: float | None = None,
) -> dict[str, Any]:
    """Estimate FX headwind/tailwind impact on EPS."""
    if dxy_change_ytd is None:
        if YF_AVAILABLE:
            try:
                dxy = yf.download(
                    "DX-Y.NYB", period="ytd", progress=False, auto_adjust=True
                )
                if not dxy.empty and len(dxy) >= 2:
                    dxy_change_ytd = float(
                        (dxy["Close"].iloc[-1] / dxy["Close"].iloc[0] - 1) * 100
                    )
            except Exception:
                pass

    if dxy_change_ytd is None:
        return {"error": "Cannot determine DXY YTD change"}

    fx_exposure_fraction = international_pct / 100.0
    passthrough = 0.6
    eps_impact_pct = -dxy_change_ytd * fx_exposure_fraction * passthrough

    return {
        "dxy_change_ytd_pct": round(dxy_change_ytd, 2),
        "international_revenue_fraction": round(fx_exposure_fraction, 3),
        "fx_passthrough_assumption": passthrough,
        "estimated_eps_impact_pct": round(eps_impact_pct, 2),
        "direction": (
            "headwind"
            if eps_impact_pct < -0.5
            else "tailwind"
            if eps_impact_pct > 0.5
            else "neutral"
        ),
        "interpretation": (
            f"USD {'strength' if dxy_change_ytd > 0 else 'weakness'} of "
            f"{abs(dxy_change_ytd):.1f}% YTD creates ~{abs(eps_impact_pct):.1f}% "
            f"EPS {'headwind' if eps_impact_pct < 0 else 'tailwind'} "
            f"(assuming {passthrough*100:.0f}% passthrough on {international_pct:.0f}% "
            f"international revenue)"
        ),
    }


def assess_hedging(info: dict) -> dict[str, Any]:
    """Assess likely FX hedging practices based on company characteristics."""
    market_cap = info.get("marketCap", 0)
    sector = info.get("sector", "")

    if market_cap > 50e9:
        hedging_likelihood = "High"
        note = "Large-cap likely maintains active FX hedging program"
    elif market_cap > 10e9:
        hedging_likelihood = "Medium"
        note = "Mid-cap may hedge major exposures but not fully"
    else:
        hedging_likelihood = "Low"
        note = "Small-cap unlikely to maintain comprehensive FX hedging"

    natural_hedge_sectors = {"Energy", "Basic Materials", "Industrials"}
    has_natural_hedge = sector in natural_hedge_sectors

    return {
        "hedging_likelihood": hedging_likelihood,
        "natural_hedge": has_natural_hedge,
        "natural_hedge_note": (
            f"{sector} companies often have natural hedges (costs and revenues in same currency)"
            if has_natural_hedge
            else "No obvious natural hedge from sector positioning"
        ),
        "note": note,
        "recommendation": (
            "Check 10-K Item 7A (Quantitative and Qualitative Disclosures About Market Risk) "
            "for specific FX hedging disclosures and notional amounts"
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch currency/FX exposure for stock analysis"
    )
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument("--output", help="Output JSON file path")
    parser.add_argument(
        "--raw-data", dest="raw_data", help="Path to raw-data.json for segment data"
    )
    parser.add_argument("--macro", help="Path to global-macro.json for FX rate context")
    args = parser.parse_args()

    ticker = args.ticker.upper()

    if not YF_AVAILABLE:
        result = {
            "ticker": ticker,
            "error": "yfinance not installed. Run: pip install yfinance",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        output = json.dumps(result, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)
        sys.exit(1)

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception as e:
        print(f"Error fetching ticker info: {e}", file=sys.stderr)
        sys.exit(1)

    raw_data = None
    if args.raw_data:
        try:
            with open(args.raw_data) as f:
                raw_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: could not load raw-data: {e}", file=sys.stderr)

    adr_status = detect_adr_status(info)
    geo_segments = extract_geographic_segments(info, raw_data)
    fx_sensitivity = compute_fx_sensitivity(ticker, adr_status["home_currency"])
    eps_impact = estimate_eps_fx_impact(
        geo_segments["international_revenue_pct"],
        adr_status["reporting_currency"],
    )
    hedging = assess_hedging(info)

    result = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "adr_status": adr_status,
        "geographic_exposure": geo_segments,
        "fx_sensitivity": fx_sensitivity,
        "eps_fx_impact": eps_impact,
        "hedging_assessment": hedging,
        "investment_implications": _derive_implications(
            adr_status, geo_segments, fx_sensitivity, eps_impact
        ),
        "methodology": (
            "ADR detection via exchange/country/name signals. "
            "FX sensitivity via 1Y correlation with DXY index. "
            "EPS impact estimated using 60% passthrough assumption on international revenue. "
            "Geographic segments from SEC filings or sector-typical estimates."
        ),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Currency exposure written to {args.output}", file=sys.stderr)
    else:
        print(output)


def _derive_implications(adr: dict, geo: dict, fx: dict, eps: dict) -> list[str]:
    """Derive actionable investment implications from FX analysis."""
    implications = []

    if adr.get("is_adr"):
        implications.append(
            f"ADR: Financials reported in {adr['reporting_currency']}. "
            "USD-denominated share price includes FX translation effect."
        )

    if geo.get("international_revenue_pct", 0) > 50:
        implications.append(
            "High international revenue exposure (>50%) — FX is a material earnings driver."
        )

    dxy_corr = fx.get("dxy_correlation")
    if dxy_corr is not None and dxy_corr < -0.25:
        implications.append(
            "Negative DXY correlation: stock benefits from USD weakness. "
            "Consider USD cycle positioning in entry timing."
        )
    elif dxy_corr is not None and dxy_corr > 0.25:
        implications.append(
            "Positive DXY correlation: stock benefits from USD strength. "
            "Unusual — may indicate USD-denominated revenue dominance."
        )

    eps_impact_pct = eps.get("estimated_eps_impact_pct", 0)
    if abs(eps_impact_pct) > 2.0:
        implications.append(
            f"Material FX impact: ~{abs(eps_impact_pct):.1f}% EPS "
            f"{'headwind' if eps_impact_pct < 0 else 'tailwind'} from currency. "
            "Adjust DCF terminal value for FX normalization."
        )

    if not implications:
        implications.append(
            "Low FX exposure — currency movements are not a material factor for this stock."
        )

    return implications


if __name__ == "__main__":
    main()
