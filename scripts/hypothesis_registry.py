#!/usr/bin/env python3
"""Hypothesis registry with lifecycle tracking and Bayesian belief updating.

Lifecycle states:
    PROPOSED → ACTIVE (when analysis begins)
    ACTIVE → TESTING (when data is being gathered)
    TESTING → CONFIRMED / FALSIFIED / REVISED
    CONFIRMED → SUPERSEDED (when better hypothesis found)
    FALSIFIED → (terminal)
    REVISED → ACTIVE (re-enter cycle with new evidence)

Run cards snapshot the evidence state at a point in time for audit trails.

Usage:
    python hypothesis_registry.py AAPL --propose \
        --statement "Services will drive 60%+ gross profit by FY2027" \
        --type bullish --prior 0.6
    python hypothesis_registry.py AAPL --list
    python hypothesis_registry.py --update HYP_ID \
        --evidence-for '{"source": "10-K", "fact": "Services gross margin 74%"}'
    python hypothesis_registry.py --transition HYP_ID --to TESTING \
        --reason "Gathering Q3 data"
    python hypothesis_registry.py --run-card HYP_ID \
        --methodology "Stage 6 valuation analysis"
"""

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from persist import get_db, init_db


# ---------------------------------------------------------------------------
# Lifecycle state machine
# ---------------------------------------------------------------------------

HYPOTHESIS_TRANSITIONS: dict[str, set[str]] = {
    "PROPOSED": {"ACTIVE"},
    "ACTIVE": {"TESTING"},
    "TESTING": {"CONFIRMED", "FALSIFIED", "REVISED"},
    "CONFIRMED": {"SUPERSEDED"},
    "FALSIFIED": set(),  # terminal
    "REVISED": {"ACTIVE"},
    "SUPERSEDED": set(),  # terminal
}

TERMINAL_STATES = {"FALSIFIED", "SUPERSEDED"}


def validate_hypothesis_transition(current: str, target: str) -> bool:
    """Return True if the transition is valid."""
    if current not in HYPOTHESIS_TRANSITIONS:
        return False
    return target in HYPOTHESIS_TRANSITIONS[current]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Hypothesis:
    id: str
    ticker: str
    statement: str
    type: str  # "bullish" | "bearish" | "neutral"
    lifecycle_state: str
    prior_probability: float
    posterior_probability: float
    evidence_for: list = field(default_factory=list)
    evidence_against: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    run_cards: list = field(default_factory=list)


@dataclass
class RunCard:
    id: str
    hypothesis_id: str
    evidence_snapshot: dict  # what evidence was available
    probability_at_time: float
    methodology: str
    created_at: str


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------


def _ensure_tables():
    """Ensure hypothesis tables exist (idempotent)."""
    conn = init_db()
    conn.executescript("""
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
    conn.close()


# ---------------------------------------------------------------------------
# Bayesian update
# ---------------------------------------------------------------------------


def bayesian_update(prior: float, likelihood: float, evidence_strength: float) -> float:
    """Simple Bayesian probability update.

    Parameters
    ----------
    prior : float
        Current belief P(H), range [0, 1].
    likelihood : float
        P(E|H) — how likely is this evidence if hypothesis is true.
    evidence_strength : float
        Weight of this evidence (0-1), used to blend with prior.

    Returns
    -------
    float
        Updated posterior probability, clamped to [0.01, 0.99].
    """
    prior = max(0.01, min(0.99, prior))
    likelihood = max(0.01, min(1.0, likelihood))
    # P(~H)
    neg_likelihood = max(0.01, 1.0 - likelihood)
    # P(E) = P(E|H)*P(H) + P(E|~H)*P(~H)
    marginal = likelihood * prior + neg_likelihood * (1.0 - prior)
    posterior = (likelihood * prior) / marginal

    # Blend with evidence strength to avoid wild swings from weak evidence
    blended = prior + evidence_strength * (posterior - prior)
    return round(max(0.01, min(0.99, blended)), 4)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def propose_hypothesis(
    ticker: str,
    statement: str,
    type: str = "neutral",
    prior: float = 0.5,
) -> dict:
    """Create a new hypothesis."""
    _ensure_tables()

    hyp_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    conn.execute(
        """INSERT INTO hypotheses
           (id, ticker, statement, type, lifecycle_state,
            prior_probability, posterior_probability,
            evidence_for_json, evidence_against_json,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, 'PROPOSED', ?, ?, '[]', '[]', ?, ?)""",
        (
            hyp_id,
            ticker.upper(),
            statement,
            type,
            prior,
            prior,
            now,
            now,
        ),
    )

    # Record creation event
    conn.execute(
        """INSERT INTO hypothesis_events
           (hypothesis_id, from_state, to_state, reason,
            probability_before, probability_after, event_at)
           VALUES (?, NULL, 'PROPOSED', 'Hypothesis proposed', NULL, ?, ?)""",
        (hyp_id, prior, now),
    )

    conn.commit()
    conn.close()

    return {
        "hypothesis_id": hyp_id,
        "ticker": ticker.upper(),
        "statement": statement,
        "type": type,
        "lifecycle_state": "PROPOSED",
        "prior_probability": prior,
        "posterior_probability": prior,
        "created_at": now,
    }


def update_hypothesis(
    hypothesis_id: str,
    evidence_for: list | None = None,
    evidence_against: list | None = None,
    bayesian_update_flag: bool = True,
) -> dict:
    """Add evidence and optionally update probability via Bayes."""
    _ensure_tables()

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"error": f"Hypothesis {hypothesis_id} not found"}

    hyp = dict(row)

    if hyp["lifecycle_state"] in TERMINAL_STATES:
        conn.close()
        return {
            "hypothesis_id": hypothesis_id,
            "message": f"Hypothesis is in terminal state '{hyp['lifecycle_state']}'",
        }

    old_evidence_for = json.loads(hyp["evidence_for_json"] or "[]")
    old_evidence_against = json.loads(hyp["evidence_against_json"] or "[]")

    new_evidence_for = evidence_for or []
    new_evidence_against = evidence_against or []

    merged_for = old_evidence_for + new_evidence_for
    merged_against = old_evidence_against + new_evidence_against

    prior = hyp["posterior_probability"]

    if bayesian_update_flag and (new_evidence_for or new_evidence_against):
        # For evidence: likelihood based on how many items support
        if new_evidence_for:
            n_for = len(new_evidence_for)
            likelihood = min(0.95, 0.5 + n_for * 0.15)
            strength = min(1.0, n_for * 0.2)
            posterior = bayesian_update(prior, likelihood, strength)
        else:
            posterior = prior

        # Against evidence: lowers probability
        if new_evidence_against:
            n_against = len(new_evidence_against)
            # Use inverse — evidence against means lower likelihood
            likelihood = max(0.05, 0.5 - n_against * 0.15)
            strength = min(1.0, n_against * 0.2)
            posterior = bayesian_update(posterior, likelihood, strength)
    else:
        posterior = prior

    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """UPDATE hypotheses SET
           posterior_probability = ?,
           evidence_for_json = ?,
           evidence_against_json = ?,
           updated_at = ?
           WHERE id = ?""",
        (
            posterior,
            json.dumps(merged_for),
            json.dumps(merged_against),
            now,
            hypothesis_id,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "hypothesis_id": hypothesis_id,
        "evidence_added_for": len(new_evidence_for),
        "evidence_added_against": len(new_evidence_against),
        "total_evidence_for": len(merged_for),
        "total_evidence_against": len(merged_against),
        "probability_before": prior,
        "probability_after": posterior,
        "updated_at": now,
    }


def transition_hypothesis(
    hypothesis_id: str,
    new_state: str,
    reason: str = "",
) -> dict:
    """Transition hypothesis lifecycle state."""
    _ensure_tables()

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"error": f"Hypothesis {hypothesis_id} not found"}

    hyp = dict(row)
    current_state = hyp["lifecycle_state"]

    if current_state in TERMINAL_STATES:
        conn.close()
        return {
            "hypothesis_id": hypothesis_id,
            "error": f"Cannot transition from terminal state '{current_state}'",
        }

    if not validate_hypothesis_transition(current_state, new_state):
        conn.close()
        valid = HYPOTHESIS_TRANSITIONS.get(current_state, set())
        return {
            "hypothesis_id": hypothesis_id,
            "error": f"Invalid transition '{current_state}' → '{new_state}'. "
            f"Valid targets: {sorted(valid) if valid else 'none (terminal)'}",
        }

    now = datetime.now(timezone.utc).isoformat()
    prob = hyp["posterior_probability"]

    conn.execute(
        """INSERT INTO hypothesis_events
           (hypothesis_id, from_state, to_state, reason,
            probability_before, probability_after, event_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (hypothesis_id, current_state, new_state, reason, prob, prob, now),
    )

    conn.execute(
        """UPDATE hypotheses SET lifecycle_state = ?, updated_at = ? WHERE id = ?""",
        (new_state, now, hypothesis_id),
    )

    conn.commit()
    conn.close()

    return {
        "hypothesis_id": hypothesis_id,
        "from_state": current_state,
        "to_state": new_state,
        "reason": reason,
        "probability": prob,
        "transitioned_at": now,
    }


def create_run_card(
    hypothesis_id: str,
    methodology: str,
) -> dict:
    """Snapshot current evidence state as a run card."""
    _ensure_tables()

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"error": f"Hypothesis {hypothesis_id} not found"}

    hyp = dict(row)

    card_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    evidence_snapshot = {
        "evidence_for": json.loads(hyp["evidence_for_json"] or "[]"),
        "evidence_against": json.loads(hyp["evidence_against_json"] or "[]"),
        "lifecycle_state": hyp["lifecycle_state"],
    }

    conn.execute(
        """INSERT INTO run_cards
           (id, hypothesis_id, evidence_snapshot_json,
            probability_at_time, methodology, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            card_id,
            hypothesis_id,
            json.dumps(evidence_snapshot),
            hyp["posterior_probability"],
            methodology,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "run_card_id": card_id,
        "hypothesis_id": hypothesis_id,
        "evidence_snapshot": evidence_snapshot,
        "probability_at_time": hyp["posterior_probability"],
        "methodology": methodology,
        "created_at": now,
    }


def get_hypotheses(ticker: str, state: str | None = None) -> list[dict]:
    """Get hypotheses for a ticker."""
    _ensure_tables()

    conn = get_db()
    if state:
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE ticker = ? AND lifecycle_state = ? ORDER BY updated_at DESC",
            (ticker.upper(), state),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE ticker = ? ORDER BY updated_at DESC",
            (ticker.upper(),),
        ).fetchall()
    conn.close()

    result = []
    for r in rows:
        entry = dict(r)
        entry["evidence_for"] = json.loads(entry.pop("evidence_for_json") or "[]")
        entry["evidence_against"] = json.loads(
            entry.pop("evidence_against_json") or "[]"
        )
        result.append(entry)
    return result


def get_hypothesis_events(hypothesis_id: str) -> list[dict]:
    """Get all events for a hypothesis."""
    _ensure_tables()

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM hypothesis_events WHERE hypothesis_id = ? ORDER BY event_at ASC",
        (hypothesis_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run_cards(hypothesis_id: str) -> list[dict]:
    """Get all run cards for a hypothesis."""
    _ensure_tables()

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM run_cards WHERE hypothesis_id = ? ORDER BY created_at ASC",
        (hypothesis_id,),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        entry = dict(r)
        entry["evidence_snapshot"] = json.loads(
            entry.pop("evidence_snapshot_json") or "{}"
        )
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Hypothesis registry with Bayesian belief updating",
    )
    sub = parser.add_subparsers(dest="command")

    # propose
    p_propose = sub.add_parser("propose", help="Propose a new hypothesis")
    p_propose.add_argument("ticker", help="Ticker symbol")
    p_propose.add_argument("--statement", required=True, help="Hypothesis statement")
    p_propose.add_argument(
        "--type", default="neutral", choices=["bullish", "bearish", "neutral"]
    )
    p_propose.add_argument(
        "--prior", type=float, default=0.5, help="Prior probability (0-1)"
    )

    # list
    p_list = sub.add_parser("list", help="List hypotheses for a ticker")
    p_list.add_argument("ticker", help="Ticker symbol")
    p_list.add_argument("--state", help="Filter by lifecycle state")

    # update
    p_update = sub.add_parser("update", help="Add evidence to a hypothesis")
    p_update.add_argument("hypothesis_id", help="Hypothesis ID")
    p_update.add_argument(
        "--evidence-for", default=None, help="JSON evidence supporting hypothesis"
    )
    p_update.add_argument(
        "--evidence-against",
        default=None,
        help="JSON evidence contradicting hypothesis",
    )
    p_update.add_argument(
        "--no-bayesian", action="store_true", help="Skip Bayesian update"
    )

    # transition
    p_trans = sub.add_parser("transition", help="Transition hypothesis state")
    p_trans.add_argument("hypothesis_id", help="Hypothesis ID")
    p_trans.add_argument("--to", required=True, help="Target state")
    p_trans.add_argument("--reason", default="", help="Reason for transition")

    # run-card
    p_card = sub.add_parser("run-card", help="Create a run card snapshot")
    p_card.add_argument("hypothesis_id", help="Hypothesis ID")
    p_card.add_argument("--methodology", required=True, help="Methodology description")

    # events
    p_events = sub.add_parser("events", help="Show hypothesis event history")
    p_events.add_argument("hypothesis_id", help="Hypothesis ID")

    # run-cards
    p_cards = sub.add_parser("run-cards", help="Show run cards for a hypothesis")
    p_cards.add_argument("hypothesis_id", help="Hypothesis ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "propose":
        result = propose_hypothesis(
            ticker=args.ticker,
            statement=args.statement,
            type=args.type,
            prior=args.prior,
        )
    elif args.command == "list":
        result = get_hypotheses(args.ticker, args.state)
    elif args.command == "update":
        raw_for = json.loads(args.evidence_for) if args.evidence_for else None
        raw_against = (
            json.loads(args.evidence_against) if args.evidence_against else None
        )
        # Wrap single dict items in a list for convenience
        ev_for = [raw_for] if isinstance(raw_for, dict) else raw_for
        ev_against = [raw_against] if isinstance(raw_against, dict) else raw_against
        result = update_hypothesis(
            hypothesis_id=args.hypothesis_id,
            evidence_for=ev_for,
            evidence_against=ev_against,
            bayesian_update_flag=not args.no_bayesian,
        )
    elif args.command == "transition":
        result = transition_hypothesis(
            hypothesis_id=args.hypothesis_id,
            new_state=args.to,
            reason=args.reason,
        )
    elif args.command == "run-card":
        result = create_run_card(
            hypothesis_id=args.hypothesis_id,
            methodology=args.methodology,
        )
    elif args.command == "events":
        result = get_hypothesis_events(args.hypothesis_id)
    elif args.command == "run-cards":
        result = get_run_cards(args.hypothesis_id)
    else:
        result = {"error": f"Unknown command: {args.command}"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
