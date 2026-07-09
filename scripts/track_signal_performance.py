#!/usr/bin/env python3
"""Track signal performance for daily review/复盘.

Implements a daily review system that tracks the performance of every
recommended/signaled stock over time. Inspired by A-share report's
"昨日复盘・选股表现" section.

Usage:
    track_signal_performance.py record AAPL MSFT --signal-type breakout_confirmed
    track_signal_performance.py record 603738.SS --signal-type strong_buy --entry-price 55.89
    track_signal_performance.py review --days-back 30 --status all
    track_signal_performance.py stats --days-back 60

Modes:
  record  — Record today's signals (tickers + entry prices + signal type)
  review  — Check performance of previously recorded signals
  stats   — Aggregate closed signals into performance statistics

Output: JSON to stdout or --output file.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write("Error: 'yfinance' package required. Run: pip install yfinance\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SIGNAL_TYPES = [
    "breakout_confirmed",
    "pullback_alert",
    "coiling",
    "platform_breakout",
    "cup_handle",
    "wedge",
    "accelerating",
    "steady",
    "strong_buy",
    "buy",
]

DEFAULT_DB_PATH = "./reports/signal_tracking.db"

# Auto-close thresholds
MAX_HOLD_DAYS = 20
STOP_LOSS_PCT = -10.0
TARGET_GAIN_PCT = 20.0


# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database with signal tracking schema."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            entry_price REAL NOT NULL,
            current_price REAL,
            max_price_since REAL,
            min_price_since REAL,
            return_pct REAL,
            max_return_pct REAL,
            max_drawdown_pct REAL,
            days_held INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            result TEXT,
            closed_date TEXT,
            close_reason TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
        CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
        CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Price Fetching
# ---------------------------------------------------------------------------


def fetch_current_price(ticker: str) -> float | None:
    """Fetch current/latest close price via yfinance."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        sys.stderr.write(f"Warning: Could not fetch price for {ticker}: {e}\n")
        return None


def fetch_price_history(ticker: str, start_date: str) -> dict | None:
    """Fetch price history since start_date. Returns dict with highs, lows, closes.

    Args:
        ticker: Stock ticker symbol
        start_date: Start date in YYYY-MM-DD format

    Returns:
        Dict with keys: closes, highs, lows, trading_days; or None on failure
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(start=start_date)
        if hist.empty:
            return None
        return {
            "closes": hist["Close"].tolist(),
            "highs": hist["High"].tolist(),
            "lows": hist["Low"].tolist(),
            "trading_days": len(hist),
        }
    except Exception as e:
        sys.stderr.write(f"Warning: Could not fetch history for {ticker}: {e}\n")
        return None


def fetch_prices_batch(tickers: list[str]) -> dict[str, float | None]:
    """Fetch current prices for multiple tickers."""
    results = {}
    for ticker in tickers:
        results[ticker] = fetch_current_price(ticker)
        time.sleep(0.2)  # Rate limiting
    return results


# ---------------------------------------------------------------------------
# Record Subcommand
# ---------------------------------------------------------------------------


def cmd_record(args, conn: sqlite3.Connection) -> dict:
    """Record new signal entries."""
    now_utc = datetime.now(timezone.utc).isoformat()
    signal_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tickers = [t.strip().upper() for t in args.tickers]

    # Validate signal type
    if args.signal_type not in VALID_SIGNAL_TYPES:
        return {
            "error": f"Invalid signal type: {args.signal_type}. "
            f"Valid types: {', '.join(VALID_SIGNAL_TYPES)}"
        }

    # Handle entry prices
    if args.entry_price is not None:
        if len(tickers) > 1:
            return {
                "error": "Cannot use --entry-price with multiple tickers. "
                "Omit --entry-price to auto-fetch, or record one ticker at a time."
            }
        prices = {tickers[0]: args.entry_price}
    else:
        # Fetch current prices for all tickers
        sys.stderr.write(f"Fetching current prices for {len(tickers)} ticker(s)...\n")
        prices = fetch_prices_batch(tickers)

    recorded = []
    errors = []

    for ticker in tickers:
        price = prices.get(ticker)
        if price is None:
            errors.append(f"Could not fetch price for {ticker}, skipping")
            continue

        conn.execute(
            """INSERT INTO signals
               (ticker, signal_date, signal_type, entry_price, current_price,
                max_price_since, min_price_since, status, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (
                ticker,
                signal_date,
                args.signal_type,
                price,
                price,
                price,
                price,
                args.run_id,
                now_utc,
            ),
        )
        recorded.append(
            {
                "ticker": ticker,
                "signal_date": signal_date,
                "signal_type": args.signal_type,
                "entry_price": round(price, 4),
                "run_id": args.run_id,
            }
        )

    conn.commit()

    result = {
        "timestamp": now_utc,
        "mode": "record",
        "recorded": len(recorded),
        "errors": errors if errors else None,
        "signals": recorded,
    }
    return result


# ---------------------------------------------------------------------------
# Review Subcommand
# ---------------------------------------------------------------------------


def compute_signal_metrics(signal: dict, history: dict | None) -> dict:
    """Compute performance metrics for a single signal given price history."""
    entry_price = signal["entry_price"]
    result = {
        "ticker": signal["ticker"],
        "signal_type": signal["signal_type"],
        "signal_date": signal["signal_date"],
        "entry_price": round(entry_price, 4),
        "run_id": signal["run_id"],
    }

    if history is None or not history["closes"]:
        result.update(
            {
                "current_price": None,
                "return_pct": None,
                "max_return_pct": None,
                "max_drawdown_pct": None,
                "days_held": signal["days_held"],
                "status": signal["status"],
                "result": None,
                "error": "No price data available",
            }
        )
        return result

    current_price = history["closes"][-1]
    max_price = max(history["highs"])
    min_price = min(history["lows"])
    trading_days = history["trading_days"]

    return_pct = (current_price - entry_price) / entry_price * 100
    max_return_pct = (max_price - entry_price) / entry_price * 100
    max_drawdown_pct = (min_price - entry_price) / entry_price * 100

    # Determine status and close reason
    status = "open"
    close_reason = None
    if trading_days >= MAX_HOLD_DAYS:
        status = "closed"
        close_reason = "max_hold_days"
    elif max_drawdown_pct <= STOP_LOSS_PCT:
        status = "closed"
        close_reason = "stop_loss"
    elif max_return_pct >= TARGET_GAIN_PCT:
        status = "closed"
        close_reason = "target_hit"

    signal_result = "WIN" if return_pct > 0 else "LOSS"

    result.update(
        {
            "current_price": round(current_price, 4),
            "return_pct": round(return_pct, 2),
            "max_return_pct": round(max_return_pct, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "days_held": trading_days,
            "status": status,
            "result": signal_result,
            "close_reason": close_reason,
        }
    )
    return result


def update_signal_in_db(conn: sqlite3.Connection, signal_id: int, metrics: dict):
    """Update a signal record in the database with latest metrics."""
    now_utc = datetime.now(timezone.utc).isoformat()
    closed_date = None
    if metrics.get("status") == "closed":
        closed_date = now_utc

    conn.execute(
        """UPDATE signals SET
            current_price = ?,
            max_price_since = CASE
                WHEN ? > COALESCE(max_price_since, 0) THEN ?
                ELSE max_price_since END,
            min_price_since = CASE
                WHEN ? < COALESCE(min_price_since, 999999) THEN ?
                ELSE min_price_since END,
            return_pct = ?,
            max_return_pct = ?,
            max_drawdown_pct = ?,
            days_held = ?,
            status = ?,
            result = ?,
            closed_date = COALESCE(closed_date, ?),
            close_reason = COALESCE(close_reason, ?),
            updated_at = ?
           WHERE id = ?""",
        (
            metrics.get("current_price"),
            metrics.get("current_price"),
            metrics.get("current_price"),
            metrics.get("current_price"),
            metrics.get("current_price"),
            metrics.get("return_pct"),
            metrics.get("max_return_pct"),
            metrics.get("max_drawdown_pct"),
            metrics.get("days_held"),
            metrics.get("status"),
            metrics.get("result"),
            closed_date,
            metrics.get("close_reason"),
            now_utc,
            signal_id,
        ),
    )


def cmd_review(args, conn: sqlite3.Connection) -> dict:
    """Review performance of previously recorded signals."""
    now_utc = datetime.now(timezone.utc).isoformat()
    cutoff_date = (
        datetime.now(timezone.utc) - timedelta(days=args.days_back)
    ).strftime("%Y-%m-%d")

    # Build query
    query = "SELECT * FROM signals WHERE signal_date >= ?"
    params: list = [cutoff_date]

    if args.status != "all":
        query += " AND status = ?"
        params.append(args.status)

    query += " ORDER BY signal_date DESC, ticker ASC"
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()

    if not rows:
        return {
            "timestamp": now_utc,
            "mode": "review",
            "signals_total": 0,
            "signals_open": 0,
            "signals_closed": 0,
            "summary": None,
            "signals": [],
        }

    # Process each signal
    all_metrics = []
    sys.stderr.write(f"Reviewing {len(rows)} signal(s)...\n")

    for row in rows:
        signal = dict(row)
        signal_id = signal["id"]

        # Only refetch prices for open signals
        if signal["status"] == "open":
            history = fetch_price_history(signal["ticker"], signal["signal_date"])
            metrics = compute_signal_metrics(signal, history)
            update_signal_in_db(conn, signal_id, metrics)
            time.sleep(0.2)  # Rate limiting
        else:
            # For closed signals, use stored values
            metrics = {
                "ticker": signal["ticker"],
                "signal_type": signal["signal_type"],
                "signal_date": signal["signal_date"],
                "entry_price": round(signal["entry_price"], 4),
                "current_price": round(signal["current_price"], 4)
                if signal["current_price"]
                else None,
                "return_pct": round(signal["return_pct"], 2)
                if signal["return_pct"] is not None
                else None,
                "max_return_pct": round(signal["max_return_pct"], 2)
                if signal["max_return_pct"] is not None
                else None,
                "max_drawdown_pct": round(signal["max_drawdown_pct"], 2)
                if signal["max_drawdown_pct"] is not None
                else None,
                "days_held": signal["days_held"],
                "status": signal["status"],
                "result": signal["result"],
                "close_reason": signal["close_reason"],
                "run_id": signal["run_id"],
            }

        all_metrics.append(metrics)

    conn.commit()

    # Compute summary
    signals_open = sum(1 for m in all_metrics if m.get("status") == "open")
    signals_closed = sum(1 for m in all_metrics if m.get("status") == "closed")
    valid_returns = [
        m["return_pct"] for m in all_metrics if m.get("return_pct") is not None
    ]
    wins = [r for r in valid_returns if r > 0]
    losses = [r for r in valid_returns if r <= 0]

    summary = None
    if valid_returns:
        win_count = len(wins)
        total_count = len(valid_returns)
        summary = {
            "win_rate": f"{win_count / total_count * 100:.1f}% ({win_count}/{total_count})",
            "avg_return": round(sum(valid_returns) / len(valid_returns), 2),
            "max_gain": round(max(valid_returns), 2) if valid_returns else 0,
            "max_loss": round(min(valid_returns), 2) if valid_returns else 0,
        }

    result = {
        "timestamp": now_utc,
        "mode": "review",
        "signals_total": len(all_metrics),
        "signals_open": signals_open,
        "signals_closed": signals_closed,
        "summary": summary,
        "signals": all_metrics,
    }
    return result


# ---------------------------------------------------------------------------
# Stats Subcommand
# ---------------------------------------------------------------------------


def cmd_stats(args, conn: sqlite3.Connection) -> dict:
    """Compute aggregate statistics from closed signals."""
    now_utc = datetime.now(timezone.utc).isoformat()
    cutoff_date = (
        datetime.now(timezone.utc) - timedelta(days=args.days_back)
    ).strftime("%Y-%m-%d")

    # Fetch all signals in period
    cursor = conn.execute(
        "SELECT * FROM signals WHERE signal_date >= ? ORDER BY signal_date DESC",
        (cutoff_date,),
    )
    all_rows = [dict(row) for row in cursor.fetchall()]

    closed_rows = [r for r in all_rows if r["status"] == "closed"]
    open_rows = [r for r in all_rows if r["status"] == "open"]

    if not closed_rows:
        return {
            "timestamp": now_utc,
            "mode": "stats",
            "period_days": args.days_back,
            "total_signals": len(all_rows),
            "closed_signals": 0,
            "open_signals": len(open_rows),
            "overall": None,
            "by_signal_type": [],
            "by_period": {},
        }

    # Overall stats from closed signals
    returns = [r["return_pct"] for r in closed_rows if r["return_pct"] is not None]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    win_rate_pct = len(wins) / len(returns) * 100 if returns else 0
    avg_return_pct = sum(returns) / len(returns) if returns else 0
    avg_win_pct = sum(wins) / len(wins) if wins else 0
    avg_loss_pct = sum(losses) / len(losses) if losses else 0
    max_gain_pct = max(returns) if returns else 0
    max_loss_pct = min(returns) if returns else 0

    sum_wins = sum(wins) if wins else 0
    sum_losses = abs(sum(losses)) if losses else 0
    profit_factor = sum_wins / sum_losses if sum_losses > 0 else float("inf")

    # Sharpe approximation (annualized, assuming daily returns)
    import statistics

    sharpe_approx = 0.0
    if len(returns) > 1:
        std_dev = statistics.stdev(returns)
        if std_dev > 0:
            sharpe_approx = (avg_return_pct / std_dev) * (252**0.5) / 100

    overall = {
        "win_rate_pct": round(win_rate_pct, 1),
        "avg_return_pct": round(avg_return_pct, 2),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "max_gain_pct": round(max_gain_pct, 2),
        "max_loss_pct": round(max_loss_pct, 2),
        "profit_factor": round(profit_factor, 2)
        if profit_factor != float("inf")
        else "inf",
        "sharpe_approx": round(sharpe_approx, 2),
    }

    # By signal type
    by_type: dict[str, list[float]] = {}
    for row in closed_rows:
        st = row["signal_type"]
        if row["return_pct"] is not None:
            by_type.setdefault(st, []).append(row["return_pct"])

    by_signal_type = []
    for st, rets in sorted(by_type.items(), key=lambda x: -len(x[1])):
        st_wins = [r for r in rets if r > 0]
        by_signal_type.append(
            {
                "type": st,
                "count": len(rets),
                "win_rate_pct": round(len(st_wins) / len(rets) * 100, 1) if rets else 0,
                "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else 0,
            }
        )

    # By period (last 7D, 14D, 30D)
    now = datetime.now(timezone.utc)
    by_period = {}
    for label, days in [("last_7d", 7), ("last_14d", 14), ("last_30d", 30)]:
        period_cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        period_rows = [
            r
            for r in closed_rows
            if r["signal_date"] >= period_cutoff and r["return_pct"] is not None
        ]
        period_returns = [r["return_pct"] for r in period_rows]
        period_wins = [r for r in period_returns if r > 0]
        by_period[label] = {
            "signals": len(period_returns),
            "win_rate_pct": round(len(period_wins) / len(period_returns) * 100, 1)
            if period_returns
            else 0,
            "avg_return_pct": round(sum(period_returns) / len(period_returns), 2)
            if period_returns
            else 0,
        }

    result = {
        "timestamp": now_utc,
        "mode": "stats",
        "period_days": args.days_back,
        "total_signals": len(all_rows),
        "closed_signals": len(closed_rows),
        "open_signals": len(open_rows),
        "overall": overall,
        "by_signal_type": by_signal_type,
        "by_period": by_period,
    }
    return result


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Track signal performance for daily review/复盘",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Record signals from today's analysis
  %(prog)s record AAPL MSFT --signal-type breakout_confirmed --run-id 202606291430

  # Record with explicit entry price
  %(prog)s record 603738.SS --signal-type strong_buy --entry-price 55.89

  # Review all signals from last 30 days
  %(prog)s review --days-back 30

  # Review only open signals
  %(prog)s review --status open

  # Show aggregate performance statistics
  %(prog)s stats --days-back 60
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # --- record ---
    rec = subparsers.add_parser(
        "record",
        help="Record new signal entries",
        description="Record today's signals (tickers + entry prices + signal type)",
    )
    rec.add_argument(
        "tickers",
        nargs="+",
        metavar="TICKER",
        help="One or more ticker symbols to record",
    )
    rec.add_argument(
        "--signal-type",
        required=True,
        choices=VALID_SIGNAL_TYPES,
        help="Type of signal being recorded",
    )
    rec.add_argument(
        "--entry-price",
        type=float,
        default=None,
        help="Entry price (if not given, fetches current price via yfinance)",
    )
    rec.add_argument(
        "--date",
        type=str,
        default=None,
        help="Signal date in YYYY-MM-DD format (default: today)",
    )
    rec.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Analysis run ID to link this signal to",
    )
    rec.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )

    # --- review ---
    rev = subparsers.add_parser(
        "review",
        help="Review performance of recorded signals",
        description="Check performance of previously recorded signals",
    )
    rev.add_argument(
        "--days-back",
        type=int,
        default=30,
        help="How far back to look for signals (default: 30)",
    )
    rev.add_argument(
        "--status",
        choices=["open", "closed", "all"],
        default="all",
        help="Filter by signal status (default: all)",
    )
    rev.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    rev.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )

    # --- stats ---
    st = subparsers.add_parser(
        "stats",
        help="Aggregate performance statistics",
        description="Compute aggregate statistics from closed signals",
    )
    st.add_argument(
        "--days-back",
        type=int,
        default=30,
        help="Period to compute stats over (default: 30)",
    )
    st.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    st.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )

    return parser


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_output(data: dict, output_path: str | None):
    """Write JSON output to file or stdout."""
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        sys.stderr.write(f"Output written to: {output_path}\n")
    else:
        print(json_str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize database
    db_path = args.db
    conn = init_db(db_path)

    try:
        if args.command == "record":
            result = cmd_record(args, conn)
        elif args.command == "review":
            result = cmd_review(args, conn)
        elif args.command == "stats":
            result = cmd_stats(args, conn)
        else:
            parser.print_help()
            sys.exit(1)

        # Determine output path
        output_path = getattr(args, "output", None)
        write_output(result, output_path)

        # Exit with error code if there were errors
        if result.get("error"):
            sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
