"""Unified data source layer — one API, all sources, automatic fallback.

Every downstream script calls this module instead of importing yfinance /
akshare / tickflow directly. The layer tries multiple sources in priority
order (TickFlow → yfinance → akshare → baostock), auto-detects the market
from the ticker format, falls back on failure, and caches within a session.

Quick start:

    from data_source import get_ohlcv, get_quote, get_financials, get_instrument

    df = get_ohlcv("AAPL", period="1y")           # → DataFrame (Open/High/Low/Close/Volume)
    df = get_ohlcv("600519.SH", count=200)        # → DataFrame (A-share via tickflow/akshare)
    q  = get_quote("AAPL")                         # → {price, bid, ask, volume, change_pct}
    f  = get_financials("AAPL")                    # → {pe, pb, market_cap, revenue, ...}
    i  = get_instrument("AAPL")                    # → {name, exchange, total_shares, ...}

Source priority by market:
    US  (.US):    tickflow → yfinance
    CN  (.SH/.SZ): tickflow → akshare → baostock
    HK  (.HK):    tickflow → yfinance

All functions return None (or empty DataFrame) on total failure — callers
should handle gracefully.
"""

import os
import sys
import time
from datetime import datetime, timezone

# ─── Source availability flags ──────────────────────────────────────────────

try:
    import pandas as pd
    _PD = True
except ImportError:
    _PD = False

try:
    from tickflow import TickFlow as _TickFlow
    _TF = True
except ImportError:
    _TF = False

try:
    import yfinance as yf
    _YF = True
except ImportError:
    _YF = False

try:
    import akshare as ak
    _AK = True
except ImportError:
    _AK = False

try:
    import baostock as bs
    _BS = True
except ImportError:
    _BS = False


# ─── Market detection ───────────────────────────────────────────────────────

def detect_market(ticker: str) -> str:
    """Return 'US', 'CN', or 'HK' based on ticker format."""
    t = ticker.strip().upper()
    if t.endswith((".SH", ".SZ", ".BJ", ".SS")):
        return "CN"
    if t.endswith(".HK"):
        return "HK"
    if t.endswith(".US"):
        return "US"
    if t.isdigit() and len(t) == 6:  # bare A-share
        return "CN"
    return "US"  # default: letters = US ticker


def _to_tf_symbol(ticker: str) -> str:
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


def _a_share_code(ticker: str) -> str:
    """Strip .SH/.SZ/.SS suffix for akshare/baostock."""
    return ticker.upper().replace(".SH", "").replace(".SZ", "").replace(".SS", "").replace(".BJ", "")


# ─── TickFlow client (lazy singleton) ───────────────────────────────────────

_tf_client = None

def _get_tf():
    global _tf_client
    if _tf_client is None and _TF:
        try:
            api_key = os.environ.get("TICKFLOW_API_KEY")
            _tf_client = _TickFlow(api_key=api_key) if api_key else _TickFlow.free()
        except Exception:
            _tf_client = None
    return _tf_client


# ─── Session cache ──────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_get(key: str):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
        del _cache[key]
    return None


def _cache_set(key: str, val):
    _cache[key] = (time.time(), val)


def clear_cache():
    """Clear the session cache."""
    _cache.clear()


# ─── Period helpers ─────────────────────────────────────────────────────────

_PERIOD_COUNT = {
    "1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 130,
    "1y": 250, "2y": 500, "5y": 1250, "10y": 2500, "max": 2000, "ytd": 200,
}

_INTERVAL_MAP = {
    "1d": "1d", "1wk": "1w", "1mo": "1M",
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m", "1h": "60m",
}


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def get_ohlcv(ticker: str, period: str = "1y", interval: str = "1d", count: int | None = None):
    """Fetch OHLCV data. Returns a pandas DataFrame (Open/High/Low/Close/Volume,
    DatetimeIndex) or None on failure.

    Tries sources in priority order based on market:
        US:  tickflow → yfinance
        CN:  tickflow → akshare → baostock
        HK:  tickflow → yfinance
    """
    if not _PD:
        return None

    cache_key = f"ohlcv:{ticker}:{period}:{interval}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    market = detect_market(ticker)
    n = count or _PERIOD_COUNT.get(period, 250)

    # Build source priority list
    if market == "CN":
        sources = [_ohlcv_tickflow, _ohlcv_akshare, _ohlcv_baostock]
    else:
        sources = [_ohlcv_tickflow, _ohlcv_yfinance]

    for src_fn in sources:
        try:
            df = src_fn(ticker, period, interval, n)
            if df is not None and not df.empty:
                _cache_set(cache_key, df)
                return df
        except Exception as e:
            sys.stderr.write(f"[data_source] {src_fn.__name__} failed for {ticker}: {e}\n")

    return None


def get_quote(ticker: str) -> dict | None:
    """Fetch real-time quote. Returns dict with price, bid, ask, volume, etc."""
    cache_key = f"quote:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    market = detect_market(ticker)

    # Try TickFlow first (all markets)
    if _TF:
        q = _quote_tickflow(ticker)
        if q:
            _cache_set(cache_key, q)
            return q

    # Fallback: yfinance (US/HK)
    if _YF and market != "CN":
        q = _quote_yfinance(ticker)
        if q:
            _cache_set(cache_key, q)
            return q

    # Fallback: akshare (CN)
    if _AK and market == "CN":
        q = _quote_akshare(ticker)
        if q:
            _cache_set(cache_key, q)
            return q

    return None


def get_financials(ticker: str) -> dict | None:
    """Fetch financial metrics (PE, PB, market_cap, revenue, etc.)."""
    cache_key = f"fin:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    result: dict = {}
    market = detect_market(ticker)

    # yfinance has the richest financials for US
    if _YF and market != "CN":
        try:
            f = _financials_yfinance(ticker)
            if f:
                result.update(f)
        except Exception:
            pass

    # TickFlow supplements (name, market_cap from shares × price)
    if _TF:
        try:
            f = _financials_tickflow(ticker)
            if f:
                for k, v in f.items():
                    if k not in result or result[k] is None:
                        result[k] = v
        except Exception:
            pass

    # akshare for CN
    if _AK and market == "CN":
        try:
            f = _financials_akshare(ticker)
            if f:
                for k, v in f.items():
                    if k not in result or result[k] is None:
                        result[k] = v
        except Exception:
            pass

    if result:
        result["ticker"] = ticker.upper()
        result["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        _cache_set(cache_key, result)
        return result

    return None


def get_instrument(ticker: str) -> dict | None:
    """Fetch instrument metadata (name, exchange, shares, listing date)."""
    cache_key = f"inst:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # TickFlow instruments
    if _TF:
        i = _instrument_tickflow(ticker)
        if i:
            _cache_set(cache_key, i)
            return i

    # yfinance .info fallback
    if _YF:
        i = _instrument_yfinance(ticker)
        if i:
            _cache_set(cache_key, i)
            return i

    return None


def resolve_ticker(name: str, market: str = "auto") -> str | None:
    """Resolve a company name to a ticker symbol."""
    if market == "auto":
        # CJK characters → CN market
        if any("\u4e00" <= c <= "\u9fff" for c in name):
            market = "CN"
        else:
            market = "US"

    # TickFlow instrument search
    if _TF:
        tf = _get_tf()
        if tf:
            try:
                symbol = _to_tf_symbol(name) if name[0].isascii() and name[0].isupper() else None
                if symbol is None:
                    # Search by name
                    results = tf.instruments.search(name, market=market)
                    if results:
                        return results[0].get("symbol")
            except Exception:
                pass

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE IMPLEMENTATIONS — OHLCV
# ═══════════════════════════════════════════════════════════════════════════════


def _ohlcv_tickflow(ticker: str, period: str, interval: str, count: int):
    """TickFlow klines → yfinance-compatible DataFrame."""
    if not _TF or not _PD:
        return None
    tf = _get_tf()
    if not tf:
        return None
    symbol = _to_tf_symbol(ticker)
    tf_period = _INTERVAL_MAP.get(interval, "1d")
    df = tf.klines.get(symbol, period=tf_period, count=count, as_dataframe=True)
    if df is None or df.empty:
        return None
    # Rename to Title Case
    for col in list(df.columns):
        cl = col.lower()
        if cl == "open": df = df.rename(columns={col: "Open"})
        elif cl == "high": df = df.rename(columns={col: "High"})
        elif cl == "low": df = df.rename(columns={col: "Low"})
        elif cl == "close": df = df.rename(columns={col: "Close"})
        elif cl == "volume": df = df.rename(columns={col: "Volume"})
    for req in ("Open", "High", "Low", "Close"):
        if req not in df.columns:
            return None
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


def _ohlcv_yfinance(ticker: str, period: str, interval: str, count: int):
    """yfinance history → DataFrame."""
    if not _YF:
        return None
    t = yf.Ticker(ticker)
    hist = t.history(period=period, interval=interval)
    if hist is None or hist.empty:
        return None
    return hist


def _ohlcv_akshare(ticker: str, period: str, interval: str, count: int):
    """akshare A-share OHLCV → DataFrame."""
    if not _AK or not _PD:
        return None
    code = _a_share_code(ticker)
    period_map = {"1mo": "daily", "3mo": "daily", "6mo": "daily", "1y": "daily", "2y": "daily", "5y": "daily"}
    adjust = "qfq"  # forward-adjusted
    try:
        df = ak.stock_zh_a_hist(symbol=code, period=period_map.get(period, "daily"), adjust=adjust)
        if df is None or df.empty:
            return None
        # akshare columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        col_map = {"日期": "date", "开盘": "Open", "收盘": "Close", "最高": "High", "最低": "Low", "成交量": "Volume"}
        df = df.rename(columns=col_map)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        df = df[["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in df.columns else [])]
        return df.tail(count) if count else df
    except Exception:
        return None


def _ohlcv_baostock(ticker: str, period: str, interval: str, count: int):
    """baostock A-share OHLCV → DataFrame."""
    if not _BS or not _PD:
        return None
    code = _a_share_code(ticker)
    # baostock uses sh./sz. prefix
    if ticker.upper().endswith(".SH") or (code.startswith("6") and not ticker.upper().endswith(".SZ")):
        bs_code = f"sh.{code}"
    else:
        bs_code = f"sz.{code}"
    try:
        bs.login()
        today = datetime.now().strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date="2020-01-01", end_date=today,
            frequency="d", adjustflag="2",
        )
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        bs.logout()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.tail(count) if count else df
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE IMPLEMENTATIONS — Quote / Financials / Instrument
# ═══════════════════════════════════════════════════════════════════════════════


def _quote_tickflow(ticker: str) -> dict | None:
    tf = _get_tf()
    if not tf:
        return None
    symbol = _to_tf_symbol(ticker)
    quotes = tf.quotes.get(symbols=[symbol])
    if not quotes:
        return None
    q = quotes[0]
    return {
        "price": q.get("last_price"),
        "open": q.get("open"),
        "high": q.get("high"),
        "low": q.get("low"),
        "volume": q.get("volume"),
        "bid": q.get("bid"),
        "ask": q.get("ask"),
        "trade_date": q.get("trade_date"),
        "source": "tickflow",
    }


def _quote_yfinance(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info if hasattr(t, "fast_info") else t.info
        price = getattr(info, "last_price", None) if hasattr(info, "last_price") else (info.get("regularMarketPrice") if isinstance(info, dict) else None)
        prev = getattr(info, "previous_close", None) if hasattr(info, "previous_close") else (info.get("regularMarketPreviousClose") if isinstance(info, dict) else None)
        change_pct = round((price - prev) / prev * 100, 2) if price and prev and prev > 0 else None
        return {"price": price, "previous_close": prev, "change_pct": change_pct, "source": "yfinance"}
    except Exception:
        return None


def _quote_akshare(ticker: str) -> dict | None:
    try:
        code = _a_share_code(ticker)
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "price": float(r.get("最新价", 0) or 0),
            "open": float(r.get("今开", 0) or 0),
            "high": float(r.get("最高", 0) or 0),
            "low": float(r.get("最低", 0) or 0),
            "volume": float(r.get("成交量", 0) or 0),
            "source": "akshare",
        }
    except Exception:
        return None


def _financials_yfinance(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        return {
            "pe": info.get("trailingPE") or info.get("forwardPE"),
            "pb": info.get("priceToBook"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "revenue": info.get("totalRevenue"),
            "net_income": info.get("netIncomeToCommon"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe": info.get("returnOnEquity"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "source": "yfinance",
        }
    except Exception:
        return None


def _financials_tickflow(ticker: str) -> dict | None:
    tf = _get_tf()
    if not tf:
        return None
    symbol = _to_tf_symbol(ticker)
    result = {}
    try:
        fin = tf.financials.get(symbol)
        if fin:
            result.update({"pe": fin.get("pe"), "pb": fin.get("pb"), "market_cap": fin.get("market_cap"), "source": "tickflow"})
    except Exception:
        pass
    try:
        inst = tf.instruments.get(symbol)
        if inst:
            ext = inst.get("ext", {}) or {}
            if ext.get("total_shares"):
                result["total_shares"] = ext["total_shares"]
    except Exception:
        pass
    return result or None


def _financials_akshare(ticker: str) -> dict | None:
    try:
        code = _a_share_code(ticker)
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty:
            return None
        info = dict(zip(df["item"], df["value"]))
        return {
            "pe": float(info.get("市盈率(动态)", 0) or 0) or None,
            "pb": float(info.get("市净率", 0) or 0) or None,
            "market_cap": float(info.get("总市值", 0) or 0) or None,
            "source": "akshare",
        }
    except Exception:
        return None


def _instrument_tickflow(ticker: str) -> dict | None:
    tf = _get_tf()
    if not tf:
        return None
    symbol = _to_tf_symbol(ticker)
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
        "source": "tickflow",
    }


def _instrument_yfinance(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        return {
            "name": info.get("longName") or info.get("shortName"),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "total_shares": info.get("sharesOutstanding"),
            "source": "yfinance",
        }
    except Exception:
        return None
