#!/usr/bin/env python3
"""Compute options market signals: IV surface, put/call skew, gamma exposure, term structure, max pain.

Usage:
    calculate_options.py AAPL                             # Basic options analysis
    calculate_options.py AAPL --output ./reports/[TICKER]/options.json
    calculate_options.py AAPL --expiry 2026-06-20         # Specific expiration
    calculate_options.py AAPL --mode full                 # Full analysis (slower)

Computes from yfinance options chain data:
  - Implied Volatility (IV) by strike (IV smile/skew)
  - Put/Call ratio (volume, open interest)
  - Max Pain (strike with max option buyer loss at expiry)
  - ATM IV, IV30 (30-day constant-maturity IV)
  - Put/Call skew (25-delta risk reversal)
  - Gamma exposure profile (simplified — dealer positioning proxy)
  - IV term structure (contango/backwardation across expiries)
  - Unusual options activity detection (volume/OI spike vs 20-day avg)

Free data source: yfinance (CBOE delayed options data).
Limitations: Delayed ~15 min, limited Greeks, no trade-by-trade flow.
For institutional-grade flow, a paid provider (CBOE LiveVol, ORATS) is needed.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
    import numpy as np
except ImportError:
    sys.stderr.write(
        "Error: yfinance and numpy required. Run: pip install yfinance numpy\n"
    )
    sys.exit(1)


def compute_max_pain(calls: list[dict], puts: list[dict]) -> dict:
    """Compute Max Pain — the strike price where option buyers lose the most.

    For each strike, compute total loss for call and put holders.
    Max Pain = strike where total loss is minimized.
    """
    if not calls or not puts:
        return {"error": "No options data available"}

    # Extract strikes and open interest
    call_strikes = {}
    for c in calls:
        strike = c.get("strike")
        oi = c.get("openInterest", 0) or 0
        if strike is not None and strike > 0:
            call_strikes[strike] = call_strikes.get(strike, 0) + oi

    put_strikes = {}
    for p in puts:
        strike = p.get("strike")
        oi = p.get("openInterest", 0) or 0
        if strike is not None and strike > 0:
            put_strikes[strike] = put_strikes.get(strike, 0) + oi

    all_strikes = sorted(set(list(call_strikes.keys()) + list(put_strikes.keys())))
    if not all_strikes:
        return {"error": "No valid strikes"}

    # For each potential settlement price (= each strike), compute total loss
    min_pain = float("inf")
    max_pain_strike = all_strikes[0]

    for settlement in all_strikes:
        total_loss = 0.0
        for strike, oi in call_strikes.items():
            if settlement > strike:
                total_loss += (settlement - strike) * oi * 100
        for strike, oi in put_strikes.items():
            if settlement < strike:
                total_loss += (strike - settlement) * oi * 100

        if total_loss < min_pain:
            min_pain = total_loss
            max_pain_strike = settlement

    return {
        "max_pain_strike": round(max_pain_strike, 2),
        "min_total_loss": round(min_pain, 2),
        "strike_count": len(all_strikes),
        "interpretation": f"Max Pain at ${max_pain_strike:.2f}. "
        f"Price tends to gravitate toward this level near expiration "
        f"due to dealer hedging dynamics.",
    }


def compute_put_call_ratios(calls: list[dict], puts: list[dict]) -> dict:
    """Compute put/call ratios (volume-based and OI-based)."""
    total_call_vol = sum(c.get("volume", 0) or 0 for c in calls)
    total_put_vol = sum(p.get("volume", 0) or 0 for p in puts)
    total_call_oi = sum(c.get("openInterest", 0) or 0 for c in calls)
    total_put_oi = sum(p.get("openInterest", 0) or 0 for p in puts)

    vol_ratio = total_put_vol / total_call_vol if total_call_vol > 0 else None
    oi_ratio = total_put_oi / total_call_oi if total_call_oi > 0 else None

    # Interpretation
    def interpret(ratio: float | None) -> str:
        if ratio is None:
            return "No data"
        if ratio > 1.2:
            return "Bearish (elevated put activity)"
        elif ratio > 0.8:
            return "Neutral (balanced)"
        elif ratio > 0.5:
            return "Bullish (call-skewed)"
        else:
            return "Very Bullish (heavily call-skewed — potential complacency)"

    return {
        "put_call_volume": {
            "total_call_volume": total_call_vol,
            "total_put_volume": total_put_vol,
            "ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
            "interpretation": interpret(vol_ratio),
        },
        "put_call_open_interest": {
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "ratio": round(oi_ratio, 3) if oi_ratio is not None else None,
            "interpretation": interpret(oi_ratio),
        },
    }


def compute_iv_surface(calls: list[dict], puts: list[dict], spot: float) -> dict:
    """Analyze implied volatility across strikes (IV smile/skew)."""
    # Extract IV by strike
    call_ivs = {}
    for c in calls:
        strike = c.get("strike")
        iv = c.get("impliedVolatility")
        if strike and iv and iv > 0 and iv < 5:  # IV as decimal (0.01-5.0 range)
            call_ivs[strike] = iv

    put_ivs = {}
    for p in puts:
        strike = p.get("strike")
        iv = p.get("impliedVolatility")
        if strike and iv and iv > 0 and iv < 5:
            put_ivs[strike] = iv

    # ATM IV (closest to spot)
    if call_ivs:
        atm_strike = min(call_ivs.keys(), key=lambda x: abs(x - spot))
        atm_iv = call_ivs.get(atm_strike) or put_ivs.get(atm_strike)
    else:
        atm_iv = None
        atm_strike = None

    # IV skew: 25-delta risk reversal (OTM put IV - OTM call IV)
    # Approximate: 90% moneyness put vs 110% moneyness call
    otm_put_strikes = [s for s in put_ivs if s < spot * 0.95]
    otm_call_strikes = [s for s in call_ivs if s > spot * 1.05]

    otm_put_iv = (
        np.mean([put_ivs[s] for s in otm_put_strikes]) if otm_put_strikes else None
    )
    otm_call_iv = (
        np.mean([call_ivs[s] for s in otm_call_strikes]) if otm_call_strikes else None
    )

    skew = None
    if otm_put_iv is not None and otm_call_iv is not None:
        skew = round(otm_put_iv - otm_call_iv, 4)

    # IV term structure: compare near-term vs next expiry IV
    near_term_iv = atm_iv

    return {
        "atm_strike": atm_strike,
        "atm_iv": round(atm_iv, 4) if atm_iv else None,
        "atm_iv_pct": f"{atm_iv * 100:.1f}%" if atm_iv else None,
        "iv_skew": skew,
        "iv_skew_interpretation": (
            f"Put skew: {skew * 100:.1f}% — "
            f"{'Elevated hedging demand (bearish signal)' if skew and skew > 0.05 else 'Normal skew' if skew and skew > 0.02 else 'Low skew (complacency)'}"
            if skew is not None
            else "No skew data"
        ),
        "otm_put_iv": round(otm_put_iv, 4) if otm_put_iv else None,
        "otm_call_iv": round(otm_call_iv, 4) if otm_call_iv else None,
        "methodology": "IV skew = OTM put IV - OTM call IV. Positive = puts expensive (hedging demand). "
        "Negative = calls expensive (speculative upside demand).",
    }


def detect_unusual_activity(calls: list[dict], puts: list[dict]) -> dict:
    """Detect unusual options activity: volume spikes relative to OI.

    Flags individual contracts where volume > 3x average volume or volume/OI > 1.0.
    """
    unusual = []

    for option_list, opt_type in [(calls, "CALL"), (puts, "PUT")]:
        for opt in option_list:
            volume = opt.get("volume", 0) or 0
            oi = opt.get("openInterest", 0) or 0
            strike = opt.get("strike")
            if volume > 500 and oi > 0 and volume / oi > 1.0:
                unusual.append(
                    {
                        "type": opt_type,
                        "strike": strike,
                        "volume": volume,
                        "open_interest": oi,
                        "volume_oi_ratio": round(volume / oi, 2),
                        "implied_volatility": opt.get("impliedVolatility"),
                        "signal": (
                            "Bullish flow — new positions being opened"
                            if opt_type == "CALL" and volume / oi > 2
                            else "Bearish flow — new positions being opened"
                            if opt_type == "PUT" and volume / oi > 2
                            else "Elevated volume — investigate further"
                        ),
                    }
                )

    unusual.sort(key=lambda x: x["volume_oi_ratio"], reverse=True)

    return {
        "unusual_contracts": unusual[:10],
        "total_unusual_detected": len(unusual),
        "threshold": "volume/OI > 1.0 and volume > 500",
        "note": "Unusual activity is directional but not definitive. Cross-reference with news and price action.",
    }


def compute_gamma_exposure(calls: list[dict], puts: list[dict], spot: float) -> dict:
    """Estimate net gamma exposure (GEX) by strike.

    Assumes dealers are short calls (retail buys calls) and long puts (retail buys puts).
    GEX per strike = OI × 100 × gamma_approx × spot. Positive GEX = pinning force;
    negative GEX = amplification (moves away from strike accelerate).
    """
    if not spot or spot <= 0:
        return {"error": "Cannot compute GEX without spot price"}

    gex_by_strike: dict[float, float] = {}
    total_call_gex = 0.0
    total_put_gex = 0.0

    for opt in calls:
        strike = opt.get("strike")
        oi = opt.get("openInterest", 0) or 0
        if not strike or oi == 0:
            continue
        moneyness = abs(spot - strike) / spot
        gamma_approx = max(0.01, 0.04 * (1 - min(moneyness * 5, 1.0)))
        contract_gex = oi * 100 * gamma_approx * spot
        gex_by_strike[strike] = gex_by_strike.get(strike, 0) + contract_gex
        total_call_gex += contract_gex

    for opt in puts:
        strike = opt.get("strike")
        oi = opt.get("openInterest", 0) or 0
        if not strike or oi == 0:
            continue
        moneyness = abs(spot - strike) / spot
        gamma_approx = max(0.01, 0.04 * (1 - min(moneyness * 5, 1.0)))
        contract_gex = oi * 100 * gamma_approx * spot
        gex_by_strike[strike] = gex_by_strike.get(strike, 0) - contract_gex
        total_put_gex += contract_gex

    net_gex = total_call_gex - total_put_gex

    top_strikes = sorted(gex_by_strike.items(), key=lambda x: abs(x[1]), reverse=True)[
        :5
    ]

    flip_strike = None
    sorted_strikes = sorted(gex_by_strike.items(), key=lambda x: x[0])
    for i in range(len(sorted_strikes) - 1):
        if sorted_strikes[i][1] > 0 and sorted_strikes[i + 1][1] < 0:
            flip_strike = sorted_strikes[i][0]
            break
        elif sorted_strikes[i][1] < 0 and sorted_strikes[i + 1][1] > 0:
            flip_strike = sorted_strikes[i + 1][0]
            break

    return {
        "net_gex": round(net_gex, 0),
        "gex_regime": "positive" if net_gex > 0 else "negative",
        "interpretation": (
            "Positive GEX: dealer hedging pins price, expect low volatility and mean reversion"
            if net_gex > 0
            else "Negative GEX: dealer hedging amplifies moves, expect high volatility and trending"
        ),
        "gamma_flip_strike": flip_strike,
        "top_gex_strikes": [{"strike": s, "gex": round(g, 0)} for s, g in top_strikes],
        "total_call_gex": round(total_call_gex, 0),
        "total_put_gex": round(total_put_gex, 0),
        "methodology": "Approximate GEX using moneyness-based gamma proxy. Dealers assumed short calls, long puts.",
    }


def compute_iv_term_structure(
    stock, expiries: list[str], spot: float, primary_expiry: str
) -> dict:
    """Compare ATM IV across expiration dates to detect vol term structure shape.

    Contango (normal): far-dated IV > near-dated IV — market calm.
    Backwardation: near-dated IV > far-dated IV — imminent event/stress.
    """
    if len(expiries) < 2:
        return {"error": "Need 2+ expiry dates for term structure"}

    term_points = []
    for exp in expiries[:5]:
        try:
            chain = stock.option_chain(exp)
            calls = chain.calls.to_dict("records")
            atm_strike = min(
                (c["strike"] for c in calls if c.get("strike")),
                key=lambda x: abs(x - spot),
                default=None,
            )
            if not atm_strike:
                continue
            atm_calls = [
                c
                for c in calls
                if c.get("strike") == atm_strike
                and c.get("impliedVolatility")
                and 0 < c["impliedVolatility"] < 5
            ]
            if atm_calls:
                iv = atm_calls[0]["impliedVolatility"]
                term_points.append({"expiry": exp, "atm_iv": round(iv, 4)})
        except Exception:
            continue

    if len(term_points) < 2:
        return {"error": "Insufficient term structure data"}

    near_iv = term_points[0]["atm_iv"]
    far_iv = term_points[-1]["atm_iv"]
    slope = round(far_iv - near_iv, 4)

    structure = (
        "contango" if slope > 0.01 else "backwardation" if slope < -0.01 else "flat"
    )

    return {
        "term_points": term_points,
        "structure": structure,
        "slope": slope,
        "interpretation": {
            "contango": "Normal — market expects future vol higher than near-term. No imminent stress.",
            "backwardation": "Inverted — near-term vol elevated. Likely event-driven (earnings, macro). Hedging demand concentrated short-term.",
            "flat": "Flat — no significant term structure signal.",
        }[structure],
    }


def classify_iv_regime(
    iv_surface: dict,
    iv_term_structure: dict | None,
    days_to_next_earnings: int | None,
    flow_5d_net_call_premium_usd: float | None,
) -> dict:
    """Classify elevated IV as event-driven vs demand-driven (pitfall 3).

    Event-IV (will crush hard post-print): days_to_earnings <14 OR steep front-week
    backwardation. Demand-IV (will sustain): days_to_earnings >45 + IV elevated
    proportionally + 5-day net call premium >$5M/day average.

    Returns iv_classification: 'event' | 'demand' | 'mixed' | 'unknown' with rationale.

    See: references/pitfalls/03-iv-event-vs-demand.md
    """
    rationale: list[str] = []
    classification = "unknown"

    atm_iv = iv_surface.get("atm_iv") if iv_surface else None
    iv_rank = iv_surface.get("iv_rank") if iv_surface else None

    # Determine if IV is elevated to begin with
    elevated = False
    if iv_rank is not None and iv_rank >= 50:
        elevated = True
        rationale.append(f"IVR {iv_rank:.0f} ≥50: elevated regime")
    elif atm_iv is not None and atm_iv >= 0.40:
        elevated = True
        rationale.append(f"ATM IV {atm_iv * 100:.0f}%: elevated absolute level")

    if not elevated:
        return {
            "iv_classification": "not_elevated",
            "rationale": ["IV not elevated; classification N/A"],
            "vega_default_rule": "neutral — direction dominates structure choice",
            "applies_pitfall_3": False,
        }

    # Event-driven IV signals
    event_signals = 0
    if days_to_next_earnings is not None and days_to_next_earnings <= 14:
        event_signals += 2
        rationale.append(
            f"Days to earnings {days_to_next_earnings} ≤14: event-driven default"
        )
    elif days_to_next_earnings is not None and days_to_next_earnings <= 45:
        event_signals += 1
        rationale.append(
            f"Days to earnings {days_to_next_earnings} in 14-45: mixed event premium building"
        )

    if iv_term_structure and iv_term_structure.get("structure") == "backwardation":
        slope = iv_term_structure.get("slope", 0)
        if slope is not None and slope <= -0.05:
            event_signals += 2
            rationale.append(
                f"Steep backwardation (slope {slope:+.3f}): event-driven term skew"
            )
        else:
            event_signals += 1
            rationale.append("Mild backwardation: some event premium")

    # Demand-driven IV signals
    demand_signals = 0
    if days_to_next_earnings is None or days_to_next_earnings > 45:
        demand_signals += 1
        if days_to_next_earnings is not None:
            rationale.append(
                f"Days to earnings {days_to_next_earnings} >45: no near-term event"
            )
        else:
            rationale.append("No near-term earnings catalyst identified")

    if iv_term_structure and iv_term_structure.get("structure") in ("contango", "flat"):
        demand_signals += 1
        rationale.append(
            "Term structure contango/flat: vol bid spread across expiries (demand-IV signature)"
        )

    if (
        flow_5d_net_call_premium_usd is not None
        and flow_5d_net_call_premium_usd >= 25_000_000  # ~$5M/day × 5 days
    ):
        demand_signals += 2
        rationale.append(
            f"5d net call premium ${flow_5d_net_call_premium_usd / 1e6:.1f}M ≥ $25M: sustained institutional accumulation"
        )

    # Classification
    if event_signals >= 3 and event_signals > demand_signals:
        classification = "event"
        vega_default = (
            "short premium (will crush post-event) — bull put spread / iron condor / "
            "bear call spread per direction"
        )
    elif demand_signals >= 2 and demand_signals > event_signals:
        classification = "demand"
        vega_default = (
            "INVERTED rule — long premium can still pay (vol bid sustains); "
            "if selling premium, prefer wide-strike short put / put spread; "
            "AVOID Jade Lizard / IC if directional conviction (pitfall 5)"
        )
    elif event_signals > 0 and demand_signals > 0:
        classification = "mixed"
        vega_default = (
            "mixed — partial event premium + partial demand bid; "
            "pull catalyst clock + flow data before sizing vega"
        )
    else:
        classification = "unknown"
        vega_default = "insufficient data to classify; default to short premium at high IVR with caution"

    return {
        "iv_classification": classification,
        "event_signals": event_signals,
        "demand_signals": demand_signals,
        "rationale": rationale,
        "vega_default_rule": vega_default,
        "applies_pitfall_3": True,
        "methodology": (
            "Pitfall 3 (event-IV vs demand-IV): combine catalyst clock + term structure + "
            "5-day net call premium flow. See references/pitfalls/03-iv-event-vs-demand.md"
        ),
    }


def _structure_pl_at_spot(structure: str, params: dict, future_spot: float) -> float:
    """Compute per-contract P/L of a named multi-leg structure at a future spot.

    Returns dollars per contract (× 100 shares). Negative = loss.
    Conventions: short legs collect credit at entry; long legs pay debit at entry.
    `params` keys vary by structure type.
    """
    cents_per_contract = 100.0

    def long_call_intrinsic(
        strike: float, premium_paid: float, spot_at: float
    ) -> float:
        return (max(0.0, spot_at - strike) - premium_paid) * cents_per_contract

    def long_put_intrinsic(strike: float, premium_paid: float, spot_at: float) -> float:
        return (max(0.0, strike - spot_at) - premium_paid) * cents_per_contract

    def short_call_pl(strike: float, premium_collected: float, spot_at: float) -> float:
        return (premium_collected - max(0.0, spot_at - strike)) * cents_per_contract

    def short_put_pl(strike: float, premium_collected: float, spot_at: float) -> float:
        return (premium_collected - max(0.0, strike - spot_at)) * cents_per_contract

    s = structure.lower()
    if s == "long_call":
        return long_call_intrinsic(params["strike"], params["debit"], future_spot)
    if s == "long_put":
        return long_put_intrinsic(params["strike"], params["debit"], future_spot)
    if s == "naked_short_put":
        return short_put_pl(params["strike"], params["credit"], future_spot)
    if s == "bull_put_spread":
        # short put high strike + long put low strike, net credit
        long_leg = long_put_intrinsic(
            params["long_strike"], params["long_debit"], future_spot
        )
        short_leg = short_put_pl(
            params["short_strike"], params["short_credit"], future_spot
        )
        return long_leg + short_leg
    if s == "bull_call_debit_spread":
        # long call low strike + short call high strike, net debit
        long_leg = long_call_intrinsic(
            params["long_strike"], params["long_debit"], future_spot
        )
        short_leg = short_call_pl(
            params["short_strike"], params["short_credit"], future_spot
        )
        return long_leg + short_leg
    if s == "bear_call_spread":
        long_leg = long_call_intrinsic(
            params["long_strike"], params["long_debit"], future_spot
        )
        short_leg = short_call_pl(
            params["short_strike"], params["short_credit"], future_spot
        )
        return long_leg + short_leg
    if s == "iron_condor":
        # short put + long put (lower) + short call + long call (higher)
        legs = (
            short_put_pl(
                params["short_put_strike"], params["short_put_credit"], future_spot
            )
            + long_put_intrinsic(
                params["long_put_strike"], params["long_put_debit"], future_spot
            )
            + short_call_pl(
                params["short_call_strike"], params["short_call_credit"], future_spot
            )
            + long_call_intrinsic(
                params["long_call_strike"], params["long_call_debit"], future_spot
            )
        )
        return legs
    if s == "jade_lizard":
        # short put (OTM) + bear call spread (short call lower + long call higher)
        # Designed: total credit > call spread width (no upside risk above long call)
        legs = (
            short_put_pl(
                params["short_put_strike"], params["short_put_credit"], future_spot
            )
            + short_call_pl(
                params["short_call_strike"], params["short_call_credit"], future_spot
            )
            + long_call_intrinsic(
                params["long_call_strike"], params["long_call_debit"], future_spot
            )
        )
        return legs
    if s == "risk_reversal":
        # short put + long call (typically same expiry, OTM both)
        return short_put_pl(
            params["short_put_strike"], params["short_put_credit"], future_spot
        ) + long_call_intrinsic(
            params["long_call_strike"], params["long_call_debit"], future_spot
        )
    return 0.0


def compute_pl_matrix(
    spot: float,
    direction: str,
    iv_surface: dict,
    calls: list[dict],
    puts: list[dict],
) -> dict:
    """Build counterfactual P/L matrix per pitfall 5.

    For a given directional thesis (bull|bear), build candidate structures from
    actual chain prices and compute P/L at +0/+10/+20/+35/+50% (or -, for bear).

    Reject any candidate that flat-lines or shows LOSS in the high-conviction
    scenario column when conviction count >= 4.

    See: references/pitfalls/05-capped-upside-vs-conviction.md
    """
    if direction not in ("bull", "bear"):
        return {"error": f"direction must be bull|bear, got {direction!r}"}
    if not calls or not puts:
        return {"error": "Empty option chain — cannot build P/L matrix"}

    # Build per-strike mid-price lookups
    def mid(opt: dict) -> float | None:
        bid = opt.get("bid")
        ask = opt.get("ask")
        last = opt.get("lastPrice")
        if bid and ask and bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        if last and last > 0:
            return last
        return None

    call_mids = {c["strike"]: mid(c) for c in calls if c.get("strike") and mid(c)}
    put_mids = {p["strike"]: mid(p) for p in puts if p.get("strike") and mid(p)}

    if not call_mids or not put_mids:
        return {"error": "No mid-prices available on chain"}

    # Find ATM and useful OTM strikes
    def nearest(strikes: list[float], target: float) -> float | None:
        if not strikes:
            return None
        return min(strikes, key=lambda s: abs(s - target))

    call_strikes_sorted = sorted(call_mids.keys())
    put_strikes_sorted = sorted(put_mids.keys())

    if direction == "bull":
        scenario_pcts = [0.0, 0.10, 0.20, 0.35, 0.50]
    else:
        scenario_pcts = [0.0, -0.10, -0.20, -0.35, -0.50]

    scenarios = [round(spot * (1 + p), 2) for p in scenario_pcts]
    scenario_labels = [f"{int(p * 100):+d}%" for p in scenario_pcts]

    candidates: list[dict] = []

    if direction == "bull":
        # Candidate 1: Naked short put (5% OTM)
        sp_strike = nearest(put_strikes_sorted, spot * 0.95)
        if sp_strike and put_mids.get(sp_strike):
            params = {"strike": sp_strike, "credit": put_mids[sp_strike]}
            candidates.append(
                {
                    "name": "naked_short_put",
                    "params": params,
                    "max_loss": -(sp_strike - put_mids[sp_strike]) * 100,
                    "uncapped_upside": False,
                    "asymmetry_class": "capped (credit only)",
                }
            )

        # Candidate 2: Bull put spread (5% OTM short, 10% OTM long)
        sp_short = nearest(put_strikes_sorted, spot * 0.95)
        sp_long = nearest(put_strikes_sorted, spot * 0.90)
        if (
            sp_short
            and sp_long
            and sp_short != sp_long
            and put_mids.get(sp_short)
            and put_mids.get(sp_long)
        ):
            params = {
                "short_strike": sp_short,
                "short_credit": put_mids[sp_short],
                "long_strike": sp_long,
                "long_debit": put_mids[sp_long],
            }
            candidates.append(
                {
                    "name": "bull_put_spread",
                    "params": params,
                    "asymmetry_class": "capped (credit only)",
                    "uncapped_upside": False,
                }
            )

        # Candidate 3: Long ATM call
        atm_call = nearest(call_strikes_sorted, spot)
        if atm_call and call_mids.get(atm_call):
            params = {"strike": atm_call, "debit": call_mids[atm_call]}
            candidates.append(
                {
                    "name": "long_call",
                    "params": params,
                    "asymmetry_class": "uncapped upside",
                    "uncapped_upside": True,
                }
            )

        # Candidate 4: Bull call debit spread (ATM long, 10% OTM short)
        c_long = nearest(call_strikes_sorted, spot)
        c_short = nearest(call_strikes_sorted, spot * 1.10)
        if (
            c_long
            and c_short
            and c_long != c_short
            and call_mids.get(c_long)
            and call_mids.get(c_short)
        ):
            params = {
                "long_strike": c_long,
                "long_debit": call_mids[c_long],
                "short_strike": c_short,
                "short_credit": call_mids[c_short],
            }
            candidates.append(
                {
                    "name": "bull_call_debit_spread",
                    "params": params,
                    "asymmetry_class": "capped at upper strike",
                    "uncapped_upside": False,
                }
            )

        # Candidate 5: Risk reversal (5% OTM short put + 5% OTM long call)
        rr_put = nearest(put_strikes_sorted, spot * 0.95)
        rr_call = nearest(call_strikes_sorted, spot * 1.05)
        if rr_put and rr_call and put_mids.get(rr_put) and call_mids.get(rr_call):
            params = {
                "short_put_strike": rr_put,
                "short_put_credit": put_mids[rr_put],
                "long_call_strike": rr_call,
                "long_call_debit": call_mids[rr_call],
            }
            candidates.append(
                {
                    "name": "risk_reversal",
                    "params": params,
                    "asymmetry_class": "uncapped upside",
                    "uncapped_upside": True,
                }
            )

        # Candidate 6 (FORBIDDEN demonstrator): Jade Lizard
        # short put 5% OTM + short call 5% OTM + long call 10% OTM
        jl_sp = nearest(put_strikes_sorted, spot * 0.95)
        jl_sc = nearest(call_strikes_sorted, spot * 1.05)
        jl_lc = nearest(call_strikes_sorted, spot * 1.10)
        if (
            jl_sp
            and jl_sc
            and jl_lc
            and jl_sc != jl_lc
            and put_mids.get(jl_sp)
            and call_mids.get(jl_sc)
            and call_mids.get(jl_lc)
        ):
            params = {
                "short_put_strike": jl_sp,
                "short_put_credit": put_mids[jl_sp],
                "short_call_strike": jl_sc,
                "short_call_credit": call_mids[jl_sc],
                "long_call_strike": jl_lc,
                "long_call_debit": call_mids[jl_lc],
            }
            candidates.append(
                {
                    "name": "jade_lizard",
                    "params": params,
                    "asymmetry_class": "CAPPED — bull tail loses (FORBIDDEN at conviction>=4)",
                    "uncapped_upside": False,
                    "forbidden_at_high_conviction": True,
                }
            )

        # Candidate 7 (FORBIDDEN demonstrator): Iron Condor
        ic_sp = nearest(put_strikes_sorted, spot * 0.95)
        ic_lp = nearest(put_strikes_sorted, spot * 0.90)
        ic_sc = nearest(call_strikes_sorted, spot * 1.05)
        ic_lc = nearest(call_strikes_sorted, spot * 1.10)
        if (
            all([ic_sp, ic_lp, ic_sc, ic_lc])
            and put_mids.get(ic_sp)
            and put_mids.get(ic_lp)
            and call_mids.get(ic_sc)
            and call_mids.get(ic_lc)
        ):
            params = {
                "short_put_strike": ic_sp,
                "short_put_credit": put_mids[ic_sp],
                "long_put_strike": ic_lp,
                "long_put_debit": put_mids[ic_lp],
                "short_call_strike": ic_sc,
                "short_call_credit": call_mids[ic_sc],
                "long_call_strike": ic_lc,
                "long_call_debit": call_mids[ic_lc],
            }
            candidates.append(
                {
                    "name": "iron_condor",
                    "params": params,
                    "asymmetry_class": "CAPPED both sides (FORBIDDEN at conviction>=4)",
                    "uncapped_upside": False,
                    "forbidden_at_high_conviction": True,
                }
            )
    else:
        # bear-side mirror
        # Candidate: Bear call spread (5% OTM short, 10% OTM long)
        bc_short = nearest(call_strikes_sorted, spot * 1.05)
        bc_long = nearest(call_strikes_sorted, spot * 1.10)
        if (
            bc_short
            and bc_long
            and bc_short != bc_long
            and call_mids.get(bc_short)
            and call_mids.get(bc_long)
        ):
            params = {
                "short_strike": bc_short,
                "short_credit": call_mids[bc_short],
                "long_strike": bc_long,
                "long_debit": call_mids[bc_long],
            }
            candidates.append(
                {
                    "name": "bear_call_spread",
                    "params": params,
                    "asymmetry_class": "capped (credit only)",
                    "uncapped_upside": False,
                }
            )
        # Long ATM put
        atm_put = nearest(put_strikes_sorted, spot)
        if atm_put and put_mids.get(atm_put):
            params = {"strike": atm_put, "debit": put_mids[atm_put]}
            candidates.append(
                {
                    "name": "long_put",
                    "params": params,
                    "asymmetry_class": "uncapped downside (bullish-for-bear)",
                    "uncapped_upside": True,
                }
            )

    # Compute P/L matrix
    matrix_rows = []
    for cand in candidates:
        row = {
            "structure": cand["name"],
            "asymmetry_class": cand["asymmetry_class"],
            "uncapped_upside": cand.get("uncapped_upside", False),
            "forbidden_at_high_conviction": cand.get(
                "forbidden_at_high_conviction", False
            ),
            "pl_per_contract": {},
        }
        for label, future_spot in zip(scenario_labels, scenarios):
            pl = _structure_pl_at_spot(cand["name"], cand["params"], future_spot)
            row["pl_per_contract"][label] = round(pl, 2)
        matrix_rows.append(row)

    # Identify recommendations
    high_conv_label = scenario_labels[-2]  # +35% or -35%
    survivors = [
        r
        for r in matrix_rows
        if not r.get("forbidden_at_high_conviction")
        and r["pl_per_contract"].get(high_conv_label, 0) > 0
    ]
    survivors.sort(key=lambda r: r["pl_per_contract"][high_conv_label], reverse=True)

    return {
        "spot": spot,
        "direction": direction,
        "scenario_labels": scenario_labels,
        "scenario_spots": scenarios,
        "candidates": matrix_rows,
        "best_for_high_conviction_tail": survivors[:3] if survivors else [],
        "rejected_at_high_conviction": [
            r["structure"]
            for r in matrix_rows
            if r.get("forbidden_at_high_conviction")
            or r["pl_per_contract"].get(high_conv_label, 0) <= 0
        ],
        "methodology": (
            "Pitfall 5 (asymmetry rule): rank candidate structures by P/L in the "
            f"high-conviction tail ({high_conv_label}). Reject any showing LOSS or "
            "flat in the conviction column. Forbidden structures (Jade Lizard, IC) "
            "shown for comparison only — never recommend at conviction>=4. "
            "See references/pitfalls/05-capped-upside-vs-conviction.md"
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compute options market signals from yfinance data"
    )
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument(
        "--expiry",
        help="Specific expiration date (YYYY-MM-DD). Default: nearest monthly.",
    )
    parser.add_argument(
        "--mode",
        choices=["basic", "full"],
        default="basic",
        help="Analysis depth (basic = nearest expiry; full = all expiries)",
    )
    parser.add_argument(
        "--days-to-earnings",
        type=int,
        default=None,
        help=(
            "Days until next earnings (used for IV classification — pitfall 3). "
            "If omitted, IV classification skips the catalyst-clock signal."
        ),
    )
    parser.add_argument(
        "--net-call-premium-5d",
        type=float,
        default=None,
        help=(
            "5-day net call premium in USD (used for IV classification + conviction "
            "count — pitfalls 3 and 5). Positive = call-side accumulation."
        ),
    )
    parser.add_argument(
        "--direction",
        choices=["bull", "bear"],
        default=None,
        help=(
            "If set, emit counterfactual P/L matrix for this directional thesis "
            "(pitfall 5). Recommended whenever conviction count >= 4."
        ),
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        spot = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )

        if not spot:
            print(
                f"Error: Cannot determine current price for {ticker}", file=sys.stderr
            )
            sys.exit(1)

        # Get available expiration dates
        expiries = stock.options
        if not expiries:
            print(f"Error: No options data available for {ticker}", file=sys.stderr)
            sys.exit(1)

        # Select expiry
        if args.expiry:
            selected_expiry = args.expiry
        else:
            # Nearest monthly (typically 3rd Friday)
            selected_expiry = expiries[0]

        # Fetch options chain
        opt_chain = stock.option_chain(selected_expiry)
        calls = [c for c in opt_chain.calls.to_dict("records") if c.get("strike")]
        puts = [p for p in opt_chain.puts.to_dict("records") if p.get("strike")]

        result = {
            "ticker": ticker,
            "spot_price": round(float(spot), 2),
            "expiration": selected_expiry,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "yfinance (CBOE delayed ~15min)",
        }

        # Basic analysis
        result["max_pain"] = compute_max_pain(calls, puts)
        result["put_call_ratios"] = compute_put_call_ratios(calls, puts)
        result["iv_surface"] = compute_iv_surface(calls, puts, spot)

        # Full mode: unusual activity detection + gamma exposure + term structure
        if args.mode == "full":
            result["unusual_activity"] = detect_unusual_activity(calls, puts)
            result["gamma_exposure"] = compute_gamma_exposure(calls, puts, spot)
            result["iv_term_structure"] = compute_iv_term_structure(
                stock, expiries, spot, selected_expiry
            )

        # Summary signal
        signals = []
        pcr = result["put_call_ratios"].get("put_call_volume", {}).get("ratio")
        skew = result["iv_surface"].get("iv_skew")
        max_pain_strike = result["max_pain"].get("max_pain_strike")

        if pcr is not None:
            if pcr > 1.2:
                signals.append("Bearish — elevated put/call ratio")
            elif pcr < 0.5:
                signals.append("Bullish — low put/call ratio (potential complacency)")
        if skew is not None:
            if skew > 0.05:
                signals.append("Bearish — elevated IV skew (hedging demand)")
            elif skew < -0.02:
                signals.append("Bullish — inverted skew (call speculation)")
        if max_pain_strike and spot:
            mp_diff_pct = (max_pain_strike - spot) / spot * 100
            if mp_diff_pct > 2:
                signals.append(
                    f"Bullish — Max Pain ${max_pain_strike:.2f} ({mp_diff_pct:.1f}% above spot)"
                )
            elif mp_diff_pct < -2:
                signals.append(
                    f"Bearish — Max Pain ${max_pain_strike:.2f} ({mp_diff_pct:.1f}% below spot)"
                )

        # GEX regime signal (full mode only)
        gex_data = result.get("gamma_exposure", {})
        if gex_data and not gex_data.get("error"):
            gex_regime = gex_data.get("gex_regime")
            if gex_regime == "negative":
                signals.append(
                    "Bearish — negative GEX (dealer hedging amplifies moves)"
                )
            elif gex_regime == "positive":
                signals.append(
                    "Neutral — positive GEX (dealer pinning, low vol expected)"
                )

        # IV term structure signal (full mode only)
        ts_data = result.get("iv_term_structure", {})
        if ts_data and not ts_data.get("error"):
            structure = ts_data.get("structure")
            if structure == "backwardation":
                signals.append(
                    "Bearish — IV backwardation (near-term stress/event premium)"
                )

        result["signals_summary"] = {
            "signals": signals,
            "net_sentiment": (
                "Bullish"
                if len([s for s in signals if "Bullish" in s])
                > len([s for s in signals if "Bearish" in s])
                else "Bearish"
                if len([s for s in signals if "Bearish" in s])
                > len([s for s in signals if "Bullish" in s])
                else "Neutral / Mixed"
            ),
        }

        # IV regime classification (pitfall 3) — always runs; uses term structure
        # if available, otherwise emits classification with the signals it has.
        result["iv_classification"] = classify_iv_regime(
            iv_surface=result.get("iv_surface", {}),
            iv_term_structure=result.get("iv_term_structure"),
            days_to_next_earnings=args.days_to_earnings,
            flow_5d_net_call_premium_usd=args.net_call_premium_5d,
        )

        # Counterfactual P/L matrix (pitfall 5) — only when direction is supplied
        if args.direction:
            result["pl_matrix"] = compute_pl_matrix(
                spot=float(spot),
                direction=args.direction,
                iv_surface=result.get("iv_surface", {}),
                calls=calls,
                puts=puts,
            )

        # Convenience flow echo for downstream consumers (compute_scores.py)
        if args.net_call_premium_5d is not None:
            result.setdefault("flow", {})["net_call_premium_5d_usd"] = (
                args.net_call_premium_5d
            )

    except Exception as e:
        result = {"ticker": ticker, "error": str(e)}

    output = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
