#!/usr/bin/env python3
"""Resolve company names to authoritative ticker codes (CN A-shares + US stocks).

Usage:
    uv run python resolve_tickers.py "纳芯微" "美埃科技" "甬矽电子"
    uv run python resolve_tickers.py "Monday.com" "CrowdStrike" "Palantir"
    uv run python resolve_tickers.py --input names.json --output resolved.json
    uv run python resolve_tickers.py "贵州茅台" "NVIDIA" --format ticker
    uv run python resolve_tickers.py --market CN "纳芯微" "圣邦股份"
    uv run python resolve_tickers.py --market US "Monday.com" "Affirm"

Solves the critical problem: LLM agents hallucinate ticker codes when given
only company names. This script provides authoritative name→ticker resolution using:
  CN A-shares: StockDB local → akshare → yfinance (cascading fallback)
  US stocks: yfinance search/lookup → akshare US spot (cascading fallback)

Auto-detects market by name content (CJK chars → CN, Latin → US) unless --market
is specified explicitly.

Returns exact matches, fuzzy matches, and explicit "NOT_FOUND" for unknown names —
never guesses. An agent receiving NOT_FOUND must exclude that company from analysis.

Output format (JSON):
{
  "results": [
    {
      "input_name": "纳芯微",
      "ticker": "688052.SH",
      "official_name": "纳芯微电子",
      "exchange": "SH",
      "match_type": "fuzzy",
      "confidence": 0.95,
      "price": 88.50,
      "source": "akshare"
    },
    {
      "input_name": "Monday.com",
      "ticker": "MNDY",
      "official_name": "Monday.com Ltd.",
      "exchange": "NASDAQ",
      "match_type": "exact",
      "confidence": 1.0,
      "price": 325.40,
      "source": "yfinance"
    },
    ...
  ],
  "errors": [
    {
      "input_name": "美埃科技",
      "status": "NOT_FOUND",
      "reason": "No listing found for this name",
      "candidates": []
    }
  ],
  "summary": {
    "total": 3,
    "resolved": 2,
    "not_found": 1,
    "timestamp": "2026-07-02T10:30:00Z"
  }
}
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

# Optional dependencies
try:
    import akshare as ak

    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch

    _YFINANCE_AVAILABLE = True
except ImportError:
    _YFINANCE_AVAILABLE = False

try:
    from tickflow import TickFlow

    _TICKFLOW_AVAILABLE = True
except ImportError:
    _TICKFLOW_AVAILABLE = False

try:
    from curl_cffi import requests as cffi_requests

    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOCKDB_BASE_URL = os.environ.get("STOCKDB_URL", "http://127.0.0.1:7899")
STOCKDB_TIMEOUT = 3  # seconds

# Exchange suffixes
EXCHANGE_MAP = {
    "6": ".SH",  # Shanghai main board (60xxxx) and STAR Market (688xxx)
    "0": ".SZ",  # Shenzhen main board (000xxx) and SME (002xxx)
    "3": ".SZ",  # ChiNext / 创业板 (300xxx, 301xxx)
    "4": ".BJ",  # Beijing Stock Exchange (4xxxxx) / NEEQ select
    "8": ".BJ",  # Beijing Stock Exchange (8xxxxx)
    "9": ".SH",  # B-share Shanghai (900xxx) — rare
}


# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------


def code_to_ticker(code: str) -> str:
    """Convert a bare 6-digit code to a full ticker with exchange suffix.

    E.g., '688052' -> '688052.SH', '300750' -> '300750.SZ'
    """
    code = code.strip()
    if not code or len(code) != 6:
        return code
    first_digit = code[0]
    suffix = EXCHANGE_MAP.get(first_digit, ".SZ")
    return f"{code}{suffix}"


def normalize_name(name: str) -> str:
    """Normalize a Chinese company name for matching.

    Strips common suffixes like 股份, 科技, 有限公司, etc.
    """
    if not name:
        return ""
    # Remove whitespace
    name = name.strip()
    # Remove common suffixes that differ between short/official names
    for suffix in [
        "股份有限公司",
        "有限公司",
        "股份",
        "(A)",
        "-U",
        "-W",
        "ST ",
        "*ST ",
        "N ",
        "C ",
    ]:
        name = name.replace(suffix, "")
    return name.strip()


def compute_similarity(name1: str, name2: str) -> float:
    """Compute similarity score between two Chinese company names.

    Returns 0.0-1.0. Uses character overlap + prefix matching.
    """
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    if not n1 or not n2:
        return 0.0

    # Exact match after normalization
    if n1 == n2:
        return 1.0

    # One contains the other (e.g., "纳芯微" in "纳芯微电子")
    if n1 in n2 or n2 in n1:
        shorter = min(len(n1), len(n2))
        longer = max(len(n1), len(n2))
        return shorter / longer  # e.g., 3/5 = 0.6 for 纳芯微/纳芯微电子

    # Character-level Jaccard similarity for Chinese text
    chars1 = set(n1)
    chars2 = set(n2)
    if not chars1 or not chars2:
        return 0.0
    intersection = chars1 & chars2
    union = chars1 | chars2
    jaccard = len(intersection) / len(union)

    # Prefix bonus: first 2 characters matching is strong signal
    prefix_len = min(2, len(n1), len(n2))
    if n1[:prefix_len] == n2[:prefix_len]:
        jaccard = min(1.0, jaccard + 0.3)

    return jaccard


# ---------------------------------------------------------------------------
# Source 1: StockDB Local (fastest)
# ---------------------------------------------------------------------------


def resolve_from_stockdb(names: list[str]) -> dict:
    """Attempt to resolve names via StockDB local service.

    StockDB supports a /query endpoint. We need to scan all stocks
    and match by name. If StockDB has a /list or /search endpoint, use it.
    Returns: {name: {ticker, official_name, price, ...} or None}
    """
    results = {}

    # Try to get full stock list from StockDB
    try:
        url = f"{STOCKDB_BASE_URL}/api/stock/list"
        req = Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=STOCKDB_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Build name→code lookup
        stock_list = data if isinstance(data, list) else data.get("data", [])
        if not stock_list:
            return results

        for name in names:
            best_match = None
            best_score = 0.0
            for stock in stock_list:
                stock_name = stock.get("name", "")
                stock_code = stock.get("code", "")
                score = compute_similarity(name, stock_name)
                if score > best_score:
                    best_score = score
                    best_match = stock

            if best_match and best_score >= 0.5:
                code = best_match.get("code", "")
                ticker = code_to_ticker(code)
                results[name] = {
                    "ticker": ticker,
                    "official_name": best_match.get("name"),
                    "price": best_match.get("close") or best_match.get("price"),
                    "confidence": best_score,
                    "match_type": "exact" if best_score >= 0.95 else "fuzzy",
                    "source": "stockdb",
                }

    except (URLError, OSError, json.JSONDecodeError, KeyError):
        pass

    # Fallback: try individual queries by name pattern
    for name in names:
        if name in results:
            continue
        try:
            from urllib.parse import quote

            encoded_name = quote(name)
            url = (
                f"{STOCKDB_BASE_URL}/query?"
                f"name={encoded_name}&frequency=1d&limit=1"
                f"&fields=code,name,close,pe,pb"
            )
            req = Request(url, method="GET")
            req.add_header("Accept", "application/json")
            with urlopen(req, timeout=STOCKDB_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            records = data if isinstance(data, list) else data.get("data", [])
            if records:
                record = records[0] if isinstance(records[0], dict) else {}
                code = record.get("code", "")
                if code:
                    ticker = code_to_ticker(code)
                    results[name] = {
                        "ticker": ticker,
                        "official_name": record.get("name"),
                        "price": record.get("close"),
                        "confidence": 0.9,
                        "match_type": "exact",
                        "source": "stockdb",
                    }
        except (URLError, OSError, json.JSONDecodeError):
            continue

    return results


# ---------------------------------------------------------------------------
# Source 2: TickFlow (CN + US, high priority)
# ---------------------------------------------------------------------------


_tickflow_instruments_cache = None  # Cache instruments within a session


def resolve_from_tickflow(names: list[str], market: str = "CN") -> dict:
    """Resolve names via TickFlow instruments API.

    Uses TickFlow universes to get all symbols, then instruments.batch()
    to get names for matching. Supports CN and US markets.

    Returns: {name: {ticker, official_name, price, ...} or None}
    """
    global _tickflow_instruments_cache
    results = {}

    if not _TICKFLOW_AVAILABLE:
        return results

    try:
        # Initialize client — auto-reads TICKFLOW_API_KEY env var
        api_key = os.environ.get("TICKFLOW_API_KEY")
        if api_key:
            tf = TickFlow(api_key=api_key)
        else:
            tf = TickFlow.free()

        # Get universe symbols
        universe_id = "CN_Equity_A" if market == "CN" else "US_Equity"
        universe = tf.universes.get(universe_id)
        all_symbols = universe.get("symbols", [])

        if not all_symbols:
            return results

        # Try to get quotes (has name in ext.name) for real-time resolution
        # Process in batches of 100 to avoid API limits
        if _tickflow_instruments_cache is None or market not in _tickflow_instruments_cache:
            if _tickflow_instruments_cache is None:
                _tickflow_instruments_cache = {}

            # For CN, batch instruments to get names
            # instruments.batch supports up to 1000 symbols
            name_map = {}  # official_name -> {symbol, ...}
            batch_size = 500
            for i in range(0, min(len(all_symbols), 6000), batch_size):
                batch = all_symbols[i : i + batch_size]
                try:
                    insts = tf.instruments.batch(symbols=batch)
                    for inst in insts:
                        inst_name = inst.get("name", "")
                        if inst_name:
                            name_map[inst_name] = {
                                "symbol": inst["symbol"],
                                "name": inst_name,
                                "total_shares": inst.get("ext", {}).get(
                                    "total_shares"
                                ),
                                "listing_date": inst.get("ext", {}).get(
                                    "listing_date"
                                ),
                            }
                except Exception:
                    continue

            _tickflow_instruments_cache[market] = name_map
        else:
            name_map = _tickflow_instruments_cache[market]

        if not name_map:
            return results

        # Match input names against instrument names
        for name in names:
            best_match = None
            best_score = 0.0

            for inst_name, inst_data in name_map.items():
                score = compute_similarity(name, inst_name)
                if score > best_score:
                    best_score = score
                    best_match = (inst_name, inst_data)

            if best_match and best_score >= 0.6:
                inst_name, inst_data = best_match
                symbol = inst_data["symbol"]
                # Try to get price from quotes
                price = None
                try:
                    if api_key:
                        quotes = tf.quotes.get(symbols=[symbol])
                        if quotes:
                            price = quotes[0].get("last_price")
                except Exception:
                    pass

                results[name] = {
                    "ticker": symbol,
                    "official_name": inst_name,
                    "exchange": symbol.split(".")[-1] if "." in symbol else "",
                    "price": float(price) if price else None,
                    "confidence": round(best_score, 3),
                    "match_type": "exact" if best_score >= 0.95 else "fuzzy",
                    "source": "tickflow",
                }

    except Exception as e:
        sys.stderr.write(f"[tickflow] Error resolving names: {e}\n")

    return results


# ---------------------------------------------------------------------------
# Source 3: Sina Finance (CN A-shares, via curl_cffi)
# ---------------------------------------------------------------------------


def resolve_from_sina(names: list[str]) -> dict:
    """Resolve CN A-share names via Sina Finance suggest API.

    Uses https://suggest3.sinajs.cn to search by Chinese company name.
    Response format: var suggestdata="name,type,code,full_code,display_name,...;..."
    Type 11 = A-share stocks.

    Returns: {name: {ticker, official_name, price, ...} or None}
    """
    results = {}

    if not _CURL_CFFI_AVAILABLE:
        return results

    headers = {"Referer": "https://finance.sina.com.cn"}

    for name in names:
        try:
            r = cffi_requests.get(
                f"https://suggest3.sinajs.cn/suggest/type=11&key={name}&name=suggestdata",
                impersonate="chrome",
                headers=headers,
                timeout=10,
            )
            if r.status_code != 200:
                continue

            # Parse: var suggestdata="entry1;entry2;..."
            text = r.text
            match = re.search(r'"([^"]*)"', text)
            if not match or not match.group(1):
                continue

            entries = match.group(1).split(";")
            if not entries or not entries[0]:
                continue

            # First entry is best match
            # Format: display_name,type,code,full_code,short_name,...
            parts = entries[0].split(",")
            if len(parts) < 5:
                continue

            display_name = parts[0]
            entry_type = parts[1]
            code = parts[2]
            full_code = parts[3]  # e.g., "sh688332"
            short_name = parts[4]

            # Only process A-share stocks (type=11)
            if entry_type != "11":
                continue

            ticker = code_to_ticker(code)

            # Get current price from Sina quotes
            price = None
            try:
                r2 = cffi_requests.get(
                    f"https://hq.sinajs.cn/list={full_code}",
                    impersonate="chrome",
                    headers=headers,
                    timeout=5,
                )
                if r2.status_code == 200:
                    quote_match = re.search(r'"([^"]*)"', r2.text)
                    if quote_match and quote_match.group(1):
                        fields = quote_match.group(1).split(",")
                        if len(fields) > 3 and fields[3]:
                            price = float(fields[3])
            except Exception:
                pass

            # Compute confidence based on name match
            confidence = compute_similarity(name, short_name)
            if confidence < 0.5:
                confidence = compute_similarity(name, display_name)
            # Sina search is authoritative — if it returns a result, it's reliable
            confidence = max(confidence, 0.85)

            results[name] = {
                "ticker": ticker,
                "official_name": short_name or display_name,
                "exchange": ticker.split(".")[-1] if "." in ticker else "",
                "price": price,
                "confidence": round(confidence, 3),
                "match_type": "exact" if confidence >= 0.95 else "fuzzy",
                "source": "sina",
            }

        except Exception as e:
            sys.stderr.write(f"[sina] Error resolving '{name}': {e}\n")
            continue

        time.sleep(0.2)  # Rate limit

    return results


# ---------------------------------------------------------------------------
# Source 4: akshare (authoritative, covers all A-shares)
# ---------------------------------------------------------------------------


_akshare_cache = None  # Cache the full A-share list within a session


def _get_akshare_stock_list():
    """Fetch and cache the full A-share stock list from akshare."""
    global _akshare_cache
    if _akshare_cache is not None:
        return _akshare_cache

    if not _AKSHARE_AVAILABLE:
        return None

    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return None
        _akshare_cache = df
        return df
    except Exception as e:
        sys.stderr.write(f"[akshare] Failed to fetch stock list: {e}\n")
        return None


def resolve_from_akshare(names: list[str]) -> dict:
    """Resolve names via akshare's comprehensive A-share listing.

    Uses ak.stock_zh_a_spot_em() which returns all actively traded A-shares
    with columns: 代码, 名称, 最新价, 市盈率-动态, 市净率, 总市值, etc.
    """
    results = {}
    df = _get_akshare_stock_list()
    if df is None:
        return results

    # Build lookup structures
    # Exact name match (most reliable)
    name_to_row = {}
    for _, row in df.iterrows():
        stock_name = str(row.get("名称", ""))
        if stock_name:
            name_to_row[stock_name] = row

    for name in names:
        # 1. Exact match
        if name in name_to_row:
            row = name_to_row[name]
            code = str(row["代码"])
            ticker = code_to_ticker(code)
            results[name] = {
                "ticker": ticker,
                "official_name": str(row["名称"]),
                "exchange": ticker.split(".")[-1] if "." in ticker else "",
                "price": float(row["最新价"])
                if row.get("最新价") and str(row["最新价"]) != "-"
                else None,
                "confidence": 1.0,
                "match_type": "exact",
                "source": "akshare",
            }
            continue

        # 2. Fuzzy match: iterate all stocks and find best match
        best_match = None
        best_score = 0.0
        candidates = []

        for stock_name, row in name_to_row.items():
            score = compute_similarity(name, stock_name)
            if score >= 0.5:
                candidates.append((score, stock_name, row))
            if score > best_score:
                best_score = score
                best_match = (stock_name, row)

        # Only accept fuzzy matches with high enough confidence
        if best_match and best_score >= 0.6:
            stock_name, row = best_match
            code = str(row["代码"])
            ticker = code_to_ticker(code)
            results[name] = {
                "ticker": ticker,
                "official_name": stock_name,
                "exchange": ticker.split(".")[-1] if "." in ticker else "",
                "price": float(row["最新价"])
                if row.get("最新价") and str(row["最新价"]) != "-"
                else None,
                "confidence": round(best_score, 3),
                "match_type": "fuzzy",
                "source": "akshare",
                "other_candidates": [
                    {"name": c[1], "code": str(c[2]["代码"]), "score": round(c[0], 3)}
                    for c in sorted(candidates, key=lambda x: -x[0])[:3]
                    if c[1] != stock_name
                ],
            }

    return results


# ---------------------------------------------------------------------------
# Source 3: yfinance search (US stocks primary, CN fallback)
# ---------------------------------------------------------------------------


def _is_likely_chinese(name: str) -> bool:
    """Detect if a name contains CJK characters (likely Chinese company)."""

    return bool(re.search(r"[一-鿿]", name))


def resolve_us_from_yfinance(names: list[str]) -> dict:
    """Resolve US company names to tickers via yfinance search API.

    Uses yf.Search() for name-based lookup — the most reliable method for
    resolving English company names like "Monday.com" → MNDY.
    """
    results = {}
    if not _YFINANCE_AVAILABLE:
        return results

    for name in names:
        try:
            # Use yfinance Search API for name-based lookup
            search = yf.Search(name, max_results=5)
            quotes = search.quotes if hasattr(search, "quotes") else []

            if not quotes:
                # Fallback: try direct Ticker lookup (works if name IS the ticker)
                try:
                    t = yf.Ticker(name)
                    info = t.info
                    if info and info.get("symbol"):
                        symbol = info["symbol"]
                        results[name] = {
                            "ticker": symbol,
                            "official_name": info.get("shortName")
                            or info.get("longName"),
                            "exchange": info.get("exchange", ""),
                            "price": info.get("regularMarketPrice")
                            or info.get("currentPrice"),
                            "confidence": 0.8,
                            "match_type": "direct_lookup",
                            "source": "yfinance",
                        }
                except Exception:
                    pass
                time.sleep(0.3)
                continue

            # Score search results by name similarity
            best_match = None
            best_score = 0.0

            for quote in quotes:
                q_name = quote.get("shortname", "") or quote.get("longname", "")
                q_symbol = quote.get("symbol", "")
                q_exchange = quote.get("exchange", "")
                q_type = quote.get("quoteType", "")

                # Skip non-equity results (ETFs, mutual funds, etc. unless specifically sought)
                if q_type and q_type not in ("EQUITY", ""):
                    continue

                # Compute name similarity
                score = _compute_us_name_similarity(name, q_name, q_symbol)
                if score > best_score:
                    best_score = score
                    best_match = quote

            if best_match and best_score >= 0.5:
                symbol = best_match.get("symbol", "")
                # Convert .SS to .SH for A-share consistency
                ticker = symbol.replace(".SS", ".SH")
                match_type = "exact" if best_score >= 0.95 else "fuzzy"

                results[name] = {
                    "ticker": ticker,
                    "official_name": best_match.get("shortname")
                    or best_match.get("longname"),
                    "exchange": best_match.get("exchange", ""),
                    "price": best_match.get("regularMarketPrice"),
                    "confidence": round(best_score, 3),
                    "match_type": match_type,
                    "source": "yfinance",
                }

        except Exception as e:
            sys.stderr.write(f"[yfinance] Error searching '{name}': {e}\n")
            continue
        # Rate limit
        time.sleep(0.3)

    return results


def resolve_cn_from_yfinance(names: list[str]) -> dict:
    """Resolve CN A-share names via yfinance (fallback for akshare failures).

    yfinance A-share format: XXXXXX.SS (Shanghai), XXXXXX.SZ (Shenzhen)
    """
    results = {}
    if not _YFINANCE_AVAILABLE:
        return results

    for name in names:
        try:
            # Try yfinance Search for Chinese names
            search = yf.Search(name, max_results=5)
            quotes = search.quotes if hasattr(search, "quotes") else []

            if not quotes:
                continue

            # Look for A-share results (.SS or .SZ suffix)
            for quote in quotes:
                symbol = quote.get("symbol", "")
                if symbol.endswith(".SS") or symbol.endswith(".SZ"):
                    ticker = symbol.replace(".SS", ".SH")
                    results[name] = {
                        "ticker": ticker,
                        "official_name": quote.get("shortname")
                        or quote.get("longname"),
                        "exchange": ticker.split(".")[-1] if "." in ticker else "",
                        "price": quote.get("regularMarketPrice"),
                        "confidence": 0.7,
                        "match_type": "yfinance_search",
                        "source": "yfinance",
                    }
                    break

        except Exception:
            continue
        time.sleep(0.3)

    return results


def _compute_us_name_similarity(
    query: str, candidate_name: str, candidate_symbol: str
) -> float:
    """Compute similarity for US stock name matching.

    Handles cases like:
    - "Monday.com" matches "Monday.com Ltd." → high score
    - "CrowdStrike" matches "CrowdStrike Holdings, Inc." → high score
    - "NVDA" matches symbol "NVDA" → direct ticker match
    """
    if not query or not candidate_name:
        return 0.0

    q = query.strip().lower()
    cn = candidate_name.strip().lower()
    cs = candidate_symbol.strip().upper()

    # Direct symbol match (user passed a ticker as "name")
    if q.upper() == cs:
        return 1.0

    # Exact name match
    if q == cn:
        return 1.0

    # Query is contained in candidate (e.g., "monday.com" in "monday.com ltd.")
    if q in cn:
        return 0.95

    # Candidate is contained in query
    if cn in q:
        return 0.9

    # Remove common suffixes for comparison
    for suffix in [
        " inc.",
        " inc",
        " ltd.",
        " ltd",
        " corp.",
        " corp",
        " holdings",
        " group",
        " co.",
        " co",
        " plc",
        " se",
        " n.v.",
        " sa",
        " ag",
        ", inc.",
        ", ltd.",
        " technologies",
        " technology",
        " systems",
        " solutions",
    ]:
        cn = cn.replace(suffix, "")
        q = q.replace(suffix, "")

    cn = cn.strip().rstrip(",").strip()
    q = q.strip().rstrip(",").strip()

    if q == cn:
        return 0.95

    if q in cn or cn in q:
        return 0.85

    # Word-level overlap
    q_words = set(q.split())
    cn_words = set(cn.split())
    if q_words and cn_words:
        common = q_words & cn_words
        if common:
            overlap = len(common) / max(len(q_words), len(cn_words))
            return min(0.9, 0.5 + overlap * 0.4)

    return 0.0


# ---------------------------------------------------------------------------
# Source 4: akshare US spot (for US stocks as supplementary)
# ---------------------------------------------------------------------------


_akshare_us_cache = None


def _get_akshare_us_stock_list():
    """Fetch and cache the US stock list from akshare."""
    global _akshare_us_cache
    if _akshare_us_cache is not None:
        return _akshare_us_cache

    if not _AKSHARE_AVAILABLE:
        return None

    try:
        df = ak.stock_us_spot_em()
        if df is None or df.empty:
            return None
        _akshare_us_cache = df
        return df
    except Exception as e:
        sys.stderr.write(f"[akshare] Failed to fetch US stock list: {e}\n")
        return None


def resolve_us_from_akshare(names: list[str]) -> dict:
    """Resolve US company names via akshare's US stock listing.

    Uses ak.stock_us_spot_em() which may have columns like: 名称, 代码, 最新价
    """
    results = {}
    df = _get_akshare_us_stock_list()
    if df is None:
        return results

    # Identify name and code columns
    name_col = None
    code_col = None
    price_col = None
    for col in df.columns:
        if "名称" in col or "name" in col.lower():
            name_col = col
        elif "代码" in col or "code" in col.lower() or "symbol" in col.lower():
            code_col = col
        elif "最新价" in col or "price" in col.lower() or "close" in col.lower():
            price_col = col

    if not name_col or not code_col:
        return results

    for name in names:
        best_match = None
        best_score = 0.0

        for _, row in df.iterrows():
            stock_name = str(row.get(name_col, ""))
            stock_code = str(row.get(code_col, ""))
            score = _compute_us_name_similarity(name, stock_name, stock_code)
            if score > best_score:
                best_score = score
                best_match = row

        if best_match is not None and best_score >= 0.6:
            ticker = str(best_match[code_col])
            # Remove any market prefix (e.g., "NASDAQ-" or "NYSE-")
            if "-" in ticker:
                ticker = ticker.split("-")[-1]
            price_val = best_match.get(price_col) if price_col else None
            results[name] = {
                "ticker": ticker,
                "official_name": str(best_match[name_col]),
                "exchange": "",
                "price": float(price_val)
                if price_val and str(price_val) != "-"
                else None,
                "confidence": round(best_score, 3),
                "match_type": "exact" if best_score >= 0.95 else "fuzzy",
                "source": "akshare_us",
            }

    return results


# ---------------------------------------------------------------------------
# Main Resolution Logic (market-aware cascading sources)
# ---------------------------------------------------------------------------


def detect_market(name: str) -> str:
    """Auto-detect market from company name content.

    Returns 'CN' for Chinese names, 'US' for English/Latin names.
    """
    if _is_likely_chinese(name):
        return "CN"
    return "US"


def resolve_tickers(names: list[str], market: str | None = None) -> dict:
    """Resolve company names to tickers using market-appropriate cascading sources.

    Args:
        names: List of company names to resolve
        market: Force market ('CN', 'US', or None for auto-detect per name)

    CN resolution priority: StockDB (local) → akshare A-share → yfinance search
    US resolution priority: yfinance search → akshare US spot

    Returns full result dict with 'results' and 'errors' keys.
    """
    resolved = {}

    # Split names by market
    cn_names = []
    us_names = []
    for name in names:
        m = market or detect_market(name)
        if m == "CN":
            cn_names.append(name)
        else:
            us_names.append(name)

    # --- Resolve CN A-share names ---
    if cn_names:
        unresolved_cn = list(cn_names)

        # CN Source 1: TickFlow (fastest, authoritative)
        if _TICKFLOW_AVAILABLE:
            sys.stderr.write(
                f"[resolve] CN: Trying TickFlow for {len(unresolved_cn)} names...\n"
            )
            tickflow_results = resolve_from_tickflow(unresolved_cn, market="CN")
            for name, data in tickflow_results.items():
                resolved[name] = data
            unresolved_cn = [n for n in unresolved_cn if n not in resolved]
            if tickflow_results:
                sys.stderr.write(
                    f"[resolve] CN: TickFlow resolved {len(tickflow_results)} names\n"
                )

        # CN Source 2: StockDB (local, fastest)
        if unresolved_cn:
            sys.stderr.write(
                f"[resolve] CN: Trying StockDB for {len(unresolved_cn)} names...\n"
            )
            stockdb_results = resolve_from_stockdb(unresolved_cn)
            for name, data in stockdb_results.items():
                resolved[name] = data
            unresolved_cn = [n for n in unresolved_cn if n not in resolved]
            if stockdb_results:
                sys.stderr.write(
                    f"[resolve] CN: StockDB resolved {len(stockdb_results)} names\n"
                )

        # CN Source 3: Sina Finance (reliable, no API key needed)
        if unresolved_cn and _CURL_CFFI_AVAILABLE:
            sys.stderr.write(
                f"[resolve] CN: Trying Sina for {len(unresolved_cn)} names...\n"
            )
            sina_results = resolve_from_sina(unresolved_cn)
            for name, data in sina_results.items():
                resolved[name] = data
            unresolved_cn = [n for n in unresolved_cn if n not in resolved]
            if sina_results:
                sys.stderr.write(
                    f"[resolve] CN: Sina resolved {len(sina_results)} names\n"
                )

        # CN Source 4: akshare A-share spot
        if unresolved_cn:
            sys.stderr.write(
                f"[resolve] CN: Trying akshare for {len(unresolved_cn)} names...\n"
            )
            akshare_results = resolve_from_akshare(unresolved_cn)
            for name, data in akshare_results.items():
                resolved[name] = data
            unresolved_cn = [n for n in unresolved_cn if n not in resolved]
            if akshare_results:
                sys.stderr.write(
                    f"[resolve] CN: akshare resolved {len(akshare_results)} names\n"
                )

        # CN Source 5: yfinance (fallback)
        if unresolved_cn:
            sys.stderr.write(
                f"[resolve] CN: Trying yfinance for {len(unresolved_cn)} names...\n"
            )
            yf_results = resolve_cn_from_yfinance(unresolved_cn)
            for name, data in yf_results.items():
                resolved[name] = data
            unresolved_cn = [n for n in unresolved_cn if n not in resolved]
            if yf_results:
                sys.stderr.write(
                    f"[resolve] CN: yfinance resolved {len(yf_results)} names\n"
                )

    # --- Resolve US stock names ---
    if us_names:
        unresolved_us = list(us_names)

        # US Source 1: yfinance search (most reliable for US name→ticker)
        sys.stderr.write(
            f"[resolve] US: Trying yfinance for {len(unresolved_us)} names...\n"
        )
        yf_us_results = resolve_us_from_yfinance(unresolved_us)
        for name, data in yf_us_results.items():
            resolved[name] = data
        unresolved_us = [n for n in unresolved_us if n not in resolved]
        if yf_us_results:
            sys.stderr.write(
                f"[resolve] US: yfinance resolved {len(yf_us_results)} names\n"
            )

        # US Source 2: akshare US spot (supplementary)
        if unresolved_us:
            sys.stderr.write(
                f"[resolve] US: Trying akshare US for {len(unresolved_us)} names...\n"
            )
            ak_us_results = resolve_us_from_akshare(unresolved_us)
            for name, data in ak_us_results.items():
                resolved[name] = data
            unresolved_us = [n for n in unresolved_us if n not in resolved]
            if ak_us_results:
                sys.stderr.write(
                    f"[resolve] US: akshare resolved {len(ak_us_results)} names\n"
                )

    # Build output
    results_list = []
    errors_list = []

    for name in names:
        if name in resolved:
            entry = {"input_name": name}
            entry.update(resolved[name])
            results_list.append(entry)
        else:
            detected = market or detect_market(name)
            errors_list.append(
                {
                    "input_name": name,
                    "status": "NOT_FOUND",
                    "market": detected,
                    "reason": f"No {detected} listing found for this name. "
                    "The company may not be publicly listed, or the name may be incorrect.",
                    "candidates": [],
                }
            )

    sources_used = []
    if cn_names:
        sources_used.extend(["tickflow", "stockdb", "sina", "akshare", "yfinance"])
    if us_names:
        sources_used.extend(["tickflow", "yfinance", "akshare_us"])

    output = {
        "results": results_list,
        "errors": errors_list,
        "summary": {
            "total": len(names),
            "resolved": len(results_list),
            "not_found": len(errors_list),
            "cn_names": len(cn_names),
            "us_names": len(us_names),
            "sources_tried": list(dict.fromkeys(sources_used)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }

    return output


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Resolve company names to authoritative ticker codes (CN A-shares + US stocks)."
    )
    parser.add_argument(
        "names",
        nargs="*",
        help="Company names to resolve (e.g., '纳芯微' 'Monday.com' 'CrowdStrike')",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="JSON file with list of names (array of strings or objects with 'name' key)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "--market",
        choices=["CN", "US", "AUTO"],
        default="AUTO",
        help="Force market detection: CN (A-shares), US (NYSE/NASDAQ), AUTO (detect per name, default)",
    )
    parser.add_argument(
        "--format",
        choices=["full", "ticker", "table"],
        default="full",
        help="Output format: full (JSON), ticker (code only), table (markdown)",
    )

    args = parser.parse_args()

    # Collect names
    names = []
    if args.names:
        names.extend(args.names)
    if args.input:
        try:
            with open(args.input) as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        names.append(item)
                    elif isinstance(item, dict) and "name" in item:
                        names.append(item["name"])
            elif isinstance(data, dict) and "names" in data:
                names.extend(data["names"])
        except (json.JSONDecodeError, FileNotFoundError) as e:
            sys.stderr.write(f"Error reading input file: {e}\n")
            sys.exit(1)

    if not names:
        sys.stderr.write(
            "Error: No company names provided. Use positional args or --input.\n"
        )
        parser.print_help()
        sys.exit(1)

    # Resolve
    market = None if args.market == "AUTO" else args.market
    result = resolve_tickers(names, market=market)

    # Format output
    if args.format == "ticker":
        # Simple ticker-only output
        for entry in result["results"]:
            print(f"{entry['input_name']}\t{entry['ticker']}")
        for entry in result["errors"]:
            print(f"{entry['input_name']}\tNOT_FOUND")
    elif args.format == "table":
        # Markdown table
        print("| 输入名称 | 代码 | 全称 | 价格 | 匹配方式 | 置信度 | 来源 |")
        print("|----------|------|------|------|----------|--------|------|")
        for entry in result["results"]:
            price_val = entry.get("price")
            if price_val:
                # Use ¥ for CN tickers, $ for US
                ticker = entry.get("ticker", "")
                is_cn = any(ticker.endswith(s) for s in (".SH", ".SZ", ".BJ"))
                price = f"¥{price_val}" if is_cn else f"${price_val}"
            else:
                price = "-"
            print(
                f"| {entry['input_name']} | {entry['ticker']} | "
                f"{entry.get('official_name', '-')} | {price} | "
                f"{entry.get('match_type', '-')} | {entry.get('confidence', '-')} | "
                f"{entry.get('source', '-')} |"
            )
        for entry in result["errors"]:
            print(f"| {entry['input_name']} | ❌ NOT_FOUND | - | - | - | - | - |")
    else:
        # Full JSON output
        output_str = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_str)
            sys.stderr.write(f"[resolve] Output written to {args.output}\n")
        else:
            print(output_str)

    # Exit code: 0 if all resolved, 1 if any NOT_FOUND
    sys.exit(0 if not result["errors"] else 1)


if __name__ == "__main__":
    main()
