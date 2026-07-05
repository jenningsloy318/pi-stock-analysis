#!/usr/bin/env python3
"""Activist Investor Exposure & Governance Catalyst Analysis.

Usage:
    fetch_activist_exposure.py AAPL
    fetch_activist_exposure.py AAPL --output ./reports/AAPL/activist_exposure.json
    fetch_activist_exposure.py MSFT --output ./reports/MSFT/activist_exposure.json

Tracks activist investor presence, insider transaction patterns, and
governance vulnerability for a given stock.

Analysis dimensions:
  1. Activist Detection         — cross-reference holders against known activist fund list
  2. Activist Presence Score    — 0-10 composite score
  3. Governance Vulnerability   — insider concentration, board independence proxy, selling signals
  4. Proxy Fight Probability    — heuristic (activist ownership + governance weakness + underperformance)
  5. Insider Activity Patterns  — net buying/selling over 3/6/12 months, cluster detection
  6. Institutional Concentration — top-5/10 ownership, passive vs active ratio

Primary source: yfinance (Yahoo Finance).
Missing data: returned as null with explanatory note — never fabricated.

Deterministic calculations only. No LLM involvement in math.
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Known activist fund registry
# ---------------------------------------------------------------------------

KNOWN_ACTIVISTS: dict[str, list[str]] = {
    "Elliott Management": ["Elliott Investment Management", "Elliott Associates", "Elliott Management"],
    "Icahn Enterprises": ["Icahn Capital", "Carl Icahn", "Icahn Enterprises"],
    "Third Point": ["Third Point LLC", "Daniel Loeb", "Third Point"],
    "Pershing Square": ["Pershing Square Capital", "Bill Ackman", "Pershing Square"],
    "Trian Partners": ["Trian Fund Management", "Nelson Peltz", "Trian Partners"],
    "Starboard Value": ["Starboard Value LP", "Starboard Value"],
    "ValueAct Capital": ["ValueAct Holdings", "ValueAct Capital"],
    "Jana Partners": ["JANA Partners LLC", "JANA Partners"],
    "Engaged Capital": ["Engaged Capital LLC", "Engaged Capital"],
    "Legion Partners": ["Legion Partners Asset Management", "Legion Partners"],
    "Ancora Holdings": ["Ancora Advisors", "Ancora Holdings"],
    "Engine No. 1": ["Engine No. 1 LLC", "Engine No. 1"],
}

# Passive / index fund name fragments (used for passive vs active ratio)
PASSIVE_FUND_FRAGMENTS: list[str] = [
    "Vanguard", "BlackRock", "State Street", "SSGA", "iShares",
    "Fidelity Index", "Schwab", "Dimensional", "Northern Trust",
    "BNY Mellon Index", "TIAA", "Invesco QQQ",
]


# ---------------------------------------------------------------------------
# Arithmetic utilities
# ---------------------------------------------------------------------------

def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pct(value: float | None, places: int = 2) -> float | None:
    if value is None:
        return None
    return round(value * 100, places)


def _round(value: float | None, places: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, places)


# ---------------------------------------------------------------------------
# 1. Holder data retrieval
# ---------------------------------------------------------------------------

def fetch_holders(ticker_obj: Any) -> dict:
    """Fetch institutional, mutual fund, and insider holder tables from yfinance."""
    result: dict[str, Any] = {
        "institutional": [],
        "mutual_fund": [],
        "insider_transactions": [],
        "warnings": [],
    }

    # Institutional holders (top 20)
    try:
        inst = ticker_obj.institutional_holders
        if inst is not None and PANDAS_AVAILABLE and not inst.empty:
            for _, row in inst.head(20).iterrows():
                entry: dict[str, Any] = {}
                for col in inst.columns:
                    val = row[col]
                    if pd.isna(val) if PANDAS_AVAILABLE else val is None:
                        entry[str(col)] = None
                    elif hasattr(val, "item"):
                        entry[str(col)] = val.item()
                    else:
                        entry[str(col)] = val
                result["institutional"].append(entry)
        else:
            result["warnings"].append("Institutional holder data unavailable from yfinance")
    except Exception as exc:
        result["warnings"].append(f"Institutional holders fetch error: {exc}")

    # Mutual fund holders
    try:
        mf = ticker_obj.mutualfund_holders
        if mf is not None and PANDAS_AVAILABLE and not mf.empty:
            for _, row in mf.head(20).iterrows():
                entry = {}
                for col in mf.columns:
                    val = row[col]
                    if pd.isna(val) if PANDAS_AVAILABLE else val is None:
                        entry[str(col)] = None
                    elif hasattr(val, "item"):
                        entry[str(col)] = val.item()
                    else:
                        entry[str(col)] = val
                result["mutual_fund"].append(entry)
        else:
            result["warnings"].append("Mutual fund holder data unavailable from yfinance")
    except Exception as exc:
        result["warnings"].append(f"Mutual fund holders fetch error: {exc}")

    # Insider transactions (last 12 months)
    try:
        ins = ticker_obj.insider_transactions
        if ins is not None and PANDAS_AVAILABLE and not ins.empty:
            cutoff = datetime.now(timezone.utc) - timedelta(days=365)
            for _, row in ins.iterrows():
                tx: dict[str, Any] = {}
                for col in ins.columns:
                    val = row[col]
                    if pd.isna(val) if PANDAS_AVAILABLE else val is None:
                        tx[str(col)] = None
                    elif hasattr(val, "isoformat"):
                        tx[str(col)] = val.isoformat()
                    elif hasattr(val, "item"):
                        tx[str(col)] = val.item()
                    else:
                        tx[str(col)] = val

                # Normalise date for filtering
                raw_date = tx.get("Start Date") or tx.get("startDate") or tx.get("date")
                if raw_date:
                    try:
                        dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt >= cutoff:
                            result["insider_transactions"].append(tx)
                    except ValueError:
                        result["insider_transactions"].append(tx)
                else:
                    result["insider_transactions"].append(tx)
        else:
            result["warnings"].append("Insider transaction data unavailable from yfinance")
    except Exception as exc:
        result["warnings"].append(f"Insider transactions fetch error: {exc}")

    return result


# ---------------------------------------------------------------------------
# 2. Activist detection
# ---------------------------------------------------------------------------

def detect_activists(
    institutional: list[dict],
    mutual_fund: list[dict],
) -> dict:
    """Cross-reference holder names against KNOWN_ACTIVISTS registry.

    Returns detected activists with their holder record and matched fund name.
    """
    detected: list[dict] = []
    total_activist_shares: float = 0.0

    all_holders = institutional + mutual_fund

    for holder in all_holders:
        holder_name: str = (
            holder.get("Holder") or holder.get("holder") or holder.get("Name") or ""
        )
        if not holder_name:
            continue
        holder_name_lower = holder_name.lower()

        for canonical, aliases in KNOWN_ACTIVISTS.items():
            matched = any(alias.lower() in holder_name_lower for alias in aliases)
            if matched:
                # Extract shares held
                raw_shares = (
                    holder.get("Shares") or holder.get("shares") or
                    holder.get("Value") or 0
                )
                shares_float: float = float(raw_shares) if raw_shares else 0.0
                pct_held = (
                    holder.get("% Out") or holder.get("pctHeld") or
                    holder.get("pct_held") or 0
                )
                pct_float: float = float(pct_held) if pct_held else 0.0

                detected.append({
                    "canonical_name": canonical,
                    "reported_holder_name": holder_name,
                    "shares_held": int(shares_float),
                    "pct_outstanding": _pct(pct_float / 100 if pct_float > 1 else pct_float),
                    "source": "institutional" if holder in institutional else "mutual_fund",
                })
                total_activist_shares += shares_float
                break  # one match per holder row is sufficient

    return {
        "activists_detected": detected,
        "activist_count": len(detected),
        "total_activist_shares": int(total_activist_shares),
    }


# ---------------------------------------------------------------------------
# 3. Activist presence score (0-10)
# ---------------------------------------------------------------------------

def compute_activist_presence_score(
    detected: list[dict],
    activist_ownership_pct: float | None,
    governance_vulnerability: float | None,
) -> dict:
    """Score activist presence on a 0-10 scale.

    Scoring bands:
      0      — No activist detected
      1-3    — Activist present but small stake (<1%)
      4-6    — Activist with meaningful stake (1-5%)
      7-9    — Activist with significant stake (>5%) or multiple activists
      10     — Active campaign signals (multiple large activists + weak governance)
    """
    score: float = 0.0
    rationale: list[str] = []

    if not detected:
        rationale.append("No known activist investors detected in top-20 holder list")
        return {"score": 0.0, "rationale": rationale}

    n_activists = len(detected)
    pct = activist_ownership_pct or 0.0

    # Base score from ownership level
    if pct >= 10.0:
        score += 7.0
        rationale.append(f"Activist ownership {pct:.1f}% — very large stake")
    elif pct >= 5.0:
        score += 5.0
        rationale.append(f"Activist ownership {pct:.1f}% — significant stake")
    elif pct >= 2.0:
        score += 3.5
        rationale.append(f"Activist ownership {pct:.1f}% — meaningful stake")
    elif pct >= 1.0:
        score += 2.0
        rationale.append(f"Activist ownership {pct:.1f}% — minor stake")
    elif pct > 0.0:
        score += 1.0
        rationale.append(f"Activist ownership {pct:.1f}% — small monitoring position")
    else:
        score += 0.5
        rationale.append("Activist detected but ownership % unavailable")

    # Multiple activists add pressure
    if n_activists >= 3:
        score += 2.0
        rationale.append(f"{n_activists} distinct activist funds present")
    elif n_activists == 2:
        score += 1.0
        rationale.append("2 activist funds present")

    # Governance weakness amplifier
    if governance_vulnerability is not None and governance_vulnerability >= 6.0:
        score = min(10.0, score + 1.5)
        rationale.append(f"Governance vulnerability score {governance_vulnerability:.1f}/10 amplifies risk")

    score = min(10.0, round(score, 1))
    return {"score": score, "rationale": rationale}


# ---------------------------------------------------------------------------
# 4. Governance vulnerability score (0-10)
# ---------------------------------------------------------------------------

def compute_governance_vulnerability(
    info: dict,
    insider_transactions: list[dict],
    now: datetime,
) -> dict:
    """Score governance vulnerability 0-10 based on structural and behavioural signals.

    Components:
      a) Insider ownership concentration (high concentration = lower vulnerability)
      b) Board independence proxy (from yfinance auditRisk + boardRisk)
      c) Recent insider selling pressure (last 6 months)
    """
    score: float = 0.0
    evidence: list[str] = []

    # a) Insider ownership concentration
    insider_pct = info.get("heldPercentInsiders")
    if insider_pct is not None:
        if insider_pct < 0.02:
            score += 3.0
            evidence.append(f"Very low insider ownership ({_pct(insider_pct):.1f}%) — activist entry easy")
        elif insider_pct < 0.05:
            score += 2.0
            evidence.append(f"Low insider ownership ({_pct(insider_pct):.1f}%)")
        elif insider_pct < 0.15:
            score += 1.0
            evidence.append(f"Moderate insider ownership ({_pct(insider_pct):.1f}%)")
        else:
            evidence.append(f"High insider ownership ({_pct(insider_pct):.1f}%) — natural defence against activists")
    else:
        score += 1.5
        evidence.append("Insider ownership data unavailable — partial penalty applied")

    # b) Board independence proxy (yfinance governance risk scores 1-10; lower = better governance)
    audit_risk = info.get("auditRisk")
    board_risk = info.get("boardRisk")
    gov_avg: float | None = None
    if audit_risk is not None and board_risk is not None:
        gov_avg = (float(audit_risk) + float(board_risk)) / 2.0
    elif audit_risk is not None:
        gov_avg = float(audit_risk)
    elif board_risk is not None:
        gov_avg = float(board_risk)

    if gov_avg is not None:
        # yfinance risk scores run 1-10 (10 = highest risk)
        # Map to our 0-4 sub-score band
        board_sub = _round(gov_avg / 10.0 * 4.0, 1)
        score += board_sub
        evidence.append(f"Board/audit risk score {gov_avg:.1f}/10 → governance sub-score {board_sub:.1f}/4")
    else:
        score += 2.0
        evidence.append("Board/audit risk data unavailable — partial penalty applied")

    # c) Recent insider selling pressure (last 6 months)
    sell_value_6m = _net_insider_value(insider_transactions, now, months=6)
    if sell_value_6m is not None and sell_value_6m < -1_000_000:
        pressure = min(3.0, abs(sell_value_6m) / 50_000_000 * 3.0)
        score += pressure
        evidence.append(
            f"Net insider selling of ${abs(sell_value_6m):,.0f} in last 6 months "
            f"→ governance sub-score +{pressure:.1f}"
        )
    elif sell_value_6m is None:
        evidence.append("Insider selling pressure: data unavailable")
    else:
        evidence.append(f"No significant insider selling in last 6 months (net ${sell_value_6m:,.0f})")

    final = min(10.0, round(score, 1))
    return {
        "score": final,
        "interpretation": (
            "High" if final >= 7.0 else "Moderate" if final >= 4.0 else "Low"
        ),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# 5. Proxy fight probability heuristic
# ---------------------------------------------------------------------------

def compute_proxy_fight_probability(
    activist_presence_score: float,
    governance_vulnerability_score: float,
    stock_1yr_return: float | None,
) -> str:
    """Heuristic proxy fight probability — Low | Moderate | High.

    Model: weighted index of activist pressure + governance weakness + underperformance.
    All three inputs increase probability; any single factor alone rarely triggers a fight.
    """
    index = 0.0

    # Activist presence (weight 0.45)
    index += activist_presence_score / 10.0 * 0.45

    # Governance vulnerability (weight 0.35)
    index += governance_vulnerability_score / 10.0 * 0.35

    # Stock underperformance vs S&P 500 rough proxy (weight 0.20)
    if stock_1yr_return is not None:
        # Rough SPX 1-year baseline: ~10% annual. Penalise underperformance.
        spx_baseline = 0.10
        underperformance = max(0.0, spx_baseline - stock_1yr_return)
        perf_score = min(1.0, underperformance / 0.30)  # cap at 30% underperformance
        index += perf_score * 0.20
    # If return unavailable, no bonus or penalty

    if index >= 0.55:
        return "High"
    if index >= 0.30:
        return "Moderate"
    return "Low"


# ---------------------------------------------------------------------------
# 6. Insider transaction analysis
# ---------------------------------------------------------------------------

def _parse_tx_date(tx: dict) -> datetime | None:
    """Extract and normalise transaction date from a yfinance insider row."""
    raw = (
        tx.get("Start Date") or tx.get("startDate") or
        tx.get("Date") or tx.get("date")
    )
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _parse_tx_value(tx: dict) -> float | None:
    """Extract transaction value (shares * price) from a yfinance insider row."""
    # yfinance columns vary; try common field names
    value = tx.get("Value") or tx.get("value") or tx.get("transactionValue")
    if value is not None:
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            pass

    shares = tx.get("Shares") or tx.get("shares")
    price = tx.get("Price") or tx.get("price") or tx.get("startPrice")
    if shares is not None and price is not None:
        try:
            return float(str(shares).replace(",", "")) * float(str(price).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return None


def _is_purchase(tx: dict) -> bool:
    """Return True if the transaction is a buy (purchase)."""
    tx_type = (
        tx.get("Transaction") or tx.get("transaction") or
        tx.get("transactionText") or tx.get("type") or ""
    )
    return "purchase" in str(tx_type).lower() or "buy" in str(tx_type).lower()


def _is_sale(tx: dict) -> bool:
    """Return True if the transaction is a sell."""
    tx_type = (
        tx.get("Transaction") or tx.get("transaction") or
        tx.get("transactionText") or tx.get("type") or ""
    )
    return "sale" in str(tx_type).lower() or "sell" in str(tx_type).lower()


def _net_insider_value(
    transactions: list[dict],
    now: datetime,
    months: int,
) -> float | None:
    """Compute net insider buy/sell value (buys positive, sells negative) over window."""
    cutoff = now - timedelta(days=months * 30)
    net = 0.0
    has_data = False

    for tx in transactions:
        dt = _parse_tx_date(tx)
        if dt is None or dt < cutoff:
            continue
        val = _parse_tx_value(tx)
        if val is None:
            continue
        has_data = True
        if _is_purchase(tx):
            net += val
        elif _is_sale(tx):
            net -= val

    return net if has_data else None


def analyze_insider_activity(
    transactions: list[dict],
    now: datetime,
) -> dict:
    """Compute net buying/selling metrics, cluster detection, and confidence ratio."""
    result: dict[str, Any] = {}

    # Net insider buying for 3, 6, 12-month windows
    for months in (3, 6, 12):
        key = f"net_insider_buying_{months}m"
        val = _net_insider_value(transactions, now, months)
        result[key] = _round(val, 0)

    # Insider confidence ratio: buys / total transactions (last 12m)
    cutoff_12m = now - timedelta(days=365)
    buys = 0
    sells = 0
    for tx in transactions:
        dt = _parse_tx_date(tx)
        if dt is None or dt < cutoff_12m:
            continue
        if _is_purchase(tx):
            buys += 1
        elif _is_sale(tx):
            sells += 1

    total_tx = buys + sells
    result["insider_confidence_ratio"] = _round(_safe_div(buys, total_tx), 3) if total_tx > 0 else None

    # Cluster selling detection: 3+ distinct insiders selling within any 30-day window
    result["cluster_selling_detected"] = _detect_cluster_selling(transactions, now, window_days=30, min_sellers=3)

    # Notable transactions: top-5 by absolute value
    notable: list[dict] = []
    for tx in transactions:
        dt = _parse_tx_date(tx)
        if dt is None:
            continue
        val = _parse_tx_value(tx)
        if val is None:
            continue
        direction = "buy" if _is_purchase(tx) else "sell" if _is_sale(tx) else "other"
        insider_name = tx.get("Insider") or tx.get("insider") or tx.get("name") or "Unknown"
        notable.append({
            "date": dt.date().isoformat(),
            "insider": str(insider_name),
            "direction": direction,
            "value_usd": int(abs(val)),
        })

    # Sort by value descending, keep top 5
    notable.sort(key=lambda x: x["value_usd"], reverse=True)
    result["notable_transactions"] = notable[:5]

    return result


def _detect_cluster_selling(
    transactions: list[dict],
    now: datetime,
    window_days: int,
    min_sellers: int,
) -> bool:
    """Return True if min_sellers distinct insiders sold within any window_days period."""
    # Collect all sell events from last 12 months
    cutoff = now - timedelta(days=365)
    sell_events: list[tuple[datetime, str]] = []

    for tx in transactions:
        if not _is_sale(tx):
            continue
        dt = _parse_tx_date(tx)
        if dt is None or dt < cutoff:
            continue
        insider = tx.get("Insider") or tx.get("insider") or tx.get("name") or "unknown"
        sell_events.append((dt, str(insider)))

    if len(sell_events) < min_sellers:
        return False

    sell_events.sort(key=lambda e: e[0])

    # Sliding window check
    for i, (start_dt, _) in enumerate(sell_events):
        window_end = start_dt + timedelta(days=window_days)
        insiders_in_window = {
            name
            for dt, name in sell_events[i:]
            if dt <= window_end
        }
        if len(insiders_in_window) >= min_sellers:
            return True

    return False


# ---------------------------------------------------------------------------
# 7. Institutional concentration
# ---------------------------------------------------------------------------

def compute_institutional_concentration(
    institutional: list[dict],
    mutual_fund: list[dict],
) -> dict:
    """Compute top-5, top-10 concentration and passive vs active ratio."""

    def _pct_from_holder(h: dict) -> float:
        raw = (
            h.get("% Out") or h.get("pctHeld") or
            h.get("pct_held") or h.get("percentageHeld") or 0
        )
        pct = float(raw) if raw else 0.0
        # yfinance may return as decimal fraction (0.07) or percentage (7.0)
        return pct if pct <= 1.0 else pct / 100.0

    def _is_passive(h: dict) -> bool:
        name = h.get("Holder") or h.get("holder") or h.get("Name") or ""
        return any(frag.lower() in str(name).lower() for frag in PASSIVE_FUND_FRAGMENTS)

    all_holders = institutional + mutual_fund
    pcts = [_pct_from_holder(h) for h in all_holders]
    pcts_sorted = sorted(pcts, reverse=True)

    top5 = _pct(sum(pcts_sorted[:5]))
    top10 = _pct(sum(pcts_sorted[:10]))

    passive_pct = sum(_pct_from_holder(h) for h in all_holders if _is_passive(h))
    active_pct = sum(_pct_from_holder(h) for h in all_holders if not _is_passive(h))
    total_pct = passive_pct + active_pct

    passive_vs_active = _round(_safe_div(passive_pct, total_pct), 3)

    return {
        "top5_ownership_pct": top5,
        "top10_ownership_pct": top10,
        "passive_vs_active_ratio": passive_vs_active,
        "note": (
            "passive_vs_active_ratio = passive_pct / (passive_pct + active_pct). "
            "1.0 = fully passive; 0.0 = fully active. "
            "Based on name-matching heuristic."
        ),
    }


# ---------------------------------------------------------------------------
# 8. Stock return helper (for proxy fight probability)
# ---------------------------------------------------------------------------

def fetch_1yr_return(ticker_obj: Any, warnings: list[str]) -> float | None:
    """Fetch trailing 1-year price return for the ticker."""
    try:
        hist = ticker_obj.history(period="1y")
        if hist is None or hist.empty:
            warnings.append("1-year price history unavailable — proxy fight score will omit performance factor")
            return None
        start_price = float(hist["Close"].iloc[0])
        end_price = float(hist["Close"].iloc[-1])
        if start_price <= 0:
            return None
        return (end_price - start_price) / start_price
    except Exception as exc:
        warnings.append(f"1-year return calculation failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def fetch_activist_exposure(ticker: str) -> dict:
    """Run full activist exposure analysis for a ticker symbol."""
    warnings: list[str] = []

    if not YFINANCE_AVAILABLE:
        return {
            "ticker": ticker,
            "error": "yfinance not installed. Run: pip install yfinance",
            "warnings": [],
        }
    if not PANDAS_AVAILABLE:
        warnings.append("pandas not installed — holder parsing may be degraded. Run: pip install pandas")

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception as exc:
        return {
            "ticker": ticker,
            "error": f"Failed to fetch data for {ticker}: {exc}",
            "warnings": [],
        }

    if not info:
        warnings.append(f"Empty info returned for {ticker} — results may be incomplete")

    now = datetime.now(timezone.utc)

    # --- Holders & transactions ---
    holders = fetch_holders(stock)
    warnings.extend(holders.get("warnings", []))
    institutional = holders["institutional"]
    mutual_fund = holders["mutual_fund"]
    insider_transactions = holders["insider_transactions"]

    # --- Activist detection ---
    activist_data = detect_activists(institutional, mutual_fund)
    detected = activist_data["activists_detected"]

    # Aggregate activist ownership %
    activist_ownership_pct: float | None = None
    if detected:
        total = sum(
            d["pct_outstanding"] or 0.0
            for d in detected
            if d.get("pct_outstanding") is not None
        )
        activist_ownership_pct = round(total, 2) if total > 0 else None

    # --- Governance vulnerability ---
    gov = compute_governance_vulnerability(info, insider_transactions, now)

    # --- Activist presence score ---
    presence = compute_activist_presence_score(
        detected,
        activist_ownership_pct,
        gov["score"],
    )

    # --- 1-year return (for proxy fight probability) ---
    stock_1yr_return = fetch_1yr_return(stock, warnings)

    # --- Proxy fight probability ---
    proxy_prob = compute_proxy_fight_probability(
        presence["score"],
        gov["score"],
        stock_1yr_return,
    )

    # --- Insider activity ---
    insider_activity = analyze_insider_activity(insider_transactions, now)

    # --- Institutional concentration ---
    inst_concentration = compute_institutional_concentration(institutional, mutual_fund)

    return {
        "ticker": ticker.upper(),
        "retrieved": now.date().isoformat(),
        "activist_exposure": {
            "activists_detected": detected,
            "activist_ownership_pct": activist_ownership_pct,
            "activist_presence_score": presence["score"],
            "activist_presence_rationale": presence["rationale"],
            "proxy_fight_probability": proxy_prob,
            "governance_vulnerability": gov["score"],
            "governance_interpretation": gov["interpretation"],
            "governance_evidence": gov["evidence"],
        },
        "insider_activity": {
            "net_insider_buying_3m": insider_activity.get("net_insider_buying_3m"),
            "net_insider_buying_6m": insider_activity.get("net_insider_buying_6m"),
            "net_insider_buying_12m": insider_activity.get("net_insider_buying_12m"),
            "cluster_selling_detected": insider_activity.get("cluster_selling_detected", False),
            "insider_confidence_ratio": insider_activity.get("insider_confidence_ratio"),
            "notable_transactions": insider_activity.get("notable_transactions", []),
        },
        "institutional_concentration": inst_concentration,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Activist investor exposure and governance catalyst analysis"
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help="Stock ticker symbol (e.g. AAPL). Positional, matches other fetch scripts.",
    )
    parser.add_argument(
        "--ticker",
        dest="ticker_flag",
        help="Alternative named form of the ticker argument (kept for back-compat).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path. Default: stdout (use --output to also write a file).",
    )
    args = parser.parse_args()

    ticker_arg = args.ticker or args.ticker_flag
    if not ticker_arg:
        parser.error("ticker required (positional or --ticker)")
    ticker = ticker_arg.upper()
    results = fetch_activist_exposure(ticker)

    output = json.dumps(results, indent=2, default=str)
    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
