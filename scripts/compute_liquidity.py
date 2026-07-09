#!/usr/bin/env python3
"""Compute market microstructure and liquidity risk metrics for position sizing.

Usage:
    compute_liquidity.py AAPL
    compute_liquidity.py AAPL --position-size 500000
    compute_liquidity.py AAPL --position-size 250000 --output ./reports/AAPL/liquidity.json

Metrics computed:
  - Amihud Illiquidity Ratio: mean(|return| / dollar_volume) — higher = less liquid
  - Average Daily Dollar Volume (ADDV): 20-day and 60-day windows
  - Days to Liquidate: position_size / (ADDV * participation_rate)
  - Market Impact Estimate: square-root model approximation in bps
  - Corwin-Schultz Bid-Ask Spread Proxy: high-low based spread estimator
  - Volume Volatility: coefficient of variation of daily volume
  - Free Float Ratio: float shares vs shares outstanding
  - Liquidity Score (1-10): composite of ADDV, Amihud, spread, volume stability
"""

import argparse
import json
import math
import sys

try:
    import numpy as np
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
except ImportError:
    sys.stderr.write(
        "Error: numpy and yfinance required. Run: pip install numpy yfinance\n"
    )
    sys.exit(1)

PARTICIPATION_RATE = 0.10


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0.0:
        return None
    return num / den


def _r(value: float | None, places: int = 6) -> float | None:
    return round(value, places) if value is not None else None


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if len(values) > 0 else None


def _std(values: list[float]) -> float | None:
    return float(np.std(values, ddof=1)) if len(values) > 1 else None


# ---------------------------------------------------------------------------
# Metric computations
# ---------------------------------------------------------------------------


def compute_amihud(returns: list[float], dollar_volumes: list[float]) -> float | None:
    """Amihud (2002) illiquidity ratio: mean(|r_t| / dv_t).

    Units: (return per dollar) — multiply by 1e6 for standard presentation
    as return per million dollars.
    """
    ratios = [
        abs(r) / dv
        for r, dv in zip(returns, dollar_volumes)
        if dv > 0 and not math.isnan(r) and not math.isnan(dv)
    ]
    return _mean(ratios)


def compute_corwin_schultz_spread(
    highs: list[float], lows: list[float]
) -> float | None:
    """Corwin-Schultz (2012) high-low spread estimator.

    Returns the estimated bid-ask spread as a fraction of price (not bps).
    Uses the two-day high-low ratio method. Returns None if insufficient data.
    """
    if len(highs) < 2 or len(lows) < 2:
        return None

    n = len(highs)
    betas: list[float] = []
    gammas: list[float] = []

    for i in range(1, n):
        h1, l1 = highs[i - 1], lows[i - 1]
        h2, l2 = highs[i], lows[i]
        if l1 <= 0 or l2 <= 0 or h1 <= 0 or h2 <= 0:
            continue

        ln_hl1 = math.log(h1 / l1)
        ln_hl2 = math.log(h2 / l2)
        beta = ln_hl1**2 + ln_hl2**2

        h_adj = max(h1, h2)
        l_adj = min(l1, l2)
        if l_adj <= 0:
            continue
        gamma = math.log(h_adj / l_adj) ** 2

        betas.append(beta)
        gammas.append(gamma)

    if not betas:
        return None

    beta_mean = _mean(betas)
    gamma_mean = _mean(gammas)
    if beta_mean is None or gamma_mean is None:
        return None

    k2 = (8.0 / math.pi) ** 0.5
    denom = 3.0 - 2.0 * math.sqrt(2.0)
    if denom == 0:
        return None

    alpha = (math.sqrt(2.0 * beta_mean) - math.sqrt(beta_mean)) / denom - math.sqrt(
        gamma_mean / denom
    )
    spread = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))

    return max(0.0, spread)


def compute_volume_cv(volumes: list[float]) -> float | None:
    """Coefficient of variation of daily volume (std / mean)."""
    m = _mean(volumes)
    s = _std(volumes)
    if m is None or s is None or m == 0:
        return None
    return s / m


def compute_liquidity_score(
    addv_20d: float | None,
    amihud: float | None,
    spread_frac: float | None,
    volume_cv: float | None,
) -> float:
    """Composite liquidity score from 1 (worst) to 10 (best).

    Component weights:
      - ADDV percentile   : 50%
      - Amihud ratio      : 25%
      - Spread estimate   : 15%
      - Volume stability  : 10%
    """
    # ADDV component (50 pts max)
    if addv_20d is None:
        addv_score = 5.0
    elif addv_20d >= 500_000_000:
        addv_score = 10.0
    elif addv_20d >= 100_000_000:
        addv_score = 8.0 + 2.0 * (addv_20d - 100_000_000) / 400_000_000
    elif addv_20d >= 50_000_000:
        addv_score = 7.0 + 1.0 * (addv_20d - 50_000_000) / 50_000_000
    elif addv_20d >= 10_000_000:
        addv_score = 5.0 + 2.0 * (addv_20d - 10_000_000) / 40_000_000
    elif addv_20d >= 1_000_000:
        addv_score = 3.0 + 2.0 * (addv_20d - 1_000_000) / 9_000_000
    else:
        addv_score = max(1.0, addv_20d / 1_000_000 * 3.0)

    # Amihud component (25 pts max) — lower ratio = better
    if amihud is None:
        amihud_score = 5.0
    else:
        amihud_scaled = amihud * 1e6  # per million dollars
        if amihud_scaled < 0.01:
            amihud_score = 10.0
        elif amihud_scaled < 0.1:
            amihud_score = 8.0 + 2.0 * (0.1 - amihud_scaled) / 0.09
        elif amihud_scaled < 1.0:
            amihud_score = 5.0 + 3.0 * (1.0 - amihud_scaled) / 0.9
        elif amihud_scaled < 10.0:
            amihud_score = 2.0 + 3.0 * (10.0 - amihud_scaled) / 9.0
        else:
            amihud_score = 1.0

    # Spread component (15 pts max) — lower spread = better
    if spread_frac is None:
        spread_score = 5.0
    else:
        spread_bps = spread_frac * 10_000
        if spread_bps < 2:
            spread_score = 10.0
        elif spread_bps < 5:
            spread_score = 8.0 + 2.0 * (5.0 - spread_bps) / 3.0
        elif spread_bps < 20:
            spread_score = 5.0 + 3.0 * (20.0 - spread_bps) / 15.0
        elif spread_bps < 50:
            spread_score = 2.0 + 3.0 * (50.0 - spread_bps) / 30.0
        else:
            spread_score = 1.0

    # Volume stability component (10 pts max) — lower CV = better
    if volume_cv is None:
        vol_score = 5.0
    elif volume_cv < 0.3:
        vol_score = 10.0
    elif volume_cv < 0.5:
        vol_score = 7.0 + 3.0 * (0.5 - volume_cv) / 0.2
    elif volume_cv < 0.8:
        vol_score = 4.0 + 3.0 * (0.8 - volume_cv) / 0.3
    elif volume_cv < 1.5:
        vol_score = 1.5 + 2.5 * (1.5 - volume_cv) / 0.7
    else:
        vol_score = 1.0

    composite = (
        addv_score * 0.50 + amihud_score * 0.25 + spread_score * 0.15 + vol_score * 0.10
    )
    return round(max(1.0, min(10.0, composite)), 1)


def liquidity_rating(score: float) -> str:
    if score >= 8.0:
        return "Excellent"
    elif score >= 6.0:
        return "Good"
    elif score >= 4.0:
        return "Moderate"
    elif score >= 2.0:
        return "Poor"
    return "Very Poor"


# ---------------------------------------------------------------------------
# Position sizing helpers
# ---------------------------------------------------------------------------


def max_position_at_impact(
    addv: float | None, target_impact_bps: float = 100.0
) -> float | None:
    """Invert the square-root market impact model to find max position for a given impact."""
    if addv is None or addv <= 0:
        return None
    ratio = (target_impact_bps / 100.0) ** 2
    return ratio * addv


def market_impact_bps(position_size: float, addv: float | None) -> float | None:
    """Kyle square-root model: impact_bps = sqrt(position / ADDV) * 100."""
    if addv is None or addv <= 0:
        return None
    return math.sqrt(position_size / addv) * 100.0


# ---------------------------------------------------------------------------
# Warning flags
# ---------------------------------------------------------------------------


def collect_warnings(
    days_to_liq: float | None,
    impact_bps: float | None,
    vol_cv: float | None,
    float_pct: float | None,
    addv_20d: float | None,
) -> list[str]:
    warnings: list[str] = []
    if days_to_liq is not None and days_to_liq > 5:
        warnings.append("LIQUIDITY_CONSTRAINED")
    if impact_bps is not None and impact_bps > 50:
        warnings.append("HIGH_IMPACT")
    if vol_cv is not None and vol_cv > 0.8:
        warnings.append("ERRATIC_VOLUME")
    if float_pct is not None and float_pct < 50:
        warnings.append("LOW_FLOAT")
    if addv_20d is not None and addv_20d < 1_000_000:
        warnings.append("THIN_MARKET")
    return warnings


# ---------------------------------------------------------------------------
# Data acquisition
# ---------------------------------------------------------------------------


def fetch_data(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    hist = t.history(period="1y", auto_adjust=True)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    if hist.empty:
        raise ValueError(f"No price data returned for {ticker}")

    closes = hist["Close"].tolist()
    highs = hist["High"].tolist()
    lows = hist["Low"].tolist()
    volumes = hist["Volume"].tolist()

    dollar_volumes = [c * v for c, v in zip(closes, volumes)]
    returns = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0:
            returns.append((closes[i] - prev) / prev)
        else:
            returns.append(0.0)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "dollar_volumes": dollar_volumes,
        "returns": returns,
        "info": info,
    }


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def compute(ticker: str, position_size: float) -> dict:
    data = fetch_data(ticker)

    closes = data["closes"]
    highs = data["highs"]
    lows = data["lows"]
    volumes = data["volumes"]
    dollar_volumes = data["dollar_volumes"]
    returns = data["returns"]
    info = data["info"]

    dv_20 = dollar_volumes[-20:] if len(dollar_volumes) >= 20 else dollar_volumes
    dv_60 = dollar_volumes[-60:] if len(dollar_volumes) >= 60 else dollar_volumes
    addv_20d = _mean(dv_20)
    addv_60d = _mean(dv_60)

    ret_window = returns[-60:] if len(returns) >= 60 else returns
    dv_window = (
        dollar_volumes[-60:] if len(dollar_volumes) >= 60 else dollar_volumes[1:]
    )
    amihud = compute_amihud(ret_window, dv_window[: len(ret_window)])

    highs_60 = highs[-60:] if len(highs) >= 60 else highs
    lows_60 = lows[-60:] if len(lows) >= 60 else lows
    cs_spread_frac = compute_corwin_schultz_spread(highs_60, lows_60)
    cs_spread_bps = _r(
        (cs_spread_frac * 10_000) if cs_spread_frac is not None else None, 2
    )

    vol_window = volumes[-60:] if len(volumes) >= 60 else volumes
    volume_cv = compute_volume_cv([v for v in vol_window if v > 0])

    shares_outstanding = info.get("sharesOutstanding") or info.get(
        "impliedSharesOutstanding"
    )
    float_shares = info.get("floatShares")
    free_float_pct: float | None = None
    if shares_outstanding and float_shares and shares_outstanding > 0:
        free_float_pct = _r(float_shares / shares_outstanding * 100, 2)

    market_cap = info.get("marketCap")

    days_to_liq: float | None = None
    if addv_20d and addv_20d > 0:
        daily_tradeable = addv_20d * PARTICIPATION_RATE
        days_to_liq = _r(position_size / daily_tradeable, 4)

    impact = market_impact_bps(position_size, addv_20d)
    max_pos_1pct = max_position_at_impact(addv_20d, target_impact_bps=100.0)

    score = compute_liquidity_score(addv_20d, amihud, cs_spread_frac, volume_cv)
    rating = liquidity_rating(score)
    warnings = collect_warnings(
        days_to_liq, impact, volume_cv, free_float_pct, addv_20d
    )

    return {
        "ticker": ticker.upper(),
        "metrics": {
            "addv_20d": _r(addv_20d, 2),
            "addv_60d": _r(addv_60d, 2),
            "amihud_ratio": _r(amihud, 10),
            "amihud_percentile_note": "Lower is more liquid",
            "corwin_schultz_spread_bps": cs_spread_bps,
            "volume_cv": _r(volume_cv, 4),
            "days_to_liquidate": days_to_liq,
            "market_impact_bps": _r(impact, 2),
            "free_float_pct": free_float_pct,
            "market_cap": market_cap,
        },
        "position_sizing": {
            "proposed_size_usd": position_size,
            "participation_rate": PARTICIPATION_RATE,
            "days_to_liquidate": days_to_liq,
            "estimated_slippage_bps": _r(impact, 2),
            "max_position_at_1pct_impact": _r(max_pos_1pct, 2),
            "liquidity_constrained": "LIQUIDITY_CONSTRAINED" in warnings,
        },
        "liquidity_score": score,
        "liquidity_rating": rating,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute market microstructure and liquidity risk metrics."
    )
    parser.add_argument("ticker", type=str, help="Stock ticker symbol (e.g. AAPL)")
    parser.add_argument(
        "--position-size",
        type=float,
        default=100_000.0,
        metavar="USD",
        help="Proposed position size in dollars (default: 100000)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional path to write JSON output",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        result = compute(args.ticker, args.position_size)
    except Exception as exc:
        result = {"ticker": args.ticker.upper(), "error": str(exc)}

    output_str = json.dumps(result, indent=2)
    print(output_str)

    if args.output:
        try:
            import os

            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as fh:
                fh.write(output_str)
        except Exception as exc:
            sys.stderr.write(f"Warning: could not write to {args.output}: {exc}\n")
