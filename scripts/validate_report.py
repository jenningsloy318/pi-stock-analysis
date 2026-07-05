#!/usr/bin/env python3
"""Pre-delivery quality gate validator for stock analysis reports.

Usage:
    validate_report.py ./reports/AAPL/ --report-type long
    validate_report.py ./reports/TSLA/ --report-type short --strict
    validate_report.py ./reports/MSFT/ --report-type mid --output ./reports/MSFT/validation.json

Validates all JSON outputs in a report directory against the nine pre-delivery
quality gates defined in the analysis philosophy:
  1. Data Freshness       — timestamps within allowed staleness window
  2. Source Coverage      — required and optional files present
  3. Conviction Consistency — score/rating bracket coherence and override rules
  4. Forensic Checks      — Beneish, Altman, Piotroski computed and flagged
  5. Kill Switch          — stage12.md risk section contains required keywords
  6. Fact Check           — 5 cross-reference checks across raw-data and metrics
  7. Chinese Language     — report files contain Chinese (中文) content
  8. Stock Price Display  — ranking tables include 当前股价 column
  9. Moat Decision Table  — 4-Moat S/M/W table present (long: + counterfactual,
                            anti-patterns, peer-pair comparison)

In --strict mode any gate failure sets overall_pass = false.
In default mode only the three blocking gates (freshness, coverage,
conviction) drive the overall result.
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRESHNESS_DAYS: dict[str, int] = {
    "short": 7,
    "mid": 30,
    "long": 90,
}

# Maps canonical filename → (required_for, description)
# required_for: set of report types that need this file; None = all
_ALL = {"short", "mid", "long"}
SOURCE_FILES: dict[str, tuple[set[str] | None, str]] = {
    "raw-data.json": (_ALL, "Financial raw data (fetch_financials)"),
    "metrics.json": (_ALL, "Calculated metrics (calculate_metrics)"),
    "tech.json": ({"short", "mid"}, "Technical indicators (fetch_technicals)"),
    "macro.json": ({"mid", "long"}, "Macro indicators (fetch_macro)"),
    "sentiment.json": ({"short", "mid"}, "Sentiment data (fetch_sentiment)"),
    "scores.json": (_ALL, "Conviction scores (compute_scores)"),
    "capital_structure.json": ({"long"}, "Capital structure (fetch_capital_structure)"),
    "credit.json": ({"long"}, "Credit risk data (fetch_credit)"),
    "forecast.json": ({"mid", "long"}, "Time-series forecast (forecast)"),
    # Optional
    "private_comps.json": (None, "Private comps / M&A (fetch_private_comps)"),
    "esg_carbon.json": (None, "ESG / carbon (fetch_esg_carbon)"),
    "behavioral.json": (None, "Behavioral signals (fetch_behavioral)"),
    "supply_chain.json": (None, "Supply chain (fetch_supply_chain)"),
    "earnings_quality.json": (None, "Earnings quality (calculate_earnings_quality)"),
    "options.json": (None, "Options signals (calculate_options)"),
    "correlation.json": (None, "Correlation regime (compute_correlation_regime)"),
    "earnings_edge.json": (None, "Earnings edge / PEAD (compute_earnings_edge)"),
    "seasonality.json": (None, "Seasonality patterns (compute_seasonality)"),
    "factors.json": (None, "Fama-French factor attribution (compute_factors)"),
    "news_nlp.json": (None, "News NLP sentiment (fetch_news_nlp)"),
    "peers.json": (None, "Peer universe (fetch_peer_universe)"),
    "short_interest.json": (None, "Short interest dynamics (fetch_short_interest)"),
    "filing_diff.json": (None, "Filing redline (diff_filings)"),
    "liquidity.json": (None, "Market microstructure (compute_liquidity)"),
    "cot.json": (None, "CFTC positioning (fetch_cot)"),
    "cross_check.json": (None, "Cross-check contradictions (cross_check)"),
    "activist.json": (None, "Activist exposure (fetch_activist_exposure)"),
    "alternatives.json": (None, "Alternative data signals (fetch_alternatives)"),
    "economic_surprises.json": (
        None,
        "Economic surprise indices (fetch_economic_surprises)",
    ),
    "global_macro.json": (None, "Global macro non-US (fetch_global_macro)"),
    "realtime.json": (None, "Real-time quotes/options (fetch_realtime)"),
    "candor.json": (None, "Management candor NLP (calculate_candor)"),
    "currency_exposure.json": (None, "FX/ADR exposure (fetch_currency_exposure)"),
    "market_breadth.json": (
        {"mid", "long"},
        "Market breadth data (fetch_market_breadth)",
    ),
    "theme_performance.json": (
        {"mid", "long"},
        "Theme/style ETF performance (fetch_theme_performance)",
    ),
    "economic_surprises.json": (
        {"mid", "long"},
        "Economic surprise indices (fetch_economic_surprises)",
    ),
    "sub_industry_universe.json": (
        {"long"},
        "GICS Level 4 universe (fetch_sub_industry_universe)",
    ),
    "hypothesis_registry.json": (None, "Hypothesis tracking (hypothesis_registry)"),
    "signal_evolution.json": (None, "Signal lifecycle (signal_evolution)"),
    "alpha_factors.json": (None, "Factor zoo output (alpha_factor_zoo)"),
}

REQUIRED_FILES = {
    fname for fname, (req_for, _) in SOURCE_FILES.items() if req_for is not None
}
OPTIONAL_FILES = {
    fname for fname, (req_for, _) in SOURCE_FILES.items() if req_for is None
}

RATING_BRACKETS: list[tuple[float, str]] = [
    (9.0, "Strong Buy"),
    (7.5, "Buy"),
    (6.0, "Hold / Accumulate"),
    (4.0, "Hold / Reduce"),
    (2.0, "Sell"),
    (0.0, "Strong Sell"),
]

KILL_SWITCH_KEYWORDS = {"kill switch", "falsification", "kill-switch"}
CATALYST_KEYWORDS = {"hard catalyst", "hard-catalyst"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: str) -> dict | None:
    """Return parsed JSON dict or None on any error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _parse_ts(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into an aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _age_days(ts: str | None, now: datetime) -> float | None:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 86400


def _expected_rating(score: float) -> str:
    for threshold, label in RATING_BRACKETS:
        if score >= threshold:
            return label
    return "Strong Sell"


# ---------------------------------------------------------------------------
# Gate 1 — Data Freshness
# ---------------------------------------------------------------------------


def gate_data_freshness(
    report_dir: str,
    report_type: str,
    now: datetime,
) -> dict:
    max_days = FRESHNESS_DAYS[report_type]
    stale: list[dict] = []
    fresh_count = 0
    checked = 0

    for fname in os.listdir(report_dir):
        if not fname.endswith(".json"):
            continue
        data = _load_json(os.path.join(report_dir, fname))
        if data is None:
            continue

        ts = data.get("retrieved_at") or data.get("computed_at")
        age = _age_days(ts, now)
        checked += 1

        if age is None:
            stale.append(
                {"file": fname, "age_days": None, "reason": "No timestamp found"}
            )
        elif age > max_days:
            stale.append(
                {
                    "file": fname,
                    "age_days": round(age, 1),
                    "reason": f">{max_days}d old",
                }
            )
        else:
            fresh_count += 1

    passed = len(stale) == 0
    details = (
        f"{fresh_count}/{checked} files within {max_days}-day window"
        if checked
        else "No JSON files found"
    )
    return {
        "pass": passed,
        "stale_files": stale,
        "files_checked": checked,
        "max_age_days": max_days,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Gate 2 — Source Coverage
# ---------------------------------------------------------------------------


def gate_source_coverage(report_dir: str, report_type: str) -> dict:
    present = {f for f in os.listdir(report_dir) if f.endswith(".json")}

    required_for_type = {
        fname
        for fname, (req_for, _) in SOURCE_FILES.items()
        if req_for is not None and report_type in req_for
    }

    required_missing = sorted(required_for_type - present)
    optional_missing = sorted(OPTIONAL_FILES - present)
    required_present = len(required_for_type) - len(required_missing)

    passed = len(required_missing) == 0
    return {
        "pass": passed,
        "required_present": required_present,
        "required_total": len(required_for_type),
        "required_missing": required_missing,
        "optional_missing": optional_missing,
        "details": (
            f"{required_present}/{len(required_for_type)} required files present"
            + (f"; missing: {required_missing}" if required_missing else "")
        ),
    }


# ---------------------------------------------------------------------------
# Gate 3 — Conviction Consistency
# ---------------------------------------------------------------------------


def gate_conviction_consistency(report_dir: str) -> dict:
    scores_path = os.path.join(report_dir, "scores.json")
    data = _load_json(scores_path)

    issues: list[str] = []

    if data is None:
        return {
            "pass": False,
            "score": None,
            "rating": None,
            "issues": ["scores.json missing or unreadable"],
            "details": "Cannot validate conviction — scores.json absent",
        }

    conviction_block = data.get("conviction", {})
    if not isinstance(conviction_block, dict):
        # Flat structure fallback
        conviction_block = data

    score = conviction_block.get("conviction")
    rating = conviction_block.get("rating")

    if score is None:
        issues.append("conviction score missing")
    else:
        if not (1.0 <= score <= 10.0):
            issues.append(f"conviction score {score} out of 1-10 range")

        if rating:
            expected = _expected_rating(score)
            # Allow partial match for "Hold / Accumulate" vs "Hold / Reduce"
            if (
                expected.lower() not in rating.lower()
                and rating.lower() not in expected.lower()
            ):
                issues.append(
                    f"rating '{rating}' inconsistent with score {score} "
                    f"(expected '{expected}')"
                )

    # Check component override rule: any component <= 3 → max Hold
    component_keys = [
        "financial_health",
        "moat_quality",
        "management_quality",
        "valuation_attractiveness",
        "macro_tailwind",
        "risk_profile",
        "alternative_alignment",
        "technical_setup",
        "capital_structure",
        "weinstein_alignment",
        "canslim",
    ]
    component_scores = {}
    for k in component_keys:
        val = data.get(k)
        if val is not None:
            # scores.json stores each component as a dict with a "score" sub-key
            if isinstance(val, dict):
                val = val.get("score")
            if val is not None:
                component_scores[k] = val
    low_components = [k for k, v in component_scores.items() if v <= 3.0]

    if low_components and score is not None and score >= 6.0:
        overrides = conviction_block.get("overrides", [])
        override_applied = any("capped" in str(o).lower() for o in overrides)
        if not override_applied:
            issues.append(
                f"Component(s) <= 3 ({low_components}) but no Hold cap applied "
                f"(score={score})"
            )

    # Flag if 3+ components are missing
    missing_components = [k for k in component_keys if data.get(k) is None]
    if len(missing_components) >= 3:
        issues.append(
            f"{len(missing_components)} component scores missing: {missing_components[:5]}"
        )

    return {
        "pass": len(issues) == 0,
        "score": score,
        "rating": rating,
        "low_components": low_components,
        "missing_component_count": len(missing_components),
        "issues": issues,
        "details": "OK" if not issues else "; ".join(issues),
    }


# ---------------------------------------------------------------------------
# Gate 4 — Forensic Checks
# ---------------------------------------------------------------------------


def gate_forensic_checks(report_dir: str) -> dict:
    metrics = _load_json(os.path.join(report_dir, "metrics.json"))

    if metrics is None:
        return {
            "pass": False,
            "beneish_flag": None,
            "altman_flag": None,
            "piotroski_present": False,
            "issues": ["metrics.json missing or unreadable"],
            "details": "Cannot run forensic checks",
        }

    issues: list[str] = []

    # Beneish M-Score (calculate_metrics writes key as "mscore")
    beneish_block = metrics.get("beneish_mscore", {})
    m_score = beneish_block.get("mscore") if isinstance(beneish_block, dict) else None
    beneish_flag = False
    if m_score is None:
        issues.append("Beneish M-Score not computed")
    elif m_score > -1.78:
        beneish_flag = True
        issues.append(
            f"Beneish M-Score {m_score:.2f} > -1.78 (earnings manipulation risk)"
        )

    # Altman Z-Score (calculate_metrics writes key as "zscore")
    altman_block = metrics.get("altman_zscore", {})
    z_score = altman_block.get("zscore") if isinstance(altman_block, dict) else None
    altman_flag = False
    if z_score is None:
        issues.append("Altman Z-Score not computed")
    elif z_score < 1.81:
        altman_flag = True
        issues.append(f"Altman Z-Score {z_score:.2f} < 1.81 (distress zone)")

    # Piotroski F-Score (calculate_metrics writes key as "fscore")
    piotroski_block = metrics.get("piotroski_fscore", {})
    piotroski_score = (
        piotroski_block.get("fscore") if isinstance(piotroski_block, dict) else None
    )
    piotroski_present = piotroski_score is not None
    if not piotroski_present:
        issues.append("Piotroski F-Score not computed")

    # Forensic flags are warnings, not blocking — gate passes unless scores are absent
    absence_count = sum([m_score is None, z_score is None, not piotroski_present])
    passed = absence_count == 0

    return {
        "pass": passed,
        "beneish_flag": beneish_flag,
        "beneish_m_score": round(m_score, 3) if m_score is not None else None,
        "altman_flag": altman_flag,
        "altman_z_score": round(z_score, 3) if z_score is not None else None,
        "piotroski_present": piotroski_present,
        "piotroski_score": piotroski_score,
        "issues": issues,
        "details": "OK" if not issues else "; ".join(issues),
    }


# ---------------------------------------------------------------------------
# Gate 5 — Kill Switch
# ---------------------------------------------------------------------------


def gate_kill_switch(report_dir: str, rating: str | None) -> dict:
    # Stage 12 = Risk Assessment (was stage 8 in earlier versions)
    risk_path = os.path.join(report_dir, "stage12.md")
    if not os.path.exists(risk_path):
        risk_path = os.path.join(report_dir, "stage8.md")  # fallback for legacy runs
    issues: list[str] = []

    if not os.path.exists(risk_path):
        return {
            "pass": False,
            "has_kill_switch": False,
            "has_catalyst": False,
            "issues": ["stage12.md (risk assessment) not found"],
            "details": "stage12.md absent",
        }

    try:
        with open(risk_path) as fh:
            text = fh.read().lower()
    except OSError as exc:
        return {
            "pass": False,
            "has_kill_switch": False,
            "has_catalyst": False,
            "issues": [f"Cannot read stage12.md: {exc}"],
            "details": "stage12.md unreadable",
        }

    has_kill_switch = any(kw in text for kw in KILL_SWITCH_KEYWORDS)
    if not has_kill_switch:
        issues.append("stage12.md missing 'kill switch' or 'falsification' keyword")

    is_buy = rating and any(b in (rating or "") for b in ("Buy", "Strong Buy"))
    has_catalyst = any(kw in text for kw in CATALYST_KEYWORDS)
    if is_buy and not has_catalyst:
        issues.append("Buy rating issued without 'hard catalyst' in stage12.md")

    return {
        "pass": len(issues) == 0,
        "has_kill_switch": has_kill_switch,
        "has_catalyst": has_catalyst,
        "issues": issues,
        "details": "OK" if not issues else "; ".join(issues),
    }


# ---------------------------------------------------------------------------
# Gate 6 — Fact Check (Hallucination Protocol)
# ---------------------------------------------------------------------------


def gate_fact_check(report_dir: str) -> dict:
    raw = _load_json(os.path.join(report_dir, "raw-data.json"))
    metrics = _load_json(os.path.join(report_dir, "metrics.json"))

    checks_passed = 0
    checks_failed = 0
    discrepancies: list[str] = []

    def _check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal checks_passed, checks_failed
        if condition:
            checks_passed += 1
        else:
            checks_failed += 1
            discrepancies.append(f"{label}: {detail}" if detail else label)

    if raw is None or metrics is None:
        return {
            "pass": False,
            "checks_passed": 0,
            "checks_failed": 5,
            "discrepancies": [
                "raw-data.json or metrics.json missing — cannot fact-check"
            ],
            "details": "Missing source files",
        }

    ratios = metrics.get("ratios", {})
    income = raw.get(
        "income_statement", raw.get("financials", {}).get("income_statement", {})
    )
    cashflow = raw.get("cash_flow", raw.get("financials", {}).get("cash_flow", {}))

    # --- Check 1: Revenue consistency ---
    raw_rev_entries = income.get("revenue", [])
    raw_rev = None
    if isinstance(raw_rev_entries, list) and raw_rev_entries:
        entry = raw_rev_entries[0]
        raw_rev = entry.get("value") if isinstance(entry, dict) else entry
    elif isinstance(raw_rev_entries, (int, float)):
        raw_rev = raw_rev_entries

    metrics_rev = metrics.get("revenue") or metrics.get("ratios", {}).get("revenue")
    rev_ok = (raw_rev is None or metrics_rev is None) or (
        abs(raw_rev - metrics_rev) / max(abs(raw_rev), 1) < 0.05
    )
    _check(
        "Revenue consistency",
        rev_ok,
        f"raw={raw_rev}, metrics={metrics_rev}" if not rev_ok else "",
    )

    # --- Check 2: Market cap consistency ---
    raw_mc = raw.get("market_cap") or raw.get("profile", {}).get("market_cap")
    metrics_mc = metrics.get("market_cap") or ratios.get("market_cap")
    mc_ok = (raw_mc is None or metrics_mc is None) or (
        abs(raw_mc - metrics_mc) / max(abs(raw_mc), 1) < 0.10
    )
    _check(
        "Market cap consistency",
        mc_ok,
        f"raw={raw_mc}, metrics={metrics_mc}" if not mc_ok else "",
    )

    # --- Check 3: P/E internal consistency (EPS × PE ≈ price) ---
    pe = ratios.get("pe_ratio")
    eps = ratios.get("eps")
    price = raw.get("price") or raw.get("profile", {}).get("price")
    if pe and eps and price and price > 0:
        implied_price = pe * eps
        pe_ok = abs(implied_price - price) / price < 0.15
        _check(
            "P/E consistency (EPS × PE ≈ price)",
            pe_ok,
            f"PE={pe}×EPS={eps}={implied_price:.2f} vs price={price}"
            if not pe_ok
            else "",
        )
    else:
        checks_passed += 1  # Cannot check; neutral pass

    # --- Check 4: FCF sign vs FCF yield sign ---
    fcf_entries = cashflow.get("free_cash_flow", [])
    fcf_val = None
    if isinstance(fcf_entries, list) and fcf_entries:
        entry = fcf_entries[0]
        fcf_val = entry.get("value") if isinstance(entry, dict) else entry
    elif isinstance(fcf_entries, (int, float)):
        fcf_val = fcf_entries

    fcf_yield = ratios.get("fcf_yield")
    if fcf_val is not None and fcf_yield is not None:
        sign_ok = (fcf_val >= 0) == (fcf_yield >= 0)
        _check(
            "FCF sign vs FCF yield sign",
            sign_ok,
            f"FCF={fcf_val}, FCF yield={fcf_yield}" if not sign_ok else "",
        )
    else:
        checks_passed += 1  # Cannot check; neutral pass

    # --- Check 5: Debt/equity direction vs leverage assessment ---
    de_ratio = ratios.get("debt_to_equity")
    net_debt = ratios.get("net_debt")
    if de_ratio is not None and net_debt is not None:
        # Both should agree on sign: D/E > 0 ↔ net_debt > 0
        direction_ok = (de_ratio > 0) == (net_debt > 0) or (
            de_ratio == 0 and net_debt <= 0
        )
        _check(
            "Debt/equity direction vs net debt",
            direction_ok,
            f"D/E={de_ratio}, net_debt={net_debt}" if not direction_ok else "",
        )
    else:
        checks_passed += 1  # Cannot check; neutral pass

    total = checks_passed + checks_failed
    passed = checks_failed == 0
    return {
        "pass": passed,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "checks_total": total,
        "discrepancies": discrepancies,
        "details": f"{checks_passed}/{total} checks passed",
    }


# ---------------------------------------------------------------------------
# Gate 7 — Chinese Language Check
# ---------------------------------------------------------------------------


def gate_chinese_language(report_dir: str) -> dict:
    """Verify report files contain Chinese content (not English-only)."""
    issues: list[str] = []
    checked = 0
    passed = 0

    # Common CJK Unified Ideographs range + common Chinese punctuation
    chinese_chars = set(
        "一丁七万上下不东严乖"
        "个中为主义之乐了五交"
        "产人什介从以们会但位"
        "何使依便保信元先先克"
        "关其内再写冲决准出分"
        "分分到削力功加务动动"
        "化印及可同向否和品市"
        "应开当得影怎性总情意"
        "成戴户手手技放政效数"
        "文方无时明星有本来正"
        "民治活物特理生用由白"
        "看码社神经统者能自艰"
        "要見见边运送通道重问"
        "限阶需面风验验验高"
    )

    for fname in sorted(os.listdir(report_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(report_dir, fname)
        try:
            with open(fpath) as fh:
                content = fh.read()
        except OSError:
            continue

        checked += 1
        # Check if content has meaningful Chinese characters (>10 chars)
        zh_count = sum(1 for ch in content if "一" <= ch <= "鿿")
        if zh_count > 10:
            passed += 1
        else:
            issues.append(
                f"{fname}: appears to lack Chinese content ({zh_count} CJK chars)"
            )

    passed_gate = checked == 0 or len(issues) == 0
    return {
        "pass": passed_gate,
        "files_checked": checked,
        "files_passed": passed,
        "issues": issues,
        "details": (
            f"{passed}/{checked} report files contain Chinese content"
            if checked
            else "No markdown report files found"
        ),
    }


# ---------------------------------------------------------------------------
# Gate 8 — Stock Price Display
# ---------------------------------------------------------------------------


def gate_stock_price_display(report_dir: str) -> dict:
    """Verify company tables include 当前股价 column."""
    issues: list[str] = []
    checked = 0
    passed = 0

    price_keywords = {"当前股价", "current price", "当前价格"}

    for fname in sorted(os.listdir(report_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(report_dir, fname)
        try:
            with open(fpath) as fh:
                content = fh.read()
        except OSError:
            continue

        # Only check files that have tables with stock tickers
        has_ticker_table = any(
            kw in content for kw in ["| 001 |", "| 002 |", "推荐标的排名"]
        )
        if not has_ticker_table:
            continue

        checked += 1
        if any(kw in content for kw in price_keywords):
            passed += 1
        else:
            issues.append(f"{fname}: stock ranking table missing 当前股价 column")

    passed_gate = checked == 0 or len(issues) == 0
    return {
        "pass": passed_gate,
        "files_checked": checked,
        "files_passed": passed,
        "issues": issues,
        "details": (
            f"{passed}/{checked} ranking tables include 当前股价"
            if checked
            else "No ranking tables found"
        ),
    }


# ---------------------------------------------------------------------------
# Confidence level
# ---------------------------------------------------------------------------


def gate_moat_decision_table(report_dir: str, report_type: str) -> dict:
    """Verify the 4-Moat Decision Table is present in equity reports.

    Long: full table + counterfactual + anti-pattern + peer-pair required.
    Mid:  condensed table required (4 moat rows + S/M/W ratings).
    Short: snapshot table required (4 moat rows + S/M/W ratings).
    """
    issues: list[str] = []
    warnings: list[str] = []
    checked = 0
    passed = 0

    # File pattern: NNN-[TICKER]_[long|mid|short]_[DATE].md
    target_suffix = f"_{report_type}_"

    moat_rows = ["网络效应", "转换成本", "规模优势", "无形资产"]
    rating_tokens = ["Strong", "Moderate", "Weak", "S/M/W"]
    counterfactual_keywords = [
        "100 亿",
        "$10B",
        "$100亿",
        "10 亿美元",
        "反事实",
        "counterfactual",
    ]
    anti_pattern_keywords = [
        "先发",
        "first-mover",
        "增长 ≠ 护城河",
        "Growth ≠ moat",
        "growth ≠ moat",
        "反例",
    ]
    peer_pair_keywords = ["同业护城河对比", "Peer-Pair", "peer pair", "peer-pair"]

    for fname in sorted(os.listdir(report_dir)):
        if not fname.endswith(".md"):
            continue
        if target_suffix not in fname:
            continue
        # Skip stage summaries / appendix-only files
        fpath = os.path.join(report_dir, fname)
        try:
            with open(fpath) as fh:
                content = fh.read()
        except OSError:
            continue

        checked += 1

        # Required for ALL horizons: 4 moat rows + at least one S/M/W rating token
        missing_rows = [r for r in moat_rows if r not in content]
        if missing_rows:
            issues.append(
                f"{fname}: 4-Moat Decision Table missing rows: {missing_rows}"
            )
            continue
        if not any(t in content for t in rating_tokens):
            issues.append(
                f"{fname}: 4-Moat Decision Table found but no S/M/W rating tokens (Strong/Moderate/Weak)"
            )
            continue

        # Long-horizon: also require counterfactual + anti-pattern + peer-pair
        if report_type == "long":
            if not any(kw in content for kw in counterfactual_keywords):
                issues.append(
                    f"{fname}: long-horizon report missing $10B counterfactual section"
                )
                continue
            if not any(kw in content for kw in anti_pattern_keywords):
                issues.append(
                    f"{fname}: long-horizon report missing anti-pattern check (first-mover/growth ≠ moat)"
                )
                continue
            if not any(kw in content for kw in peer_pair_keywords):
                issues.append(
                    f"{fname}: long-horizon report missing peer-pair moat comparison"
                )
                continue

        passed += 1

    passed_gate = checked == 0 or len(issues) == 0
    return {
        "pass": passed_gate,
        "files_checked": checked,
        "files_passed": passed,
        "issues": issues,
        "warnings": warnings,
        "details": (
            f"{passed}/{checked} reports include 4-Moat Decision Table"
            if checked
            else f"No {report_type} reports found"
        ),
    }


def gate_yields_causality(report_dir: str) -> dict:
    """Pitfall 2: yields don't cause equity moves.

    Lints prose for sentences of the form 'X happened because [yields/dollar/oil]
    moved'. Flags as warnings; does NOT block. Suggested rewrite: 'X and yields
    both moved because the market revised [growth/inflation/policy] expectations.'
    """
    import re

    bad_patterns = [
        # English
        r"because\s+(?:bond\s+)?yields\s+(?:moved|rose|fell|hit|crossed|spiked)",
        r"because\s+(?:the\s+)?(?:dollar|DXY)\s+(?:moved|rose|fell|strengthened|weakened)",
        r"because\s+oil\s+(?:moved|rose|fell|spiked)",
        r"due\s+to\s+(?:the\s+)?(?:rise|fall|spike)\s+in\s+(?:bond\s+)?yields",
        # Chinese
        r"因为(?:债券|国债)?收益率",
        r"由于(?:美元|油价)上涨",
    ]

    issues: list[str] = []
    files_checked = 0
    if not os.path.isdir(report_dir):
        return {
            "pass": True,
            "files_checked": 0,
            "issues": [],
            "details": "report_dir not found; skipping",
        }
    for fname in sorted(os.listdir(report_dir)):
        if not fname.endswith(".md"):
            continue
        files_checked += 1
        try:
            with open(os.path.join(report_dir, fname)) as fh:
                content = fh.read()
        except OSError:
            continue
        for pat in bad_patterns:
            for match in re.finditer(pat, content, re.IGNORECASE):
                # Capture surrounding context
                start = max(0, match.start() - 40)
                end = min(len(content), match.end() + 40)
                snippet = content[start:end].replace("\n", " ")
                issues.append(
                    f"{fname}: weak causality — '{snippet}'. Rewrite: both moved due to upstream macro driver (pitfall 2)."
                )

    return {
        "pass": len(issues) == 0,
        "files_checked": files_checked,
        "issues": issues,
        "details": (
            f"Linted {files_checked} markdown files for yield-causality fallacy. "
            f"{len(issues)} suspect phrases."
        ),
        "methodology": (
            "Pitfall 2: 'X happened because yields moved Y' is the rooster-crowing-at-sunrise "
            "fallacy. See references/pitfalls/02-yields-not-causal.md"
        ),
    }


def gate_three_axis_check(report_dir: str, report_type: str) -> dict:
    """Pitfall 4 + 5: short-term reports require Direction × Vega × Asymmetry check.

    Inspects scores.json for `conviction_count_directional`. If asymmetry rule is
    active (count >= 4), the short-term report MUST contain a counterfactual P/L
    matrix and explicit banned-structures section.
    """
    if report_type != "short":
        return {
            "pass": True,
            "applicable": False,
            "details": "Three-axis check applies only to short-term reports",
        }

    issues: list[str] = []
    scores_path = os.path.join(report_dir, "scores.json")
    scores = _load_json(scores_path) or {}
    ccd = scores.get("conviction_count_directional", {})

    if not ccd:
        return {
            "pass": True,
            "applicable": True,
            "issues": [
                "scores.json missing conviction_count_directional — cannot verify asymmetry"
            ],
            "details": "Asymmetry-rule check skipped (no scores)",
        }

    if not ccd.get("asymmetry_rule_active"):
        return {
            "pass": True,
            "applicable": True,
            "asymmetry_rule_active": False,
            "details": (
                f"Conviction count: bull={ccd.get('bull_conviction_count')}, "
                f"bear={ccd.get('bear_conviction_count')}; asymmetry rule inactive"
            ),
        }

    direction = ccd.get("high_conviction_directional")
    banned = ccd.get("banned_structures", [])

    # Look for required artifacts in the short-term report markdown
    needed_keywords_en = ["P/L matrix", "+35%", "banned"]
    needed_keywords_zh = ["反事实损益", "禁用结构", "+35%"]

    short_md_files = [
        f for f in os.listdir(report_dir) if f.endswith(".md") and "short" in f.lower()
    ]
    if not short_md_files:
        issues.append(
            "Short-term report markdown not found — cannot verify 3-axis section"
        )
    else:
        for fname in short_md_files:
            with open(os.path.join(report_dir, fname)) as fh:
                content = fh.read()
            has_pl_matrix = any(kw in content for kw in needed_keywords_en) or any(
                kw in content for kw in needed_keywords_zh
            )
            mentions_banned = any(b in content for b in banned[:3]) if banned else False
            if not has_pl_matrix:
                issues.append(
                    f"{fname}: asymmetry-rule active ({direction}, count>=4) but counterfactual P/L matrix missing (pitfall 5)"
                )
            if not mentions_banned:
                issues.append(
                    f"{fname}: banned structures ({', '.join(banned[:3])}) not enumerated in report (pitfall 5)"
                )

    return {
        "pass": len(issues) == 0,
        "applicable": True,
        "asymmetry_rule_active": True,
        "direction": direction,
        "banned_structures": banned,
        "issues": issues,
        "methodology": (
            "Pitfall 4+5: short-term reports must show direction × vega × asymmetry "
            "and counterfactual P/L matrix when conviction count >= 4. "
            "See references/pitfalls/05-capped-upside-vs-conviction.md"
        ),
    }


def gate_trade_signals(report_dir: str, report_type: str) -> dict:
    """Gate 10: mid/short-term reports MUST include trade signals section.

    Checks that the report contains:
    - Active signal IDs (B1-B6, S1-S6)
    - Net direction (BUY/SELL/HOLD)
    - Stop-loss and target levels
    - Invalidation condition
    """
    if report_type == "long":
        return {
            "pass": True,
            "applicable": False,
            "details": "Trade signals gate applies only to mid/short-term reports",
        }

    issues: list[str] = []
    checked = 0
    passed_files = 0

    target_suffix = f"_{report_type}_"
    signal_id_pattern = re.compile(r"\b[BS][1-6]\b")
    direction_keywords = [
        "BUY",
        "SELL",
        "HOLD",
        "CONFLICTING",
        "建仓",
        "加仓",
        "持有",
        "减仓",
        "清仓",
        "观望",
    ]
    level_keywords = [
        "止损",
        "stop.loss",
        "stop_loss",
        "目标",
        "target",
        "失效",
        "invalidat",
    ]
    section_keywords = ["交易信号", "trade signal", "Trade Signal"]

    for fname in sorted(os.listdir(report_dir)):
        if not fname.endswith(".md"):
            continue
        if target_suffix not in fname:
            continue
        fpath = os.path.join(report_dir, fname)
        try:
            with open(fpath) as fh:
                content = fh.read()
        except OSError:
            continue

        checked += 1

        # Check for trade signals section header
        has_section = any(kw in content for kw in section_keywords)
        if not has_section:
            issues.append(f"{fname}: missing '交易信号' / 'Trade Signals' section")
            continue

        # Check for signal IDs (B1-B6, S1-S6)
        has_signal_ids = bool(signal_id_pattern.search(content))
        if not has_signal_ids:
            # Also accept "无明确买卖信号" as valid (no signal = explicitly stated)
            if "无明确" not in content and "no clear signal" not in content.lower():
                issues.append(
                    f"{fname}: trade signals section lacks signal IDs (B1-B6/S1-S6) "
                    f"or explicit '无明确买卖信号' statement"
                )
                continue

        # Check for direction keywords
        has_direction = any(kw in content for kw in direction_keywords)
        if not has_direction:
            issues.append(f"{fname}: trade signals section missing action direction")
            continue

        # Check for price levels (stop-loss, target, invalidation)
        has_levels = any(re.search(kw, content, re.IGNORECASE) for kw in level_keywords)
        if not has_levels:
            issues.append(
                f"{fname}: trade signals section missing key levels "
                f"(止损/stop-loss, 目标/target, or 失效/invalidation)"
            )
            continue

        passed_files += 1

    passed_gate = checked == 0 or len(issues) == 0
    return {
        "pass": passed_gate,
        "applicable": True,
        "files_checked": checked,
        "files_passed": passed_files,
        "issues": issues,
        "details": (
            f"{passed_files}/{checked} {report_type} reports include valid trade signals"
            if checked
            else f"No {report_type} reports found"
        ),
    }


def gate_framework_diversity(report_dir: str) -> dict:
    """Pitfall 12: every report must cite >=2 frameworks + acknowledge >=1 divergence."""
    framework_keywords = [
        # English
        "Buffett",
        "Munger",
        "Graham",
        "Mauboussin",
        "Lynch",
        "Fisher",
        "ARK",
        "Dalio",
        "Soros",
        "Druckenmiller",
        "Marks",
        "Greenblatt",
        "Burry",
        "Taleb",
        "Damodaran",
        # Chinese transliteration / common usage
        "巴菲特",
        "芒格",
        "格雷厄姆",
        "莫布森",
        "彼得林奇",
        "费雪",
        "方舟",
        "达里奥",
        "索罗斯",
        "德鲁肯米勒",
        "马克斯",
        "格林布拉特",
        "伯里",
        "塔勒布",
        "达莫达兰",
    ]
    divergence_keywords = ["divergence", "diverge", "tension", "分歧", "不一致", "矛盾"]

    issues: list[str] = []
    files_checked = 0
    if not os.path.isdir(report_dir):
        return {
            "pass": True,
            "files_checked": 0,
            "issues": [],
            "details": "report_dir not found; skipping",
        }
    for fname in sorted(os.listdir(report_dir)):
        if not fname.endswith(".md"):
            continue
        # Only check the per-horizon report files
        if not any(h in fname.lower() for h in ("long", "mid", "short")):
            continue
        files_checked += 1
        try:
            with open(os.path.join(report_dir, fname)) as fh:
                content = fh.read()
        except OSError:
            continue
        cited = {kw for kw in framework_keywords if kw in content}
        if len(cited) < 2:
            issues.append(
                f"{fname}: only {len(cited)} framework(s) cited ({', '.join(sorted(cited)) or 'none'}); pitfall 12 requires >=2"
            )
        has_divergence = any(kw in content for kw in divergence_keywords)
        if not has_divergence:
            issues.append(f"{fname}: no acknowledged framework divergence (pitfall 12)")

    return {
        "pass": len(issues) == 0,
        "files_checked": files_checked,
        "issues": issues,
        "methodology": (
            "Pitfall 12: every report must cite >=2 analytical frameworks AND "
            "acknowledge >=1 divergence. See references/pitfalls/12-single-framework-anchoring.md"
        ),
    }


# ---------------------------------------------------------------------------
# Spot-Check Mode — Data Point Extraction & Verification
# ---------------------------------------------------------------------------

_FINANCIAL_PATTERNS: list[tuple[str, str]] = [
    # Currency amounts: $123.45, ¥123.45
    (r"\$[\d,]+(?:\.\d{1,2})?", "USD"),
    (r"¥[\d,]+(?:\.\d{1,2})?", "CNY"),
    # Chinese units: 123.4亿, 1234万
    (r"[\d,]+(?:\.\d+)?亿(?:元|美元|港元)?", "亿"),
    (r"[\d,]+(?:\.\d+)?万(?:亿)?(?:元|美元)?", "万"),
    # Percentages: 12.3%, -5.2%
    (r"-?[\d]+(?:\.\d+)?%", "pct"),
    # Multiples: 12.3x, 25倍
    (r"[\d]+(?:\.\d+)?x\b", "multiple"),
    (r"[\d]+(?:\.\d+)?倍", "multiple_cn"),
    # Scores: 7.5/10, 8/10
    (r"[\d]+(?:\.\d+)?/10", "score"),
]


def _extract_data_points(content: str) -> list[dict]:
    """Extract all financial data points from markdown report content."""
    data_points: list[dict] = []

    for pattern, unit_type in _FINANCIAL_PATTERNS:
        for match in re.finditer(pattern, content):
            text = match.group(0)
            start = match.start()

            # Extract numeric value
            numeric_str = text.replace("$", "").replace("¥", "").replace(",", "")
            numeric_str = (
                numeric_str.replace("亿元", "")
                .replace("亿美元", "")
                .replace("亿港元", "")
            )
            numeric_str = (
                numeric_str.replace("亿", "").replace("万亿", "").replace("万", "")
            )
            numeric_str = (
                numeric_str.replace("%", "").replace("x", "").replace("倍", "")
            )
            numeric_str = numeric_str.replace("/10", "")

            try:
                value = float(numeric_str)
            except ValueError:
                continue

            # Get surrounding context (±50 chars)
            ctx_start = max(0, start - 50)
            ctx_end = min(len(content), match.end() + 50)
            context = content[ctx_start:ctx_end].replace("\n", " ").strip()

            data_points.append(
                {
                    "text": text,
                    "value": value,
                    "unit": unit_type,
                    "context": context,
                    "position": start,
                }
            )

    return data_points


def _guess_source_file(context: str, unit_type: str) -> tuple[str, str]:
    """Guess which stage JSON file and field path a data point came from."""
    context_lower = context.lower()

    # Mapping of context keywords to likely source files
    mappings: list[tuple[list[str], str, str]] = [
        (["营收", "revenue", "收入"], "raw-data.json", "income_statement.revenue"),
        (
            ["净利", "net income", "利润"],
            "raw-data.json",
            "income_statement.net_income",
        ),
        (["毛利率", "gross margin"], "metrics.json", "ratios.gross_margin"),
        (["pe", "市盈率", "p/e"], "metrics.json", "ratios.pe_ratio"),
        (["pb", "市净率", "p/b"], "metrics.json", "ratios.pb_ratio"),
        (["roe", "净资产收益"], "metrics.json", "ratios.roe"),
        (["fcf", "自由现金流"], "metrics.json", "ratios.fcf_yield"),
        (["市值", "market cap"], "raw-data.json", "market_cap"),
        (["rsi", "macd", "技术"], "tech.json", "indicators"),
        (["评分", "score", "得分", "/10"], "scores.json", "conviction.score"),
        (["增长", "cagr", "growth"], "metrics.json", "ratios.revenue_cagr_5yr"),
        (["debt", "负债", "leverage"], "metrics.json", "ratios.debt_to_equity"),
        (["sentiment", "情绪"], "sentiment.json", "sentiment_score"),
    ]

    for keywords, source_file, field_path in mappings:
        if any(kw in context_lower for kw in keywords):
            return source_file, field_path

    # Default guess based on unit type
    if unit_type == "score":
        return "scores.json", "component_score"
    if unit_type == "pct":
        return "metrics.json", "ratios.unknown_pct"
    return "raw-data.json", "unknown"


def _cross_reference_value(
    report_dir: str,
    source_file: str,
    field_path: str,
    expected_value: float,
    unit_type: str,
) -> dict:
    """Cross-reference a data point against source JSON files.

    Returns verification result with pass/fail based on 1% tolerance.
    """
    json_path = os.path.join(report_dir, source_file)
    if not os.path.exists(json_path):
        return {
            "status": "source_not_found",
            "source_file": source_file,
            "verified": None,
        }

    data = _load_json(json_path)
    if data is None:
        return {
            "status": "source_unreadable",
            "source_file": source_file,
            "verified": None,
        }

    # Navigate the field path
    parts = field_path.split(".")
    current: object = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return {
                "status": "field_not_found",
                "source_file": source_file,
                "field_path": field_path,
                "verified": None,
            }

    # Extract actual value from source
    actual_value: float | None = None
    if isinstance(current, (int, float)):
        actual_value = float(current)
    elif isinstance(current, list) and current:
        entry = current[0]
        if isinstance(entry, dict) and "value" in entry:
            actual_value = float(entry["value"])
        elif isinstance(entry, (int, float)):
            actual_value = float(entry)
    elif isinstance(current, dict) and "value" in current:
        actual_value = float(current["value"])

    if actual_value is None:
        return {
            "status": "value_not_numeric",
            "source_file": source_file,
            "field_path": field_path,
            "raw_value": str(current)[:100],
            "verified": None,
        }

    # Compare with 1% tolerance
    if actual_value == 0 and expected_value == 0:
        deviation_pct = 0.0
    elif actual_value == 0:
        deviation_pct = 100.0
    else:
        deviation_pct = abs(expected_value - actual_value) / abs(actual_value) * 100

    passed = deviation_pct <= 1.0

    return {
        "status": "verified",
        "source_file": source_file,
        "field_path": field_path,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "deviation_pct": round(deviation_pct, 4),
        "tolerance_pct": 1.0,
        "verified": passed,
    }


def spot_check_report(report_dir: str, report_file: str | None = None) -> dict:
    """Perform data spot-check on a generated report.

    Extracts financial numbers, samples a subset, and cross-references
    against source JSON files.

    Args:
        report_dir: Path to report directory.
        report_file: Specific .md file to check (if None, checks all .md files).

    Returns:
        dict with sampled data points, verification results, and overall verdict.
    """
    now = datetime.now(timezone.utc)

    # Find report markdown files
    if report_file:
        md_files = [report_file]
    else:
        md_files = [
            f
            for f in sorted(os.listdir(report_dir))
            if f.endswith(".md")
            and any(h in f.lower() for h in ("long", "mid", "short"))
        ]

    if not md_files:
        return {
            "mode": "spot-check",
            "error": "No report markdown files found",
            "pass": False,
        }

    # Extract data points from all report files
    all_data_points: list[dict] = []
    for fname in md_files:
        fpath = os.path.join(report_dir, fname)
        try:
            with open(fpath) as fh:
                content = fh.read()
        except OSError:
            continue

        points = _extract_data_points(content)
        for p in points:
            p["source_report"] = fname
        all_data_points.extend(points)

    if not all_data_points:
        return {
            "mode": "spot-check",
            "error": "No financial data points found in reports",
            "total_extracted": 0,
            "pass": False,
        }

    # Sample 15% (min 5, max 20)
    sample_size = max(5, min(20, int(len(all_data_points) * 0.15)))
    sample_size = min(sample_size, len(all_data_points))
    sampled = random.sample(all_data_points, sample_size)

    # Cross-reference each sampled point
    verifications: list[dict] = []
    verified_count = 0
    failed_count = 0
    skipped_count = 0

    for point in sampled:
        source_file, field_path = _guess_source_file(point["context"], point["unit"])
        point["source_file"] = source_file
        point["field_path"] = field_path

        xref = _cross_reference_value(
            report_dir=report_dir,
            source_file=source_file,
            field_path=field_path,
            expected_value=point["value"],
            unit_type=point["unit"],
        )

        entry = {
            "text": point["text"],
            "value": point["value"],
            "unit": point["unit"],
            "context": point["context"],
            "source_file": source_file,
            "field_path": field_path,
            "verification": xref,
        }
        verifications.append(entry)

        if xref["verified"] is True:
            verified_count += 1
        elif xref["verified"] is False:
            failed_count += 1
        else:
            skipped_count += 1

    # Overall verdict: pass only if no checkable point failed
    checkable = verified_count + failed_count
    passed = failed_count == 0

    return {
        "mode": "spot-check",
        "report_dir": report_dir,
        "validation_timestamp": now.isoformat(),
        "total_data_points_extracted": len(all_data_points),
        "sample_size": sample_size,
        "sample_pct": round(sample_size / len(all_data_points) * 100, 1),
        "data_points": verifications,
        "summary": {
            "verified_pass": verified_count,
            "verified_fail": failed_count,
            "skipped_no_source": skipped_count,
            "checkable_total": checkable,
        },
        "pass": passed,
        "verdict": (
            f"PASS — {verified_count}/{checkable} checked data points within 1% tolerance"
            if passed
            else f"FAIL — {failed_count}/{checkable} data points deviate >1% from source"
        ),
    }


# ---------------------------------------------------------------------------
# Confidence level
# ---------------------------------------------------------------------------


def _derive_confidence(gates: dict, report_type: str) -> str:
    """Heuristic: High if all pass, Medium if only optional fail, Low otherwise."""
    blocking_keys = {"data_freshness", "source_coverage", "conviction_consistency"}
    all_pass = all(g.get("pass", False) for g in gates.values())
    blocking_pass = all(gates[k].get("pass", False) for k in blocking_keys)

    if all_pass:
        return "High"
    if blocking_pass:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate stock analysis report against pre-delivery quality gates.",
    )
    parser.add_argument(
        "--mode",
        choices=["validate", "spot-check"],
        default="validate",
        help="Mode: 'validate' (default quality gates) or 'spot-check' (data point verification)",
    )
    parser.add_argument(
        "report_dir",
        help="Path to report directory, e.g. ./reports/AAPL/",
    )
    parser.add_argument(
        "--report-type",
        choices=["short", "mid", "long"],
        default=None,
        help="Analysis horizon: short (<7d data), mid (<30d), long (<90d). Required for validate mode.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: any gate failure causes overall_pass=false",
    )
    parser.add_argument(
        "--output",
        help="Write JSON result to this file instead of stdout",
    )
    args = parser.parse_args()

    # Route to spot-check mode
    if args.mode == "spot-check":
        report_dir = os.path.abspath(args.report_dir)
        if not os.path.isdir(report_dir):
            print(
                json.dumps({"error": f"Directory not found: {report_dir}"}, indent=2),
                file=sys.stderr,
            )
            sys.exit(1)
        result = spot_check_report(report_dir)
        output = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as fh:
                fh.write(output)
        else:
            print(output)
        sys.exit(0 if result.get("pass", False) else 1)

    report_dir = os.path.abspath(args.report_dir)
    if not os.path.isdir(report_dir):
        print(
            json.dumps({"error": f"Directory not found: {report_dir}"}, indent=2),
            file=sys.stderr,
        )
        sys.exit(1)

    # --report-type is required for validate mode
    if args.report_type is None:
        parser.error("--report-type is required for validate mode")

    ticker = os.path.basename(report_dir)
    now = datetime.now(timezone.utc)

    # Run all gates
    freshness = gate_data_freshness(report_dir, args.report_type, now)
    coverage = gate_source_coverage(report_dir, args.report_type)
    conviction = gate_conviction_consistency(report_dir)
    forensic = gate_forensic_checks(report_dir)
    kill_switch = gate_kill_switch(report_dir, conviction.get("rating"))
    fact_check = gate_fact_check(report_dir)
    chinese = gate_chinese_language(report_dir)
    stock_price = gate_stock_price_display(report_dir)
    moat_table = gate_moat_decision_table(report_dir, args.report_type)
    yields_causality = gate_yields_causality(report_dir)
    three_axis = gate_three_axis_check(report_dir, args.report_type)
    framework_diversity = gate_framework_diversity(report_dir)
    trade_signals = gate_trade_signals(report_dir, args.report_type)

    gates = {
        "data_freshness": freshness,
        "source_coverage": coverage,
        "conviction_consistency": conviction,
        "forensic_checks": forensic,
        "kill_switch": kill_switch,
        "fact_check": fact_check,
        "chinese_language": chinese,
        "stock_price_display": stock_price,
        "moat_decision_table": moat_table,
        "yields_causality": yields_causality,
        "three_axis_check": three_axis,
        "framework_diversity": framework_diversity,
        "trade_signals": trade_signals,
    }

    # Determine overall pass
    blocking_gates = {
        "data_freshness",
        "source_coverage",
        "conviction_consistency",
    }
    if args.strict:
        overall_pass = all(g["pass"] for g in gates.values())
    else:
        overall_pass = all(gates[k]["pass"] for k in blocking_gates)

    # Collect issues
    blocking_issues: list[str] = []
    warnings: list[str] = []
    for name, gate in gates.items():
        for issue in gate.get("issues", []):
            if name in blocking_gates or args.strict:
                blocking_issues.append(f"[{name}] {issue}")
            else:
                warnings.append(f"[{name}] {issue}")

    confidence = _derive_confidence(gates, args.report_type)

    result = {
        "ticker": ticker,
        "report_type": args.report_type,
        "validation_timestamp": now.isoformat(),
        "strict_mode": args.strict,
        "overall_pass": overall_pass,
        "gates": gates,
        "confidence_level": confidence,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "methodology": (
            "Pre-delivery quality gates per CLAUDE.md analysis philosophy. "
            "Blocking gates: data_freshness, source_coverage, conviction_consistency. "
            "Non-blocking (warn only unless --strict): forensic_checks, kill_switch, "
            "fact_check, chinese_language, stock_price_display, yields_causality "
            "(pitfall 2), three_axis_check (pitfalls 4+5; short-term only), "
            "framework_diversity (pitfall 12)."
        ),
    }

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(output)
        print(f"Validation written to {args.output}", file=sys.stderr)
    else:
        print(output)

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
