"""yfinance transparent patch — delegates to data_source.py.

When imported, monkey-patches `yfinance.Ticker.history()` to route through
the unified data_source layer (TickFlow → yfinance → akshare → baostock).
All 38+ scripts that do `yf.Ticker(t).history(...)` automatically get
multi-source fallback without code changes — just import this module.

Usage (one line after `import yfinance`):

    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # multi-source OHLCV via data_source
"""

import sys

try:
    import data_source
    _DS = True
except ImportError:
    _DS = False


def _apply_patch():
    if not _DS:
        return False

    try:
        import yfinance as yf
    except ImportError:
        return False

    if getattr(yf.Ticker.history, "_data_source_patched", False):
        return True

    _original_history = yf.Ticker.history

    def _patched_history(self, period="1y", interval="1d", **kwargs):
        ticker = getattr(self, "ticker", None) or getattr(self, "_ticker", None) or str(self)
        if not ticker:
            return _original_history(self, period=period, interval=interval, **kwargs)

        # Route through unified data_source layer
        try:
            df = data_source.get_ohlcv(ticker, period=period, interval=interval)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            sys.stderr.write(f"[_yfinance_patch] data_source miss for {ticker}: {e}\n")

        # Fallback to original yfinance
        return _original_history(self, period=period, interval=interval, **kwargs)

    _patched_history._data_source_patched = True
    yf.Ticker.history = _patched_history
    return True


_patched = _apply_patch()
if _patched:
    sys.stderr.write("[_yfinance_patch] Multi-source OHLCV active (tickflow → yfinance → akshare → baostock)\n")
