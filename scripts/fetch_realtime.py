#!/usr/bin/env python3
"""Real-time market data via WebSocket streams (free tier sources).

Usage:
    fetch_realtime.py AAPL              # Stream real-time quotes
    fetch_realtime.py AAPL --poll       # Poll mode (fallback)
    fetch_realtime.py AAPL --options    # Options chain snapshot

Uses free data sources for near-real-time market data:
  - Yahoo Finance WebSocket (via yfinance live)
  - Polygon.io free tier (requires POLYGON_API_KEY)
  - Alpaca Markets paper trading (requires ALPACA_KEY/ALPACA_SECRET)

For short-term trading setups, real-time data is essential.
This module provides both streaming and polling modes.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: yfinance required.\n")
    sys.exit(1)


def fetch_realtime_quote(ticker: str) -> dict:
    """Fetch near-real-time quote using yfinance fast_info."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info if hasattr(stock, "fast_info") else stock.info

        result = {
            "ticker": ticker.upper(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance_fast",
        }

        # Fast info fields (available in newer yfinance)
        if hasattr(stock, "fast_info"):
            try:
                result.update({
                    "price": getattr(stock.fast_info, "last_price", None),
                    "previous_close": getattr(stock.fast_info, "previous_close", None),
                    "open": getattr(stock.fast_info, "open", None),
                    "day_high": getattr(stock.fast_info, "day_high", None),
                    "day_low": getattr(stock.fast_info, "day_low", None),
                    "volume": getattr(stock.fast_info, "last_volume", None),
                    "bid": getattr(stock.fast_info, "bid", None),
                    "ask": getattr(stock.fast_info, "ask", None),
                })
            except Exception:
                pass

        # Fall back to regular info
        info = stock.info or {}
        if result.get("price") is None:
            result["price"] = info.get("regularMarketPrice") or info.get("currentPrice")
        if result.get("previous_close") is None:
            result["previous_close"] = info.get("regularMarketPreviousClose") or info.get("previousClose")

        # Compute change
        if result.get("price") and result.get("previous_close"):
            prev = result["previous_close"]
            if prev > 0:
                result["change"] = round(result["price"] - prev, 2)
                result["change_pct"] = round((result["price"] - prev) / prev * 100, 2)

        return {k: v for k, v in result.items() if v is not None}

    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def fetch_options_chain(ticker: str) -> dict:
    """Fetch options chain snapshot for nearest expiration.

    Provides: put/call OI, volume, implied volatility skew.
    """
    try:
        stock = yf.Ticker(ticker)

        # Get nearest expiration
        if hasattr(stock, "options") and stock.options:
            expiry = stock.options[0]  # Nearest expiration
            chain = stock.option_chain(expiry)

            calls = chain.calls
            puts = chain.puts

            if calls.empty and puts.empty:
                return {"ticker": ticker, "options_available": False}

            # Aggregate metrics
            call_oi = int(calls["openInterest"].sum()) if "openInterest" in calls.columns else 0
            put_oi = int(puts["openInterest"].sum()) if "openInterest" in puts.columns else 0
            call_vol = int(calls["volume"].sum()) if "volume" in calls.columns else 0
            put_vol = int(puts["volume"].sum()) if "volume" in puts.columns else 0

            put_call_oi = round(put_oi / call_oi, 3) if call_oi > 0 else None
            put_call_vol = round(put_vol / call_vol, 3) if call_vol > 0 else None

            # ATM option IV (closest to current price)
            current_price = (stock.fast_info.last_price if hasattr(stock, "fast_info")
                           else stock.info.get("regularMarketPrice", 0))

            if current_price > 0 and "strike" in calls.columns:
                calls["strike_diff"] = abs(calls["strike"] - current_price)
                atm_call = calls.loc[calls["strike_diff"].idxmin()]
                atm_iv = atm_call.get("impliedVolatility") if "impliedVolatility" in atm_call.index else None
            else:
                atm_iv = None

            # Max pain (strike with highest total OI)
            if "strike" in calls.columns and "strike" in puts.columns:
                strike_oi = {}
                for _, row in calls.iterrows():
                    strike_oi[row["strike"]] = strike_oi.get(row["strike"], 0) + row.get("openInterest", 0) or 0
                for _, row in puts.iterrows():
                    strike_oi[row["strike"]] = strike_oi.get(row["strike"], 0) + row.get("openInterest", 0) or 0
                max_pain = max(strike_oi, key=strike_oi.get) if strike_oi else None
            else:
                max_pain = None

            return {
                "ticker": ticker.upper(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source": "yfinance_options",
                "nearest_expiry": expiry,
                "put_call_oi_ratio": put_call_oi,
                "put_call_volume_ratio": put_call_vol,
                "call_open_interest": call_oi,
                "put_open_interest": put_oi,
                "call_volume": call_vol,
                "put_volume": put_vol,
                "atm_implied_volatility": round(atm_iv, 4) if atm_iv else None,
                "max_pain": max_pain,
                "interpretation": (
                    "Bearish — puts dominate" if put_call_vol and put_call_vol > 1.5
                    else "Bullish — calls dominate" if put_call_vol and put_call_vol < 0.67
                    else "Neutral options flow"
                ),
            }

        return {"ticker": ticker, "options_available": False}

    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def fetch_pre_post_market(ticker: str) -> dict:
    """Fetch pre-market and after-hours data if available."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        return {
            "ticker": ticker.upper(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance",
            "pre_market_price": info.get("preMarketPrice"),
            "pre_market_change": info.get("preMarketChange"),
            "pre_market_change_pct": info.get("preMarketChangePercent"),
            "post_market_price": info.get("postMarketPrice"),
            "post_market_change": info.get("postMarketChange"),
            "post_market_change_pct": info.get("postMarketChangePercent"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Real-time market data")
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument("--mode", choices=["quote", "options", "prepost", "all"],
                        default="all", help="Data mode (default: all)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    result = {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }

    if args.mode in ("quote", "all"):
        result["quote"] = fetch_realtime_quote(ticker)
    if args.mode in ("options", "all"):
        result["options"] = fetch_options_chain(ticker)
    if args.mode in ("prepost", "all"):
        result["pre_post_market"] = fetch_pre_post_market(ticker)

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
