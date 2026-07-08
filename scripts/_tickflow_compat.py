"""TickFlow OHLCV compatibility layer for downstream scripts.

Provides `fetch_ohlcv_tickflow(ticker, count)` that returns a pandas DataFrame
in yfinance-compatible format (columns: Open, High, Low, Close, Volume; indexed
by date). Downstream scripts (fetch_technicals, compute_factors, etc.) can call
this instead of `yf.Ticker(t).history()` when TICKFLOW_API_KEY is set or
yfinance fails.

Usage in downstream scripts:

    from _tickflow_compat import fetch_ohlcv_tickflow, is_available

    df = None
    if is_available():
        df = fetch_ohlcv_tickflow(ticker, count=200)
    if df is None:
        df = yf.Ticker(ticker).history(period="6mo", interval="1d")
"""

import os
import sys
from datetime import datetime, timezone

try:
    import pandas as pd
    _PD_AVAILABLE = True
except ImportError:
    _PD_AVAILABLE = False

try:
    from tickflow import TickFlow
    _TF_AVAILABLE = True
except ImportError:
    _TF_AVAILABLE = False


def is_available() -> bool:
    """Check if TickFlow SDK is installed."""
    return _TF_AVAILABLE


def _to_tf_symbol(ticker: str) -> str:
    """Convert pipeline ticker to TickFlow symbol."""
    t = ticker.strip().upper()
    if t.endswith((".US", ".SH", ".SZ", ".BJ", ".HK")):
        return t
    if t.isalpha():
        return f"{t}.US"
    if t.isdigit() and len(t) == 6:
        suffix = "SH" if t[:2] in ("60", "68", "90") else "SZ"
        return f"{t}.{suffix}"
    if t.endswith(".SS"):
        return t[:-3] + ".SH"
    return t


def _get_client():
    api_key = os.environ.get("TICKFLOW_API_KEY")
    if api_key:
        return TickFlow(api_key=api_key)
    return TickFlow.free()


def fetch_ohlcv_tickflow(ticker: str, count: int = 200, period: str = "1d") -> "pd.DataFrame | None":
    """Fetch OHLCV data via TickFlow, returning a yfinance-compatible DataFrame.

    Returns a DataFrame with columns: Open, High, Low, Close, Volume
    and a DatetimeIndex — same shape as `yf.Ticker(t).history()`.
    Returns None on failure (so callers can fall back to yfinance).
    """
    if not _TF_AVAILABLE or not _PD_AVAILABLE:
        return None

    try:
        tf = _get_client()
        symbol = _to_tf_symbol(ticker)
        df = tf.klines.get(symbol, period=period, count=count, as_dataframe=True)
        tf.close()

        if df is None or df.empty:
            return None

        # Rename tickflow columns to yfinance-compatible Title Case
        rename_map = {}
        for col in df.columns:
            cl = col.lower()
            if cl == "open":
                rename_map[col] = "Open"
            elif cl == "high":
                rename_map[col] = "High"
            elif cl == "low":
                rename_map[col] = "Low"
            elif cl == "close":
                rename_map[col] = "Close"
            elif cl == "volume":
                rename_map[col] = "Volume"
        df = df.rename(columns=rename_map)

        # Ensure required columns exist
        for required in ("Open", "High", "Low", "Close"):
            if required not in df.columns:
                return None

        # Drop any rows with NaN in OHLC
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        # Ensure DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        return df

    except Exception as e:
        sys.stderr.write(f"[tickflow-compat] OHLCV fetch failed for {ticker}: {e}\n")
        return None


def fetch_ohlcv_with_fallback(ticker: str, count: int = 200, yf_period: str = "1y") -> "pd.DataFrame | None":
    """Fetch OHLCV via TickFlow first; fall back to yfinance on failure.

    This is the recommended function for downstream scripts — it tries
    TickFlow (higher quality for many tickers) and transparently falls
    back to yfinance if TickFlow fails or is unavailable.
    """
    # Try TickFlow first
    df = fetch_ohlcv_tickflow(ticker, count=count)
    if df is not None:
        return df

    # Fallback to yfinance
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=yf_period, interval="1d")
        if hist is not None and not hist.empty:
            return hist
    except Exception as e:
        sys.stderr.write(f"[tickflow-compat] yfinance fallback also failed for {ticker}: {e}\n")

    return None
