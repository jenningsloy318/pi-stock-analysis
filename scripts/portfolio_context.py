#!/usr/bin/env python3
"""Portfolio context: correlation analysis, position sizing, risk contribution.

Usage:
    portfolio_context.py AAPL --portfolio '{"AAPL":0.15,"MSFT":0.10,"SPY":0.25}'
    portfolio_context.py AAPL --portfolio-file ./reports/portfolio.json
    portfolio_context.py AAPL --portfolio '{"AAPL":0.2}' --risk-free 0.04

Computes:
  - Correlation of new position with existing portfolio
  - Marginal risk contribution
  - Portfolio variance impact
  - Recommended position size relative to existing exposure
  - Diversification benefit score
  - Factor exposure overlap
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

try:
    import numpy as np
    import yfinance as yf
    from scipy import stats as scipy_stats
except ImportError:
    sys.stderr.write("Error: numpy, scipy, and yfinance required.\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------


def fetch_returns(tickers: list[str], period: str = "1y") -> dict[str, list[float]]:
    """Fetch daily returns for a list of tickers."""
    returns = {}
    for t in tickers:
        try:
            stock = yf.Ticker(t)
            hist = stock.history(period=period)
            if hist.empty or len(hist) < 20:
                returns[t] = []
                continue
            closes = hist["Close"].values
            daily_returns = [
                (closes[i] - closes[i - 1]) / closes[i - 1]
                for i in range(1, len(closes))
            ]
            returns[t] = daily_returns
        except Exception:
            returns[t] = []
    return returns


def compute_correlation(returns_a: list[float], returns_b: list[float]) -> float | None:
    """Compute Pearson correlation between two return series."""
    if len(returns_a) < 20 or len(returns_b) < 20:
        return None
    min_len = min(len(returns_a), len(returns_b))
    a = returns_a[-min_len:]
    b = returns_b[-min_len:]
    if len(a) < 2:
        return None
    corr = np.corrcoef(a, b)[0, 1]
    return round(float(corr), 4) if not math.isnan(corr) else None


# ---------------------------------------------------------------------------
# Portfolio risk metrics
# ---------------------------------------------------------------------------


def compute_portfolio_metrics(
    new_ticker: str,
    new_weight: float,
    portfolio: dict[str, float],
    returns: dict[str, list[float]],
    risk_free: float = 0.04,
) -> dict:
    """Compute portfolio risk metrics with the new position."""
    all_tickers = list(portfolio.keys()) + [new_ticker]
    all_weights = [portfolio.get(t, 0) for t in all_tickers[:-1]] + [new_weight]

    # Normalize weights (existing portfolio is (1 - new_weight))
    remaining = 1.0 - new_weight
    normalized = [w * remaining for w in all_weights[:-1]] + [new_weight]

    # Extract aligned return series
    min_len = min(len(returns.get(t, [])) for t in all_tickers if returns.get(t, []))
    if min_len < 20:
        return {"error": "Insufficient price history (need ≥20 days)"}

    aligned = {}
    for t in all_tickers:
        r = returns.get(t, [])
        if len(r) >= min_len:
            aligned[t] = r[-min_len:]

    if not aligned:
        return {"error": "No aligned return data"}

    # Covariance matrix
    tickers_available = [t for t in all_tickers if t in aligned]
    n = len(tickers_available)
    returns_matrix = np.array([aligned[t] for t in tickers_available])
    cov_matrix = np.cov(returns_matrix)

    # Portfolio variance and std
    weights_arr = np.array(
        [normalized[i] for i, t in enumerate(all_tickers) if t in tickers_available]
    )

    port_variance = weights_arr @ cov_matrix @ weights_arr
    port_std = math.sqrt(max(0, port_variance))

    # Annualized volatility
    ann_std = port_std * math.sqrt(252)
    ann_return = 0  # Can't predict returns, just risk

    # Sharpe ratio (approximate, using 0 expected return)
    sharpe = -risk_free / ann_std if ann_std > 0 else 0

    # Marginal risk contribution of new position
    # MRC_i = w_i * (Σw)_i / σ_p
    new_idx = (
        tickers_available.index(new_ticker) if new_ticker in tickers_available else -1
    )
    mrc = None
    if new_idx >= 0 and port_std > 0:
        marginal_cov = cov_matrix[new_idx] @ weights_arr
        mrc = new_weight * marginal_cov / port_std

    # Correlation of new ticker with existing portfolio
    if new_ticker in tickers_available and len(tickers_available) > 1:
        existing_returns = np.zeros(min_len)
        existing_weights_sum = 0
        for i, t in enumerate(tickers_available):
            if t != new_ticker:
                existing_returns += aligned[t] * normalized[i]
                existing_weights_sum += normalized[i]
        if existing_weights_sum > 0:
            existing_returns /= existing_weights_sum
            port_corr = np.corrcoef(aligned[new_ticker], existing_returns)[0, 1]
        else:
            port_corr = None
    else:
        port_corr = None

    # Diversification benefit
    # DB = 1 - (portfolio_var / weighted_avg_individual_var)
    individual_vars = np.diag(cov_matrix)
    weighted_avg_var = weights_arr @ individual_vars
    diversification = (
        1 - (port_variance / weighted_avg_var) if weighted_avg_var > 0 else 0
    )

    # Correlation matrix for display
    corr_summary = {}
    for i, t1 in enumerate(tickers_available):
        for j, t2 in enumerate(tickers_available):
            if i < j:
                if cov_matrix[i, i] > 0 and cov_matrix[j, j] > 0:
                    corr = cov_matrix[i, j] / math.sqrt(
                        cov_matrix[i, i] * cov_matrix[j, j]
                    )
                    corr_summary[f"{t1}_vs_{t2}"] = round(float(corr), 4)

    return {
        "portfolio_std_annualized": round(float(ann_std), 4),
        "portfolio_variance": round(float(port_variance), 6),
        "diversification_benefit": round(float(diversification), 4),
        "correlation_with_portfolio": round(float(port_corr), 4)
        if port_corr is not None
        else None,
        "marginal_risk_contribution": round(float(mrc), 6) if mrc is not None else None,
        "existing_holdings": len(tickers_available) - 1,
        "correlation_matrix": corr_summary,
        "concentration_warning": (
            "High concentration risk — new position highly correlated with portfolio"
            if port_corr and abs(port_corr) > 0.8
            else "Moderate correlation — provides some diversification"
            if port_corr and abs(port_corr) > 0.5
            else "Low correlation — good diversification candidate"
            if port_corr is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Position sizing recommendation
# ---------------------------------------------------------------------------


def recommend_position_size(
    conviction: float,
    portfolio_corr: float | None,
    sharpe: float,
    max_single: float = 0.20,
) -> dict:
    """Recommend position size based on conviction and portfolio context.

    Uses a combination of:
    - Conviction score (1-10) → base allocation
    - Portfolio correlation → diversification adjustment
    - Maximum single-position cap
    """
    if conviction is None:
        return {"recommended_size": None, "error": "Conviction score required"}

    # Base size from conviction
    if conviction >= 9.0:
        base = 0.12
    elif conviction >= 7.5:
        base = 0.08
    elif conviction >= 6.0:
        base = 0.05
    elif conviction >= 4.0:
        base = 0.02
    else:
        base = 0.0  # Don't allocate to low-conviction ideas

    # Diversification adjustment
    if portfolio_corr is not None:
        if abs(portfolio_corr) < 0.3:
            base *= 1.3  # Low correlation → size up
        elif abs(portfolio_corr) > 0.7:
            base *= 0.6  # High correlation → size down

    # Cap at maximum
    recommended = min(base, max_single)

    # Kelly criterion overlay (simplified)
    # f* = edge / odds
    # Edge ≈ conviction - 5 (shift to -4 to +5 range)
    edge = (conviction - 5.0) / 5.0  # -1 to +1
    if edge > 0:
        # Rough odds: assume 3:1 risk/reward for high conviction
        odds = 3.0 if conviction >= 7.5 else 2.0 if conviction >= 6.0 else 1.5
        kelly = edge / odds
        kelly_quarter = kelly * 0.25
    else:
        kelly_quarter = 0.0

    return {
        "recommended_size": round(recommended, 4),
        "recommended_size_pct": f"{recommended:.1%}",
        "base_allocation": round(base, 4),
        "quarter_kelly": round(kelly_quarter, 4),
        "max_position_cap": max_single,
        "methodology": "Base from conviction × diversification adjustment, capped at max. Quarter-Kelly overlay.",
    }


# ---------------------------------------------------------------------------
# Factor exposure overlap
# ---------------------------------------------------------------------------

FACTOR_PROXIES = {
    "market_beta": "SPY",
    "value": "VTV",
    "growth": "VUG",
    "small_cap": "IWM",
    "momentum": "MTUM",
    "quality": "QUAL",
    "low_vol": "USMV",
    "dividend": "VYM",
}


def compute_factor_exposure(ticker: str) -> dict:
    """Estimate factor exposures by correlation to factor ETFs."""
    exposures = {}
    ticker_returns = fetch_returns([ticker], "6mo").get(ticker, [])

    if len(ticker_returns) < 20:
        return {"error": "Insufficient data for factor analysis"}

    # Fetch factor ETF returns
    factor_tickers = list(set(FACTOR_PROXIES.values()))
    factor_returns = fetch_returns(factor_tickers, "6mo")

    for factor_name, etf in FACTOR_PROXIES.items():
        etf_rets = factor_returns.get(etf, [])
        if etf_rets:
            corr = compute_correlation(ticker_returns, etf_rets)
            exposures[factor_name] = corr

    # Dominant factors
    if exposures:
        significant = {
            k: v for k, v in exposures.items() if v is not None and abs(v) > 0.5
        }
        dominant = sorted(significant.items(), key=lambda x: -abs(x[1]))
    else:
        dominant = []

    return {
        "factor_exposures": exposures,
        "dominant_factors": [
            {"factor": d[0], "correlation": d[1]} for d in dominant[:3]
        ],
        "interpretation": (
            f"Stock primarily driven by: {', '.join(d[0] for d in dominant[:3])}"
            if dominant
            else "No dominant factor exposure detected"
        ),
    }


# ---------------------------------------------------------------------------
# Tail risk analysis
# ---------------------------------------------------------------------------


def compute_tail_risk(returns: np.ndarray, confidence: float = 0.95) -> dict:
    """Compute tail risk metrics from a daily returns series.

    Parameters
    ----------
    returns:    1-D array of daily returns (e.g. [0.01, -0.02, ...])
    confidence: primary confidence level (default 0.95; 0.99 also computed)

    Returns
    -------
    dict with VaR/CVaR at 95% & 99%, max drawdown, drawdown duration,
    and Calmar ratio.
    """
    if len(returns) < 20:
        return {"error": "Insufficient returns data (need ≥20 observations)"}

    r = np.asarray(returns, dtype=float)

    def _var(arr: np.ndarray, conf: float) -> float:
        """Historical-simulation VaR (loss expressed as positive number)."""
        return float(-np.percentile(arr, (1 - conf) * 100))

    def _cvar(arr: np.ndarray, conf: float) -> float:
        """CVaR / Expected Shortfall (mean of losses beyond VaR cutoff)."""
        cutoff = np.percentile(arr, (1 - conf) * 100)
        tail = arr[arr <= cutoff]
        return float(-tail.mean()) if len(tail) > 0 else _var(arr, conf)

    var_95 = _var(r, 0.95)
    var_99 = _var(r, 0.99)
    cvar_95 = _cvar(r, 0.95)
    cvar_99 = _cvar(r, 0.99)

    # Maximum drawdown and duration from cumulative returns
    cum = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cum)
    drawdown_series = (cum - running_max) / running_max  # negative values

    max_dd = float(drawdown_series.min())

    # Longest continuous period underwater (drawdown_series < 0)
    underwater = drawdown_series < 0
    max_duration = 0
    current = 0
    for uw in underwater:
        if uw:
            current += 1
            max_duration = max(max_duration, current)
        else:
            current = 0

    # Calmar ratio: annualized return / abs(max drawdown)
    ann_return = float(np.mean(r) * 252)
    calmar = ann_return / abs(max_dd) if max_dd != 0 else None

    return {
        "var_95": round(var_95, 6),
        "var_99": round(var_99, 6),
        "cvar_95": round(cvar_95, 6),
        "cvar_99": round(cvar_99, 6),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_pct": f"{max_dd:.2%}",
        "max_drawdown_duration_days": int(max_duration),
        "annualized_return": round(ann_return, 6),
        "calmar_ratio": round(calmar, 4) if calmar is not None else None,
        "observations": int(len(r)),
    }


# ---------------------------------------------------------------------------
# Correlation regime detection
# ---------------------------------------------------------------------------


def detect_correlation_regime(returns_matrix: np.ndarray, window: int = 60) -> dict:
    """Identify the current pairwise correlation regime across a portfolio.

    Parameters
    ----------
    returns_matrix: 2-D array of shape (n_assets, n_days)
    window:         rolling window in trading days (default 60)

    Returns
    -------
    dict with rolling average correlation, percentile rank vs history,
    and regime label: "normal" / "elevated" / "crisis".
    """
    m = np.asarray(returns_matrix, dtype=float)
    n_assets, n_days = m.shape

    if n_assets < 2:
        return {"error": "Need at least 2 assets for correlation regime detection"}
    if n_days < window + 10:
        return {"error": f"Need at least {window + 10} days of history"}

    # Collect all unique pair indices
    pairs = [(i, j) for i in range(n_assets) for j in range(i + 1, n_assets)]

    # Rolling average pairwise correlation at each step
    rolling_avg_corrs: list[float] = []
    for end in range(window, n_days + 1):
        window_slice = m[:, end - window : end]
        pair_corrs = [
            float(np.corrcoef(window_slice[i], window_slice[j])[0, 1]) for i, j in pairs
        ]
        # Filter NaN (e.g. zero-variance windows)
        valid = [c for c in pair_corrs if not math.isnan(c)]
        if valid:
            rolling_avg_corrs.append(float(np.mean(valid)))

    if not rolling_avg_corrs:
        return {"error": "Could not compute rolling correlations"}

    current_corr = rolling_avg_corrs[-1]
    pct_rank = float(scipy_stats.percentileofscore(rolling_avg_corrs, current_corr))

    if pct_rank >= 80:
        regime = "crisis"
    elif pct_rank >= 60:
        regime = "elevated"
    else:
        regime = "normal"

    return {
        "current_avg_pairwise_correlation": round(current_corr, 4),
        "percentile_rank": round(pct_rank, 2),
        "regime": regime,
        "rolling_window_days": window,
        "history_length_days": int(n_days),
        "n_pairs": len(pairs),
        "interpretation": (
            f"Correlation regime is '{regime}' "
            f"(current avg corr {current_corr:.3f} is at the "
            f"{pct_rank:.0f}th percentile of historical rolling correlations)"
        ),
    }


# ---------------------------------------------------------------------------
# Drawdown recovery analysis
# ---------------------------------------------------------------------------


def analyze_drawdown_recovery(prices: np.ndarray) -> dict:
    """Identify significant drawdowns and characterise recovery behaviour.

    Parameters
    ----------
    prices: 1-D array of prices (not returns) in chronological order

    Returns
    -------
    dict with all drawdowns >10%, per-drawdown depth/duration/recovery,
    mean/median recovery times, and current drawdown status.
    """
    p = np.asarray(prices, dtype=float)
    if len(p) < 10:
        return {"error": "Insufficient price history for drawdown analysis"}

    THRESHOLD = 0.10  # 10% minimum drawdown depth

    drawdowns: list[dict] = []
    n = len(p)
    i = 0

    while i < n:
        # Find next peak
        peak_idx = i
        for k in range(i, n):
            if p[k] >= p[peak_idx]:
                peak_idx = k
            elif k > peak_idx:
                # Prices have started falling from peak_idx
                break
        else:
            # Reached end without a trough — no more drawdowns
            break

        # Walk forward from peak to find trough
        trough_idx = peak_idx
        for k in range(peak_idx + 1, n):
            if p[k] < p[trough_idx]:
                trough_idx = k
            elif p[k] >= p[peak_idx]:
                # Recovered before finding a deep enough trough
                i = k
                break
        else:
            i = n  # exhausted series

        depth = (p[trough_idx] - p[peak_idx]) / p[peak_idx]  # negative
        if abs(depth) < THRESHOLD:
            i = max(i, trough_idx + 1)
            continue

        # Search for recovery (price >= peak price) after trough
        recovery_idx = None
        for k in range(trough_idx + 1, n):
            if p[k] >= p[peak_idx]:
                recovery_idx = k
                break

        duration = trough_idx - peak_idx  # days from peak to trough
        recovery_days = (
            (recovery_idx - trough_idx) if recovery_idx is not None else None
        )

        drawdowns.append(
            {
                "peak_index": int(peak_idx),
                "trough_index": int(trough_idx),
                "recovery_index": int(recovery_idx)
                if recovery_idx is not None
                else None,
                "depth": round(float(depth), 6),
                "depth_pct": f"{depth:.2%}",
                "duration_days": int(duration),
                "recovery_days": int(recovery_days)
                if recovery_days is not None
                else None,
                "recovered": recovery_idx is not None,
            }
        )

        i = recovery_idx + 1 if recovery_idx is not None else trough_idx + 1

    # Mean / median recovery times (completed drawdowns only)
    completed = [
        d["recovery_days"]
        for d in drawdowns
        if d["recovered"] and d["recovery_days"] is not None
    ]
    mean_recovery = round(float(np.mean(completed)), 1) if completed else None
    median_recovery = round(float(np.median(completed)), 1) if completed else None

    # Current drawdown status
    peak_so_far = float(np.max(p))
    peak_so_far_idx = int(np.argmax(p))
    current_price = float(p[-1])
    in_drawdown = current_price < peak_so_far
    current_depth = (current_price - peak_so_far) / peak_so_far if in_drawdown else 0.0
    current_duration = (n - 1 - peak_so_far_idx) if in_drawdown else 0

    return {
        "drawdowns_over_10pct": drawdowns,
        "total_significant_drawdowns": len(drawdowns),
        "mean_recovery_days": mean_recovery,
        "median_recovery_days": median_recovery,
        "current_status": {
            "in_drawdown": bool(in_drawdown),
            "current_depth": round(float(current_depth), 6),
            "current_depth_pct": f"{current_depth:.2%}",
            "days_since_peak": int(current_duration),
            "all_time_high": round(peak_so_far, 4),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Portfolio context: correlation, sizing, risk contribution"
    )
    parser.add_argument("ticker", help="Ticker to analyze in portfolio context")
    parser.add_argument(
        "--portfolio", help='JSON portfolio: \'{"AAPL":0.15,"MSFT":0.10}\''
    )
    parser.add_argument("--portfolio-file", help="Path to portfolio JSON file")
    parser.add_argument("--conviction", type=float, help="Conviction score (1-10)")
    parser.add_argument(
        "--risk-free", type=float, default=0.04, help="Risk-free rate (default: 0.04)"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    # Load portfolio
    portfolio = {}
    if args.portfolio:
        try:
            portfolio = json.loads(args.portfolio)
        except json.JSONDecodeError as e:
            print(f"Error parsing portfolio JSON: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.portfolio_file:
        try:
            with open(args.portfolio_file) as f:
                portfolio = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading portfolio file: {e}", file=sys.stderr)
            sys.exit(1)

    result = {
        "ticker": ticker,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "existing_portfolio": {k: f"{v:.1%}" for k, v in portfolio.items()}
        if portfolio
        else {},
    }

    # Fetch returns for ticker + portfolio holdings
    all_tickers = [ticker] + [t for t in portfolio.keys() if t != ticker]
    returns = fetch_returns(all_tickers)

    # Correlation of ticker with each portfolio holding
    correlations = {}
    for pt, pw in portfolio.items():
        if pt != ticker:
            corr = compute_correlation(returns.get(ticker, []), returns.get(pt, []))
            correlations[pt] = corr

    result["pairwise_correlations"] = correlations

    # Portfolio risk metrics
    if portfolio:
        # Default new weight: 5% if not specified
        new_weight = portfolio.get(ticker, 0.05)
        metrics = compute_portfolio_metrics(
            ticker, new_weight, portfolio, returns, args.risk_free
        )
        result["portfolio_risk"] = metrics

        # Position sizing
        if args.conviction is not None:
            port_corr = metrics.get("correlation_with_portfolio")
            sizing = recommend_position_size(
                args.conviction, port_corr, metrics.get("sharpe_ratio", 0)
            )
            result["position_sizing"] = sizing

    # Factor exposure
    result["factor_exposure"] = compute_factor_exposure(ticker)

    # Tail risk analysis (uses ticker's own return series)
    ticker_returns = returns.get(ticker, [])
    if ticker_returns:
        result["tail_risk"] = compute_tail_risk(np.asarray(ticker_returns))
    else:
        result["tail_risk"] = {
            "error": "No return data available for tail risk analysis"
        }

    # Correlation regime detection (requires ≥2 assets with aligned histories)
    available_tickers = [t for t in all_tickers if len(returns.get(t, [])) >= 70]
    if len(available_tickers) >= 2:
        min_len = min(len(returns[t]) for t in available_tickers)
        ret_matrix = np.array([returns[t][-min_len:] for t in available_tickers])
        result["correlation_regime"] = detect_correlation_regime(ret_matrix)
    else:
        result["correlation_regime"] = {
            "error": "Need ≥2 tickers with ≥70 days of history for regime detection"
        }

    # Drawdown recovery analysis (uses ticker price history)
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        if not hist.empty and len(hist) >= 10:
            prices = hist["Close"].values
            result["drawdown_analysis"] = analyze_drawdown_recovery(prices)
        else:
            result["drawdown_analysis"] = {
                "error": "Insufficient price history for drawdown analysis"
            }
    except Exception as exc:
        result["drawdown_analysis"] = {"error": f"Failed to fetch price history: {exc}"}

    # Summary
    warnings = []
    if correlations:
        high_corr = [
            (t, c) for t, c in correlations.items() if c is not None and abs(c) > 0.7
        ]
        if high_corr:
            warnings.append(
                f"High correlation with existing holdings: {', '.join(t for t, _ in high_corr)}"
            )

    result["portfolio_summary"] = {
        "warnings": warnings,
        "warning_count": len(warnings),
        "recommendation": (
            "Good diversification candidate — add to portfolio"
            if not warnings
            and result.get("position_sizing", {}).get("recommended_size", 0) > 0.03
            else "Moderate addition — size conservatively, monitor correlation"
            if not warnings
            else "Proceed with caution — high overlap with existing holdings"
        ),
    }

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
