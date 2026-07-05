#!/usr/bin/env python3
"""State persistence and checkpointing for stock analysis plugin.

Usage:
    persist.py init AAPL                    # Initialize analysis session
    persist.py save AAPL stage1 ./reports/AAPL/stage1.md  # Save stage output
    persist.py load AAPL                    # Load all stage outputs
    persist.py resume AAPL                  # Check if analysis can be resumed
    persist.py list                         # List all active analyses
    persist.py history AAPL                 # Show prior analysis history

Replaces the ./reports/ file-based approach with SQLite-backed checkpoints.
Enables:
  - Resume interrupted analyses
  - Incremental updates when new quarterly data arrives
  - Full audit trail of every analysis run
  - Conviction tracking over time
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.stock-analysis/state.db")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            report_type TEXT NOT NULL DEFAULT 'mid',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            conviction REAL,
            rating TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            stage_number INTEGER NOT NULL,
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            output_path TEXT,
            score REAL,
            started_at TEXT,
            completed_at TEXT,
            error_message TEXT,
            FOREIGN KEY (analysis_id) REFERENCES analyses(id)
        );

        CREATE TABLE IF NOT EXISTS conviction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            conviction REAL NOT NULL,
            rating TEXT NOT NULL,
            component_scores TEXT,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (analysis_id) REFERENCES analyses(id)
        );

        CREATE TABLE IF NOT EXISTS script_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            script_name TEXT NOT NULL,
            output_json TEXT,
            output_path TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (analysis_id) REFERENCES analyses(id)
        );

        CREATE INDEX IF NOT EXISTS idx_analyses_ticker ON analyses(ticker);
        CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);
        CREATE INDEX IF NOT EXISTS idx_stages_analysis ON stages(analysis_id);
        CREATE INDEX IF NOT EXISTS idx_conviction_analysis ON conviction_history(analysis_id);

        -- Signal evolution tables (signal_evolution.py)
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            dimension TEXT NOT NULL,
            description TEXT NOT NULL,
            lifecycle_state TEXT NOT NULL DEFAULT 'NEW',
            isq_score REAL,
            isq_innovation REAL,
            isq_speed REAL,
            isq_quality REAL,
            isq_confidence REAL,
            isq_counter_evidence REAL,
            source_tier INTEGER,
            sub_scores_json TEXT,
            cross_check_flags_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            trigger_reason TEXT,
            isq_before REAL,
            isq_after REAL,
            sub_scores_json TEXT,
            transitioned_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
        CREATE INDEX IF NOT EXISTS idx_signals_state ON signals(lifecycle_state);
        CREATE INDEX IF NOT EXISTS idx_signal_history_signal ON signal_history(signal_id);

        -- Hypothesis registry tables (hypothesis_registry.py)
        CREATE TABLE IF NOT EXISTS hypotheses (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            statement TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'neutral',
            lifecycle_state TEXT NOT NULL DEFAULT 'PROPOSED',
            prior_probability REAL DEFAULT 0.5,
            posterior_probability REAL DEFAULT 0.5,
            evidence_for_json TEXT DEFAULT '[]',
            evidence_against_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hypothesis_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hypothesis_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            reason TEXT,
            probability_before REAL,
            probability_after REAL,
            event_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_cards (
            id TEXT PRIMARY KEY,
            hypothesis_id TEXT NOT NULL,
            evidence_snapshot_json TEXT NOT NULL,
            probability_at_time REAL NOT NULL,
            methodology TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_hypotheses_ticker ON hypotheses(ticker);
        CREATE INDEX IF NOT EXISTS idx_hypotheses_state ON hypotheses(lifecycle_state);
        CREATE INDEX IF NOT EXISTS idx_hypothesis_events_hyp ON hypothesis_events(hypothesis_id);
        CREATE INDEX IF NOT EXISTS idx_run_cards_hyp ON run_cards(hypothesis_id);
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Analysis lifecycle
# ---------------------------------------------------------------------------


def init_analysis(ticker: str, report_type: str = "mid") -> dict:
    """Initialize a new analysis session."""
    conn = init_db()
    now = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        "INSERT INTO analyses (ticker, report_type, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (ticker.upper(), report_type, now, now),
    )
    analysis_id = cursor.lastrowid

    if report_type == "screen":
        stage_names = {
            0: "Setup & Scope",
            1: "Sub-Industry Screening",
            2: "Sub-Industry Deep Dive",
            3: "Company Screening",
            4: "Report Generation",
        }
    else:
        stage_names = {
            1: "Company Fundamentals",
            2: "Executive & Board Profiles",
            3: "Product & Industry",
            4: "Macro Economics",
            5: "Politics & Geopolitics",
            6: "Valuation & Quantitative Signals",
            7: "Market Regime & Positioning",
            8: "Risk Assessment",
            9: "Alternative Data",
            10: "Report Generation",
        }

    for stage_num, stage_name in stage_names.items():
        conn.execute(
            "INSERT INTO stages (analysis_id, stage_number, stage_name, status) VALUES (?, ?, ?, 'pending')",
            (analysis_id, stage_num, stage_name),
        )

    conn.commit()
    conn.close()

    return {
        "analysis_id": analysis_id,
        "ticker": ticker.upper(),
        "report_type": report_type,
        "status": "active",
        "created_at": now,
        "message": f"Analysis session {analysis_id} initialized for {ticker.upper()}",
    }


def save_stage(
    analysis_id: int, stage_num: int, output_path: str, score: float | None = None
) -> dict:
    """Save a completed stage output."""
    conn = init_db()

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE stages SET status = 'completed', output_path = ?, score = ?,
           completed_at = ? WHERE analysis_id = ? AND stage_number = ?""",
        (output_path, score, now, analysis_id, stage_num),
    )
    conn.execute(
        "UPDATE analyses SET updated_at = ? WHERE id = ?",
        (now, analysis_id),
    )
    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "analysis_id": analysis_id,
        "stage": stage_num,
        "saved_at": now,
    }


def save_conviction(
    analysis_id: int,
    conviction: float,
    rating: str,
    component_scores: dict | None = None,
) -> dict:
    """Record conviction rating for tracking over time."""
    conn = init_db()
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO conviction_history (analysis_id, conviction, rating, component_scores, recorded_at) VALUES (?, ?, ?, ?, ?)",
        (
            analysis_id,
            conviction,
            rating,
            json.dumps(component_scores) if component_scores else None,
            now,
        ),
    )
    conn.execute(
        "UPDATE analyses SET conviction = ?, rating = ?, updated_at = ? WHERE id = ?",
        (conviction, rating, now, analysis_id),
    )
    conn.commit()
    conn.close()
    return {
        "status": "ok",
        "analysis_id": analysis_id,
        "conviction": conviction,
        "recorded_at": now,
    }


def save_script_output(
    analysis_id: int, script_name: str, output_json: str, output_path: str | None = None
) -> dict:
    """Save a script output for later retrieval."""
    conn = init_db()
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO script_outputs (analysis_id, script_name, output_json, output_path, created_at) VALUES (?, ?, ?, ?, ?)",
        (analysis_id, script_name, output_json, output_path, now),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "analysis_id": analysis_id, "script": script_name}


# ---------------------------------------------------------------------------
# Analysis loading / resumption
# ---------------------------------------------------------------------------


def load_analysis(analysis_id: int) -> dict:
    """Load a full analysis with all stages."""
    conn = init_db()

    analysis = conn.execute(
        "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    if not analysis:
        conn.close()
        return {"error": f"Analysis {analysis_id} not found"}

    stages = conn.execute(
        "SELECT * FROM stages WHERE analysis_id = ? ORDER BY stage_number",
        (analysis_id,),
    ).fetchall()

    history = conn.execute(
        "SELECT * FROM conviction_history WHERE analysis_id = ? ORDER BY recorded_at DESC",
        (analysis_id,),
    ).fetchall()

    outputs = conn.execute(
        "SELECT * FROM script_outputs WHERE analysis_id = ? ORDER BY created_at DESC",
        (analysis_id,),
    ).fetchall()

    conn.close()

    return {
        "analysis": dict(analysis),
        "stages": [dict(s) for s in stages],
        "conviction_history": [dict(h) for h in history],
        "script_outputs": [
            {
                "id": o["id"],
                "script_name": o["script_name"],
                "output_path": o["output_path"],
                "created_at": o["created_at"],
            }
            for o in outputs
        ],
    }


def check_resume(ticker: str) -> dict | None:
    """Check if an interrupted analysis can be resumed."""
    conn = init_db()

    analysis = conn.execute(
        "SELECT * FROM analyses WHERE ticker = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()

    if not analysis:
        conn.close()
        return None

    stages = conn.execute(
        "SELECT * FROM stages WHERE analysis_id = ? ORDER BY stage_number",
        (analysis["id"],),
    ).fetchall()

    conn.close()

    completed = [s for s in stages if s["status"] == "completed"]
    pending = [s for s in stages if s["status"] == "pending"]

    return {
        "analysis_id": analysis["id"],
        "ticker": ticker.upper(),
        "created_at": analysis["created_at"],
        "completed_stages": len(completed),
        "total_stages": len(stages),
        "next_stage": pending[0]["stage_number"] if pending else None,
        "resumable": len(pending) > 0 and len(completed) > 0,
    }


def complete_analysis(analysis_id: int) -> dict:
    """Mark an analysis as completed."""
    conn = init_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE analyses SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, analysis_id),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "analysis_id": analysis_id, "completed_at": now}


def list_analyses(limit: int = 20) -> list[dict]:
    """List recent analyses."""
    conn = init_db()
    rows = conn.execute(
        "SELECT * FROM analyses ORDER BY updated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_history(ticker: str) -> list[dict]:
    """Get conviction history for a ticker."""
    conn = init_db()

    analyses = conn.execute(
        "SELECT id FROM analyses WHERE ticker = ? ORDER BY created_at DESC",
        (ticker.upper(),),
    ).fetchall()

    results = []
    for a in analyses:
        history = conn.execute(
            "SELECT * FROM conviction_history WHERE analysis_id = ? ORDER BY recorded_at DESC",
            (a["id"],),
        ).fetchall()
        for h in history:
            entry = dict(h)
            entry["analysis_id"] = a["id"]
            results.append(entry)

    conn.close()
    return results


# ---------------------------------------------------------------------------
# Kill switch monitoring
# ---------------------------------------------------------------------------


def check_kill_switch(ticker: str, condition_sql: str) -> dict:
    """Check if a kill switch condition is triggered.

    condition_sql is a simple expression like "revenue_cagr < 0.05"
    that gets evaluated against the most recent conviction history.
    """
    history = get_history(ticker)
    if not history:
        return {"status": "unknown", "reason": "No conviction history for this ticker"}

    latest = history[0]
    return {
        "ticker": ticker.upper(),
        "latest_conviction": latest["conviction"],
        "latest_rating": latest["rating"],
        "latest_date": latest["recorded_at"],
        "condition": condition_sql,
        "triggered": False,  # Requires live data to evaluate
        "note": "Run compute_scores.py against latest data for automatic kill switch evaluation",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="State persistence for stock analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize new analysis")
    p_init.add_argument("ticker", help="Ticker symbol")
    p_init.add_argument(
        "--report-type",
        default="mid",
        choices=["long", "mid", "short", "quick", "screen"],
    )

    # save
    p_save = sub.add_parser("save", help="Save stage output")
    p_save.add_argument("analysis_id", type=int)
    p_save.add_argument("stage", type=int)
    p_save.add_argument("output_path")
    p_save.add_argument("--score", type=float)

    # conviction
    p_conv = sub.add_parser("conviction", help="Record conviction rating")
    p_conv.add_argument("analysis_id", type=int)
    p_conv.add_argument("conviction", type=float)
    p_conv.add_argument("rating")
    p_conv.add_argument("--component-scores", help="Path to scores JSON")

    # script-output
    p_script = sub.add_parser("script-output", help="Save script output")
    p_script.add_argument("analysis_id", type=int)
    p_script.add_argument("script_name")
    p_script.add_argument("--output-json", default="{}")
    p_script.add_argument("--output-path")

    # load
    p_load = sub.add_parser("load", help="Load analysis")
    p_load.add_argument("analysis_id", type=int)

    # resume
    p_resume = sub.add_parser("resume", help="Check if analysis can be resumed")
    p_resume.add_argument("ticker")

    # complete
    p_complete = sub.add_parser("complete", help="Mark analysis as completed")
    p_complete.add_argument("analysis_id", type=int)

    # list
    p_list = sub.add_parser("list", help="List recent analyses")
    p_list.add_argument("--limit", type=int, default=20)

    # history
    p_history = sub.add_parser("history", help="Conviction history for ticker")
    p_history.add_argument("ticker")

    # kill-switch
    p_kill = sub.add_parser("kill-switch", help="Check kill switch condition")
    p_kill.add_argument("ticker")
    p_kill.add_argument("--condition", default="")

    args = parser.parse_args()

    init_db()

    if args.command == "init":
        result = init_analysis(args.ticker, args.report_type)
    elif args.command == "save":
        result = save_stage(args.analysis_id, args.stage, args.output_path, args.score)
    elif args.command == "conviction":
        scores = None
        if args.component_scores:
            with open(args.component_scores) as f:
                scores = json.load(f)
        result = save_conviction(args.analysis_id, args.conviction, args.rating, scores)
    elif args.command == "script-output":
        result = save_script_output(
            args.analysis_id, args.script_name, args.output_json, args.output_path
        )
    elif args.command == "load":
        result = load_analysis(args.analysis_id)
    elif args.command == "resume":
        result = check_resume(args.ticker)
        if result is None:
            result = {
                "resumable": False,
                "message": f"No active analysis found for {args.ticker}",
            }
    elif args.command == "complete":
        result = complete_analysis(args.analysis_id)
    elif args.command == "list":
        result = list_analyses(args.limit)
    elif args.command == "history":
        result = get_history(args.ticker)
    elif args.command == "kill-switch":
        result = check_kill_switch(args.ticker, args.condition)
    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
