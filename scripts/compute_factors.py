#!/usr/bin/env python3
"""Compute Fama-French factor exposures for a stock.

Usage:
    compute_factors.py AAPL                             # 3-factor regression
    compute_factors.py AAPL --model 5factor             # 5-factor (incl. RMW, CMA)
    compute_factors.py AAPL --benchmark SPY --period 5y
    compute_factors.py AAPL --output ./reports/[TICKER]/factors.json

Computes factor loadings via linear regression of stock excess returns against
Fama-French factor returns from Kenneth French's data library (public/free).

Factors:
  - Mkt-RF: Market excess return (value-weight)
  - SMB: Small Minus Big (size factor)
  - HML: High Minus Low (value factor)
  - RMW: Robust Minus Weak (profitability factor — 5-factor only)
  - CMA: Conservative Minus Aggressive (investment factor — 5-factor only)
  - Momentum: Winners Minus Losers (optional momentum factor)

Output: Regression coefficients (betas), t-statistics, R², and factor attribution
         showing what % of historical returns is explained by each factor.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from io import StringIO
from typing import Any

try:
    import numpy as np
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
    import pandas as pd
except ImportError:
    sys.stderr.write("Error: numpy, yfinance, and pandas required. Run: pip install numpy yfinance pandas\n")
    sys.exit(1)


# Kenneth French data library URLs
FF_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"

FF_DATASETS = {
    "3factor_daily": f"{FF_BASE}/F-F_Research_Data_Factors_daily_CSV.zip",
    "5factor_daily": f"{FF_BASE}/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "momentum_daily": f"{FF_BASE}/F-F_Momentum_Factor_daily_CSV.zip",
}


def fetch_ff_factors(model: str = "3factor") -> pd.DataFrame:
    """Fetch Fama-French factor returns from Kenneth French's data library.

    Download CSV, parse the date column, and convert to a DataFrame
    with datetime index and factor columns in decimal (not percentage).
    """
    url = FF_DATASETS.get(f"{model}_daily", FF_DATASETS["3factor_daily"])

    try:
        # Read the zip file directly
        df = pd.read_csv(
            url,
            skiprows=3,  # Skip header lines
            engine="python",
        )

        # Find the row with "Copyright" to stop parsing
        copyright_idx = df[df.iloc[:, 0].astype(str).str.contains("Copyright", na=False)].index
        if len(copyright_idx) > 0:
            df = df.iloc[:copyright_idx[0]]

        # Rename first column to "date"
        df.columns = df.columns.astype(str)
        df.rename(columns={df.columns[0]: "date"}, inplace=True)

        # Convert date to datetime
        df["date"] = pd.to_datetime(df["date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.set_index("date")

        # Convert all factor columns to float, divide by 100 (French data is in %)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

        return df.dropna()
    except Exception as e:
        # Silently fail — the data library can be intermittently unavailable
        return pd.DataFrame()


def fetch_stock_returns(ticker: str, period: str = "5y") -> pd.Series:
    """Fetch daily returns for a stock."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist.empty:
            return pd.Series(dtype=float)

        returns = hist["Close"].pct_change().dropna()
        returns.name = ticker
        return returns
    except Exception:
        return pd.Series(dtype=float)


def fetch_benchmark_returns(benchmark: str = "SPY", period: str = "5y") -> pd.Series:
    """Fetch daily returns for the benchmark (for excess return calculation)."""
    return fetch_stock_returns(benchmark, period)


def compute_risk_free_rate() -> float:
    """Get approximate risk-free rate (annualized, daily equivalent).

    Uses recent 3-month T-bill rate as a rough proxy.
    """
    try:
        # 3-month T-bill from yfinance
        tbill = yf.Ticker("^IRX")
        info = tbill.info
        rate = info.get("regularMarketPrice") or info.get("previousClose")
        if rate:
            return rate / 100 / 252  # Annual % → daily decimal
    except Exception:
        pass
    # Fallback: ~4% annual → ~0.016% daily
    return 0.04 / 252


def run_regression(stock_excess: pd.Series, factors: pd.DataFrame) -> dict:
    """Run linear regression: stock_excess = α + β₁·MktRF + β₂·SMB + β₃·HML + ...

    Returns coefficients, t-statistics, R², and factor attribution.
    """
    # Align indices
    common_dates = stock_excess.index.intersection(factors.index)
    if len(common_dates) < 60:
        return {"error": f"Insufficient common trading days ({len(common_dates)}). Need ≥60."}

    y = stock_excess.loc[common_dates].values
    X = factors.loc[common_dates].values

    n = len(y)
    k = X.shape[1]

    if n <= k:
        return {"error": f"Not enough observations ({n}) for {k} factors."}

    # OLS: β = (X'X)⁻¹ X'y
    try:
        X_with_const = np.column_stack([np.ones(n), X])
        beta = np.linalg.inv(X_with_const.T @ X_with_const) @ X_with_const.T @ y

        # Residuals
        y_pred = X_with_const @ beta
        residuals = y - y_pred

        # Standard errors
        sigma2 = np.sum(residuals ** 2) / (n - k - 1)
        se = np.sqrt(sigma2 * np.diag(np.linalg.inv(X_with_const.T @ X_with_const)))

        # t-statistics
        t_stats = beta / se

        # R²
        ss_total = np.sum((y - np.mean(y)) ** 2)
        ss_residual = np.sum(residuals ** 2)
        r_squared = 1 - ss_residual / ss_total if ss_total > 0 else 0

        # Adjusted R²
        adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - k - 1)

        # Annualize alpha (intercept)
        alpha_daily = beta[0]
        alpha_annual = (1 + alpha_daily) ** 252 - 1

        factor_names = ["Alpha"] + list(factors.columns)
        factor_coefficients = {}
        for i, name in enumerate(factor_names):
            factor_coefficients[name] = {
                "coefficient": round(float(beta[i]), 6),
                "t_statistic": round(float(t_stats[i]), 3),
                "significant_at_5pct": abs(float(t_stats[i])) > 1.96,
                "annualized_impact_pct": round(float(beta[i]) * 252 * 100, 2) if i > 0 else None,
            }

        return {
            "observations": n,
            "factors": k,
            "r_squared": round(float(r_squared), 4),
            "adj_r_squared": round(float(adj_r_squared), 4),
            "alpha_daily": round(float(alpha_daily), 6),
            "alpha_annual": round(float(alpha_annual), 4),
            "alpha_annual_pct": f"{alpha_annual * 100:.2f}%",
            "coefficients": factor_coefficients,
            "interpretation": interpret_factors(factor_coefficients),
        }
    except np.linalg.LinAlgError:
        return {"error": "Singular matrix — factor collinearity detected."}


def interpret_factors(coefficients: dict) -> dict:
    """Human-readable interpretation of factor loadings."""
    interp = {}
    for name, data in coefficients.items():
        if name == "Alpha":
            alpha_daily = data["coefficient"]
            alpha_annual = (1 + alpha_daily) ** 252 - 1
            if abs(data["t_statistic"]) < 1.96:
                interp["alpha"] = "Not statistically significant — returns explained by factor exposure."
            elif alpha_daily > 0:
                interp["alpha"] = f"Positive alpha ({alpha_annual * 100:.2f}% annualized) — stock outperformed factor model."
            else:
                interp["alpha"] = f"Negative alpha ({alpha_annual * 100:.2f}% annualized) — stock underperformed factor model."
        else:
            beta = data["coefficient"]
            sig = data["significant_at_5pct"]
            if name == "Mkt-RF":
                if beta > 1.2:
                    interp["market"] = f"High beta ({beta:.2f}) — aggressive, amplifies market moves."
                elif beta > 0.8:
                    interp["market"] = f"Market-like beta ({beta:.2f}) — moves with the market."
                else:
                    interp["market"] = f"Low beta ({beta:.2f}) — defensive, less market-sensitive."
            elif name == "SMB":
                if sig and beta > 0:
                    interp["size"] = f"Small-cap tilt ({beta:.2f}) — behaves like smaller companies."
                elif sig and beta < 0:
                    interp["size"] = f"Large-cap tilt ({beta:.2f}) — behaves like larger companies."
                else:
                    interp["size"] = "No significant size exposure."
            elif name == "HML":
                if sig and beta > 0:
                    interp["value"] = f"Value tilt ({beta:.2f}) — stock has value characteristics."
                elif sig and beta < 0:
                    interp["value"] = f"Growth tilt ({beta:.2f}) — stock has growth characteristics."
                else:
                    interp["value"] = "No significant value/growth tilt."
            elif name == "RMW":
                if sig and beta > 0:
                    interp["profitability"] = f"Profitable tilt ({beta:.2f}) — strong operating profitability exposure."
                elif sig and beta < 0:
                    interp["profitability"] = f"Weak profitability exposure ({beta:.2f})."
                else:
                    interp["profitability"] = "No significant profitability exposure."
            elif name == "CMA":
                if sig and beta > 0:
                    interp["investment"] = f"Conservative investment tilt ({beta:.2f})."
                elif sig and beta < 0:
                    interp["investment"] = f"Aggressive investment tilt ({beta:.2f}) — high asset growth companies."
                else:
                    interp["investment"] = "No significant investment exposure."
            elif name == "Mom":
                if sig and beta > 0:
                    interp["momentum"] = f"Positive momentum ({beta:.2f}) — winner characteristics."
                elif sig and beta < 0:
                    interp["momentum"] = f"Negative momentum ({beta:.2f}) — loser/contrarian characteristics."
                else:
                    interp["momentum"] = "No significant momentum exposure."

    return interp


def main():
    parser = argparse.ArgumentParser(
        description="Compute Fama-French factor exposures for a stock"
    )
    parser.add_argument("ticker", help="Ticker symbol")
    parser.add_argument("--model", choices=["3factor", "5factor", "5factor_momentum"],
                        default="5factor", help="Factor model (default: 5factor)")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark for excess returns")
    parser.add_argument("--period", default="5y", help="Lookback period (yfinance format: 1y, 3y, 5y, 10y)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()

    # Fetch Fama-French factors
    if args.model == "3factor":
        factors = fetch_ff_factors("3factor")
    else:
        factors = fetch_ff_factors("5factor")
        if args.model == "5factor_momentum":
            mom = fetch_ff_factors("momentum")
            if not mom.empty:
                factors = factors.join(mom, how="inner")

    if factors.empty:
        result = {
            "ticker": ticker,
            "error": "Could not fetch Fama-French factor data. "
                     "Kenneth French data library may be temporarily unavailable. "
                     "Try again later or use web search for cached factor data.",
            "data_source": "Kenneth French Data Library (mba.tuck.dartmouth.edu)",
        }
    else:
        # Fetch stock and benchmark returns
        stock_returns = fetch_stock_returns(ticker, args.period)
        bench_returns = fetch_benchmark_returns(args.benchmark, args.period)

        if stock_returns.empty:
            result = {"ticker": ticker, "error": f"No price data for {ticker}"}
        else:
            # Compute excess returns
            rf_daily = compute_risk_free_rate()
            stock_excess = stock_returns - rf_daily

            # Run regression
            regression = run_regression(stock_excess, factors)

            result = {
                "ticker": ticker,
                "model": args.model,
                "benchmark": args.benchmark,
                "period": args.period,
                "risk_free_rate_approx": round(rf_daily * 252 * 100, 2),
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "data_sources": {
                    "factor_returns": "Kenneth French Data Library (free/public)",
                    "stock_returns": "yfinance",
                    "benchmark_returns": f"yfinance ({args.benchmark})",
                },
                "regression": regression,
                "usage": (
                    "Factor loadings explain what drives the stock's historical returns. "
                    "High market beta (>1.2) = aggressive; negative HML = growth; "
                    "positive SMB = small-cap exposure. "
                    "Use factor exposures to understand what factor bets you're making "
                    "by buying this stock, and how it fits into a factor-diversified portfolio."
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
