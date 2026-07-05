#!/usr/bin/env python3
"""Signal evolution tracking with ISQ (Investment Signal Quality) 5-dimension model.

Tracks investment signals through a lifecycle state machine:
    NEW → UNCHANGED / STRENGTHENED / WEAKENED / FALSIFIED
    STRENGTHENED → STRENGTHENED / UNCHANGED / REALIZED
    WEAKENED → WEAKENED / FALSIFIED / DORMANT
    FALSIFIED → DORMANT
    DORMANT → NEW
    REALIZED → (terminal)

ISQ 5 Dimensions:
    innovation       — How novel is this signal?
    speed            — How fast was it detected?
    quality          — Source reliability tier
    confidence       — Based on number of confirming sub-scores
    counter_evidence — How much cross-check evidence contradicts?

Usage:
    python signal_evolution.py AAPL --create --dimension valuation \
        --description "P/E below sector median" --source-tier 1
    python signal_evolution.py AAPL --list
    python signal_evolution.py AAPL --history SIGNAL_ID
    python signal_evolution.py --update SIGNAL_ID --sub-scores '{"pe_ratio": 0.8}'
"""

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from persist import get_db, init_db


# ---------------------------------------------------------------------------
# Lifecycle state machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"UNCHANGED", "STRENGTHENED", "WEAKENED", "FALSIFIED"},
    "UNCHANGED": {"UNCHANGED", "STRENGTHENED", "WEAKENED", "FALSIFIED"},
    "STRENGTHENED": {"STRENGTHENED", "UNCHANGED", "REALIZED"},
    "WEAKENED": {"WEAKENED", "FALSIFIED", "DORMANT"},
    "FALSIFIED": {"DORMANT"},
    "DORMANT": {"NEW"},
    "REALIZED": set(),  # terminal
}

TERMINAL_STATES = {"REALIZED"}


def validate_transition(current: str, target: str) -> bool:
    """Return True if the transition from *current* to *target* is valid."""
    if current not in VALID_TRANSITIONS:
        return False
    return target in VALID_TRANSITIONS[current]


# ---------------------------------------------------------------------------
# ISQ model
# ---------------------------------------------------------------------------


@dataclass
class ISQDimensions:
    innovation: float  # 0-1: Novelty of source / score
    speed: float  # 0-1: Inverse of detection lag
    quality: float  # 0-1: Source reliability tier
    confidence: float  # 0-1: Number of confirming sub-scores
    counter_evidence: float  # 0-1: Inverse of contradicting flags

    def composite(self) -> float:
        """Weighted average of all five dimensions."""
        weights = {
            "innovation": 0.15,
            "speed": 0.15,
            "quality": 0.25,
            "confidence": 0.25,
            "counter_evidence": 0.20,
        }
        return (
            self.innovation * weights["innovation"]
            + self.speed * weights["speed"]
            + self.quality * weights["quality"]
            + self.confidence * weights["confidence"]
            + self.counter_evidence * weights["counter_evidence"]
        )


TIER_QUALITY_MAP = {1: 1.0, 2: 0.7, 3: 0.4}


def compute_isq(
    sub_scores: dict,
    source_tier: int,
    detection_lag_days: int,
    cross_check_flags: list,
) -> ISQDimensions:
    """Compute ISQ dimensions from raw data proxies.

    Parameters
    ----------
    sub_scores : dict
        Mapping of metric name → score (0-1). More keys → higher confidence.
    source_tier : int
        1 (best), 2, or 3. Maps to quality dimension.
    detection_lag_days : int
        Days between event occurrence and detection. Lower → higher speed.
    cross_check_flags : list
        Cross-check flags. More flags → lower counter_evidence score.
    """
    # Innovation: heuristic — more sub-scores from diverse sources is more novel
    innovation = min(1.0, len(sub_scores) / 10.0)

    # Speed: inverse of detection lag, saturating at 0 for very stale data
    speed = max(0.0, 1.0 - detection_lag_days / 30.0)

    # Quality: source tier mapping
    quality = TIER_QUALITY_MAP.get(source_tier, 0.4)

    # Confidence: more confirming sub-scores → higher
    if sub_scores:
        avg_score = sum(sub_scores.values()) / len(sub_scores)
        confidence = min(1.0, avg_score * len(sub_scores) / 5.0)
    else:
        confidence = 0.1

    # Counter-evidence: inverse of number of cross-check flags
    counter_evidence = max(0.0, 1.0 - len(cross_check_flags) / 5.0)

    return ISQDimensions(
        innovation=round(innovation, 4),
        speed=round(speed, 4),
        quality=round(quality, 4),
        confidence=round(confidence, 4),
        counter_evidence=round(counter_evidence, 4),
    )


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def _ensure_tables():
    """Ensure signal tables exist (idempotent)."""
    conn = init_db()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


def create_signal(
    ticker: str,
    dimension: str,
    description: str,
    source_tier: int,
    sub_scores: dict | None = None,
    cross_check_flags: list | None = None,
) -> dict:
    """Create a new signal with ISQ computation."""
    _ensure_tables()

    sub_scores = sub_scores or {}
    cross_check_flags = cross_check_flags or []

    signal_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    isq = compute_isq(sub_scores, source_tier, 0, cross_check_flags)

    conn = get_db()
    conn.execute(
        """INSERT INTO signals
           (id, ticker, dimension, description, lifecycle_state,
            isq_score, isq_innovation, isq_speed, isq_quality,
            isq_confidence, isq_counter_evidence, source_tier,
            sub_scores_json, cross_check_flags_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'NEW', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal_id,
            ticker.upper(),
            dimension,
            description,
            isq.composite(),
            isq.innovation,
            isq.speed,
            isq.quality,
            isq.confidence,
            isq.counter_evidence,
            source_tier,
            json.dumps(sub_scores),
            json.dumps(cross_check_flags),
            now,
            now,
        ),
    )

    # Record initial history entry
    conn.execute(
        """INSERT INTO signal_history
           (signal_id, from_state, to_state, trigger_reason,
            isq_before, isq_after, sub_scores_json, transitioned_at)
           VALUES (?, NULL, 'NEW', 'Signal created', NULL, ?, ?, ?)""",
        (signal_id, isq.composite(), json.dumps(sub_scores), now),
    )

    conn.commit()
    conn.close()

    return {
        "signal_id": signal_id,
        "ticker": ticker.upper(),
        "dimension": dimension,
        "lifecycle_state": "NEW",
        "isq": asdict(isq),
        "isq_composite": isq.composite(),
        "created_at": now,
    }


def _determine_lifecycle(
    current_state: str,
    isq_before: float,
    isq_after: float,
    cross_check_flags: list,
) -> str:
    """Determine the next lifecycle state based on ISQ delta and flags."""
    if current_state in TERMINAL_STATES:
        return current_state

    has_falsification = any("falsif" in str(f).lower() for f in cross_check_flags)
    if has_falsification and current_state in {"NEW", "UNCHANGED", "WEAKENED"}:
        return "FALSIFIED"

    delta = isq_after - isq_before
    if delta > 0.05:
        candidate = "STRENGTHENED"
    elif delta < -0.05:
        candidate = "WEAKENED"
    else:
        candidate = "UNCHANGED"

    # Validate against state machine
    if validate_transition(current_state, candidate):
        return candidate

    # Fall back to UNCHANGED if the preferred transition is invalid
    if validate_transition(current_state, "UNCHANGED"):
        return "UNCHANGED"

    # Stay in current state if no valid transition exists
    return current_state


def update_signal(
    signal_id: str,
    new_sub_scores: dict | None = None,
    new_cross_check_flags: list | None = None,
) -> dict:
    """Update a signal with new data. Compute lifecycle transition."""
    _ensure_tables()

    conn = get_db()
    row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()

    if not row:
        conn.close()
        return {"error": f"Signal {signal_id} not found"}

    signal = dict(row)

    if signal["lifecycle_state"] in TERMINAL_STATES:
        conn.close()
        return {
            "signal_id": signal_id,
            "message": f"Signal is in terminal state '{signal['lifecycle_state']}'",
        }

    # Merge sub-scores and flags
    old_sub_scores = json.loads(signal["sub_scores_json"] or "{}")
    old_flags = json.loads(signal["cross_check_flags_json"] or "[]")

    merged_sub_scores = {**old_sub_scores, **(new_sub_scores or {})}
    merged_flags = list(set(old_flags + (new_cross_check_flags or [])))

    isq_before = signal["isq_score"] or 0.0
    isq = compute_isq(
        merged_sub_scores,
        signal["source_tier"] or 3,
        _compute_detection_lag(signal["created_at"]),
        merged_flags,
    )
    isq_after = isq.composite()

    new_state = _determine_lifecycle(
        signal["lifecycle_state"], isq_before, isq_after, merged_flags
    )

    now = datetime.now(timezone.utc).isoformat()

    # Record history if state changed
    if new_state != signal["lifecycle_state"]:
        conn.execute(
            """INSERT INTO signal_history
               (signal_id, from_state, to_state, trigger_reason,
                isq_before, isq_after, sub_scores_json, transitioned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                signal["lifecycle_state"],
                new_state,
                f"ISQ delta: {isq_after - isq_before:+.4f}",
                isq_before,
                isq_after,
                json.dumps(merged_sub_scores),
                now,
            ),
        )

    # Update signal
    conn.execute(
        """UPDATE signals SET
           lifecycle_state = ?,
           isq_score = ?, isq_innovation = ?, isq_speed = ?,
           isq_quality = ?, isq_confidence = ?, isq_counter_evidence = ?,
           sub_scores_json = ?, cross_check_flags_json = ?,
           updated_at = ?
           WHERE id = ?""",
        (
            new_state,
            isq_after,
            isq.innovation,
            isq.speed,
            isq.quality,
            isq.confidence,
            isq.counter_evidence,
            json.dumps(merged_sub_scores),
            json.dumps(merged_flags),
            now,
            signal_id,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "signal_id": signal_id,
        "previous_state": signal["lifecycle_state"],
        "new_state": new_state,
        "isq_before": isq_before,
        "isq_after": isq_after,
        "isq": asdict(isq),
        "updated_at": now,
    }


def _compute_detection_lag(created_at: str) -> int:
    """Compute days since signal creation as a proxy for detection lag."""
    try:
        created = datetime.fromisoformat(created_at)
        now = datetime.now(timezone.utc)
        return max(0, (now - created).days)
    except (ValueError, TypeError):
        return 0


def get_signals(ticker: str, status: str | None = None) -> list[dict]:
    """Get all signals for a ticker, optionally filtered by status."""
    _ensure_tables()

    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM signals WHERE ticker = ? AND lifecycle_state = ? ORDER BY updated_at DESC",
            (ticker.upper(), status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM signals WHERE ticker = ? ORDER BY updated_at DESC",
            (ticker.upper(),),
        ).fetchall()
    conn.close()

    result = []
    for r in rows:
        entry = dict(r)
        entry["sub_scores"] = json.loads(entry.pop("sub_scores_json") or "{}")
        entry["cross_check_flags"] = json.loads(
            entry.pop("cross_check_flags_json") or "[]"
        )
        result.append(entry)
    return result


def get_signal_history(signal_id: str) -> list[dict]:
    """Get full history of a signal's lifecycle transitions."""
    _ensure_tables()

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM signal_history WHERE signal_id = ? ORDER BY transitioned_at ASC",
        (signal_id,),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        entry = dict(r)
        if entry.get("sub_scores_json"):
            entry["sub_scores"] = json.loads(entry.pop("sub_scores_json"))
        else:
            entry.pop("sub_scores_json", None)
            entry["sub_scores"] = None
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Signal evolution tracking with ISQ model",
    )
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new signal")
    p_create.add_argument("ticker", help="Ticker symbol")
    p_create.add_argument(
        "--dimension",
        required=True,
        help="Signal dimension (e.g., valuation, moat, momentum)",
    )
    p_create.add_argument("--description", required=True, help="Signal description")
    p_create.add_argument("--source-tier", type=int, default=2, choices=[1, 2, 3])
    p_create.add_argument("--sub-scores", default="{}", help="JSON sub-scores dict")
    p_create.add_argument(
        "--cross-check-flags", default="[]", help="JSON cross-check flags list"
    )

    # list
    p_list = sub.add_parser("list", help="List signals for a ticker")
    p_list.add_argument("ticker", help="Ticker symbol")
    p_list.add_argument("--status", help="Filter by lifecycle state")

    # history
    p_history = sub.add_parser("history", help="Show signal lifecycle history")
    p_history.add_argument("signal_id", help="Signal ID")

    # update
    p_update = sub.add_parser("update", help="Update a signal with new data")
    p_update.add_argument("signal_id", help="Signal ID")
    p_update.add_argument("--sub-scores", default="{}", help="JSON sub-scores to merge")
    p_update.add_argument(
        "--cross-check-flags", default="[]", help="JSON cross-check flags to add"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "create":
        sub_scores = json.loads(args.sub_scores)
        flags = json.loads(args.cross_check_flags)
        result = create_signal(
            ticker=args.ticker,
            dimension=args.dimension,
            description=args.description,
            source_tier=args.source_tier,
            sub_scores=sub_scores,
            cross_check_flags=flags,
        )
    elif args.command == "list":
        result = get_signals(args.ticker, args.status)
    elif args.command == "history":
        result = get_signal_history(args.signal_id)
    elif args.command == "update":
        sub_scores = json.loads(args.sub_scores)
        flags = json.loads(args.cross_check_flags)
        result = update_signal(
            signal_id=args.signal_id,
            new_sub_scores=sub_scores,
            new_cross_check_flags=flags,
        )
    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
