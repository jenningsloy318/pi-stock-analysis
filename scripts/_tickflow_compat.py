"""TickFlow OHLCV compatibility layer — delegates to data_source.py.

Kept for backward compatibility: fetch_technicals.py and other scripts that
import from _tickflow_compat will transparently use the unified data_source
layer (TickFlow → yfinance → akshare → baostock fallback chain).
"""

import sys

try:
    from data_source import get_ohlcv, detect_market
    _DS = True
except ImportError:
    _DS = False

try:
    from tickflow import TickFlow
    _TF_AVAILABLE = True
except ImportError:
    _TF_AVAILABLE = False


def is_available() -> bool:
    return _TF_AVAILABLE or _DS


def fetch_ohlcv_tickflow(ticker: str, count: int = 200, period: str = "1d"):
    """Fetch OHLCV via the unified data_source layer (TickFlow first, fallback chain).

    Returns a yfinance-compatible DataFrame (Open/High/Low/Close/Volume) or None.
    """
    if _DS:
        # Map count to a period string for data_source
        period_str = "1y" if count >= 200 else "6mo" if count >= 100 else "3mo" if count >= 50 else "1mo"
        return get_ohlcv(ticker, period=period_str, interval=period)
    return None


def fetch_ohlcv_with_fallback(ticker: str, count: int = 200, yf_period: str = "1y"):
    """Fetch OHLCV with automatic source fallback (TickFlow → yfinance → akshare).

    This is the recommended entry point — it tries all available sources.
    """
    if _DS:
        return get_ohlcv(ticker, period=yf_period, interval="1d")
    return None
