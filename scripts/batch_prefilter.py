#!/usr/bin/env python3
"""Batch pre-filter: deterministic vectorized elimination of unqualified stocks.

Runs BEFORE the LLM company-screener agent to narrow 5000+ → 200-500 candidates
using Polars vectorized filters. No per-ticker API calls — single bulk fetch.

Usage:
    uv run python batch_prefilter.py --market CN --top-price 200 --output ./reports/RUN_ID/stage4_prefilter.json
    uv run python batch_prefilter.py --market US --tickers AAPL MSFT NVDA --min-cap 1000
    uv run python batch_prefilter.py --market both --output prefilter.json --verbose

Performance: ~5000 A-share stocks processed in <5 seconds (network-dominated).
Polars vectorized filter chain executes in <10ms on the fetched DataFrame.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Dependency imports with clear error messages
# ---------------------------------------------------------------------------

try:
    import polars as pl
except ImportError:
    sys.stderr.write("Error: 'polars' required. Run: pip install polars\n")
    sys.exit(1)

try:
    import akshare as ak

    _AKSHARE_AVAILABLE = True
except ImportError:
    ak = None
    _AKSHARE_AVAILABLE = False

try:
    import yfinance as yf

    _YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    _YFINANCE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# akshare column mapping (Chinese → normalized English)
CN_COLUMN_MAP = {
    "代码": "ticker_raw",
    "名称": "name",
    "最新价": "price",
    "总市值": "market_cap",
    "流通市值": "float_cap",
    "成交量": "volume_avg",
    "52周最高": "high_52w",
    "52周最低": "low_52w",
    "市盈率-动态": "pe_dynamic",
    "市净率": "pb",
    "60日涨跌幅": "pct_change_60d",
    "涨跌幅": "pct_change_1d",
}

# Maximum retries for data source fetching
MAX_RETRIES = 2
RETRY_DELAY = 3  # seconds


# ---------------------------------------------------------------------------
# Data Fetchers
# ---------------------------------------------------------------------------


def fetch_cn_universe() -> pl.DataFrame | None:
    """Fetch all A-share real-time quotes via akshare (single bulk call).

    Returns normalized Polars DataFrame or None on failure.
    """
    if not _AKSHARE_AVAILABLE:
        sys.stderr.write("[prefilter] Error: akshare not installed (required for --market CN)\n")
        return None

    for attempt in range(MAX_RETRIES):
        try:
            sys.stderr.write(
                f"[prefilter] Fetching CN universe via akshare (attempt {attempt + 1})...\n"
            )
            df_pandas = ak.stock_zh_a_spot_em()
            if df_pandas is None or df_pandas.empty:
                sys.stderr.write("[prefilter] akshare returned empty DataFrame\n")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
            sys.stderr.write(f"[prefilter] CN universe: {len(df_pandas)} stocks fetched\n")
            return normalize_cn_schema(df_pandas)
        except Exception as e:
            sys.stderr.write(f"[prefilter] akshare error (attempt {attempt + 1}): {e}\n")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)

    return None


def fetch_us_universe(tickers: list[str] | None = None) -> pl.DataFrame | None:
    """Fetch US stock data via yfinance batch download.

    Args:
        tickers: Explicit list of tickers. If None, uses a broad US universe
                 (via akshare US spot if available, else requires explicit tickers).

    Returns normalized Polars DataFrame or None on failure.
    """
    if not _YFINANCE_AVAILABLE:
        sys.stderr.write("[prefilter] Error: yfinance not installed (required for --market US)\n")
        return None

    # If no tickers provided, try akshare US universe
    if not tickers:
        if _AKSHARE_AVAILABLE:
            try:
                sys.stderr.write("[prefilter] Fetching US universe via akshare...\n")
                df_pandas = ak.stock_us_spot_em()
                if df_pandas is not None and not df_pandas.empty:
                    return normalize_us_akshare_schema(df_pandas)
            except Exception as e:
                sys.stderr.write(f"[prefilter] akshare US error: {e}\n")

        sys.stderr.write(
            "[prefilter] No US tickers provided and akshare US unavailable. "
            "Use --tickers to specify stocks.\n"
        )
        return None

    # Batch download via yfinance
    sys.stderr.write(f"[prefilter] Fetching {len(tickers)} US stocks via yfinance...\n")
    try:
        # yfinance supports batch downloads
        # Chunk into batches of 200 for reliability
        all_rows = []
        batch_size = 200
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            try:
                data = yf.download(
                    batch,
                    period="1mo",
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )
                if data is not None and not data.empty:
                    rows = _extract_yfinance_batch(data, batch)
                    all_rows.extend(rows)
            except Exception as e:
                sys.stderr.write(f"[prefilter] yfinance batch error: {e}\n")
                continue

        if not all_rows:
            return None

        df = pl.DataFrame(all_rows)
        sys.stderr.write(f"[prefilter] US universe: {df.height} stocks fetched\n")
        return df

    except Exception as e:
        sys.stderr.write(f"[prefilter] yfinance error: {e}\n")
        return None


def _extract_yfinance_batch(data, tickers: list[str]) -> list[dict]:
    """Extract per-ticker summary from yfinance batch download result."""
    rows = []
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                ticker_data = data
            else:
                ticker_data = data[ticker] if ticker in data.columns.get_level_values(0) else None

            if ticker_data is None or ticker_data.empty:
                continue

            # Get latest values
            close_prices = ticker_data["Close"].dropna()
            if close_prices.empty:
                continue

            latest_price = float(close_prices.iloc[-1])
            volume_avg = float(ticker_data["Volume"].mean()) if "Volume" in ticker_data else 0

            # Compute 20D momentum
            if len(close_prices) >= 20:
                price_20d_ago = float(close_prices.iloc[-20])
                pct_change_20d = (latest_price - price_20d_ago) / price_20d_ago if price_20d_ago > 0 else None
            else:
                pct_change_20d = None

            # 52w high/low approximation from available data
            high_52w = float(close_prices.max())
            low_52w = float(close_prices.min())

            rows.append(
                {
                    "ticker": ticker,
                    "name": ticker,  # yfinance batch doesn't return names easily
                    "price": latest_price,
                    "market_cap": None,  # Not available in batch OHLCV
                    "volume_avg": volume_avg,
                    "high_52w": high_52w,
                    "low_52w": low_52w,
                    "pe_dynamic": None,
                    "pb": None,
                    "pct_change_20d": pct_change_20d,
                    "market": "US",
                }
            )
        except (KeyError, IndexError, TypeError):
            continue

    return rows


# ---------------------------------------------------------------------------
# Schema Normalization
# ---------------------------------------------------------------------------


def normalize_cn_schema(df_pandas) -> pl.DataFrame:
    """Convert akshare pandas DataFrame to typed Polars with unified schema."""
    # Select only columns we need (some may be absent in older akshare versions)
    available_cols = {}
    for cn_col, en_col in CN_COLUMN_MAP.items():
        if cn_col in df_pandas.columns:
            available_cols[cn_col] = en_col

    # Subset and rename
    df_subset = df_pandas[list(available_cols.keys())].copy()
    df_subset.columns = [available_cols[c] for c in df_subset.columns]

    # Convert to Polars
    df = pl.from_pandas(df_subset)

    # Cast numeric columns (akshare sometimes returns strings like "-")
    numeric_cols = [
        "price", "market_cap", "float_cap", "volume_avg",
        "high_52w", "low_52w", "pe_dynamic", "pb",
        "pct_change_60d", "pct_change_1d",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).cast(pl.Float64, strict=False).alias(col)
            )

    # Add market column
    df = df.with_columns(pl.lit("CN").alias("market"))

    return df


def normalize_us_akshare_schema(df_pandas) -> pl.DataFrame:
    """Convert akshare US spot data to Polars with unified schema."""
    # akshare US spot columns vary; try common patterns
    col_map = {}
    for col in df_pandas.columns:
        col_lower = col.lower()
        if "代码" in col or "symbol" in col_lower or "code" in col_lower:
            col_map[col] = "ticker"
        elif "名称" in col or "name" in col_lower:
            col_map[col] = "name"
        elif "最新价" in col or "price" in col_lower or "close" in col_lower:
            col_map[col] = "price"
        elif "总市值" in col or "market" in col_lower:
            col_map[col] = "market_cap"
        elif "成交量" in col or "volume" in col_lower:
            col_map[col] = "volume_avg"

    if "ticker" not in col_map.values():
        sys.stderr.write("[prefilter] Cannot identify ticker column in US akshare data\n")
        return None

    df_subset = df_pandas[list(col_map.keys())].copy()
    df_subset.columns = [col_map[c] for c in df_subset.columns]
    df = pl.from_pandas(df_subset)

    # Cast numeric
    for col in ["price", "market_cap", "volume_avg"]:
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False).alias(col))

    # Clean ticker (remove market prefix like "NASDAQ-" or "NYSE-")
    if "ticker" in df.columns:
        df = df.with_columns(
            pl.when(pl.col("ticker").str.contains("-"))
            .then(pl.col("ticker").str.split("-").list.last())
            .otherwise(pl.col("ticker"))
            .alias("ticker")
        )

    # Add missing columns as null
    for col in ["high_52w", "low_52w", "pe_dynamic", "pb", "pct_change_20d"]:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Float64).alias(col))

    df = df.with_columns(pl.lit("US").alias("market"))
    return df


# ---------------------------------------------------------------------------
# Derived Columns
# ---------------------------------------------------------------------------


def compute_derived_columns(df: pl.DataFrame, market: str) -> pl.DataFrame:
    """Add computed columns needed by filters: drawdown, 20D momentum, ticker suffix."""

    # Compute drawdown from 52-week high
    if "high_52w" in df.columns:
        df = df.with_columns(
            pl.when(pl.col("high_52w").is_not_null() & (pl.col("high_52w") > 0))
            .then((pl.col("high_52w") - pl.col("price")) / pl.col("high_52w"))
            .otherwise(None)
            .alias("drawdown_from_high")
        )
    else:
        df = df.with_columns(pl.lit(None).cast(pl.Float64).alias("drawdown_from_high"))

    # For CN: approximate 20D momentum from 60D return
    if market == "CN" and "pct_change_60d" in df.columns and "pct_change_20d" not in df.columns:
        df = df.with_columns(
            pl.when(pl.col("pct_change_60d").is_not_null())
            .then(pl.col("pct_change_60d") / 100.0 / 3.0)  # Convert % to fraction, approx 20D
            .otherwise(None)
            .alias("pct_change_20d")
        )

    # For CN: compute ticker with exchange suffix
    if market == "CN" and "ticker_raw" in df.columns and "ticker" not in df.columns:
        df = df.with_columns(
            pl.when(pl.col("ticker_raw").str.starts_with("6"))
            .then(pl.col("ticker_raw") + pl.lit(".SH"))
            .when(
                pl.col("ticker_raw").str.starts_with("0")
                | pl.col("ticker_raw").str.starts_with("3")
            )
            .then(pl.col("ticker_raw") + pl.lit(".SZ"))
            .when(
                pl.col("ticker_raw").str.starts_with("4")
                | pl.col("ticker_raw").str.starts_with("8")
            )
            .then(pl.col("ticker_raw") + pl.lit(".BJ"))
            .otherwise(pl.col("ticker_raw"))
            .alias("ticker")
        )

    return df


# ---------------------------------------------------------------------------
# Filter Chain
# ---------------------------------------------------------------------------


def make_filter_chain(cfg: dict) -> list[tuple[str, pl.Expr]]:
    """Return ordered list of (name, expression) filter tuples.

    Ordered by: cheapest computation first, highest rejection rate first.
    """
    filters = []

    # F1: Valid price (not null, positive, not suspended)
    filters.append((
        "valid_price",
        pl.col("price").is_not_null() & (pl.col("price") > 0),
    ))

    # F2: Exclude ST stocks (A-share only)
    if cfg.get("exclude_st", True) and cfg.get("market") in ("CN", "both"):
        filters.append((
            "exclude_st",
            ~pl.col("name").str.contains("ST"),
        ))

    # F3: Price ceiling
    if cfg["top_price"] > 0:
        filters.append((
            "price_ceiling",
            pl.col("price") < cfg["top_price"],
        ))

    # F4: Market cap floor (min_cap is in millions, market_cap is in raw currency)
    min_cap_raw = cfg["min_cap"] * 1e6
    filters.append((
        "market_cap_floor",
        pl.col("market_cap").is_null() | (pl.col("market_cap") >= min_cap_raw),
        # Note: null market_cap passes (benefit of doubt — will be verified later)
    ))

    # F5: Volume floor
    filters.append((
        "volume_floor",
        pl.col("volume_avg").is_null() | (pl.col("volume_avg") >= cfg["min_volume"]),
    ))

    # F6: Not a falling knife (drawdown from 52w high <= threshold)
    filters.append((
        "falling_knife",
        pl.col("drawdown_from_high").is_null()
        | (pl.col("drawdown_from_high") <= cfg["max_drawdown"]),
    ))

    # F7: Minimum momentum (20-day return >= threshold)
    filters.append((
        "momentum_floor",
        pl.col("pct_change_20d").is_null()
        | (pl.col("pct_change_20d") >= cfg["min_momentum"]),
    ))

    return filters


def apply_filters(
    df: pl.DataFrame, filters: list[tuple[str, pl.Expr]]
) -> tuple[pl.DataFrame, dict]:
    """Apply filters sequentially, tracking per-filter rejection counts.

    Sequential application (not functools.reduce) gives per-filter stats.
    """
    stats = {}
    remaining = df

    for name, expr, *_ in filters:
        before = remaining.height
        remaining = remaining.filter(expr)
        after = remaining.height
        stats[name] = {"rejected": before - after, "remaining": after}

    return remaining, stats


# ---------------------------------------------------------------------------
# Rejection Sampling
# ---------------------------------------------------------------------------


def sample_rejections(
    original: pl.DataFrame,
    survivors: pl.DataFrame,
    filters: list[tuple[str, pl.Expr]],
    cfg: dict,
    max_samples: int = 50,
) -> list[dict]:
    """Capture a sample of rejected tickers with their rejection reasons."""
    if "ticker" not in original.columns:
        return []

    survivor_tickers = set(survivors["ticker"].to_list())
    rejected_df = original.filter(~pl.col("ticker").is_in(list(survivor_tickers)))

    if rejected_df.height == 0:
        return []

    # Take a sample
    sample_df = rejected_df.head(max_samples)
    samples = []

    for row in sample_df.iter_rows(named=True):
        # Determine which filter rejected this row
        rejection_filter = "unknown"
        for name, expr, *_ in filters:
            try:
                single_row_df = pl.DataFrame([row])
                if single_row_df.filter(expr).height == 0:
                    rejection_filter = name
                    break
            except Exception:
                continue

        detail = ""
        if rejection_filter == "price_ceiling":
            detail = f"price={row.get('price')} >= {cfg['top_price']}"
        elif rejection_filter == "market_cap_floor":
            cap_m = row.get("market_cap", 0)
            if cap_m:
                cap_m = cap_m / 1e6
            detail = f"market_cap={cap_m:.0f}M < {cfg['min_cap']}M"
        elif rejection_filter == "falling_knife":
            detail = f"drawdown={row.get('drawdown_from_high', '?'):.2%}"
        elif rejection_filter == "momentum_floor":
            detail = f"momentum_20d={row.get('pct_change_20d', '?')}"

        samples.append({
            "ticker": row.get("ticker", "?"),
            "name": row.get("name", "?"),
            "rejection_filter": rejection_filter,
            "rejection_detail": detail,
            "price": row.get("price"),
        })

    return samples


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def build_output(
    survivors: pl.DataFrame,
    stats: dict,
    cfg: dict,
    total_universe: int,
    elapsed: float,
    rejects_sample: list[dict],
) -> dict:
    """Build the output JSON payload."""
    # Convert survivors to list of dicts
    output_cols = [
        "ticker", "name", "price", "market_cap", "volume_avg",
        "pe_dynamic", "pb", "pct_change_20d", "drawdown_from_high",
        "high_52w", "low_52w", "market",
    ]
    available_cols = [c for c in output_cols if c in survivors.columns]
    survivors_list = survivors.select(available_cols).to_dicts()

    # Clean None/NaN in output
    for row in survivors_list:
        for k, v in row.items():
            if v is not None and isinstance(v, float) and (v != v):  # NaN check
                row[k] = None

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": cfg["market"],
        "parameters": {
            "top_price": cfg["top_price"],
            "min_cap_M": cfg["min_cap"],
            "min_volume": cfg["min_volume"],
            "max_drawdown": cfg["max_drawdown"],
            "min_momentum": cfg["min_momentum"],
            "exclude_st": cfg.get("exclude_st", True),
        },
        "summary": {
            "total_universe": total_universe,
            "survivors": survivors.height,
            "rejected": total_universe - survivors.height,
            "filter_stats": stats,
            "elapsed_seconds": round(elapsed, 2),
        },
        "survivors": survivors_list,
        "rejects_sample": rejects_sample,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Batch pre-filter: narrow stock universe using vectorized Polars filters. "
        "Runs BEFORE LLM company-screener to eliminate 90%+ of obviously unqualified stocks."
    )
    parser.add_argument(
        "--market",
        choices=["US", "CN", "both"],
        default="US",
        help="Which market universe to bulk-fetch (default: US)",
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        help="Explicit ticker list (bypasses bulk market fetch). Required for US without akshare.",
    )
    parser.add_argument(
        "--top-price",
        type=float,
        default=200.0,
        help="Max stock price in local currency (default: 200). Set 0 to disable.",
    )
    parser.add_argument(
        "--min-cap",
        type=float,
        default=500.0,
        help="Minimum market cap in millions (default: 500M)",
    )
    parser.add_argument(
        "--min-volume",
        type=int,
        default=500000,
        help="Minimum average daily volume in shares (default: 500000)",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.50,
        help="Max drawdown from 52w high as fraction (default: 0.50 = reject if >50%% down)",
    )
    parser.add_argument(
        "--min-momentum",
        type=float,
        default=-0.20,
        help="Min 20D price return fraction (default: -0.20 = reject if worse than -20%%)",
    )
    parser.add_argument(
        "--exclude-st",
        action="store_true",
        default=True,
        help="Exclude ST/*ST stocks (A-share only, default: True)",
    )
    parser.add_argument(
        "--no-exclude-st",
        action="store_false",
        dest="exclude_st",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Log per-filter rejection counts to stderr",
    )

    args = parser.parse_args()

    start_time = time.time()

    # Build config
    cfg = {
        "market": args.market,
        "top_price": args.top_price,
        "min_cap": args.min_cap,
        "min_volume": args.min_volume,
        "max_drawdown": args.max_drawdown,
        "min_momentum": args.min_momentum,
        "exclude_st": args.exclude_st,
    }

    # --------------- Fetch data ---------------
    frames = []

    if args.market in ("CN", "both"):
        cn_df = fetch_cn_universe()
        if cn_df is not None:
            cn_df = compute_derived_columns(cn_df, "CN")
            frames.append(cn_df)
        elif args.market == "CN":
            # CN-only mode and fetch failed
            error_out = {"error": "data_source_cn_failure", "detail": "akshare fetch failed after retries"}
            _write_output(error_out, args.output)
            sys.exit(1)

    if args.market in ("US", "both"):
        us_df = fetch_us_universe(args.tickers)
        if us_df is not None:
            us_df = compute_derived_columns(us_df, "US")
            frames.append(us_df)
        elif args.market == "US":
            # US-only mode and fetch failed
            error_out = {"error": "data_source_us_failure", "detail": "yfinance/akshare US fetch failed"}
            _write_output(error_out, args.output)
            sys.exit(1)

    if not frames:
        error_out = {"error": "empty_universe", "detail": "No data fetched from any source"}
        _write_output(error_out, args.output)
        sys.exit(1)

    # Combine frames (for "both" mode)
    if len(frames) == 1:
        df = frames[0]
    else:
        # Align columns before concatenation
        all_cols = set()
        for f in frames:
            all_cols.update(f.columns)
        aligned = []
        for f in frames:
            for col in all_cols:
                if col not in f.columns:
                    f = f.with_columns(pl.lit(None).alias(col))
            aligned.append(f.select(sorted(all_cols)))
        df = pl.concat(aligned)

    total_universe = df.height
    sys.stderr.write(f"[prefilter] Total universe: {total_universe} stocks\n")

    # --------------- Apply filters ---------------
    filters = make_filter_chain(cfg)
    survivors, stats = apply_filters(df, filters)

    if args.verbose:
        sys.stderr.write("[prefilter] Filter results:\n")
        for name, stat in stats.items():
            sys.stderr.write(f"  {name}: -{stat['rejected']} → {stat['remaining']} remaining\n")

    sys.stderr.write(
        f"[prefilter] Survivors: {survivors.height}/{total_universe} "
        f"({survivors.height / total_universe * 100:.1f}%)\n"
    )

    # --------------- Build output ---------------
    elapsed = time.time() - start_time

    # Sample rejections for diagnostics
    rejects_sample = sample_rejections(df, survivors, filters, cfg)

    output = build_output(survivors, stats, cfg, total_universe, elapsed, rejects_sample)

    _write_output(output, args.output)

    # Exit 0 even if 0 survivors (not an error — filters may be too strict)
    sys.exit(0)


def _write_output(data: dict, output_path: str | None):
    """Write JSON output to file or stdout."""
    output_str = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_str)
        sys.stderr.write(f"[prefilter] Output written to {output_path}\n")
    else:
        print(output_str)


if __name__ == "__main__":
    main()
