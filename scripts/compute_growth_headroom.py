#!/usr/bin/env python3
"""Growth Headroom Score — measures upside potential vs "fully developed" status.

Aggregates 7 dimensions into a unified 1-10 score:
  1. TAM Runway (20%): from compute_tam_adj_peg.py — penetration + TAM CAGR
  2. Growth Gap (15%): from compute_bayesian_growth.py — intrinsic vs market-implied CAGR
  3. Inflection Signal (10%): from detect_growth_inflection.py — revenue acceleration 2nd derivative
  4. Phase Quality (10%): from classify_uptrend_phase.py — uptrend phase + momentum
  5. Valuation Attractiveness (15%): from calculate_metrics.py — PEG + FCF yield + reverse DCF
  6. Money Flow Confirmation (5%): from compute_money_flow.py — institutional demand
  7. Overheating Penalty (25%): HIGHEST WEIGHT — penalizes stocks that already rallied
     60-170% and are likely near a top. Prevents "buying at the mountain top."
     Signals: rally from 52w low, distance from 200MA/50MA, range position.

Interpretation:
  9-10  MASSIVE_HEADROOM  — newly inflecting, underpriced growth, NOT overheated
  7-8   HIGH_HEADROOM     — accelerating fundamentals, decent valuation, moderate rally
  5-6   MODERATE_HEADROOM — steady growth, fairly valued, some run-up
  3-4   LIMITED_HEADROOM  — slowing/cyclical OR already rallied 60%+, pullback likely
  1-2   CAPPED            — stagnating OR extreme rally (100%+), buying at the top

Usage:
    compute_growth_headroom.py TICKER [--data-dir ./reports/RUN_ID/] [--output headroom.json]
    compute_growth_headroom.py raw-data.json [--output headroom.json]

The script reads from pre-computed stage outputs if --data-dir is provided,
otherwise computes sub-scores from raw-data.json directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def safe_div(a, b):
    try:
        if b in (None, 0) or a is None:
            return None
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


def clamp(val, lo=1.0, hi=10.0):
    if val is None:
        return None
    return max(lo, min(hi, val))


# ─── Dimension 1: TAM Runway Score ───────────────────────────────────────────


def compute_tam_runway(raw: dict) -> tuple[float | None, dict]:
    """Assess how much growth runway remains (TAM penetration vs TAM growth)."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}
    annual = company.get("annual", {}) or {}

    revenue = info.get("totalRevenue") or info.get("revenue")
    market_cap = info.get("marketCap") or info.get("market_cap")

    # Revenue growth as proxy for TAM growth if no explicit TAM data
    rev_growth = info.get("revenueGrowth")
    if rev_growth is None:
        ann_rev = annual.get("revenue") or []
        if len(ann_rev) >= 2:
            try:
                latest = (
                    float(ann_rev[-1])
                    if not isinstance(ann_rev[-1], dict)
                    else float(ann_rev[-1].get("value", 0))
                )
                prior = (
                    float(ann_rev[-2])
                    if not isinstance(ann_rev[-2], dict)
                    else float(ann_rev[-2].get("value", 0))
                )
                if prior > 0:
                    rev_growth = (latest - prior) / prior
            except (ValueError, TypeError):
                pass

    # Scoring heuristics for TAM runway
    # Higher revenue growth + smaller market cap relative to industry = more runway
    score = 5.0  # default mid
    evidence = {}

    if rev_growth is not None:
        evidence["revenue_growth"] = round(rev_growth, 4)
        if rev_growth > 0.30:
            score += 2.0
        elif rev_growth > 0.15:
            score += 1.0
        elif rev_growth < 0.03:
            score -= 2.0
        elif rev_growth < 0.08:
            score -= 1.0

    # Market cap as penetration proxy (smaller = more runway)
    if market_cap is not None:
        evidence["market_cap_B"] = round(market_cap / 1e9, 2)
        if market_cap < 5e9:
            score += 1.5  # small cap = early stage
        elif market_cap < 20e9:
            score += 0.5
        elif market_cap > 100e9:
            score -= 1.5  # large cap = likely mature
        elif market_cap > 50e9:
            score -= 0.5

    return clamp(score), evidence


# ─── Dimension 2: Growth Gap ─────────────────────────────────────────────────


def compute_growth_gap(raw: dict) -> tuple[float | None, dict]:
    """Compare intrinsic growth potential to what market prices in."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}

    # Earnings growth (forward) vs what P/E implies
    earnings_growth = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    forward_pe = info.get("forwardPE") or info.get("forward_pe")
    trailing_pe = info.get("trailingPE") or info.get("pe_ratio")

    # Type safety: yfinance sometimes returns 'Infinity' as string
    def safe_num(v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                v = float(v)
            except (ValueError, OverflowError):
                return None
        if isinstance(v, (int, float)) and v != float("inf") and v != float("-inf"):
            return float(v)
        return None

    earnings_growth = safe_num(earnings_growth)
    forward_pe = safe_num(forward_pe)
    trailing_pe = safe_num(trailing_pe)

    evidence = {}
    score = 5.0

    if earnings_growth is not None:
        evidence["earnings_growth"] = round(earnings_growth, 4)

    pe = forward_pe or trailing_pe
    if pe is not None and pe > 0:
        evidence["pe_ratio"] = round(pe, 2)
        # Implied growth = PE / market_average_PE * baseline_growth
        # Simplified: PEG < 1 = underpriced growth
        if earnings_growth and earnings_growth > 0:
            peg = pe / (earnings_growth * 100)
            evidence["peg"] = round(peg, 2)
            if peg < 0.5:
                score += 3.0  # massively underpriced
            elif peg < 0.8:
                score += 2.0
            elif peg < 1.0:
                score += 1.0
            elif peg > 2.5:
                score -= 2.5  # overpriced growth
            elif peg > 1.5:
                score -= 1.0
        elif pe > 40:
            score -= 1.5  # high PE with no growth = capped
        elif pe < 15 and (earnings_growth is None or earnings_growth > 0):
            score += 1.0  # cheap

    return clamp(score), evidence


# ─── Dimension 3: Inflection Signal ──────────────────────────────────────────


def compute_inflection(raw: dict) -> tuple[float | None, dict]:
    """Detect revenue acceleration / deceleration signals."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    quarterly = company.get("quarterly", {}) or {}
    annual = company.get("annual", {}) or {}

    evidence = {}
    score = 5.0

    # Revenue acceleration (2nd derivative): compare recent growth to prior growth
    rev_series = quarterly.get("revenue") or annual.get("revenue") or []
    if len(rev_series) >= 4:
        try:
            vals = []
            for x in rev_series[-4:]:
                v = float(x) if not isinstance(x, dict) else float(x.get("value", 0))
                vals.append(v)

            if len(vals) == 4 and vals[0] > 0 and vals[1] > 0 and vals[2] > 0:
                g1 = (vals[2] - vals[0]) / vals[0]  # first half growth
                g2 = (vals[3] - vals[1]) / vals[1]  # second half growth
                acceleration = g2 - g1
                evidence["revenue_acceleration"] = round(acceleration, 4)

                if acceleration > 0.10:
                    score += 3.0  # strong acceleration
                elif acceleration > 0.03:
                    score += 1.5
                elif acceleration < -0.10:
                    score -= 3.0  # strong deceleration
                elif acceleration < -0.03:
                    score -= 1.5
        except (ValueError, TypeError):
            pass

    # Margin expansion signal
    info = company.get("info", {}) or {}
    gross_margin = info.get("grossMargins") or info.get("gross_margin")
    if gross_margin is not None:
        evidence["gross_margin"] = round(gross_margin, 4)
        if gross_margin > 0.60:
            score += 0.5
        elif gross_margin < 0.20:
            score -= 0.5

    return clamp(score), evidence


# ─── Dimension 4: Phase Quality ──────────────────────────────────────────────


def compute_phase(raw: dict) -> tuple[float | None, dict]:
    """Score based on uptrend phase and momentum indicators."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}

    evidence = {}
    score = 5.0

    # 52-week range position as phase proxy
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    fifty_two_high = info.get("fiftyTwoWeekHigh")
    fifty_two_low = info.get("fiftyTwoWeekLow")

    if (
        current_price
        and fifty_two_high
        and fifty_two_low
        and fifty_two_high > fifty_two_low
    ):
        range_position = (current_price - fifty_two_low) / (
            fifty_two_high - fifty_two_low
        )
        evidence["52w_range_position"] = round(range_position, 3)

        # Sweet spot: 0.4-0.7 (advancing but not overextended)
        if 0.4 <= range_position <= 0.7:
            score += 1.5  # healthy uptrend
        elif range_position < 0.2:
            score += 0.5  # bottoming (opportunity but risky)
        elif range_position > 0.9:
            score -= 2.0  # near high, limited near-term upside

    # 50-day vs 200-day MA relationship (golden/death cross proxy)
    fifty_ma = info.get("fiftyDayAverage")
    two_hundred_ma = info.get("twoHundredDayAverage")
    if fifty_ma and two_hundred_ma and two_hundred_ma > 0:
        ma_ratio = fifty_ma / two_hundred_ma
        evidence["50ma_vs_200ma"] = round(ma_ratio, 3)
        if ma_ratio > 1.05:
            score += 1.0  # above 200ma, golden cross territory
        elif ma_ratio < 0.95:
            score -= 1.5  # death cross territory

    return clamp(score), evidence


# ─── Dimension 5: Valuation Attractiveness ───────────────────────────────────


def compute_valuation(raw: dict) -> tuple[float | None, dict]:
    """Score valuation headroom (margin of safety)."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}

    evidence = {}
    score = 5.0

    # FCF yield (FCF / market_cap)
    fcf = info.get("freeCashflow") or info.get("free_cash_flow")
    market_cap = info.get("marketCap") or info.get("market_cap")
    if fcf and market_cap and market_cap > 0:
        fcf_yield = fcf / market_cap
        evidence["fcf_yield"] = round(fcf_yield, 4)
        if fcf_yield > 0.06:
            score += 2.0  # very attractive
        elif fcf_yield > 0.03:
            score += 1.0
        elif fcf_yield < 0:
            score -= 1.5  # negative FCF
        elif fcf_yield < 0.01:
            score -= 0.5

    # EV/EBITDA
    ev = info.get("enterpriseValue") or info.get("enterprise_value")
    ebitda = info.get("ebitda")
    if ev and ebitda and ebitda > 0:
        ev_ebitda = ev / ebitda
        evidence["ev_ebitda"] = round(ev_ebitda, 2)
        if ev_ebitda < 10:
            score += 1.5
        elif ev_ebitda < 15:
            score += 0.5
        elif ev_ebitda > 40:
            score -= 2.0
        elif ev_ebitda > 25:
            score -= 1.0

    # Price to Book
    pb = info.get("priceToBook") or info.get("price_to_book")
    if pb is not None:
        evidence["price_to_book"] = round(pb, 2)
        if pb < 2:
            score += 0.5
        elif pb > 15:
            score -= 0.5

    return clamp(score), evidence


# ─── Dimension 6: Money Flow Confirmation ────────────────────────────────────


def compute_flow(raw: dict) -> tuple[float | None, dict]:
    """Score institutional demand / supply dynamics."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}

    evidence = {}
    score = 5.0

    # Institutional holders percentage
    inst_pct = info.get("heldPercentInstitutions")
    if inst_pct is not None:
        evidence["institutional_pct"] = round(inst_pct, 4)
        # Sweet spot: 30-70% (growing institutional interest)
        if 0.30 <= inst_pct <= 0.70:
            score += 1.0
        elif inst_pct > 0.90:
            score -= 1.0  # fully owned, limited new buyers

    # Short interest as contrarian signal
    short_ratio = info.get("shortRatio")
    if short_ratio is not None:
        evidence["short_ratio"] = round(short_ratio, 2)
        if short_ratio > 5:
            score += 0.5  # short squeeze potential
        elif short_ratio < 1:
            score -= 0.3

    # Volume trend (average vs recent)
    avg_vol = info.get("averageVolume")
    avg_vol_10d = info.get("averageVolume10days") or info.get("averageDailyVolume10Day")
    if avg_vol and avg_vol_10d and avg_vol > 0:
        vol_ratio = avg_vol_10d / avg_vol
        evidence["volume_10d_vs_avg"] = round(vol_ratio, 2)
        if vol_ratio > 1.5:
            score += 1.5  # surging volume = institutional accumulation
        elif vol_ratio > 1.2:
            score += 0.5
        elif vol_ratio < 0.7:
            score -= 1.0  # dying volume

    return clamp(score), evidence


# ─── Dimension 7: Overheating Penalty ────────────────────────────────────────


def compute_overheating(raw: dict) -> tuple[float | None, dict]:
    """Penalize stocks that have already run up excessively (buying at the top).

    Key insight: a stock that's up 60-170% in 3 months has LIMITED remaining
    upside and HIGH pullback probability. Even if fundamentals are good,
    the risk/reward is skewed negative at this entry point.

    Signals:
    - Price vs 52-week low: if current > 2x low → overheated
    - Price vs 200-day MA: if current > 1.4x 200MA → extended
    - Price vs 50-day MA: if current > 1.15x 50MA → near-term stretched
    """
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"
    company = raw.get(ticker, {})
    info = company.get("info", {}) or {}

    evidence = {}
    score = 7.0  # start above average (not overheated = positive)

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    fifty_two_low = info.get("fiftyTwoWeekLow")
    fifty_two_high = info.get("fiftyTwoWeekHigh")
    fifty_ma = info.get("fiftyDayAverage")
    two_hundred_ma = info.get("twoHundredDayAverage")

    # Signal 1: Price rally from 52-week low (strongest overheating signal)
    if current_price and fifty_two_low and fifty_two_low > 0:
        rally_from_low = (current_price - fifty_two_low) / fifty_two_low
        evidence["rally_from_52w_low"] = round(rally_from_low, 3)

        if rally_from_low > 1.5:
            score -= 5.0  # up 150%+ from low → extreme overheating
        elif rally_from_low > 1.0:
            score -= 3.5  # up 100%+ → severe
        elif rally_from_low > 0.6:
            score -= 2.0  # up 60%+ → moderate overheating
        elif rally_from_low > 0.3:
            score -= 0.5  # up 30%+ → mild
        elif rally_from_low < 0.1:
            score += 1.0  # near 52w low → contrarian opportunity

    # Signal 2: Distance from 200-day MA (mean reversion pressure)
    if current_price and two_hundred_ma and two_hundred_ma > 0:
        dist_200ma = (current_price - two_hundred_ma) / two_hundred_ma
        evidence["dist_from_200ma"] = round(dist_200ma, 3)

        if dist_200ma > 0.5:
            score -= 2.0  # 50%+ above 200MA → extreme
        elif dist_200ma > 0.3:
            score -= 1.0  # 30%+ above → stretched
        elif dist_200ma > 0.15:
            score -= 0.5
        elif dist_200ma < -0.1:
            score += 1.0  # below 200MA → room to revert up

    # Signal 3: Distance from 50-day MA (short-term overextension)
    if current_price and fifty_ma and fifty_ma > 0:
        dist_50ma = (current_price - fifty_ma) / fifty_ma
        evidence["dist_from_50ma"] = round(dist_50ma, 3)

        if dist_50ma > 0.2:
            score -= 1.5  # 20%+ above 50MA → short-term top
        elif dist_50ma > 0.1:
            score -= 0.5
        elif dist_50ma < -0.05:
            score += 0.5  # below 50MA → pullback entry

    # Signal 4: 52-week range position extreme (near all-time high)
    if (
        current_price
        and fifty_two_high
        and fifty_two_low
        and fifty_two_high > fifty_two_low
    ):
        range_pct = (current_price - fifty_two_low) / (fifty_two_high - fifty_two_low)
        evidence["52w_range_pct"] = round(range_pct, 3)
        if range_pct > 0.95:
            score -= 1.0  # at the very top of range

    return clamp(score), evidence


WEIGHTS = {
    "tam_runway": 0.20,
    "growth_gap": 0.15,
    "inflection": 0.10,
    "phase": 0.10,
    "valuation": 0.15,
    "money_flow": 0.05,
    "overheating": 0.25,  # HIGHEST weight — buying at the top is the #1 failure mode
}


def compute_headroom(raw: dict) -> dict:
    """Compute the composite Growth Headroom score."""
    ticker = list(raw.keys())[0] if raw else "UNKNOWN"

    tam_score, tam_ev = compute_tam_runway(raw)
    gap_score, gap_ev = compute_growth_gap(raw)
    infl_score, infl_ev = compute_inflection(raw)
    phase_score, phase_ev = compute_phase(raw)
    val_score, val_ev = compute_valuation(raw)
    flow_score, flow_ev = compute_flow(raw)
    heat_score, heat_ev = compute_overheating(raw)

    dimensions = {
        "tam_runway": {
            "score": tam_score,
            "weight": WEIGHTS["tam_runway"],
            "evidence": tam_ev,
        },
        "growth_gap": {
            "score": gap_score,
            "weight": WEIGHTS["growth_gap"],
            "evidence": gap_ev,
        },
        "inflection": {
            "score": infl_score,
            "weight": WEIGHTS["inflection"],
            "evidence": infl_ev,
        },
        "phase": {
            "score": phase_score,
            "weight": WEIGHTS["phase"],
            "evidence": phase_ev,
        },
        "valuation": {
            "score": val_score,
            "weight": WEIGHTS["valuation"],
            "evidence": val_ev,
        },
        "money_flow": {
            "score": flow_score,
            "weight": WEIGHTS["money_flow"],
            "evidence": flow_ev,
        },
        "overheating": {
            "score": heat_score,
            "weight": WEIGHTS["overheating"],
            "evidence": heat_ev,
        },
    }

    # Weighted average (skip None dimensions)
    total_weight = 0.0
    weighted_sum = 0.0
    for dim, data in dimensions.items():
        if data["score"] is not None:
            weighted_sum += data["score"] * data["weight"]
            total_weight += data["weight"]

    composite = round(weighted_sum / total_weight, 2) if total_weight > 0 else None

    # Category classification
    if composite is None:
        category = "INSUFFICIENT_DATA"
    elif composite >= 9:
        category = "MASSIVE_HEADROOM"
    elif composite >= 7:
        category = "HIGH_HEADROOM"
    elif composite >= 5:
        category = "MODERATE_HEADROOM"
    elif composite >= 3:
        category = "LIMITED_HEADROOM"
    else:
        category = "CAPPED"

    # Chinese labels for reports
    category_zh = {
        "MASSIVE_HEADROOM": "极高成长潜力",
        "HIGH_HEADROOM": "高成长潜力",
        "MODERATE_HEADROOM": "中等空间",
        "LIMITED_HEADROOM": "空间有限",
        "CAPPED": "已涨到位",
        "INSUFFICIENT_DATA": "数据不足",
    }

    return {
        "ticker": ticker,
        "headroom_score": composite,
        "headroom_category": category,
        "headroom_category_zh": category_zh.get(category, "未知"),
        "dimensions": dimensions,
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ─── Pre-computed Data Path ──────────────────────────────────────────────────


def load_precomputed(data_dir: str, ticker: str) -> dict | None:
    """If sub-score JSONs already exist in data_dir, load and aggregate them."""
    # Look for outputs from prior scripts
    tam_path = os.path.join(data_dir, f"{ticker}_tam_adj_peg.json")
    bayesian_path = os.path.join(data_dir, f"{ticker}_bayesian_growth.json")
    inflection_path = os.path.join(data_dir, f"{ticker}_growth_inflection.json")
    phase_path = os.path.join(data_dir, f"{ticker}_uptrend_phase.json")
    money_flow_path = os.path.join(data_dir, f"{ticker}_money_flow.json")

    # Only use precomputed path if at least one file exists
    found_any = False
    result = {"ticker": ticker}
    dimensions = {}

    if os.path.isfile(tam_path):
        found_any = True
        with open(tam_path) as f:
            data = json.load(f)
        tam_runway_score = data.get("tam_runway_score", 1.0)
        # Normalize 0.5-2.0 range to 1-10
        normalized = clamp((tam_runway_score - 0.5) / 1.5 * 9 + 1)
        dimensions["tam_runway"] = {
            "score": round(normalized, 2),
            "weight": WEIGHTS["tam_runway"],
            "source": tam_path,
        }

    if os.path.isfile(bayesian_path):
        found_any = True
        with open(bayesian_path) as f:
            data = json.load(f)
        gap = data.get("intrinsic_minus_implied", 0)
        # Normalize: -20 to +20 pp → 1-10
        normalized = clamp((gap + 20) / 40 * 9 + 1)
        dimensions["growth_gap"] = {
            "score": round(normalized, 2),
            "weight": WEIGHTS["growth_gap"],
            "source": bayesian_path,
        }

    if os.path.isfile(inflection_path):
        found_any = True
        with open(inflection_path) as f:
            data = json.load(f)
        composite = data.get("inflection_composite", 0)
        # Normalize: -10 to +10 → 1-10
        normalized = clamp((composite + 10) / 20 * 9 + 1)
        dimensions["inflection"] = {
            "score": round(normalized, 2),
            "weight": WEIGHTS["inflection"],
            "source": inflection_path,
        }

    if os.path.isfile(phase_path):
        found_any = True
        with open(phase_path) as f:
            data = json.load(f)
        phase = data.get("phase", "")
        momentum = data.get("momentum_score", 5)
        phase_map = {
            "ACCELERATING": 9,
            "STEADY": 7,
            "OSCILLATING": 5,
            "BOTTOMING": 6,
            "DECLINING": 2,
        }
        base = phase_map.get(phase, 5)
        # Blend phase type with momentum score
        normalized = clamp(base * 0.6 + momentum * 0.4)
        dimensions["phase"] = {
            "score": round(normalized, 2),
            "weight": WEIGHTS["phase"],
            "source": phase_path,
        }

    if os.path.isfile(money_flow_path):
        found_any = True
        with open(money_flow_path) as f:
            data = json.load(f)
        flow_composite = data.get("composite_score", 5)
        # Already 0-10, just clamp
        dimensions["money_flow"] = {
            "score": clamp(flow_composite),
            "weight": WEIGHTS["money_flow"],
            "source": money_flow_path,
        }

    if not found_any:
        return None

    # Compute weighted average from available precomputed dimensions
    total_weight = sum(d["weight"] for d in dimensions.values())
    weighted_sum = sum(d["score"] * d["weight"] for d in dimensions.values())
    composite = round(weighted_sum / total_weight, 2) if total_weight > 0 else None

    if composite is None:
        category = "INSUFFICIENT_DATA"
    elif composite >= 9:
        category = "MASSIVE_HEADROOM"
    elif composite >= 7:
        category = "HIGH_HEADROOM"
    elif composite >= 5:
        category = "MODERATE_HEADROOM"
    elif composite >= 3:
        category = "LIMITED_HEADROOM"
    else:
        category = "CAPPED"

    category_zh = {
        "MASSIVE_HEADROOM": "极高成长潜力",
        "HIGH_HEADROOM": "高成长潜力",
        "MODERATE_HEADROOM": "中等空间",
        "LIMITED_HEADROOM": "空间有限",
        "CAPPED": "已涨到位",
        "INSUFFICIENT_DATA": "数据不足",
    }

    return {
        "ticker": ticker,
        "headroom_score": composite,
        "headroom_category": category,
        "headroom_category_zh": category_zh.get(category, "未知"),
        "dimensions": dimensions,
        "precomputed": True,
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Compute Growth Headroom Score (1-10)")
    parser.add_argument("input", help="raw-data.json file OR ticker symbol")
    parser.add_argument(
        "--data-dir", help="Directory with pre-computed sub-score JSONs"
    )
    parser.add_argument("--output", "-o", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    result = None

    # Try precomputed path first
    if args.data_dir:
        ticker = args.input.upper().replace(".JSON", "").split("/")[-1].split("_")[0]
        result = load_precomputed(args.data_dir, ticker)

    # Fall back to computing from raw-data.json
    if result is None:
        input_path = args.input
        if not os.path.isfile(input_path):
            # Maybe it's a ticker — look for common raw-data patterns
            candidates = [
                f"{input_path.lower()}_raw-data.json",
                "raw-data.json",
                os.path.join(
                    args.data_dir or ".", f"{input_path.upper()}", "raw-data.json"
                ),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    input_path = c
                    break
            else:
                print(
                    json.dumps(
                        {
                            "error": f"Cannot find data for {args.input}",
                            "headroom_score": None,
                            "headroom_category": "INSUFFICIENT_DATA",
                        }
                    )
                )
                sys.exit(1)

        with open(input_path) as f:
            raw = json.load(f)

        result = compute_headroom(raw)

    # Output
    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Written to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
