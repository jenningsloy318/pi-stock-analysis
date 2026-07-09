#!/usr/bin/env python3
"""Multi-source stock data cross-validation to catch ticker/price/financial errors.

Usage:
    uv run python validate_stock_data.py 603738.SS 002475.SZ
    uv run python validate_stock_data.py AAPL MSFT --strict
    uv run python validate_stock_data.py 600519.SS --sources yfinance,stockdb --output validation.json

Fetches data from multiple sources (yfinance, StockDB, akshare) and flags
discrepancies in ticker codes, prices, names, and financial metrics. Produces
a validation score (0-100) per ticker with detailed per-check breakdown.

Problem solved: screening/discovery sometimes produces wrong ticker codes,
stale prices, or mismatched company names. This script provides automated
cross-validation before analysis stages begin.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: 'yfinance' package required. Run: pip install yfinance\n")
    sys.exit(1)

# Optional: akshare
try:
    import akshare as ak

    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False

# Optional: tickflow
try:
    from tickflow import TickFlow

    _TICKFLOW_AVAILABLE = True
except ImportError:
    _TICKFLOW_AVAILABLE = False

# Optional: curl_cffi for Sina/Tencent
try:
    from curl_cffi import requests as cffi_requests

    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOCKDB_BASE_URL = "http://127.0.0.1:7899"
STOCKDB_TIMEOUT = 2  # seconds

# Validation weights
VALIDATION_WEIGHTS = {
    "V1_name": 0.30,
    "V2_price": 0.30,
    "V3_market_cap": 0.15,
    "V4_valuation": 0.15,
    "V5_freshness": 0.10,
}

# Verdicts
VERDICTS = [
    (90, "VALIDATED", "✅"),
    (70, "VALIDATED_WITH_NOTES", "⚠️"),
    (50, "SUSPICIOUS", "\U0001f536"),
    (0, "INVALID", "❌"),
]

# A-share suffix patterns
A_SHARE_SUFFIXES = (".SS", ".SZ", ".BJ", ".SH")


# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------


def is_a_share(ticker: str) -> bool:
    """Check if a ticker is a China A-share stock."""
    upper = ticker.upper()
    return any(upper.endswith(s) for s in A_SHARE_SUFFIXES)


def extract_code(ticker: str) -> str:
    """Extract numeric code from ticker (e.g., 603738.SS -> 603738)."""
    parts = ticker.split(".")
    return parts[0] if parts else ticker


def normalize_ticker(raw: str) -> str:
    """Normalize ticker to uppercase, strip whitespace."""
    normalized = raw.strip().upper()
    return normalized


def fuzzy_name_match(name1: str, name2: str) -> str:
    """Compare two company names and return match level.

    Returns: 'exact', 'partial', or 'mismatch'
    """
    if not name1 or not name2:
        return "mismatch"

    n1 = name1.strip().lower()
    n2 = name2.strip().lower()

    # Exact match
    if n1 == n2:
        return "exact"

    # Chinese: first 2 characters match
    chinese_chars_1 = re.findall(r"[一-鿿]", n1)
    chinese_chars_2 = re.findall(r"[一-鿿]", n2)
    if chinese_chars_1 and chinese_chars_2:
        if chinese_chars_1[:2] == chinese_chars_2[:2]:
            return "partial"

    # Cross-language case: one is Chinese, other is English
    # This happens with yfinance (English) vs tickflow/sina (Chinese)
    # Treat as "partial" — cannot compare across languages, not a true mismatch
    if chinese_chars_1 and not chinese_chars_2:
        return "partial"
    if chinese_chars_2 and not chinese_chars_1:
        return "partial"

    # English: root word containment
    words_1 = set(re.findall(r"[a-z]+", n1))
    words_2 = set(re.findall(r"[a-z]+", n2))
    if words_1 and words_2:
        common = words_1 & words_2
        # If significant overlap
        if len(common) >= min(len(words_1), len(words_2)) * 0.5:
            return "partial"

    # One name contained in the other
    if n1 in n2 or n2 in n1:
        return "partial"

    return "mismatch"


def compute_pct_diff(val1: float, val2: float) -> float:
    """Compute percentage difference between two values.

    Returns absolute percentage difference. Handles zero denominators.
    """
    if val1 is None or val2 is None:
        return float("inf")
    avg = (abs(val1) + abs(val2)) / 2
    if avg == 0:
        return 0.0
    return abs(val1 - val2) / avg * 100


def get_verdict(score: float) -> tuple:
    """Return (verdict_name, emoji) based on validation score."""
    for threshold, name, emoji in VERDICTS:
        if score >= threshold:
            return name, emoji
    return "INVALID", "❌"


def trading_days_ago(date_str: str) -> int:
    """Estimate trading days between given date and today.

    Simple approximation: weekdays only.
    """
    if not date_str:
        return 999
    try:
        if isinstance(date_str, str):
            # Handle various date formats
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y%m%d"):
                try:
                    d = datetime.strptime(date_str[:10], fmt[: min(len(fmt), 10)])
                    break
                except ValueError:
                    continue
            else:
                return 999
        else:
            d = date_str

        today = datetime.now()
        delta = (today - d).days
        # Rough trading days estimate (5/7 of calendar days)
        return max(0, int(delta * 5 / 7))
    except (ValueError, TypeError):
        return 999


# ---------------------------------------------------------------------------
# Source 1: yfinance
# ---------------------------------------------------------------------------


def fetch_from_yfinance(ticker: str) -> dict | None:
    """Fetch stock data from yfinance.

    Returns dict with price, name, pe, pb, market_cap, sector, industry, date.
    Returns None on failure.
    """
    try:
        # yfinance uses .SS for Shanghai stocks, not .SH
        yf_ticker = (
            ticker.replace(".SH", ".SS") if ticker.upper().endswith(".SH") else ticker
        )
        t = yf.Ticker(yf_ticker)
        info = t.info

        if not info or info.get("regularMarketPrice") is None:
            # Try fast_info as fallback
            try:
                fast = t.fast_info
                price = getattr(fast, "last_price", None)
                market_cap = getattr(fast, "market_cap", None)
            except Exception:
                return None

            if price is None:
                return None

            return {
                "source": "yfinance",
                "price": float(price) if price else None,
                "name": info.get("shortName") or info.get("longName"),
                "pe": info.get("trailingPE"),
                "pb": info.get("priceToBook"),
                "market_cap": float(market_cap) if market_cap else None,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }

        price = info.get("regularMarketPrice") or info.get("currentPrice")
        name = info.get("shortName") or info.get("longName")
        pe = info.get("trailingPE")
        pb = info.get("priceToBook")
        market_cap = info.get("marketCap")
        sector = info.get("sector")
        industry = info.get("industry")

        # Determine data date
        data_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if info.get("regularMarketTime"):
            try:
                ts = info["regularMarketTime"]
                data_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )
            except (TypeError, ValueError, OSError):
                pass

        return {
            "source": "yfinance",
            "price": float(price) if price else None,
            "name": name,
            "pe": float(pe) if pe else None,
            "pb": float(pb) if pb else None,
            "market_cap": float(market_cap) if market_cap else None,
            "sector": sector,
            "industry": industry,
            "date": data_date,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        sys.stderr.write(f"[yfinance] Error fetching {ticker}: {e}\n")
        return None


# ---------------------------------------------------------------------------
# Source 2: StockDB (A-shares only, local instance)
# ---------------------------------------------------------------------------


def fetch_from_stockdb(ticker: str) -> dict | None:
    """Fetch stock data from local StockDB instance.

    Only works for A-share tickers. Returns None if StockDB is unavailable
    or ticker is not an A-share.
    """
    if not is_a_share(ticker):
        return None

    code = extract_code(ticker)

    # Try query endpoint
    url = (
        f"{STOCKDB_BASE_URL}/query?"
        f"code={code}&frequency=1d&limit=1"
        f"&fields=code,name,close,pe,pb,volume,date"
    )

    try:
        req = Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=STOCKDB_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Parse response - handle various response formats
        if isinstance(data, list) and len(data) > 0:
            record = data[0] if isinstance(data[0], dict) else data
        elif isinstance(data, dict):
            # Might be wrapped in a data key
            record = data.get("data", [{}])
            if isinstance(record, list):
                record = record[0] if record else {}
        else:
            return None

        if not record:
            return None

        return {
            "source": "stockdb",
            "price": float(record.get("close")) if record.get("close") else None,
            "name": record.get("name"),
            "pe": float(record.get("pe")) if record.get("pe") else None,
            "pb": float(record.get("pb")) if record.get("pb") else None,
            "market_cap": None,  # StockDB may not provide this directly
            "volume": record.get("volume"),
            "date": record.get("date"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    except (URLError, OSError, json.JSONDecodeError):
        # Connection refused, timeout, or invalid response — skip silently
        pass

    # Try alternative POST endpoint
    try:
        post_data = json.dumps(
            {
                "code": code,
                "frequency": "1d",
                "limit": 1,
            }
        ).encode("utf-8")

        req = Request(
            STOCKDB_BASE_URL,
            data=post_data,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        with urlopen(req, timeout=STOCKDB_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if isinstance(data, list) and len(data) > 0:
            record = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            record = data.get("data", [{}])
            if isinstance(record, list):
                record = record[0] if record else {}
        else:
            return None

        if not record:
            return None

        return {
            "source": "stockdb",
            "price": float(record.get("close")) if record.get("close") else None,
            "name": record.get("name"),
            "pe": float(record.get("pe")) if record.get("pe") else None,
            "pb": float(record.get("pb")) if record.get("pb") else None,
            "market_cap": None,
            "volume": record.get("volume"),
            "date": record.get("date"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    except (URLError, OSError, json.JSONDecodeError):
        # StockDB not available — skip silently
        return None


# ---------------------------------------------------------------------------
# Source 3: akshare (A-shares, optional)
# ---------------------------------------------------------------------------


def fetch_from_akshare(ticker: str) -> dict | None:
    """Fetch stock data from akshare.

    Only works for A-share tickers and only if akshare is installed.
    Returns None if unavailable.
    """
    if not _AKSHARE_AVAILABLE:
        return None

    if not is_a_share(ticker):
        return None

    code = extract_code(ticker)

    try:
        # Fetch real-time quote from A-share spot data
        df_spot = ak.stock_zh_a_spot_em()

        if df_spot is None or df_spot.empty:
            return None

        # Find the ticker in the spot data
        row = df_spot[df_spot["代码"] == code]
        if row.empty:
            # Try with leading zeros stripped/added
            row = df_spot[df_spot["代码"].str.contains(code)]

        if row.empty:
            return None

        row = row.iloc[0]

        price = row.get("最新价")  # 最新价
        name = row.get("名称")  # 名称
        pe = row.get("市盈率-动态")  # 市盈率-动态
        pb = row.get("市净率")  # 市净率
        market_cap = row.get("总市值")  # 总市值

        return {
            "source": "akshare",
            "price": float(price) if price and price != "-" else None,
            "name": str(name) if name else None,
            "pe": float(pe) if pe and pe != "-" else None,
            "pb": float(pb) if pb and pb != "-" else None,
            "market_cap": float(market_cap)
            if market_cap and market_cap != "-"
            else None,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        sys.stderr.write(f"[akshare] Error fetching {ticker}: {e}\n")
        return None


# ---------------------------------------------------------------------------
# Source 4: TickFlow (CN + US, via tickflow SDK)
# ---------------------------------------------------------------------------


def fetch_from_tickflow(ticker: str) -> dict | None:
    """Fetch stock data from TickFlow API.

    Works for A-shares (SH/SZ/BJ) and US stocks. Provides real-time quotes
    and instrument metadata (name, total_shares, listing_date).
    Returns None on failure.
    """
    if not _TICKFLOW_AVAILABLE:
        return None

    try:
        # Initialize client
        api_key = os.environ.get("TICKFLOW_API_KEY")
        if api_key:
            tf = TickFlow(api_key=api_key)
        else:
            tf = TickFlow.free()

        # Convert ticker format: .SS -> .SH for TickFlow
        tf_ticker = ticker.upper()
        if tf_ticker.endswith(".SS"):
            tf_ticker = tf_ticker[:-3] + ".SH"

        # Get instrument info (name)
        name = None
        total_shares = None
        try:
            inst = tf.instruments.get(tf_ticker)
            name = inst.get("name")
            total_shares = inst.get("ext", {}).get("total_shares")
        except Exception:
            pass

        # Get real-time quote (price)
        price = None
        data_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            if api_key:
                quotes = tf.quotes.get(symbols=[tf_ticker])
                if quotes:
                    q = quotes[0]
                    price = q.get("last_price")
                    # Extract date from trade_date field
                    trade_date = q.get("trade_date")
                    if trade_date:
                        data_date = trade_date
        except Exception:
            pass

        # Fallback: get price from latest kline if quotes unavailable
        if price is None:
            try:
                df = tf.klines.get(tf_ticker, period="1d", count=1, as_dataframe=True)
                if df is not None and not df.empty:
                    price = float(df["close"].iloc[-1])
            except Exception:
                pass

        if price is None and name is None:
            return None

        # Compute market cap from price * total_shares
        market_cap = None
        if price and total_shares:
            market_cap = price * total_shares

        return {
            "source": "tickflow",
            "price": float(price) if price else None,
            "name": name,
            "pe": None,  # TickFlow free/basic doesn't provide PE
            "pb": None,  # TickFlow free/basic doesn't provide PB
            "market_cap": market_cap,
            "date": data_date,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        sys.stderr.write(f"[tickflow] Error fetching {ticker}: {e}\n")
        return None


# ---------------------------------------------------------------------------
# Source 5: Sina Finance (A-shares only, via curl_cffi)
# ---------------------------------------------------------------------------


def fetch_from_sina(ticker: str) -> dict | None:
    """Fetch stock data from Sina Finance real-time quotes.

    Only works for A-share tickers. Uses curl_cffi with Chrome impersonation
    to bypass TLS fingerprint checks.
    Returns None on failure.
    """
    if not _CURL_CFFI_AVAILABLE:
        return None

    if not is_a_share(ticker):
        return None

    code = extract_code(ticker)
    upper = ticker.upper()

    # Determine Sina code format: sh688332 or sz300750
    if upper.endswith(".SH") or upper.endswith(".SS"):
        sina_code = f"sh{code}"
    elif upper.endswith(".SZ"):
        sina_code = f"sz{code}"
    elif upper.endswith(".BJ"):
        sina_code = f"bj{code}"
    else:
        # Infer from first digit
        first = code[0] if code else ""
        if first in ("6", "9"):
            sina_code = f"sh{code}"
        else:
            sina_code = f"sz{code}"

    try:
        r = cffi_requests.get(
            f"https://hq.sinajs.cn/list={sina_code}",
            impersonate="chrome",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
        if r.status_code != 200:
            return None

        # Parse: var hq_str_sh688332="name,open,prev_close,price,...,date,time,status";
        match = re.search(r'"([^"]*)"', r.text)
        if not match or not match.group(1):
            return None

        fields = match.group(1).split(",")
        if len(fields) < 32:
            return None

        name = fields[0]
        price = float(fields[3]) if fields[3] else None
        data_date = fields[30] if len(fields) > 30 else None

        if not name and not price:
            return None

        return {
            "source": "sina",
            "price": price,
            "name": name,
            "pe": None,  # Sina quote doesn't include PE
            "pb": None,  # Sina quote doesn't include PB
            "market_cap": None,
            "date": data_date,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        sys.stderr.write(f"[sina] Error fetching {ticker}: {e}\n")
        return None


# ---------------------------------------------------------------------------
# Validation Check V1: Ticker-Name Consistency
# ---------------------------------------------------------------------------


def check_v1_name(source_data: dict) -> dict:
    """V1: Compare company names across all available sources.

    Returns check result dict with score, pass status, and detail.
    """
    names = {}
    for src, data in source_data.items():
        if data and data.get("name"):
            names[src] = data["name"]

    if len(names) < 2:
        # Only one source available — cannot cross-validate
        if len(names) == 1:
            src, name = list(names.items())[0]
            return {
                "score": 70,
                "pass": True,
                "detail": f"Only 1 source available ({src}: {name}) — cannot cross-validate",
            }
        return {
            "score": 0,
            "pass": False,
            "detail": "No name data available from any source",
        }

    # Compare all pairs
    sources = list(names.keys())
    match_levels = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            level = fuzzy_name_match(names[sources[i]], names[sources[j]])
            match_levels.append((sources[i], sources[j], level))

    # Determine overall result
    all_levels = [m[2] for m in match_levels]

    if all(level == "exact" for level in all_levels):
        name_list = ", ".join(f"{s}={names[s]}" for s in sources)
        return {
            "score": 100,
            "pass": True,
            "detail": f"Exact match across {len(sources)} sources: {name_list}",
        }
    elif all(level in ("exact", "partial") for level in all_levels):
        name_list = ", ".join(f"{s}={names[s]}" for s in sources)
        return {
            "score": 60,
            "pass": True,
            "detail": f"Partial match across sources: {name_list}",
        }
    else:
        name_list = ", ".join(f"{s}={names[s]}" for s in sources)
        mismatches = [f"{m[0]} vs {m[1]}" for m in match_levels if m[2] == "mismatch"]
        return {
            "score": 0,
            "pass": False,
            "detail": f"CRITICAL: Name mismatch — {name_list}. Conflicts: {', '.join(mismatches)}",
        }


# ---------------------------------------------------------------------------
# Validation Check V2: Price Consistency
# ---------------------------------------------------------------------------


def check_v2_price(source_data: dict) -> dict:
    """V2: Compare current/latest close price from all available sources.

    Returns check result dict with score, pass status, and detail.
    """
    prices = {}
    for src, data in source_data.items():
        if data and data.get("price") is not None:
            prices[src] = data["price"]

    if len(prices) < 2:
        if len(prices) == 1:
            src, price = list(prices.items())[0]
            return {
                "score": 70,
                "pass": True,
                "detail": f"Only 1 source ({src}={price}) — cannot cross-validate price",
            }
        return {
            "score": 0,
            "pass": False,
            "detail": "No price data available from any source",
        }

    # Compute pairwise differences
    sources = list(prices.keys())
    max_diff = 0.0
    diff_details = []

    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            diff = compute_pct_diff(prices[sources[i]], prices[sources[j]])
            max_diff = max(max_diff, diff)
            diff_details.append(
                f"{sources[i]}={prices[sources[i]]:.2f}, "
                f"{sources[j]}={prices[sources[j]]:.2f} "
                f"(diff {diff:.2f}%)"
            )

    # Score based on maximum discrepancy
    if max_diff <= 2.0:
        score = 100
    elif max_diff <= 5.0:
        score = 70
    elif max_diff <= 10.0:
        score = 40
    else:
        score = 0

    passed = score >= 40
    detail = "; ".join(diff_details)

    if max_diff > 20:
        detail = f"CRITICAL: {detail}"
    elif max_diff > 5:
        detail = f"WARNING: {detail}"

    return {
        "score": score,
        "pass": passed,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Validation Check V3: Market Cap Consistency
# ---------------------------------------------------------------------------


def check_v3_market_cap(source_data: dict) -> dict:
    """V3: Compare market cap across sources.

    Returns check result dict with score, pass status, and detail.
    """
    caps = {}
    for src, data in source_data.items():
        if data and data.get("market_cap") is not None and data["market_cap"] > 0:
            caps[src] = data["market_cap"]

    if len(caps) < 2:
        if len(caps) == 1:
            src, cap = list(caps.items())[0]
            cap_display = f"{cap / 1e8:.1f}亿" if cap > 1e8 else f"{cap:,.0f}"
            return {
                "score": 70,
                "pass": True,
                "detail": f"Only 1 source ({src}={cap_display}) — cannot cross-validate market cap",
            }
        return {
            "score": 50,
            "pass": True,
            "detail": "Market cap not available from multiple sources — skipped",
        }

    # Compute pairwise differences
    sources = list(caps.keys())
    max_diff = 0.0
    diff_details = []

    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            diff = compute_pct_diff(caps[sources[i]], caps[sources[j]])
            max_diff = max(max_diff, diff)
            cap_i = f"{caps[sources[i]] / 1e8:.1f}亿"
            cap_j = f"{caps[sources[j]] / 1e8:.1f}亿"
            diff_details.append(
                f"{sources[i]}={cap_i}, {sources[j]}={cap_j} " f"(diff {diff:.1f}%)"
            )

    if max_diff <= 10.0:
        score = 100
    elif max_diff <= 30.0:
        score = 60
    else:
        score = 0

    passed = score >= 60
    detail = "; ".join(diff_details)

    return {
        "score": score,
        "pass": passed,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Validation Check V4: Valuation Consistency (PE/PB)
# ---------------------------------------------------------------------------


def check_v4_valuation(source_data: dict) -> dict:
    """V4: Compare PE and PB ratios across sources.

    Returns check result dict with score, pass status, and detail.
    """
    pe_values = {}
    pb_values = {}

    for src, data in source_data.items():
        if data:
            if data.get("pe") is not None:
                pe_values[src] = data["pe"]
            if data.get("pb") is not None:
                pb_values[src] = data["pb"]

    pe_score = _score_valuation_metric(pe_values, "PE")
    pb_score = _score_valuation_metric(pb_values, "PB")

    # Average the two scores
    scores = []
    details = []

    if pe_score is not None:
        scores.append(pe_score["score"])
        details.append(f"PE: {pe_score['detail']}")
    if pb_score is not None:
        scores.append(pb_score["score"])
        details.append(f"PB: {pb_score['detail']}")

    if not scores:
        return {
            "score": 50,
            "pass": True,
            "detail": "Valuation metrics not available from multiple sources — skipped",
        }

    avg_score = sum(scores) / len(scores)
    return {
        "score": avg_score,
        "pass": avg_score >= 40,
        "detail": ". ".join(details),
    }


def _score_valuation_metric(values: dict, metric_name: str) -> dict | None:
    """Score a single valuation metric (PE or PB) across sources."""
    if len(values) < 2:
        if len(values) == 1:
            src, val = list(values.items())[0]
            return {
                "score": 70,
                "detail": f"{src}={val:.1f} (single source)",
            }
        return None

    sources = list(values.keys())

    # Check sign consistency (both negative or both positive)
    signs = [values[s] > 0 for s in sources]
    if len(set(signs)) > 1:
        # Inconsistent signs — one shows profit, other shows loss
        vals_str = ", ".join(f"{s}={values[s]:.1f}" for s in sources)
        return {
            "score": 30,
            "detail": f"Sign mismatch ({vals_str})",
        }

    # Compute max percentage difference
    max_diff = 0.0
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            diff = compute_pct_diff(values[sources[i]], values[sources[j]])
            max_diff = max(max_diff, diff)

    vals_str = ", ".join(f"{s}={values[s]:.1f}" for s in sources)

    if max_diff <= 10.0:
        score = 100
    elif max_diff <= 30.0:
        score = 60
    else:
        score = 30

    return {
        "score": score,
        "detail": f"{vals_str} (diff {max_diff:.1f}%)",
    }


# ---------------------------------------------------------------------------
# Validation Check V5: Data Freshness
# ---------------------------------------------------------------------------


def check_v5_freshness(source_data: dict) -> dict:
    """V5: Check how fresh the data is from each source.

    Returns check result dict with score, pass status, and detail.
    """
    freshness_details = []
    worst_days = 0

    for src, data in source_data.items():
        if data and data.get("date"):
            days = trading_days_ago(data["date"])
            freshness_details.append(f"{src}: {data['date']} ({days}d ago)")
            worst_days = max(worst_days, days)
        elif data:
            freshness_details.append(f"{src}: no date info")
            worst_days = max(worst_days, 5)

    if not freshness_details:
        return {
            "score": 0,
            "pass": False,
            "detail": "No date information available from any source",
        }

    # Score based on worst staleness
    if worst_days == 0:
        score = 100
    elif worst_days <= 3:
        score = 70
    elif worst_days <= 10:
        score = 30
    else:
        score = 0

    detail = "; ".join(freshness_details)
    if worst_days == 0:
        detail = f"All sources have today's data. {detail}"
    elif worst_days <= 3:
        detail = f"Data within 3 trading days. {detail}"
    else:
        detail = f"STALE: data is {worst_days} trading days old. {detail}"

    return {
        "score": score,
        "pass": score >= 30,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Auto-Correction Logic
# ---------------------------------------------------------------------------


def compute_recommended_values(source_data: dict) -> dict:
    """Determine the best-validated values from all sources.

    When sources disagree on price:
    - If 2 of 3 agree (within 2%): use majority value
    - If all disagree: use source with most recent timestamp
    - Always output recommended_values with best-validated data
    """
    prices = {}
    for src, data in source_data.items():
        if data and data.get("price") is not None:
            prices[src] = data["price"]

    # Find consensus price
    consensus_price = None
    consensus_source = None

    if len(prices) >= 3:
        # Check if 2 of 3 agree
        sources = list(prices.keys())
        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                diff = compute_pct_diff(prices[sources[i]], prices[sources[j]])
                if diff <= 2.0:
                    # These two agree — use their average
                    consensus_price = (prices[sources[i]] + prices[sources[j]]) / 2
                    consensus_source = f"{sources[i]}+{sources[j]} consensus"
                    break
            if consensus_price is not None:
                break

    if consensus_price is None and prices:
        # Use most recent source or primary (yfinance)
        if "yfinance" in prices:
            consensus_price = prices["yfinance"]
            consensus_source = "yfinance (primary)"
        else:
            # Pick source with most recent date
            best_src = None
            best_date = ""
            for src, data in source_data.items():
                if data and data.get("price") is not None:
                    date = data.get("date", "")
                    if date >= best_date:
                        best_date = date
                        best_src = src
            if best_src:
                consensus_price = prices[best_src]
                consensus_source = f"{best_src} (most recent)"

    # Gather best values for each field
    recommended = {
        "price": consensus_price,
        "source": consensus_source,
    }

    # Name: prefer tickflow (Chinese name), then yfinance, then sina, then akshare, then stockdb
    for src in ("tickflow", "sina", "yfinance", "akshare", "stockdb"):
        data = source_data.get(src)
        if data and data.get("name"):
            recommended["name"] = data["name"]
            break

    # PE/PB: prefer yfinance (trailing), then akshare, then stockdb
    for src in ("yfinance", "akshare", "stockdb"):
        data = source_data.get(src)
        if data and data.get("pe") is not None:
            recommended["pe_trailing"] = data["pe"]
            break

    for src in ("yfinance", "akshare", "stockdb"):
        data = source_data.get(src)
        if data and data.get("pb") is not None:
            recommended["pb"] = data["pb"]
            break

    # Market cap: prefer yfinance, then tickflow, then akshare
    for src in ("yfinance", "tickflow", "akshare", "stockdb"):
        data = source_data.get(src)
        if data and data.get("market_cap") is not None:
            recommended["market_cap"] = data["market_cap"]
            break

    # Annotate source validation
    validated_by = [
        s
        for s in source_data
        if source_data[s] is not None and s not in ("yfinance",)
    ]
    if validated_by and consensus_source and "yfinance" in consensus_source:
        recommended["source"] = (
            f"yfinance (primary, validated by {', '.join(validated_by)})"
        )

    return recommended


# ---------------------------------------------------------------------------
# Per-Ticker Validation Orchestrator
# ---------------------------------------------------------------------------


def validate_ticker(ticker: str, enabled_sources: list) -> dict:
    """Run all validation checks for a single ticker.

    Args:
        ticker: Normalized ticker symbol.
        enabled_sources: List of source names to check.

    Returns:
        Full validation result dict for this ticker.
    """
    source_data = {}
    sources_checked = []

    # Source 1: yfinance (always tried if enabled)
    if "yfinance" in enabled_sources:
        yf_data = fetch_from_yfinance(ticker)
        if yf_data is not None:
            source_data["yfinance"] = yf_data
            sources_checked.append("yfinance")
        else:
            source_data["yfinance"] = None

    # Source 2: TickFlow (CN + US)
    if "tickflow" in enabled_sources:
        tf_data = fetch_from_tickflow(ticker)
        if tf_data is not None:
            source_data["tickflow"] = tf_data
            sources_checked.append("tickflow")
        else:
            source_data["tickflow"] = None

    # Source 3: Sina (A-shares only)
    if "sina" in enabled_sources and is_a_share(ticker):
        sina_data = fetch_from_sina(ticker)
        if sina_data is not None:
            source_data["sina"] = sina_data
            sources_checked.append("sina")
        else:
            source_data["sina"] = None

    # Source 4: StockDB (A-shares only, local)
    if "stockdb" in enabled_sources and is_a_share(ticker):
        sdb_data = fetch_from_stockdb(ticker)
        if sdb_data is not None:
            source_data["stockdb"] = sdb_data
            sources_checked.append("stockdb")
        else:
            source_data["stockdb"] = None

    # Source 5: akshare (A-shares only, optional)
    if "akshare" in enabled_sources and is_a_share(ticker):
        ak_data = fetch_from_akshare(ticker)
        if ak_data is not None:
            source_data["akshare"] = ak_data
            sources_checked.append("akshare")
        else:
            source_data["akshare"] = None

    # If no sources returned data, report error
    available_data = {k: v for k, v in source_data.items() if v is not None}
    if not available_data:
        return {
            "ticker": ticker,
            "validation_score": 0,
            "verdict": "INVALID",
            "verdict_emoji": "❌",
            "checks": {
                "V1_name": {
                    "score": 0,
                    "pass": False,
                    "detail": "No data from any source",
                },
                "V2_price": {
                    "score": 0,
                    "pass": False,
                    "detail": "No data from any source",
                },
                "V3_market_cap": {
                    "score": 0,
                    "pass": False,
                    "detail": "No data from any source",
                },
                "V4_valuation": {
                    "score": 0,
                    "pass": False,
                    "detail": "No data from any source",
                },
                "V5_freshness": {
                    "score": 0,
                    "pass": False,
                    "detail": "No data from any source",
                },
            },
            "source_data": {k: v for k, v in source_data.items() if v is not None},
            "recommended_values": None,
            "issues": ["No data could be retrieved from any source"],
            "sources_checked": sources_checked,
        }

    # Run validation checks
    checks = {
        "V1_name": check_v1_name(available_data),
        "V2_price": check_v2_price(available_data),
        "V3_market_cap": check_v3_market_cap(available_data),
        "V4_valuation": check_v4_valuation(available_data),
        "V5_freshness": check_v5_freshness(available_data),
    }

    # Compute composite validation score
    validation_score = sum(
        checks[k]["score"] * VALIDATION_WEIGHTS[k] for k in VALIDATION_WEIGHTS
    )

    # Hard-fail: PE/PB sign mismatch (one source profit, other loss) forces INVALID
    # This catches cases where V4_valuation has only 15% weight but data is fundamentally wrong
    if checks["V4_valuation"]["score"] <= 30:
        pe_values = [
            d.get("pe") for d in available_data.values() if d.get("pe") is not None
        ]
        if len(pe_values) >= 2:
            has_positive = any(v > 0 for v in pe_values)
            has_negative = any(v < 0 for v in pe_values)
            if has_positive and has_negative:
                # Sign mismatch: one source shows profit, another loss
                validation_score = min(validation_score, 40)

    # Determine verdict
    verdict_name, verdict_emoji = get_verdict(validation_score)

    # Collect issues
    issues = []
    for check_name, result in checks.items():
        if not result["pass"]:
            issues.append(f"{check_name}: {result['detail']}")

    # Compute recommended values
    recommended = compute_recommended_values(available_data)

    # Build clean source_data for output (remove internal fields)
    output_sources = {}
    for src, data in source_data.items():
        if data is not None:
            output_sources[src] = {
                "price": data.get("price"),
                "name": data.get("name"),
                "pe": data.get("pe"),
                "pb": data.get("pb"),
                "market_cap": data.get("market_cap"),
                "date": data.get("date"),
            }
        else:
            output_sources[src] = None

    return {
        "ticker": ticker,
        "validation_score": round(validation_score, 1),
        "verdict": verdict_name,
        "verdict_emoji": verdict_emoji,
        "checks": checks,
        "source_data": output_sources,
        "recommended_values": recommended,
        "issues": issues,
        "sources_checked": sources_checked,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Multi-source stock data cross-validation"
    )
    parser.add_argument(
        "tickers",
        nargs="+",
        help="One or more ticker symbols to validate (e.g., 603738.SS AAPL)",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit with code 2 if ANY ticker has discrepancies (validation_score < 90)",
    )
    parser.add_argument(
        "--sources",
        default="yfinance,tickflow,sina,stockdb,akshare",
        help="Comma-separated list of sources to check (default: yfinance,tickflow,sina,stockdb,akshare)",
    )

    args = parser.parse_args()

    # Parse enabled sources
    enabled_sources = [s.strip().lower() for s in args.sources.split(",")]
    valid_sources = {"yfinance", "stockdb", "akshare", "tickflow", "sina"}
    for src in enabled_sources:
        if src not in valid_sources:
            sys.stderr.write(f"Warning: Unknown source '{src}' — ignoring\n")
    enabled_sources = [s for s in enabled_sources if s in valid_sources]

    if not enabled_sources:
        sys.stderr.write("Error: No valid sources specified.\n")
        sys.exit(1)

    # Validate each ticker
    results = {}
    has_failure = False

    for raw_ticker in args.tickers:
        ticker = normalize_ticker(raw_ticker)

        try:
            result = validate_ticker(ticker, enabled_sources)
            results[ticker] = result

            # Check for failures in strict mode
            if result["validation_score"] < 90:
                has_failure = True

            # Log progress to stderr
            sys.stderr.write(
                f"[{result['verdict_emoji']}] {ticker}: "
                f"score={result['validation_score']}, "
                f"verdict={result['verdict']}\n"
            )

        except Exception as e:
            results[ticker] = {
                "ticker": ticker,
                "validation_score": 0,
                "verdict": "ERROR",
                "verdict_emoji": "❌",
                "error": str(e),
                "checks": {},
                "source_data": {},
                "recommended_values": None,
                "issues": [f"Unexpected error: {e}"],
                "sources_checked": [],
            }
            has_failure = True
            sys.stderr.write(f"[❌] {ticker}: ERROR — {e}\n")

        # Brief delay between tickers to avoid rate limiting
        time.sleep(0.5)

    # Build final output
    output_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources_checked": enabled_sources,
        "results": results,
    }

    output = json.dumps(output_data, indent=2, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        sys.stderr.write(f"\nResults written to: {args.output}\n")
    else:
        print(output)

    # Exit codes
    if args.strict and has_failure:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
