#!/usr/bin/env python3
"""Fetch comprehensive stock data via TickFlow SDK.

Supports US stocks (.US), A-shares (.SH/.SZ), HK (.HK). Provides OHLCV
history, real-time quotes, and instrument metadata — a drop-in alternative
to yfinance for the analyze/screening pipeline stages.

Usage:
    fetch_stock_data_tickflow.py AAPL
    fetch_stock_data_tickflow.py AAPL MSFT NVDA --period 1y
    fetch_stock_data_tickflow.py 600519.SH --count 200
    fetch_stock_data_tickflow.py AAPL --output ./reports/[RUN]/raw/tickflow_AAPL.json

Output: JSON to stdout or --output file. One object per ticker.

TickFlow provides higher-quality intraday + daily data than yfinance for
many tickers, and works for A-shares without akshare. Set TICKFLOW_API_KEY
for the paid tier; falls back to TickFlow.free() (rate-limited).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    from tickflow import TickFlow
    _TF_AVAILABLE = True
except ImportError:
    _TF_AVAILABLE = False


def _to_tf_symbol(ticker: str) -> str:
    """Convert a pipeline ticker to TickFlow symbol format.

    AAPL → AAPL.US
    600519.SH → 600519.SH (already TickFlow format)
    000001.SZ → 000001.SZ
    00700.HK → 00700.HK
    """
    t = ticker.strip().upper()
    if t.endswith((".US", ".SH", ".SZ", ".BJ", ".HK")):
        return t
    # Bare US ticker (letters, no suffix)
    if t.isalpha():
        return f"{t}.US"
    # Bare 6-digit → A-share
    if t.isdigit() and len(t) == 6:
        suffix = "SH" if t[:2] in ("60", "68", "90") else "SZ"
        return f"{t}.{suffix}"
    # .SS → .SH (yfinance uses .SS, tickflow uses .SH)
    if t.endswith(".SS"):
        return t[:-3] + ".SH"
    return t


def _get_client():
    """Get a TickFlow client (API key or free tier)."""
    api_key = os.environ.get("TICKFLOW_API_KEY")
    if api_key:
        return TickFlow(api_key=api_key)
    return TickFlow.free()


def fetch_klines(tf, symbol: str, period: str = "1d", count: int = 200) -> dict | None:
    """Fetch OHLCV kline data. Returns dict with arrays or None."""
    try:
        df = tf.klines.get(symbol, period=period, count=count, as_dataframe=True)
        if df is None or df.empty:
            return None
        # DataFrame columns: open, high, low, close, volume (datetime index)
        result = {
            "dates": [idx.strftime("%Y-%m-%d") for idx in df.index],
            "open": [round(float(v), 4) for v in df["open"].tolist()],
            "high": [round(float(v), 4) for v in df["high"].tolist()],
            "low": [round(float(v), 4) for v in df["low"].tolist()],
            "close": [round(float(v), 4) for v in df["close"].tolist()],
        }
        if "volume" in df.columns:
            result["volume"] = [int(v) for v in df["volume"].tolist()]
        if "turnover" in df.columns:
            result["turnover"] = [round(float(v), 2) for v in df["turnover"].tolist()]
        if "amount" in df.columns:
            result["amount"] = [round(float(v), 2) for v in df["amount"].tolist()]
        result["count"] = len(result["dates"])
        return result
    except Exception as e:
        sys.stderr.write(f"[tickflow] klines error for {symbol}: {e}\n")
        return None


def fetch_quote(tf, symbol: str) -> dict | None:
    """Fetch real-time quote."""
    try:
        quotes = tf.quotes.get(symbols=[symbol])
        if not quotes:
            return None
        q = quotes[0]
        return {
            "last_price": q.get("last_price"),
            "open": q.get("open"),
            "high": q.get("high"),
            "low": q.get("low"),
            "volume": q.get("volume"),
            "bid": q.get("bid"),
            "ask": q.get("ask"),
            "trade_date": q.get("trade_date"),
        }
    except Exception:
        return None


def fetch_instrument(tf, symbol: str) -> dict | None:
    """Fetch instrument metadata (name, shares, listing date)."""
    try:
        inst = tf.instruments.get(symbol)
        if not inst:
            return None
        ext = inst.get("ext", {}) or {}
        return {
            "name": inst.get("name"),
            "name_en": inst.get("name_en"),
            "exchange": inst.get("exchange"),
            "type": inst.get("type"),
            "total_shares": ext.get("total_shares"),
            "float_shares": ext.get("float_shares"),
            "listing_date": ext.get("listing_date"),
            "currency": ext.get("currency"),
        }
    except Exception:
        return None


def fetch_financials(tf, symbol: str) -> dict | None:
    """Fetch basic financials if available."""
    try:
        fin = tf.financials.get(symbol)
        if not fin:
            return None
        return {
            "pe": fin.get("pe") or fin.get("pe_ratio"),
            "pb": fin.get("pb") or fin.get("pb_ratio"),
            "market_cap": fin.get("market_cap"),
            "revenue": fin.get("revenue"),
            "net_income": fin.get("net_income"),
        }
    except Exception:
        return None


def fetch_ticker(tf, ticker: str, period: str = "1d", count: int = 200) -> dict:
    """Fetch all available data for one ticker via TickFlow."""
    symbol = _to_tf_symbol(ticker)
    now = datetime.now(timezone.utc).isoformat()

    result = {
        "ticker": ticker.upper(),
        "symbol": symbol,
        "source": "tickflow",
        "retrieved_at": now,
    }

    # Instrument metadata (name, shares)
    inst = fetch_instrument(tf, symbol)
    if inst:
        result["instrument"] = inst
        result["name"] = inst.get("name") or inst.get("name_en")

    # Real-time quote
    quote = fetch_quote(tf, symbol)
    if quote:
        result["quote"] = quote
        result["price"] = quote.get("last_price")
        result["data_date"] = quote.get("trade_date") or now[:10]

    # OHLCV history
    klines = fetch_klines(tf, symbol, period=period, count=count)
    if klines:
        result["klines"] = klines
        # If no quote price, use latest close
        if result.get("price") is None and klines["close"]:
            result["price"] = klines["close"][-1]
            result["data_date"] = klines["dates"][-1]

    # Financials (optional — may not be available on free tier)
    fin = fetch_financials(tf, symbol)
    if fin:
        result["financials"] = fin
        if result.get("price") and fin.get("market_cap") is None and inst and inst.get("total_shares"):
            result["market_cap"] = result["price"] * inst["total_shares"]
        elif fin.get("market_cap"):
            result["market_cap"] = fin["market_cap"]

    # Market cap from price × total_shares
    if result.get("market_cap") is None and result.get("price") and inst and inst.get("total_shares"):
        result["market_cap"] = result["price"] * inst["total_shares"]

    if not any(k in result for k in ("klines", "quote", "instrument")):
        result["error"] = "no data returned from TickFlow"

    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch stock data via TickFlow SDK")
    parser.add_argument("tickers", nargs="+", help="Ticker symbol(s): AAPL, 600519.SH, etc.")
    parser.add_argument("--period", default="1d", help="K-line period: 1d, 1w, 1M (default: 1d)")
    parser.add_argument("--count", type=int, default=200, help="Number of klines (default: 200)")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    args = parser.parse_args()

    if not _TF_AVAILABLE:
        print(json.dumps({"error": "tickflow SDK not installed. Run: uv add tickflow"}))
        sys.exit(1)

    tf = _get_client()

    results = {}
    for ticker in args.tickers:
        sys.stderr.write(f"[tickflow] Fetching {ticker}...\n")
        results[ticker.upper()] = fetch_ticker(tf, ticker, period=args.period, count=args.count)

    try:
        tf.close()
    except Exception:
        pass

    output = json.dumps(results, indent=2, default=str, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        sys.stderr.write(f"[tickflow] Wrote {args.output}\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
