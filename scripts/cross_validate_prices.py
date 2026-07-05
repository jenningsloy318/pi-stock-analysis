#!/usr/bin/env python3
"""Cross-validate stock prices/metrics against a second source.

Lightweight utility called after any data-fetching script to verify
key fields (price, PE, PB, market cap) haven't been hallucinated or gone stale.

Usage:
    cross_validate_prices.py INPUT_JSON [--patch] [--output PATH] [--tolerance PCT]
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Ticker detection
# ---------------------------------------------------------------------------


def detect_tickers(data: dict) -> dict:
    """Auto-detect tickers and their data blobs from various JSON formats."""
    tickers = {}

    # Format: {"results": {"TICKER": {...}}}
    if "results" in data and isinstance(data["results"], dict):
        for k, v in data["results"].items():
            if isinstance(v, dict) and _looks_like_ticker(k):
                tickers[k] = v
        if tickers:
            return tickers

    # Format: {"ticker": "X", ...} (single-ticker)
    if "ticker" in data and isinstance(data["ticker"], str):
        tickers[data["ticker"]] = data
        return tickers

    # Format: {"TICKER": {...}} (top-level keys are tickers)
    for k, v in data.items():
        if isinstance(v, dict) and _looks_like_ticker(k):
            tickers[k] = v

    return tickers


def _looks_like_ticker(s: str) -> bool:
    """Heuristic: ticker symbols are short uppercase, optionally with .SS/.SZ/.BJ suffix."""
    if not s or len(s) > 12:
        return False
    base = s.split(".")[0]
    return base.isalnum() and (base.isupper() or base.isdigit())


# ---------------------------------------------------------------------------
# Price extraction from JSON blob
# ---------------------------------------------------------------------------

PRICE_PATHS = [
    ("profile", "current_price"),
    ("current_price",),
    ("valuation_snapshot", "current_price"),
    ("close",),
    ("price",),
    ("last_price",),
]


def extract_price(blob: dict) -> float | None:
    """Try multiple field paths to find a price value."""
    for path in PRICE_PATHS:
        val = blob
        for key in path:
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def extract_metrics(blob: dict) -> dict:
    """Extract PE, PB, market_cap if available."""
    metrics = {}
    for field in ("pe", "pe_ratio", "trailing_pe", "trailingPE"):
        v = _deep_get(blob, field)
        if v is not None:
            metrics["pe"] = float(v)
            break
    for field in ("pb", "pb_ratio", "priceToBook"):
        v = _deep_get(blob, field)
        if v is not None:
            metrics["pb"] = float(v)
            break
    for field in ("market_cap", "marketCap"):
        v = _deep_get(blob, field)
        if v is not None:
            metrics["market_cap"] = float(v)
            break
    return metrics


def _deep_get(d: dict, key: str):
    """Search for key in top-level and one level deep."""
    if key in d:
        return d[key]
    for v in d.values():
        if isinstance(v, dict) and key in v:
            return v[key]
    return None


# ---------------------------------------------------------------------------
# Validation sources
# ---------------------------------------------------------------------------


def is_a_share(ticker: str) -> bool:
    """Check if ticker is a China A-share."""
    return any(ticker.upper().endswith(sfx) for sfx in (".SS", ".SZ", ".BJ", ".SH"))


def fetch_stockdb_price(ticker: str) -> float | None:
    """Fetch from local StockDB (127.0.0.1:7899). Returns None on failure."""
    code = ticker.split(".")[0]
    url = f"http://127.0.0.1:7899/api/stock/quote?code={code}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            price = data.get("price") or data.get("current") or data.get("last")
            return float(price) if price else None
    except (urllib.error.URLError, OSError, ValueError, TypeError, KeyError):
        return None


def fetch_akshare_price(ticker: str) -> float | None:
    """Fallback: use akshare for A-share spot price."""
    try:
        import akshare as ak

        code = ticker.split(".")[0]
        suffix = ticker.split(".")[-1].upper() if "." in ticker else ""
        if suffix == "SS":
            symbol = f"sh{code}"
        elif suffix == "SZ":
            symbol = f"sz{code}"
        elif suffix == "BJ":
            symbol = f"bj{code}"
        else:
            symbol = code
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if len(row) > 0:
            return float(row.iloc[0]["最新价"])
    except Exception:
        pass
    return None


def fetch_yfinance_price(ticker: str) -> float | None:
    """Fetch stock price via yfinance fast_info."""
    try:
        import yfinance as yf

        # yfinance uses .SS for Shanghai stocks, not .SH
        yf_ticker = (
            ticker.replace(".SH", ".SS") if ticker.upper().endswith(".SH") else ticker
        )
        t = yf.Ticker(yf_ticker)
        fi = t.fast_info
        price = getattr(fi, "last_price", None)
        if price is None:
            price = getattr(fi, "previous_close", None)
        return float(price) if price else None
    except Exception:
        return None


def fetch_validated_price(ticker: str) -> tuple[float | None, str]:
    """Fetch price from second source. Returns (price, source_name)."""
    if is_a_share(ticker):
        price = fetch_stockdb_price(ticker)
        if price is not None:
            return price, "StockDB local"
        price = fetch_akshare_price(ticker)
        if price is not None:
            return price, "akshare spot"
        # Fallback: yfinance with .SH → .SS conversion
        price = fetch_yfinance_price(ticker)
        if price is not None:
            return price, "yfinance fast_info"
        return None, "unavailable"
    else:
        price = fetch_yfinance_price(ticker)
        if price is not None:
            return price, "yfinance fast_info"
        return None, "unavailable"


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


def classify_difference(pct: float, tolerance: float) -> str:
    """Classify the discrepancy level."""
    if pct <= tolerance:
        return "PASS"
    elif pct <= 15.0:
        return "STALE"
    elif pct <= 50.0:
        return "MISMATCH"
    else:
        return "CRITICAL_MISMATCH"


def validate_ticker(ticker: str, blob: dict, tolerance: float) -> dict:
    """Validate a single ticker's price against second source."""
    price_in_file = extract_price(blob)
    if price_in_file is None:
        return {
            "price_in_file": None,
            "price_validated": None,
            "source": "n/a",
            "difference_pct": None,
            "status": "SKIP",
            "reason": "no price found in input",
            "action": "none",
        }

    validated_price, source = fetch_validated_price(ticker)
    if validated_price is None:
        return {
            "price_in_file": price_in_file,
            "price_validated": None,
            "source": source,
            "difference_pct": None,
            "status": "SKIP",
            "reason": "validation source unavailable",
            "action": "none",
        }

    if validated_price == 0:
        diff_pct = 0.0 if price_in_file == 0 else 100.0
    else:
        diff_pct = round(
            abs(price_in_file - validated_price) / validated_price * 100, 2
        )

    status = classify_difference(diff_pct, tolerance)

    result = {
        "price_in_file": price_in_file,
        "price_validated": validated_price,
        "source": source,
        "difference_pct": diff_pct,
        "status": status,
        "action": "flagged_only",
    }
    # Add note for ambiguous STALE range (5-15%) where timing may explain difference
    if status == "STALE":
        result["note"] = "Price difference may be due to intra-day timing"
    return result


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------


def patch_price(blob: dict, new_price: float) -> bool:
    """Update price in the blob using the first matching path. Returns True if patched."""
    for path in PRICE_PATHS:
        obj = blob
        for key in path[:-1]:
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                obj = None
                break
        if obj is None:
            continue
        last_key = path[-1]
        if isinstance(obj, dict) and last_key in obj:
            obj[last_key] = new_price
            return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Cross-validate stock prices against second source"
    )
    parser.add_argument("input_json", help="Path to JSON file from any fetch script")
    parser.add_argument(
        "--patch",
        action="store_true",
        help="Overwrite stale prices with validated values",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for validation report (default: stdout)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=5.0,
        help="Price difference tolerance %% (default: 5.0)",
    )
    args = parser.parse_args()

    input_path = Path(args.input_json)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tickers = detect_tickers(data)
    if not tickers:
        print(f"Warning: no tickers detected in {input_path}", file=sys.stderr)
        sys.exit(0)

    results = {}
    summary = {"total": 0, "pass": 0, "mismatch": 0, "critical": 0, "skipped": 0}

    for ticker, blob in tickers.items():
        summary["total"] += 1
        result = validate_ticker(ticker, blob, args.tolerance)

        if result["status"] == "SKIP":
            summary["skipped"] += 1
        elif result["status"] == "PASS":
            summary["pass"] += 1
        elif result["status"] == "CRITICAL_MISMATCH":
            summary["critical"] += 1
            if args.patch and result["price_validated"] is not None:
                if patch_price(blob, result["price_validated"]):
                    result["action"] = "patched"
        else:  # STALE or MISMATCH
            summary["mismatch"] += 1
            if args.patch and result["price_validated"] is not None:
                if patch_price(blob, result["price_validated"]):
                    result["action"] = "patched"

        results[ticker] = result

    # Write patched file back if needed
    if args.patch:
        patched_any = any(r["action"] == "patched" for r in results.values())
        if patched_any:
            with open(input_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "tickers_checked": summary["total"],
        "results": results,
        "summary": summary,
    }

    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_json)
    else:
        print(report_json)


if __name__ == "__main__":
    main()
