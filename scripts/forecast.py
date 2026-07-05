#!/usr/bin/env python3
"""Time-series forecasting for revenue, EPS, FCF, and volatility/risk metrics.

Usage:
    forecast.py ./reports/AAPL/raw-data.json
    forecast.py raw-data.json --horizon 5 --output ./reports/[TICKER]/forecast.json
    forecast.py raw-data.json --method arima --confidence 0.80
    forecast.py raw-data.json --enhanced --returns-file returns.json

Fits ARIMA and ETS models to financial time series extracted from the
raw financial data JSON (output of fetch_financials.py). Produces
forecast distributions with confidence intervals.

Replaces the single constant growth-rate assumption in DCF with
data-derived projections that include uncertainty bands.

Enhanced capabilities (--enhanced flag):
  - GARCH(1,1) volatility forecasting: fits a GARCH model to daily returns
    and produces annualized vol forecasts with mean-reversion / persistence
    classification. Uses the `arch` library if available; falls back to a
    numpy-only maximum-likelihood GARCH(1,1) estimator.
  - Fat-tail distribution fitting: fits a Student-t distribution to returns
    and computes tail-risk VaR at 5th/1st percentiles, comparing normal vs
    t-distribution estimates and measuring observed tail-excess.
  - Monte Carlo with fat tails: simulates price paths using Student-t shocks
    instead of Gaussian, reporting 5/25/50/75/95th percentile outcomes plus
    tail-risk probabilities. Compares against normal-distribution Monte Carlo
    to quantify the fat-tail premium.
  - Volatility regime detection: classifies the current volatility environment
    (Low Vol / Normal / High Vol / Crisis) using a 63-day rolling window and
    historical percentile rank, with mean-reversion signal.
"""

import argparse
import json
import math
import os
import sys
import warnings
from datetime import datetime, timezone
from typing import Any

import numpy as np

# Suppress statsmodels warnings about convergence
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import acorr_ljungbox

    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False

# Optional: arch library for GARCH volatility modelling
try:
    from arch import arch_model

    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False

# Optional: scipy for Student-t fitting (used in fat-tail functions)
try:
    from scipy.stats import t as scipy_t
    from scipy.stats import norm as scipy_norm

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# Trading days per year used to annualise daily volatility
_TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------


def extract_series(financials: dict, field_path: list[str]) -> list[float]:
    """Extract a time series of values from nested financial data.

    field_path: e.g., ["income_statement", "revenue"]
    Returns list of annual values (most recent first).
    """
    data = financials
    for key in field_path:
        data = data.get(key, {})
        if not data:
            return []

    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        # Already in {period, value} format?
        entries = data
    else:
        return []

    values = []
    for entry in entries:
        if isinstance(entry, dict):
            val = entry.get("value")
            if val is not None:
                values.append(float(val))
        elif isinstance(entry, (int, float)):
            values.append(float(entry))

    # Reverse to chronological order (oldest first) for time-series models
    values.reverse()
    return values


# ---------------------------------------------------------------------------
# Stationarity test
# ---------------------------------------------------------------------------


def test_stationarity(series: list[float]) -> dict:
    """Augmented Dickey-Fuller test for stationarity."""
    if len(series) < 5:
        return {"stationary": False, "p_value": None, "note": "Insufficient data"}

    try:
        result = adfuller(series, autolag="AIC")
        p_value = result[1]
        return {
            "stationary": p_value < 0.05,
            "adf_statistic": round(result[0], 4),
            "p_value": round(p_value, 4),
            "critical_values": {k: round(v, 4) for k, v in result[4].items()},
        }
    except Exception as e:
        return {"stationary": False, "p_value": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Model diagnostics
# ---------------------------------------------------------------------------


def compute_model_diagnostics(fitted_model, series: list[float]) -> dict:
    """Compute model fit diagnostics: Ljung-Box, MAPE, residual stats."""
    diagnostics = {}
    try:
        residuals = fitted_model.resid
        if len(residuals) < 3:
            return {"note": "Too few residuals for diagnostics"}

        # Ljung-Box test for residual autocorrelation
        try:
            lb_result = acorr_ljungbox(residuals, lags=[min(5, len(residuals) - 1)])
            lb_pvalue = float(lb_result["lb_pvalue"].iloc[0])
            diagnostics["ljung_box"] = {
                "p_value": round(lb_pvalue, 4),
                "autocorrelation_present": lb_pvalue < 0.05,
                "interpretation": (
                    "Residuals show autocorrelation (model may be underfit)"
                    if lb_pvalue < 0.05
                    else "No significant autocorrelation in residuals (good fit)"
                ),
            }
        except Exception:
            diagnostics["ljung_box"] = {"error": "Could not compute"}

        # In-sample MAPE
        fitted_values = fitted_model.fittedvalues
        actual = np.array(series[-len(fitted_values) :], dtype=float)
        fitted_arr = np.array(fitted_values, dtype=float)
        nonzero_mask = actual != 0
        if nonzero_mask.any():
            mape = float(
                np.mean(
                    np.abs(
                        (actual[nonzero_mask] - fitted_arr[nonzero_mask])
                        / actual[nonzero_mask]
                    )
                )
                * 100
            )
            diagnostics["mape_pct"] = round(mape, 2)
            diagnostics["mape_quality"] = (
                "Excellent (<5%)"
                if mape < 5
                else "Good (5-10%)"
                if mape < 10
                else "Acceptable (10-20%)"
                if mape < 20
                else "Poor (>20%) — forecasts have wide uncertainty"
            )

        # Residual normality (Jarque-Bera via skew/kurtosis)
        res_arr = np.array(residuals, dtype=float)
        diagnostics["residual_std"] = round(float(np.std(res_arr)), 2)
        diagnostics["residual_mean"] = round(float(np.mean(res_arr)), 4)

    except Exception as e:
        diagnostics["error"] = str(e)

    return diagnostics


# ---------------------------------------------------------------------------
# ARIMA forecast
# ---------------------------------------------------------------------------


def forecast_arima(
    series: list[float], horizon: int = 5, confidence: float = 0.80
) -> dict:
    """Fit ARIMA model and produce forecasts with confidence intervals."""
    if len(series) < 5:
        return {"method": "ARIMA", "error": "Insufficient data (need ≥5 observations)"}

    try:
        # Auto-select ARIMA order (simplified grid search)
        best_aic = float("inf")
        best_order = (1, 1, 1)
        best_model = None

        # Try common orders
        orders = [(0, 1, 0), (1, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 1), (1, 1, 2)]

        for order in orders:
            try:
                model = ARIMA(series, order=order)
                fitted = model.fit()
                if fitted.aic < best_aic:
                    best_aic = fitted.aic
                    best_order = order
                    best_model = fitted
            except Exception:
                continue

        if best_model is None:
            return {"method": "ARIMA", "error": "Could not fit any ARIMA model"}

        # Forecast
        forecast_result = best_model.get_forecast(steps=horizon)
        forecast_mean = forecast_result.predicted_mean
        alpha = 1.0 - confidence
        conf_int = forecast_result.conf_int(alpha=alpha)

        forecasts = []
        for i in range(horizon):
            forecasts.append(
                {
                    "period": i + 1,
                    "mean": round(float(forecast_mean.iloc[i]), 2)
                    if i < len(forecast_mean)
                    else None,
                    "lower": round(float(conf_int.iloc[i, 0]), 2)
                    if i < len(conf_int)
                    else None,
                    "upper": round(float(conf_int.iloc[i, 1]), 2)
                    if i < len(conf_int)
                    else None,
                }
            )

        result_dict = {
            "method": "ARIMA",
            "order": list(best_order),
            "aic": round(best_aic, 2),
            "horizon": horizon,
            "confidence_level": confidence,
            "last_observed": round(float(series[-1]), 2) if series else None,
            "forecasts": forecasts,
            "implied_cagr": round(
                (forecasts[-1]["mean"] / series[-1]) ** (1 / horizon) - 1, 4
            )
            if series and series[-1] > 0 and forecasts[-1]["mean"]
            else None,
            "diagnostics": compute_model_diagnostics(best_model, series),
        }
        return result_dict

    except Exception as e:
        return {"method": "ARIMA", "error": str(e)}


# ---------------------------------------------------------------------------
# ETS (Exponential Smoothing) forecast
# ---------------------------------------------------------------------------


def forecast_ets(
    series: list[float], horizon: int = 5, confidence: float = 0.80
) -> dict:
    """Fit Holt-Winters exponential smoothing model and forecast."""
    if len(series) < 4:
        return {"method": "ETS", "error": "Insufficient data (need ≥4 observations)"}

    try:
        # Try additive trend, no seasonality (annual data rarely has seasonality)
        model = ExponentialSmoothing(
            series,
            trend="add",
            seasonal=None,
            initialization_method="estimated",
        )
        fitted = model.fit()

        # Forecast
        forecast_mean = fitted.forecast(horizon)

        # Approximate confidence intervals using residual std
        residuals = fitted.resid
        if len(residuals) > 1:
            residual_std = np.std(residuals)
            z_score = (
                1.28 if confidence == 0.80 else 1.645 if confidence == 0.90 else 1.96
            )
        else:
            residual_std = 0
            z_score = 1.28

        forecasts = []
        for i in range(horizon):
            mean_val = float(forecast_mean.iloc[i]) if i < len(forecast_mean) else None
            margin = residual_std * z_score * np.sqrt(i + 1)  # Wider as horizon grows
            forecasts.append(
                {
                    "period": i + 1,
                    "mean": round(mean_val, 2) if mean_val is not None else None,
                    "lower": round(mean_val - margin, 2)
                    if mean_val is not None
                    else None,
                    "upper": round(mean_val + margin, 2)
                    if mean_val is not None
                    else None,
                }
            )

        return {
            "method": "ETS (Holt-Winters, additive trend)",
            "aic": round(fitted.aic, 2) if hasattr(fitted, "aic") else None,
            "horizon": horizon,
            "confidence_level": confidence,
            "last_observed": round(float(series[-1]), 2) if series else None,
            "forecasts": forecasts,
            "implied_cagr": round(
                (forecasts[-1]["mean"] / series[-1]) ** (1 / horizon) - 1, 4
            )
            if series and series[-1] > 0 and forecasts[-1]["mean"]
            else None,
            "residual_std": round(float(residual_std), 2),
        }

    except Exception as e:
        return {"method": "ETS", "error": str(e)}


# ---------------------------------------------------------------------------
# Naive forecast (constant growth fallback)
# ---------------------------------------------------------------------------


def forecast_naive(series: list[float], horizon: int = 5) -> dict:
    """Simple constant-CAGR forecast as fallback when models fail."""
    if len(series) < 2:
        return {"method": "Naive (constant CAGR)", "error": "Insufficient data"}

    if series[0] > 0 and series[-1] > 0:
        cagr = (series[-1] / series[0]) ** (1 / (len(series) - 1)) - 1
    else:
        cagr = 0

    forecasts = []
    last = series[-1]
    for i in range(horizon):
        last = last * (1 + cagr)
        forecasts.append(
            {
                "period": i + 1,
                "mean": round(last, 2),
                "lower": round(last * 0.7, 2),  # ±30% ad-hoc band
                "upper": round(last * 1.3, 2),
            }
        )

    return {
        "method": "Naive (constant CAGR)",
        "historical_cagr": round(cagr, 4),
        "horizon": horizon,
        "last_observed": round(float(series[-1]), 2) if series else None,
        "forecasts": forecasts,
        "implied_cagr": round(cagr, 4),
    }


# ---------------------------------------------------------------------------
# Combined forecast
# ---------------------------------------------------------------------------


def forecast_series(
    series: list[float],
    horizon: int = 5,
    confidence: float = 0.80,
    method: str = "auto",
) -> dict:
    """Forecast a single time series with the best available method."""
    if not series or len(series) < 2:
        return {"error": "Insufficient data", "observations": len(series)}

    result = {
        "observations": len(series),
        "historical_values": [round(v, 2) for v in series],
    }

    # Stationarity test
    if STATSMODELS_AVAILABLE and len(series) >= 5:
        result["stationarity_test"] = test_stationarity(series)

    if method == "arima" and STATSMODELS_AVAILABLE:
        result["forecast"] = forecast_arima(series, horizon, confidence)
        if "error" in result["forecast"]:
            result["forecast"] = forecast_ets(series, horizon, confidence)
    elif method == "ets" and STATSMODELS_AVAILABLE:
        result["forecast"] = forecast_ets(series, horizon, confidence)
        if "error" in result["forecast"]:
            result["forecast"] = forecast_arima(series, horizon, confidence)
    elif method == "naive":
        result["forecast"] = forecast_naive(series, horizon)
    else:
        # Auto: try ARIMA first, then ETS, then naive
        if STATSMODELS_AVAILABLE:
            arima_result = forecast_arima(series, horizon, confidence)
            if "error" not in arima_result:
                result["forecast"] = arima_result
            else:
                ets_result = forecast_ets(series, horizon, confidence)
                if "error" not in ets_result:
                    result["forecast"] = ets_result
                else:
                    result["forecast"] = forecast_naive(series, horizon)
        else:
            result["forecast"] = forecast_naive(series, horizon)

    return result


# ---------------------------------------------------------------------------
# Ensemble forecast (combine multiple methods)
# ---------------------------------------------------------------------------


def forecast_ensemble(
    series: list[float], horizon: int = 5, confidence: float = 0.80
) -> dict:
    """Produce ensemble forecast combining ARIMA, ETS, and naive methods.

    Weights: ARIMA 0.4, ETS 0.4, Naive 0.2 when all available.
    """
    methods = {}

    if STATSMODELS_AVAILABLE:
        methods["arima"] = forecast_arima(series, horizon, confidence)
        methods["ets"] = forecast_ets(series, horizon, confidence)
    methods["naive"] = forecast_naive(series, horizon)

    # Compute ensemble mean
    ensemble_forecasts = []
    weights = {"arima": 0.4, "ets": 0.4, "naive": 0.2}

    for i in range(horizon):
        weighted_sum = 0.0
        total_weight = 0.0
        for name, result in methods.items():
            if "forecasts" in result and i < len(result["forecasts"]):
                mean_val = result["forecasts"][i].get("mean")
                if mean_val is not None:
                    w = weights.get(name, 0.2)
                    weighted_sum += mean_val * w
                    total_weight += w

        if total_weight > 0:
            ensemble_mean = weighted_sum / total_weight
        else:
            ensemble_mean = None

        # Ensemble lower = min of lower bounds
        lower_vals = []
        upper_vals = []
        for name, result in methods.items():
            if "forecasts" in result and i < len(result["forecasts"]):
                lo = result["forecasts"][i].get("lower")
                hi = result["forecasts"][i].get("upper")
                if lo is not None:
                    lower_vals.append(lo)
                if hi is not None:
                    upper_vals.append(hi)

        ensemble_lower = min(lower_vals) if lower_vals else None
        ensemble_upper = max(upper_vals) if upper_vals else None

        ensemble_forecasts.append(
            {
                "period": i + 1,
                "mean": round(ensemble_mean, 2) if ensemble_mean is not None else None,
                "lower": round(ensemble_lower, 2)
                if ensemble_lower is not None
                else None,
                "upper": round(ensemble_upper, 2)
                if ensemble_upper is not None
                else None,
            }
        )

    last_val = series[-1] if series else 1
    ensemble_cagr = (
        (ensemble_forecasts[-1]["mean"] / last_val) ** (1 / horizon) - 1
        if last_val > 0 and ensemble_forecasts[-1]["mean"]
        else None
    )

    return {
        "method": "Ensemble (ARIMA + ETS + Naive)",
        "horizon": horizon,
        "confidence_level": confidence,
        "last_observed": round(float(last_val), 2) if series else None,
        "ensemble_forecasts": ensemble_forecasts,
        "ensemble_cagr": round(ensemble_cagr, 4) if ensemble_cagr is not None else None,
        "individual_methods": {
            name: {
                "method": result.get("method", name),
                "cagr": result.get("implied_cagr"),
                "error": result.get("error"),
            }
            for name, result in methods.items()
        },
    }


# ---------------------------------------------------------------------------
# GARCH(1,1) helpers — numpy-only MLE fallback
# ---------------------------------------------------------------------------


def _garch_loglikelihood(params: np.ndarray, returns: np.ndarray) -> float:
    """Negative log-likelihood for a GARCH(1,1) model (used in numpy fallback).

    Model:
        sigma2_t = omega + alpha * eps_{t-1}^2 + beta * sigma2_{t-1}

    params = [omega, alpha, beta]
    """
    omega, alpha, beta = params
    n = len(returns)
    sigma2 = np.empty(n)
    # Initialise with unconditional variance
    sigma2[0] = np.var(returns)
    for i in range(1, n):
        sigma2[i] = omega + alpha * returns[i - 1] ** 2 + beta * sigma2[i - 1]
        if sigma2[i] <= 0:
            return 1e10  # Penalise invalid variance
    ll = -0.5 * np.sum(np.log(2 * math.pi * sigma2) + returns**2 / sigma2)
    return -ll  # Return negative (we minimise)


def _fit_garch_numpy(returns: np.ndarray) -> dict[str, float]:
    """Estimate GARCH(1,1) parameters via scipy.optimize or a grid search.

    Returns dict with keys: omega, alpha, beta.
    Falls back to reasonable defaults if optimisation fails.
    """
    # Try scipy minimisation first
    try:
        from scipy.optimize import minimize

        init = np.array([1e-6, 0.1, 0.85])
        bounds = [(1e-9, 1.0), (1e-6, 1.0), (1e-6, 1.0)]
        result = minimize(
            _garch_loglikelihood,
            init,
            args=(returns,),
            method="L-BFGS-B",
            bounds=bounds,
        )
        omega, alpha, beta = result.x
        # Enforce stationarity and positivity
        if alpha + beta < 1.0 and omega > 0 and alpha > 0 and beta > 0:
            return {"omega": float(omega), "alpha": float(alpha), "beta": float(beta)}
    except Exception:
        pass

    # Coarse grid search fallback (no scipy)
    best_ll = float("inf")
    best_params = {"omega": 1e-6, "alpha": 0.1, "beta": 0.85}
    var_init = float(np.var(returns))
    for alpha in [0.05, 0.10, 0.15, 0.20]:
        for beta in [0.75, 0.80, 0.85, 0.88]:
            if alpha + beta >= 1.0:
                continue
            omega = var_init * (1.0 - alpha - beta)
            if omega <= 0:
                continue
            params = np.array([omega, alpha, beta])
            ll = _garch_loglikelihood(params, returns)
            if ll < best_ll:
                best_ll = ll
                best_params = {"omega": omega, "alpha": alpha, "beta": beta}
    return best_params


# ---------------------------------------------------------------------------
# Multi-model GARCH selection
# ---------------------------------------------------------------------------


def _try_fit_arch_model(
    r_pct: np.ndarray,
    vol_model: str,
    p: int,
    o: int,
    q: int,
    dist: str,
) -> tuple[dict[str, Any] | None, Any]:
    """Try to fit a single arch model specification; return (info_dict, fitted).

    Returns (None, None) if the model fails to converge or raises an error.
    """
    try:
        am = arch_model(r_pct, vol=vol_model, p=p, o=o, q=q, dist=dist, rescale=False)
        res = am.fit(disp="off", show_warning=False)

        # Build a human-readable model name
        dist_label = {
            "normal": "Normal",
            "studentst": "StudentT",
            "skewt": "SkewT",
        }.get(dist, dist)
        vol_label = {
            "GARCH": "GARCH",
            "EGARCH": "EGARCH",
        }.get(vol_model, vol_model)

        if o > 0:
            # GJR-GARCH / TARCH variants
            if vol_model == "GARCH" and o > 0:
                vol_label = "GJR-GARCH"
            name = f"{vol_label}({p},{o},{q})-{dist_label}"
        else:
            name = f"{vol_label}({p},{q})-{dist_label}"

        info = {
            "model": name,
            "vol": vol_model,
            "p": p,
            "o": o,
            "q": q,
            "dist": dist,
            "aic": round(float(res.aic), 4),
            "bic": round(float(res.bic), 4),
            "llf": round(float(res.loglikelihood), 4),
        }
        return info, res
    except Exception:
        return None, None


def compute_garch_multi_model(
    returns: list[float], forecast_horizon: int = 21
) -> dict[str, Any]:
    """Fit multiple GARCH variants and select the best by BIC.

    Tries combinations of:
      - Volatility models: GARCH, EGARCH, GJR-GARCH (GARCH with o=1)
      - Orders: (1,1), (2,1), (1,2)
      - Distributions: normal, studentst, skewt

    Selects the model with the lowest BIC (more conservative than AIC).
    Runs residual diagnostics (Ljung-Box, ARCH-LM) on the best model.

    Returns the same keys as compute_garch_volatility for backward compat,
    plus additional ``model_selection`` and ``residual_diagnostics`` keys.
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 30:
        return {
            "error": "Insufficient data (need ≥30 daily returns)",
            "methodology": "Multi-model GARCH",
        }
    if not ARCH_AVAILABLE:
        return {
            "error": "arch library required for multi-model GARCH",
            "methodology": "Multi-model GARCH",
        }

    r_pct = r * 100.0  # scale to pct for numerical stability

    # Build model grid
    vol_models = ["GARCH", "EGARCH"]
    orders = [(1, 1), (2, 1), (1, 2)]
    distributions = ["normal", "studentst", "skewt"]

    comparison_table: list[dict[str, Any]] = []
    best_bic = float("inf")
    best_info: dict[str, Any] | None = None
    best_res = None

    for vol in vol_models:
        for p_val, q_val in orders:
            for dist in distributions:
                # GJR-GARCH: GARCH with o=1 (leverage term)
                for o_val in [0, 1] if vol == "GARCH" else [0]:
                    # Skip high-order EGARCH that may be unstable
                    if vol == "EGARCH" and max(p_val, q_val) > 2:
                        continue
                    info, res = _try_fit_arch_model(
                        r_pct, vol, p_val, o_val, q_val, dist
                    )
                    if info is None or res is None:
                        continue
                    comparison_table.append(info)
                    if info["bic"] < best_bic:
                        best_bic = info["bic"]
                        best_info = info
                        best_res = res

    if best_res is None or best_info is None:
        # All models failed — fall back to basic GARCH(1,1)
        fallback_info, fallback_res = _try_fit_arch_model(
            r_pct, "GARCH", 1, 0, 1, "normal"
        )
        if fallback_res is None:
            return {
                "error": "All GARCH model specifications failed to converge",
                "methodology": "Multi-model GARCH",
            }
        best_info = fallback_info or {
            "model": "GARCH(1,1)-Normal",
            "bic": None,
            "aic": None,
            "llf": None,
        }
        best_res = fallback_res

    # --- Extract parameters from best model ---
    params = best_res.params
    omega = float(params.get("omega", 0))
    # alpha, gamma, beta keys depend on p, o, q
    alpha = float(params.get("alpha[1]", 0))
    beta = float(params.get("beta[1]", 0))
    gamma = float(params.get("gamma[1]", 0)) if "gamma[1]" in params else 0.0

    # Persistence approximation: sum of all ARCH + GARCH coefficients
    # For GJR-GARCH: alpha + gamma/2 + beta
    persistence = alpha + gamma * 0.5 + beta
    if best_info.get("vol") == "EGARCH":
        # EGARCH persistence is approximate; use |alpha| + |beta| as proxy
        persistence = abs(alpha) + abs(beta)

    # Current conditional variance
    cond_vol = best_res.conditional_volatility
    if hasattr(cond_vol, "iloc"):
        current_var_pct2 = float(cond_vol.iloc[-1] ** 2)
    else:
        current_var_pct2 = float(np.asarray(cond_vol)[-1] ** 2)

    # Unconditional variance (for standard GARCH-family)
    if best_info.get("vol") == "GARCH" or (
        best_info.get("vol") == "GARCH" and best_info.get("o", 0) > 0
    ):
        uncond_var_pct2 = (
            omega / max(1.0 - persistence, 1e-9) if persistence < 1 else omega / 1e-9
        )
    else:
        # EGARCH: use sample variance as proxy for unconditional level
        uncond_var_pct2 = float(np.var(r_pct))

    # Forecast — EGARCH/TARCH require simulation-based forecasts for horizon > 1
    try:
        fc = best_res.forecast(horizon=forecast_horizon, reindex=False)
        daily_var_forecasts_pct2 = (fc.variance.values[-1] / 1e4).tolist()
    except ValueError:
        # Analytic forecasts not supported for this model/horizon combo
        fc = best_res.forecast(
            horizon=forecast_horizon,
            method="simulation",
            reindex=False,
        )
        fc_var = np.asarray(fc.variance.values[-1], dtype=float)
        daily_var_forecasts_pct2 = (fc_var / 1e4).tolist()

    # --- Residual diagnostics ---
    residual_diagnostics: dict[str, Any] = {}
    try:
        resid_arr = np.asarray(best_res.resid, dtype=float)
        cond_vol_arr = np.asarray(best_res.conditional_volatility, dtype=float)
        std_resid = resid_arr / np.where(cond_vol_arr != 0, cond_vol_arr, 1.0)
        std_resid_arr = std_resid[np.isfinite(std_resid)]

        # Ljung-Box test on standardized residuals (lag 10)
        try:
            from statsmodels.stats.diagnostic import acorr_ljungbox as _lb

            lb_result = _lb(std_resid_arr, lags=[min(10, len(std_resid_arr) // 5, 10)])
            lb_stat = float(lb_result["lb_stat"].iloc[0])
            lb_pvalue = float(lb_result["lb_pvalue"].iloc[0])
            residual_diagnostics["ljung_box_stat"] = round(lb_stat, 4)
            residual_diagnostics["ljung_box_pvalue"] = round(lb_pvalue, 4)
            residual_diagnostics["standardized_residuals_ok"] = bool(lb_pvalue > 0.05)
        except Exception:
            residual_diagnostics["ljung_box_stat"] = None
            residual_diagnostics["ljung_box_pvalue"] = None
            residual_diagnostics["standardized_residuals_ok"] = None

        # ARCH-LM test for remaining heteroskedasticity
        try:
            from statsmodels.stats.diagnostic import het_arch

            arch_lm_stat, arch_lm_pvalue, _, _ = het_arch(
                std_resid_arr, nlags=min(5, len(std_resid_arr) // 5, 5)
            )
            residual_diagnostics["arch_lm_stat"] = round(float(arch_lm_stat), 4)
            residual_diagnostics["arch_lm_pvalue"] = round(float(arch_lm_pvalue), 4)
        except Exception:
            residual_diagnostics["arch_lm_stat"] = None
            residual_diagnostics["arch_lm_pvalue"] = None

        # Jarque-Bera normality test on standardized residuals
        if SCIPY_AVAILABLE:
            try:
                from scipy.stats import jarque_bera

                jb_stat, jb_pvalue = jarque_bera(std_resid_arr)
                residual_diagnostics["residuals_normal"] = bool(jb_pvalue > 0.05)
                residual_diagnostics["jarque_bera_stat"] = round(float(jb_stat), 4)
                residual_diagnostics["jarque_bera_pvalue"] = round(float(jb_pvalue), 4)
            except Exception:
                residual_diagnostics["residuals_normal"] = None
        else:
            residual_diagnostics["residuals_normal"] = None

    except Exception:
        residual_diagnostics["note"] = "Could not compute residual diagnostics"

    # --- Build output (backward compatible with compute_garch_volatility) ---
    current_ann_vol = float(np.sqrt(current_var_pct2 * _TRADING_DAYS))
    forecasted_ann_vols = [
        float(math.sqrt(v * _TRADING_DAYS)) for v in daily_var_forecasts_pct2
    ]
    mean_forecast_vol = float(np.mean(forecasted_ann_vols))
    uncond_ann_vol = float(math.sqrt(uncond_var_pct2 * _TRADING_DAYS))

    # Realised vol from recent 21-day window (for reference)
    realised_vol = (
        float(np.std(r[-21:]) * math.sqrt(_TRADING_DAYS)) if len(r) >= 21 else None
    )

    methodology = f"{best_info['model']} via arch (BIC selected)"

    result: dict[str, Any] = {
        "current_annualized_vol": round(realised_vol, 4) if realised_vol else None,
        "garch_annualized_vol_now": round(current_ann_vol, 4),
        "forecasted_annualized_vol": round(mean_forecast_vol, 4),
        "unconditional_vol": round(uncond_ann_vol, 4),
        "vol_term_structure": [round(v, 4) for v in forecasted_ann_vols],
        "persistence": round(persistence, 4),
        "mean_reverting": persistence < 0.95,
        "parameters": {
            "omega": round(omega, 8),
            "alpha": round(alpha, 4),
            "beta": round(beta, 4),
        },
        "forecast_horizon_days": forecast_horizon,
        "methodology": methodology,
        # New multi-model keys
        "model_selection": {
            "best_model": best_info.get("model", "unknown"),
            "best_bic": best_info.get("bic"),
            "best_aic": best_info.get("aic"),
            "best_llf": best_info.get("llf"),
            "models_compared": len(comparison_table),
            "comparison_table": sorted(
                comparison_table, key=lambda x: x.get("bic", float("inf"))
            ),
        },
        "residual_diagnostics": residual_diagnostics,
    }

    # Include gamma in parameters if present (GJR-GARCH)
    if gamma != 0.0:
        result["parameters"]["gamma"] = round(gamma, 4)

    return result


# ---------------------------------------------------------------------------
# GARCH(1,1) volatility forecast
# ---------------------------------------------------------------------------


def compute_garch_volatility(
    returns: list[float], forecast_horizon: int = 21
) -> dict[str, Any]:
    """Fit a GARCH model to daily returns and forecast volatility.

    When the ``arch`` library is available, delegates to
    :func:`compute_garch_multi_model` which tries multiple GARCH variants
    (GARCH, EGARCH, GJR-GARCH across several orders and distributions) and
    selects the best model by BIC.

    When ``arch`` is not available, falls back to a numpy-only
    maximum-likelihood GARCH(1,1) estimator.

    Args:
        returns: Daily log returns (e.g. np.log(price_t / price_{t-1})).
                 Must have at least 30 observations.
        forecast_horizon: Number of trading days to forecast (default 21 ≈ 1 month).

    Returns:
        dict with keys:
          - current_annualized_vol: realised vol from recent 21-day window (annualised)
          - garch_annualized_vol_now: GARCH conditional vol today (annualised)
          - forecasted_annualized_vol: mean forecast vol over horizon (annualised)
          - vol_term_structure: list of daily annualised vol forecasts
          - persistence: alpha + beta (closeness to 1 = more persistent shocks)
          - mean_reverting: True if persistence < 0.95
          - unconditional_vol: long-run GARCH vol (annualised)
          - parameters: {omega, alpha, beta}
          - methodology: description string
          - model_selection: (arch only) model comparison table and best model info
          - residual_diagnostics: (arch only) Ljung-Box, ARCH-LM, normality tests
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 30:
        return {
            "error": "Insufficient data (need ≥30 daily returns)",
            "methodology": "GARCH(1,1)",
        }

    try:
        if ARCH_AVAILABLE:
            # Delegate to multi-model selection
            return compute_garch_multi_model(returns, forecast_horizon)
        else:
            # Numpy-only path
            params = _fit_garch_numpy(r)
            omega = params["omega"]
            alpha = params["alpha"]
            beta = params["beta"]
            # Compute in-sample conditional variance
            n = len(r)
            sigma2 = np.empty(n)
            sigma2[0] = np.var(r)
            for i in range(1, n):
                sigma2[i] = omega + alpha * r[i - 1] ** 2 + beta * sigma2[i - 1]
            current_var_pct2 = float(sigma2[-1])  # already in decimal^2 units
            # Multi-step variance forecast: E[sigma2_{t+h}] converges to unconditional var
            uncond_var = omega / max(1.0 - alpha - beta, 1e-9)
            persistence = alpha + beta
            daily_var_forecasts = []
            prev_var = current_var_pct2
            for _ in range(forecast_horizon):
                next_var = omega + persistence * prev_var
                daily_var_forecasts.append(float(next_var))
                prev_var = next_var
            methodology = (
                "GARCH(1,1) numpy-only MLE fallback (arch library not installed)"
            )

        persistence = alpha + beta
        uncond_var = omega / max(1.0 - alpha - beta, 1e-9)

        # Annualise: vol = sqrt(var * 252)
        current_ann_vol = float(np.sqrt(current_var_pct2 * _TRADING_DAYS))
        forecasted_ann_vols = [
            float(math.sqrt(v * _TRADING_DAYS)) for v in daily_var_forecasts
        ]
        mean_forecast_vol = float(np.mean(forecasted_ann_vols))
        uncond_ann_vol = float(math.sqrt(uncond_var * _TRADING_DAYS))

        # Realised vol from recent 21-day window (for reference)
        realised_vol = (
            float(np.std(r[-21:]) * math.sqrt(_TRADING_DAYS)) if len(r) >= 21 else None
        )

        return {
            "current_annualized_vol": round(realised_vol, 4) if realised_vol else None,
            "garch_annualized_vol_now": round(current_ann_vol, 4),
            "forecasted_annualized_vol": round(mean_forecast_vol, 4),
            "unconditional_vol": round(uncond_ann_vol, 4),
            "vol_term_structure": [round(v, 4) for v in forecasted_ann_vols],
            "persistence": round(persistence, 4),
            "mean_reverting": persistence < 0.95,
            "parameters": {
                "omega": round(omega, 8),
                "alpha": round(alpha, 4),
                "beta": round(beta, 4),
            },
            "forecast_horizon_days": forecast_horizon,
            "methodology": methodology,
        }

    except Exception as exc:
        return {"error": str(exc), "methodology": "GARCH(1,1)"}


# ---------------------------------------------------------------------------
# Fat-tail distribution fitting
# ---------------------------------------------------------------------------


def fit_tail_distribution(returns: list[float]) -> dict[str, Any]:
    """Fit a Student-t distribution to daily returns and analyse tail risk.

    Student-t is preferred over normal for financial returns because it
    naturally captures excess kurtosis (fat tails).

    Args:
        returns: Daily log returns. Need at least 20 observations.

    Returns:
        dict with keys:
          - t_params: {df, loc, scale} — degrees of freedom (lower = fatter tails)
          - var_5pct_t: 5th-percentile Value-at-Risk under t-distribution
          - var_1pct_t: 1st-percentile VaR under t-distribution
          - var_5pct_normal: 5th-percentile VaR under normal distribution
          - var_1pct_normal: 1st-percentile VaR under normal distribution
          - var_comparison: table comparing normal vs t VaR at each level
          - tail_ratio_5pct: actual extreme events / normal-predicted (>1 = fatter tails)
          - tail_ratio_1pct: same at 1% threshold
          - excess_kurtosis: sample excess kurtosis (0 = normal, >0 = fat tails)
          - methodology: description string
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 20:
        return {"error": "Insufficient data (need ≥20 daily returns)"}

    mu = float(np.mean(r))
    sigma = float(np.std(r, ddof=1))
    n = len(r)

    # Excess kurtosis (sample)
    excess_kurt = float(
        np.mean((r - mu) ** 4) / max(np.mean((r - mu) ** 2) ** 2, 1e-30) - 3.0
    )

    # --- Fit Student-t ---
    if SCIPY_AVAILABLE:
        df_fit, loc_fit, scale_fit = scipy_t.fit(r, floc=mu)
        # VaR from fitted t
        var_5_t = float(scipy_t.ppf(0.05, df=df_fit, loc=loc_fit, scale=scale_fit))
        var_1_t = float(scipy_t.ppf(0.01, df=df_fit, loc=loc_fit, scale=scale_fit))
        # VaR from normal with same mean/std
        var_5_n = float(scipy_norm.ppf(0.05, loc=mu, scale=sigma))
        var_1_n = float(scipy_norm.ppf(0.01, loc=mu, scale=sigma))
        methodology = "Student-t MLE via scipy.stats.t.fit"
    else:
        # Method-of-moments: match variance and kurtosis to Student-t
        # For t(df): kurtosis = 6/(df-4) for df>4, else use df=6 as safe fallback
        if excess_kurt > 0:
            df_fit = max(4.5, 6.0 / max(excess_kurt, 0.01) + 4.0)
        else:
            df_fit = 30.0  # Near-normal
        loc_fit = mu
        scale_fit = sigma * math.sqrt((df_fit - 2.0) / df_fit) if df_fit > 2 else sigma
        # t quantiles via approximation using normal when df is large
        t_crit_5 = _t_ppf(0.05, df_fit)
        t_crit_1 = _t_ppf(0.01, df_fit)
        var_5_t = loc_fit + scale_fit * t_crit_5
        var_1_t = loc_fit + scale_fit * t_crit_1
        # Normal VaR
        var_5_n = mu - 1.6449 * sigma
        var_1_n = mu - 2.3263 * sigma
        methodology = "Student-t method-of-moments (scipy not installed)"

    # Observed tail frequencies vs normal prediction
    threshold_5n = var_5_n
    threshold_1n = var_1_n
    observed_5 = float(np.mean(r < threshold_5n))
    observed_1 = float(np.mean(r < threshold_1n))
    tail_ratio_5 = round(observed_5 / 0.05, 3) if observed_5 > 0 else None
    tail_ratio_1 = round(observed_1 / 0.01, 3) if observed_1 > 0 else None

    return {
        "observations": n,
        "t_params": {
            "df": round(df_fit, 2),
            "loc": round(loc_fit, 6),
            "scale": round(scale_fit, 6),
        },
        "var_5pct_t": round(var_5_t, 6),
        "var_1pct_t": round(var_1_t, 6),
        "var_5pct_normal": round(var_5_n, 6),
        "var_1pct_normal": round(var_1_n, 6),
        "var_comparison": {
            "5pct": {
                "normal": round(var_5_n, 4),
                "student_t": round(var_5_t, 4),
                "fat_tail_premium": round(abs(var_5_t - var_5_n), 4),
            },
            "1pct": {
                "normal": round(var_1_n, 4),
                "student_t": round(var_1_t, 4),
                "fat_tail_premium": round(abs(var_1_t - var_1_n), 4),
            },
        },
        "tail_ratio_5pct": tail_ratio_5,
        "tail_ratio_1pct": tail_ratio_1,
        "excess_kurtosis": round(excess_kurt, 4),
        "mean_daily_return": round(mu, 6),
        "daily_std": round(sigma, 6),
        "methodology": methodology,
    }


def _t_ppf(p: float, df: float) -> float:
    """Approximate quantile of Student-t(df) at probability p (no scipy).

    Uses a rational approximation of the normal quantile scaled by the
    Wilson-Hilferty cube-root transformation for moderate df.
    Only accurate enough for df >= 3 and p in [0.001, 0.999].
    """

    # Normal quantile via rational approximation (Abramowitz & Stegun 26.2.17)
    def _norm_ppf(prob: float) -> float:
        if prob <= 0 or prob >= 1:
            return float("nan")
        # Rational approximation for p < 0.5; reflect for p >= 0.5
        p0 = prob if prob < 0.5 else 1.0 - prob
        t_val = math.sqrt(-2.0 * math.log(p0))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        num = c0 + c1 * t_val + c2 * t_val**2
        den = 1.0 + d1 * t_val + d2 * t_val**2 + d3 * t_val**3
        z = t_val - num / den
        return -z if prob < 0.5 else z

    z = _norm_ppf(p)
    if df >= 100:
        return z
    # Cornish-Fisher expansion for t-distribution
    g1 = z**3 + z
    g2 = 5 * z**5 + 16 * z**3 + 3 * z
    t_q = z + g1 / (4 * df) + g2 / (96 * df**2)
    return t_q


# ---------------------------------------------------------------------------
# Monte Carlo with fat tails
# ---------------------------------------------------------------------------


def monte_carlo_fat_tails(
    current_price: float,
    mu: float,
    sigma: float,
    df: float,
    days: int = 252,
    simulations: int = 10000,
) -> dict[str, Any]:
    """Monte Carlo price simulation using Student-t shocks (fat tails).

    Compares against a standard normal-distribution simulation to quantify
    the fat-tail premium on tail-risk probabilities.

    Args:
        current_price: Current stock price.
        mu: Daily drift (log return mean).
        sigma: Daily volatility (log return std).
        df: Degrees of freedom for Student-t distribution (lower = fatter tails).
            Use output of fit_tail_distribution()["t_params"]["df"].
        days: Simulation horizon in trading days (default 252 = 1 year).
        simulations: Number of Monte Carlo paths (default 10 000).

    Returns:
        dict with keys:
          - price_percentiles_t: price distribution at horizon under t-distribution
          - price_percentiles_normal: same under normal distribution
          - prob_decline_20pct_t / _normal: probability of >20% loss
          - prob_gain_30pct_t / _normal: probability of >30% gain
          - fat_tail_effect: dict comparing key tail probabilities
          - methodology: description string
    """
    if current_price <= 0:
        return {"error": "current_price must be positive"}
    if df <= 2:
        return {"error": "df must be > 2 for finite variance"}

    rng = np.random.default_rng(seed=42)

    # Scale factor so t-distributed shocks have the same variance as normal(0, sigma)
    # Var(t_df) = df/(df-2), so scale = sigma / sqrt(df/(df-2))
    t_scale = sigma / math.sqrt(df / (df - 2.0))

    # --- Student-t simulation ---
    # Draw standardised t(df) shocks, scale to match sigma
    t_shocks = rng.standard_t(df=df, size=(simulations, days)) * t_scale
    # Log-return paths: mu*dt + shock (dt=1 day, so no sqrt needed for shock)
    log_ret_t = mu + t_shocks
    final_log_t = log_ret_t.sum(axis=1)
    final_prices_t = current_price * np.exp(final_log_t)

    # --- Normal simulation ---
    norm_shocks = rng.normal(loc=mu, scale=sigma, size=(simulations, days))
    final_log_n = norm_shocks.sum(axis=1)
    final_prices_n = current_price * np.exp(final_log_n)

    def _percentiles(prices: np.ndarray) -> dict[str, float]:
        pcts = np.percentile(prices, [5, 25, 50, 75, 95])
        return {
            "p5": round(float(pcts[0]), 2),
            "p25": round(float(pcts[1]), 2),
            "p50": round(float(pcts[2]), 2),
            "p75": round(float(pcts[3]), 2),
            "p95": round(float(pcts[4]), 2),
        }

    decline_threshold = current_price * 0.80  # >20% decline
    gain_threshold = current_price * 1.30  # >30% gain

    prob_decline_t = float(np.mean(final_prices_t < decline_threshold))
    prob_decline_n = float(np.mean(final_prices_n < decline_threshold))
    prob_gain_t = float(np.mean(final_prices_t > gain_threshold))
    prob_gain_n = float(np.mean(final_prices_n > gain_threshold))

    return {
        "inputs": {
            "current_price": current_price,
            "daily_mu": round(mu, 6),
            "daily_sigma": round(sigma, 6),
            "t_df": round(df, 2),
            "horizon_days": days,
            "simulations": simulations,
        },
        "price_percentiles_t": _percentiles(final_prices_t),
        "price_percentiles_normal": _percentiles(final_prices_n),
        "prob_decline_20pct_t": round(prob_decline_t, 4),
        "prob_decline_20pct_normal": round(prob_decline_n, 4),
        "prob_gain_30pct_t": round(prob_gain_t, 4),
        "prob_gain_30pct_normal": round(prob_gain_n, 4),
        "fat_tail_effect": {
            "downside_tail_ratio": round(prob_decline_t / max(prob_decline_n, 1e-6), 3),
            "upside_tail_ratio": round(prob_gain_t / max(prob_gain_n, 1e-6), 3),
            "note": (
                "downside_tail_ratio > 1 means fat tails increase crash probability vs normal. "
                "upside_tail_ratio > 1 means fat tails also increase large-gain probability."
            ),
        },
        "methodology": (
            f"Monte Carlo ({simulations:,} paths, {days} days) using Student-t(df={df:.1f}) "
            "shocks scaled to match empirical sigma. Normal simulation uses same mu/sigma."
        ),
    }


# ---------------------------------------------------------------------------
# Volatility regime detection
# ---------------------------------------------------------------------------


def detect_volatility_regime(returns: list[float], window: int = 63) -> dict[str, Any]:
    """Classify the current volatility regime using rolling historical vol.

    Regimes are defined relative to the full history of rolling vol:
      - Low Vol:  current rolling vol < 25th percentile
      - Normal:   25th <= current rolling vol <= 75th percentile
      - High Vol: current rolling vol > 75th percentile
      - Crisis:   current rolling vol > 95th percentile

    Args:
        returns: Daily log returns. Need at least window + 20 observations.
        window: Rolling window in trading days (default 63 ≈ 3 months).

    Returns:
        dict with keys:
          - current_regime: one of "Low Vol", "Normal", "High Vol", "Crisis"
          - current_rolling_vol: annualised vol from most recent window
          - vol_percentile_rank: where current vol sits in full history (0–100)
          - regime_thresholds: {p25, p75, p95} annualised vol levels
          - regime_history: last 4 quarters (most recent first) with vol + regime
          - mean_reversion_signal: "Buy signal (vol elevated, mean-reversion expected)"
            or "Neutral" or "Caution (low vol, complacency risk)"
          - methodology: description string
    """
    r = np.asarray(returns, dtype=float)
    min_obs = window + 20
    if len(r) < min_obs:
        return {
            "error": f"Insufficient data (need ≥{min_obs} daily returns for window={window})",
            "methodology": "Rolling volatility regime detection",
        }

    # Compute rolling annualised vol for every position from index `window-1` onward
    rolling_vols = []
    for i in range(window - 1, len(r)):
        window_slice = r[i - window + 1 : i + 1]
        rolling_vols.append(
            float(np.std(window_slice, ddof=1) * math.sqrt(_TRADING_DAYS))
        )

    rv = np.asarray(rolling_vols)
    p25, p75, p95 = (
        float(np.percentile(rv, 25)),
        float(np.percentile(rv, 75)),
        float(np.percentile(rv, 95)),
    )
    current_vol = rolling_vols[-1]
    percentile_rank = float(np.mean(rv <= current_vol) * 100.0)

    # Regime classification
    if current_vol > p95:
        regime = "Crisis"
    elif current_vol > p75:
        regime = "High Vol"
    elif current_vol >= p25:
        regime = "Normal"
    else:
        regime = "Low Vol"

    # Mean-reversion signal
    if regime in ("High Vol", "Crisis"):
        mr_signal = "Buy signal (vol elevated, mean-reversion expected)"
    elif regime == "Low Vol":
        mr_signal = "Caution (low vol, complacency risk — vol spike possible)"
    else:
        mr_signal = "Neutral"

    # Regime history: snapshot each quarter (≈63 trading days) for last 4 quarters
    history = []
    quarter_step = 63
    for q in range(4):
        idx = -(1 + q * quarter_step)
        if abs(idx) > len(rolling_vols):
            break
        q_vol = rolling_vols[idx]
        if q_vol > p95:
            q_regime = "Crisis"
        elif q_vol > p75:
            q_regime = "High Vol"
        elif q_vol >= p25:
            q_regime = "Normal"
        else:
            q_regime = "Low Vol"
        history.append(
            {
                "quarter_offset": q,
                "annualized_vol": round(q_vol, 4),
                "regime": q_regime,
            }
        )

    return {
        "current_regime": regime,
        "current_rolling_vol": round(current_vol, 4),
        "vol_percentile_rank": round(percentile_rank, 1),
        "regime_thresholds": {
            "p25_low_vol_cutoff": round(p25, 4),
            "p75_high_vol_cutoff": round(p75, 4),
            "p95_crisis_cutoff": round(p95, 4),
        },
        "regime_history_last_4q": history,
        "mean_reversion_signal": mr_signal,
        "window_days": window,
        "total_observations": len(r),
        "methodology": (
            f"Rolling {window}-day annualised volatility percentile rank "
            "against full history. Thresholds: p25/p75/p95."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Time-series forecasting for financial data"
    )
    parser.add_argument("input", help="Path to raw financial data JSON")
    parser.add_argument(
        "--horizon", type=int, default=5, help="Forecast horizon in years (default: 5)"
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.80,
        help="Confidence level (default: 0.80)",
    )
    parser.add_argument(
        "--method",
        choices=["auto", "arima", "ets", "naive", "ensemble"],
        default="ensemble",
        help="Forecast method (default: ensemble)",
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--enhanced",
        action="store_true",
        help=(
            "Run enhanced volatility analysis: GARCH(1,1), fat-tail fitting, "
            "Monte Carlo with fat tails, and regime detection. "
            "Requires --returns-file or a 'daily_returns' key in the input JSON."
        ),
    )
    parser.add_argument(
        "--returns-file",
        dest="returns_file",
        help="Path to a JSON file containing daily returns list (for --enhanced mode).",
    )
    args = parser.parse_args()

    if not STATSMODELS_AVAILABLE and args.method in ("arima", "ets", "auto"):
        print(
            "Warning: statsmodels not installed. Falling back to naive forecast.",
            file=sys.stderr,
        )
        print("Install: pip install statsmodels", file=sys.stderr)
        args.method = "naive"

    with open(args.input) as f:
        raw_data = json.load(f)

    # Extract the first ticker's data
    ticker = list(raw_data.keys())[0] if raw_data else "UNKNOWN"
    data = raw_data.get(ticker, {})
    financials = data.get("financials", {})

    # Extract series
    revenue = extract_series(financials, ["income_statement", "revenue"])
    net_income = extract_series(financials, ["income_statement", "net_income"])
    operating_income = extract_series(
        financials, ["income_statement", "operating_income"]
    )
    fcf = extract_series(financials, ["cash_flow", "free_cash_flow"])
    ocf = extract_series(financials, ["cash_flow", "operating_cash_flow"])

    result = {
        "ticker": ticker,
        "forecast_date": datetime.now(timezone.utc).isoformat(),
        "data_source": data.get("source", "unknown"),
        "horizon_years": args.horizon,
        "confidence_level": args.confidence,
        "forecast_method": args.method,
    }

    # Forecast each series
    for name, series in [
        ("revenue", revenue),
        ("net_income", net_income),
        ("operating_income", operating_income),
        ("free_cash_flow", fcf),
        ("operating_cash_flow", ocf),
    ]:
        if len(series) >= 2:
            if args.method == "ensemble":
                result[name] = forecast_ensemble(series, args.horizon, args.confidence)
            else:
                result[name] = forecast_series(
                    series, args.horizon, args.confidence, args.method
                )
        else:
            result[name] = {"error": "Insufficient data", "observations": len(series)}

    # Growth rate comparison table
    growth_table = {}
    for name, forecast_data in result.items():
        if isinstance(forecast_data, dict) and "ensemble_cagr" in forecast_data:
            growth_table[name] = {
                "ensemble_cagr": forecast_data["ensemble_cagr"],
                "individual_cagrs": forecast_data.get("individual_methods", {}),
            }
        elif isinstance(forecast_data, dict) and "forecast" in forecast_data:
            fc = forecast_data["forecast"]
            if isinstance(fc, dict):
                growth_table[name] = {"cagr": fc.get("implied_cagr")}

    result["growth_rate_summary"] = growth_table

    # Recommended DCF inputs
    if "free_cash_flow" in result and isinstance(result["free_cash_flow"], dict):
        fcf_data = result["free_cash_flow"]
        ensemble_cagr = fcf_data.get("ensemble_cagr")
        if ensemble_cagr is not None:
            result["dcf_recommendations"] = {
                "fcf_growth_rate": round(ensemble_cagr, 4),
                "growth_rate_source": "Ensemble forecast (ARIMA + ETS + Naive)",
                "growth_rate_lower": round(
                    (
                        fcf_data["ensemble_forecasts"][-1]["lower"]
                        / fcf_data["last_observed"]
                    )
                    ** (1 / args.horizon)
                    - 1,
                    4,
                )
                if fcf_data.get("ensemble_forecasts") and fcf_data["last_observed"] > 0
                else None,
                "growth_rate_upper": round(
                    (
                        fcf_data["ensemble_forecasts"][-1]["upper"]
                        / fcf_data["last_observed"]
                    )
                    ** (1 / args.horizon)
                    - 1,
                    4,
                )
                if fcf_data.get("ensemble_forecasts") and fcf_data["last_observed"] > 0
                else None,
                "note": (
                    "Use these growth rates in DCF instead of single constant assumption."
                    " Lower/upper provide a range for sensitivity analysis."
                ),
            }

    # --enhanced: volatility / fat-tail analysis
    if args.enhanced:
        returns: list[float] | None = None

        # 1. Explicit --returns-file flag
        if args.returns_file:
            try:
                with open(args.returns_file) as rf:
                    ret_data = json.load(rf)
                if isinstance(ret_data, list):
                    returns = [float(x) for x in ret_data]
                elif isinstance(ret_data, dict):
                    # Accept {"returns": [...]} or {"daily_returns": [...]}
                    returns = [
                        float(x)
                        for x in (
                            ret_data.get("returns")
                            or ret_data.get("daily_returns")
                            or []
                        )
                    ]
            except Exception as exc:
                print(f"Warning: could not load returns file: {exc}", file=sys.stderr)

        # 2. Fall back to daily_returns embedded in the input JSON
        if not returns:
            returns = [
                float(x)
                for x in (data.get("daily_returns") or data.get("returns") or [])
            ]

        if not returns or len(returns) < 30:
            result["enhanced_volatility"] = {
                "error": (
                    "Enhanced mode requires at least 30 daily returns. "
                    "Provide via --returns-file or embed 'daily_returns' in input JSON."
                )
            }
        else:
            garch_result = compute_garch_volatility(returns)
            tail_result = fit_tail_distribution(returns)

            # For Monte Carlo: use GARCH current vol if available, else sample std
            mc_sigma = (
                math.sqrt(
                    garch_result.get("garch_annualized_vol_now", 0.0) ** 2
                    / _TRADING_DAYS
                )
                if "garch_annualized_vol_now" in garch_result
                else float(np.std(returns, ddof=1))
            )
            mc_mu = float(np.mean(returns))
            t_df = (
                tail_result.get("t_params", {}).get("df", 5.0)
                if "t_params" in tail_result
                else 5.0
            )

            # Attempt to get current price from input JSON
            current_price: float | None = (
                data.get("current_price") or data.get("price") or data.get("last_price")
            )
            mc_result: dict[str, Any]
            if current_price:
                mc_result = monte_carlo_fat_tails(
                    current_price=float(current_price),
                    mu=mc_mu,
                    sigma=mc_sigma,
                    df=t_df,
                )
            else:
                mc_result = {
                    "note": (
                        "Monte Carlo skipped: no current_price in input JSON. "
                        "Add 'current_price' field or pass price programmatically."
                    )
                }

            regime_result = detect_volatility_regime(returns)

            result["enhanced_volatility"] = {
                "garch_volatility": garch_result,
                "tail_distribution": tail_result,
                "monte_carlo_fat_tails": mc_result,
                "volatility_regime": regime_result,
                "arch_available": ARCH_AVAILABLE,
                "scipy_available": SCIPY_AVAILABLE,
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
