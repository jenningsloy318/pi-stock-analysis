#!/usr/bin/env python3
"""Fetch Asian market (Japan, Korea, China/HK, Taiwan) sector momentum and relative strength vs SPY.

Integrates into the stock-analysis pipeline at Stage 1 (Data Collection) and Stage 9 (Macro Analysis).

Usage:
    # All regions, output to stdout
    uv run python scripts/fetch_asia_market_momentum.py

    # Specific regions
    uv run python scripts/fetch_asia_market_momentum.py --groups japan,korea

    # Custom benchmark and file output
    uv run python scripts/fetch_asia_market_momentum.py --benchmark QQQ --output reports/asia_momentum.json

    # Only indices for quick trend check
    uv run python scripts/fetch_asia_market_momentum.py --groups indices

CLI Arguments:
    --output PATH       Output file path (default: stdout)
    --groups GROUPS     Comma-separated: japan,korea,china,taiwan,indices (default: "all")
    --benchmark BENCH   Benchmark ticker for RS computation (default: SPY)

Output:
    JSON with per-region ETF momentum, relative strength vs benchmark,
    cross-market analysis (tech leadership, semiconductor momentum, risk appetite),
    and directional scoring (1-10 scale).

Data Source: yfinance (Yahoo Finance)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    sys.stderr.write("ERROR: yfinance not installed. Run: pip install yfinance\n")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    sys.stderr.write("ERROR: pandas not installed. Run: pip install pandas\n")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    sys.stderr.write("ERROR: numpy not installed. Run: pip install numpy\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# ETF Universe
# ---------------------------------------------------------------------------

JAPAN_BROAD: dict[str, str] = {
    "EWJ": "iShares MSCI Japan",
    "DXJS": "WisdomTree Japan SmallCap Dividend",
    "JPXN": "iShares JPX-Nikkei 400",
    "BBJP": "JPMorgan BetaBuilders Japan",
    "FLJP": "Franklin FTSE Japan",
}

JAPAN_SECTORS: dict[str, str] = {
    "2644.T": "Global X Semiconductor Japan",
    "BOTZ": "Global X Robotics & AI (Japan-heavy)",
    "2516.T": "MAXIS Topix ETF",
}

KOREA_BROAD: dict[str, str] = {
    "EWY": "iShares MSCI South Korea",
    "KORU": "Direxion Daily South Korea Bull 3X",
    "FLKR": "Franklin FTSE South Korea",
}

KOREA_SECTORS: dict[str, str] = {
    "005930.KS": "Samsung Electronics (Semi proxy)",
    "000660.KS": "SK Hynix (Semi proxy)",
    "373220.KS": "LG Energy Solution (EV/Battery)",
    "006400.KS": "Samsung SDI (EV/Battery)",
    "035420.KS": "Naver (Internet)",
    "035720.KS": "Kakao (Internet)",
}

CHINA_HK: dict[str, str] = {
    "KWEB": "KraneShares CSI China Internet",
    "MCHI": "iShares MSCI China",
    "FXI": "iShares China Large-Cap",
    "CXSE": "WisdomTree China ex-State-Owned",
    "2800.HK": "Tracker Fund of Hong Kong",
}

TAIWAN: dict[str, str] = {
    "EWT": "iShares MSCI Taiwan",
    "TSM": "TSMC ADR",
}

CROSS_MARKET_INDICES: dict[str, str] = {
    "^N225": "Nikkei 225",
    "^KS11": "KOSPI",
    "^HSI": "Hang Seng",
    "^TWII": "TAIEX",
    "000001.SS": "Shanghai Composite",
}

# Tickers used for cross-market analysis signals
TECH_PROXIES: dict[str, str] = {
    "japan": "2644.T",
    "korea": "005930.KS",
    "taiwan": "TSM",
    "china": "KWEB",
}

SEMI_PROXIES: list[str] = ["2644.T", "005930.KS", "000660.KS", "TSM"]


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _safe_round(value: float | None, decimals: int = 2) -> float | None:
    """Round a value safely, returning None if input is None or NaN."""
    if value is None:
        return None
    try:
        if np.isnan(value) or np.isinf(value):
            return None
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


def _compute_return(prices: pd.Series, days: int) -> float | None:
    """Compute return over N trading days as percentage."""
    if prices is None or len(prices) < days + 1:
        return None
    try:
        old_price = prices.iloc[-(days + 1)]
        new_price = prices.iloc[-1]
        if old_price == 0 or pd.isna(old_price) or pd.isna(new_price):
            return None
        return (new_price / old_price - 1) * 100
    except (IndexError, TypeError):
        return None


def _compute_rs_ratio(
    etf_prices: pd.Series, bench_prices: pd.Series
) -> pd.Series | None:
    """Compute normalized RS ratio (ETF/Benchmark), base 100 at start."""
    if etf_prices is None or bench_prices is None:
        return None
    if len(etf_prices) < 2 or len(bench_prices) < 2:
        return None

    # Align on common dates
    common_idx = etf_prices.index.intersection(bench_prices.index)
    if len(common_idx) < 2:
        return None

    etf_aligned = etf_prices.loc[common_idx]
    bench_aligned = bench_prices.loc[common_idx]

    # Normalize both to 100 at start
    etf_norm = etf_aligned / etf_aligned.iloc[0] * 100
    bench_norm = bench_aligned / bench_aligned.iloc[0] * 100

    # RS ratio
    rs = etf_norm / bench_norm * 100
    return rs


def _rs_change(rs_series: pd.Series | None, days: int) -> float | None:
    """Compute RS change over N days as percentage."""
    if rs_series is None or len(rs_series) < days + 1:
        return None
    try:
        old_val = rs_series.iloc[-(days + 1)]
        new_val = rs_series.iloc[-1]
        if old_val == 0 or pd.isna(old_val) or pd.isna(new_val):
            return None
        return (new_val / old_val - 1) * 100
    except (IndexError, TypeError):
        return None


def _rs_momentum_label(rs_1m: float | None, rs_3m: float | None) -> str:
    """Determine RS momentum direction by comparing 1M vs 3M RS change."""
    if rs_1m is None or rs_3m is None:
        return "unknown"

    # If 1M RS change is accelerating vs 3M trend
    if rs_1m > 2.0 and rs_1m > rs_3m * 0.5:
        return "strong_positive"
    elif rs_1m > 0.5:
        return "positive"
    elif rs_1m < -2.0 and rs_1m < rs_3m * 0.5:
        return "strong_negative"
    elif rs_1m < -0.5:
        return "negative"
    else:
        return "neutral"


def _momentum_bonus(label: str) -> float:
    """Convert directional label to scoring bonus."""
    bonuses = {
        "strong_positive": 1.5,
        "positive": 0.8,
        "neutral": 0.0,
        "negative": -0.8,
        "strong_negative": -1.5,
        "unknown": 0.0,
    }
    return bonuses.get(label, 0.0)


def _compute_composite_rs(
    rs_1m: float | None, rs_3m: float | None, rs_6m: float | None, momentum_label: str
) -> float | None:
    """Compute composite RS score using period weights + momentum bonus.

    Weights: 1M=15%, 3M=30%, 6M=30%, 12M=25% (use 6M for 12M slot).
    Each period value capped at +/- 4.0 before weighting.
    Momentum bonus added after weighted sum.
    Final score mapped to 1-10 scale.
    """
    values = [rs_1m, rs_3m, rs_6m]
    if all(v is None for v in values):
        return None

    def cap(v: float | None) -> float:
        if v is None:
            return 0.0
        return min(4.0, max(-4.0, v * 0.5))

    # Weights: 1M=15%, 3M=30%, 6M=30%, 12M(=6M)=25%
    weighted = (
        cap(rs_1m) * 0.15
        + cap(rs_3m) * 0.30
        + cap(rs_6m) * 0.30
        + cap(rs_6m) * 0.25  # Use 6M as 12M proxy
    )

    # Add momentum bonus
    bonus = _momentum_bonus(momentum_label)
    raw_score = weighted + bonus

    # Map from roughly [-5.5, 5.5] to [1, 10]
    score = 5.5 + raw_score * 0.82
    return max(1.0, min(10.0, round(score, 1)))


def _volume_ratio(volumes: pd.Series) -> float | None:
    """Compute 5D avg volume / 20D avg volume ratio."""
    if volumes is None or len(volumes) < 20:
        return None
    try:
        avg_5d = volumes.iloc[-5:].mean()
        avg_20d = volumes.iloc[-20:].mean()
        if avg_20d == 0 or pd.isna(avg_20d):
            return None
        return round(float(avg_5d / avg_20d), 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Core Data Fetching
# ---------------------------------------------------------------------------


def fetch_benchmark_data(benchmark: str, period: str = "1y") -> pd.Series | None:
    """Fetch benchmark close prices for RS computation."""
    try:
        ticker = yf.Ticker(benchmark)
        hist = ticker.history(period=period)
        if hist.empty or len(hist) < 20:
            return None
        return hist["Close"]
    except Exception as e:
        sys.stderr.write(f"ERROR: Failed to fetch benchmark {benchmark}: {e}\n")
        return None


def fetch_ticker_data(
    ticker: str, label: str, bench_prices: pd.Series, period: str = "1y"
) -> dict:
    """Fetch and compute momentum/RS data for a single ticker.

    Returns a dict with returns, RS metrics, volume ratio, and scoring.
    On error returns {"ticker": ticker, "label": label, "error": message}.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)

        if hist.empty or len(hist) < 5:
            return {"ticker": ticker, "label": label, "error": "Insufficient data"}

        closes = hist["Close"]
        volumes = hist["Volume"] if "Volume" in hist.columns else None

        # Compute returns
        ret_1d = _compute_return(closes, 1)
        ret_5d = _compute_return(closes, 5)
        ret_1m = _compute_return(closes, 21)
        ret_3m = _compute_return(closes, 63)
        ret_6m = _compute_return(closes, 126)

        # Compute RS ratio vs benchmark
        rs_series = _compute_rs_ratio(closes, bench_prices)
        rs_change_1m = _rs_change(rs_series, 21)
        rs_change_3m = _rs_change(rs_series, 63)
        rs_change_6m = _rs_change(rs_series, 126)

        # RS momentum direction
        momentum_label = _rs_momentum_label(rs_change_1m, rs_change_3m)

        # Composite RS score (1-10)
        composite = _compute_composite_rs(
            rs_change_1m, rs_change_3m, rs_change_6m, momentum_label
        )

        # Volume ratio
        vol_ratio = _volume_ratio(volumes) if volumes is not None else None

        # Current price
        current_price = (
            _safe_round(float(closes.iloc[-1]), 2) if len(closes) > 0 else None
        )

        return {
            "ticker": ticker,
            "label": label,
            "current_price": current_price,
            "returns": {
                "1d": _safe_round(ret_1d, 2),
                "5d": _safe_round(ret_5d, 2),
                "1m": _safe_round(ret_1m, 2),
                "3m": _safe_round(ret_3m, 2),
                "6m": _safe_round(ret_6m, 2),
            },
            "relative_strength": {
                "rs_change_1m": _safe_round(rs_change_1m, 2),
                "rs_change_3m": _safe_round(rs_change_3m, 2),
                "rs_change_6m": _safe_round(rs_change_6m, 2),
                "rs_momentum": momentum_label,
                "composite_rs": composite,
            },
            "volume_ratio_5d_20d": vol_ratio,
            "data_points": len(closes),
        }

    except Exception as e:
        return {"ticker": ticker, "label": label, "error": str(e)}


def fetch_group(etf_map: dict[str, str], bench_prices: pd.Series) -> list[dict]:
    """Fetch data for all tickers in a group."""
    results = []
    for ticker, label in etf_map.items():
        data = fetch_ticker_data(ticker, label, bench_prices)
        results.append(data)
    return results


def compute_region_summary(broad_data: list[dict], sector_data: list[dict]) -> dict:
    """Compute summary statistics for a region."""
    all_data = broad_data + sector_data

    # Filter out errors
    valid = [d for d in all_data if "error" not in d]
    if not valid:
        return {"composite_rs": None, "direction": "unknown", "top_sector": None}

    # Average composite RS
    composites = [
        d["relative_strength"]["composite_rs"]
        for d in valid
        if d["relative_strength"]["composite_rs"] is not None
    ]
    avg_composite = round(sum(composites) / len(composites), 1) if composites else None

    # Overall direction based on average composite
    if avg_composite is None:
        direction = "unknown"
    elif avg_composite >= 7.0:
        direction = "strong_outperform"
    elif avg_composite >= 6.0:
        direction = "outperform"
    elif avg_composite >= 4.5:
        direction = "neutral"
    elif avg_composite >= 3.5:
        direction = "underperform"
    else:
        direction = "strong_underperform"

    # Top sector/ticker by composite RS
    top = max(valid, key=lambda d: d["relative_strength"]["composite_rs"] or 0)

    return {
        "composite_rs": avg_composite,
        "direction": direction,
        "top_sector": top["label"] if top else None,
        "top_ticker": top["ticker"] if top else None,
        "top_rs_score": top["relative_strength"]["composite_rs"] if top else None,
        "ticker_count": len(valid),
        "error_count": len(all_data) - len(valid),
    }


# ---------------------------------------------------------------------------
# Cross-Market Analysis
# ---------------------------------------------------------------------------


def compute_cross_market_analysis(
    all_region_data: dict[str, list[dict]], bench_prices: pd.Series
) -> dict:
    """Compute cross-market signals: tech leadership, semiconductor momentum,
    risk appetite, asia vs US tech spread."""

    # Flatten all valid tickers
    all_valid = []
    for region, data_list in all_region_data.items():
        for d in data_list:
            if "error" not in d:
                d["_region"] = region
                all_valid.append(d)

    # --- Tech Leadership ---
    tech_rs_by_region: dict[str, float] = {}
    for region, proxy_ticker in TECH_PROXIES.items():
        for d in all_valid:
            if (
                d["ticker"] == proxy_ticker
                and d["relative_strength"]["rs_change_3m"] is not None
            ):
                tech_rs_by_region[region] = d["relative_strength"]["rs_change_3m"]
                break

    tech_leader_region = None
    tech_leader_rs = None
    if tech_rs_by_region:
        tech_leader_region = max(tech_rs_by_region, key=tech_rs_by_region.get)
        tech_leader_rs = _safe_round(tech_rs_by_region[tech_leader_region], 2)

    tech_leadership = {
        "region": tech_leader_region,
        "rs_3m": tech_leader_rs,
        "all_regions": {k: _safe_round(v, 2) for k, v in tech_rs_by_region.items()},
    }

    # --- Semiconductor Momentum ---
    semi_scores = []
    for d in all_valid:
        if d["ticker"] in SEMI_PROXIES:
            score = d["relative_strength"]["composite_rs"]
            if score is not None:
                semi_scores.append(score)

    semi_avg = round(sum(semi_scores) / len(semi_scores), 1) if semi_scores else None
    if semi_avg is None:
        semi_direction = "unknown"
    elif semi_avg >= 7.0:
        semi_direction = "strong_positive"
    elif semi_avg >= 5.5:
        semi_direction = "positive"
    elif semi_avg >= 4.5:
        semi_direction = "neutral"
    elif semi_avg >= 3.0:
        semi_direction = "negative"
    else:
        semi_direction = "strong_negative"

    semiconductor_momentum = {
        "score": semi_avg,
        "direction": semi_direction,
        "proxies_used": len(semi_scores),
    }

    # --- Risk Appetite ---
    risk_tickers = ["EWJ", "EWY", "KWEB"]
    risk_scores = []
    for d in all_valid:
        if d["ticker"] in risk_tickers:
            score = d["relative_strength"]["composite_rs"]
            if score is not None:
                risk_scores.append(score)

    risk_avg = round(sum(risk_scores) / len(risk_scores), 1) if risk_scores else None
    if risk_avg is None:
        risk_direction = "unknown"
    elif risk_avg >= 7.0:
        risk_direction = "strong_risk_on"
    elif risk_avg >= 5.5:
        risk_direction = "risk_on"
    elif risk_avg >= 4.5:
        risk_direction = "neutral"
    elif risk_avg >= 3.0:
        risk_direction = "risk_off"
    else:
        risk_direction = "strong_risk_off"

    risk_appetite = {
        "score": risk_avg,
        "direction": risk_direction,
    }

    # --- Asia vs US Tech ---
    # Fetch QQQ RS for comparison
    asia_tech_scores = []
    for region, proxy_ticker in TECH_PROXIES.items():
        for d in all_valid:
            if d["ticker"] == proxy_ticker:
                rs_3m = d["relative_strength"]["rs_change_3m"]
                if rs_3m is not None:
                    asia_tech_scores.append(rs_3m)
                break

    # QQQ 3M return vs SPY for spread calculation
    qqq_data = fetch_ticker_data("QQQ", "Invesco QQQ Trust", bench_prices)
    qqq_rs_3m = None
    if "error" not in qqq_data:
        qqq_rs_3m = qqq_data["relative_strength"]["rs_change_3m"]

    asia_tech_avg = (
        round(sum(asia_tech_scores) / len(asia_tech_scores), 2)
        if asia_tech_scores
        else None
    )

    if asia_tech_avg is not None and qqq_rs_3m is not None:
        spread = round(asia_tech_avg - qqq_rs_3m, 2)
    else:
        spread = None

    if spread is None:
        asia_us_trend = "unknown"
    elif spread > 3.0:
        asia_us_trend = "asia_leading"
    elif spread > 0.5:
        asia_us_trend = "asia_slight_lead"
    elif spread > -0.5:
        asia_us_trend = "parity"
    elif spread > -3.0:
        asia_us_trend = "us_slight_lead"
    else:
        asia_us_trend = "us_leading"

    asia_vs_us_tech = {
        "asia_tech_avg_rs_3m": asia_tech_avg,
        "qqq_rs_3m": _safe_round(qqq_rs_3m, 2),
        "spread": spread,
        "trend": asia_us_trend,
    }

    # --- Signals ---
    signals = _generate_signals(
        tech_leadership,
        semiconductor_momentum,
        risk_appetite,
        asia_vs_us_tech,
        all_valid,
    )

    return {
        "tech_leadership": tech_leadership,
        "semiconductor_momentum": semiconductor_momentum,
        "risk_appetite": risk_appetite,
        "asia_vs_us_tech": asia_vs_us_tech,
        "signals": signals,
    }


def _generate_signals(
    tech_leadership: dict,
    semi_momentum: dict,
    risk_appetite: dict,
    asia_vs_us: dict,
    all_valid: list[dict],
) -> list[str]:
    """Generate notable observation signals based on cross-market data."""
    signals = []

    # Tech leadership signal
    if tech_leadership["region"]:
        rs = tech_leadership["rs_3m"]
        if rs is not None and abs(rs) > 3.0:
            direction = "outperforming" if rs > 0 else "underperforming"
            signals.append(
                f"{tech_leadership['region'].upper()} tech {direction} significantly "
                f"(3M RS: {rs:+.1f}%)"
            )

    # Semiconductor cycle signal
    if semi_momentum["score"] is not None:
        if semi_momentum["score"] >= 7.5:
            signals.append(
                "Asia semiconductor cycle in STRONG UPTREND — all proxies outperforming"
            )
        elif semi_momentum["score"] <= 3.0:
            signals.append(
                "Asia semiconductor cycle WEAKENING — broad underperformance vs SPY"
            )

    # Risk appetite signal
    if risk_appetite["score"] is not None:
        if risk_appetite["direction"] == "strong_risk_on":
            signals.append(
                "Asia risk appetite ELEVATED — EWJ/EWY/KWEB all outperforming SPY"
            )
        elif risk_appetite["direction"] == "strong_risk_off":
            signals.append(
                "Asia risk appetite DEPRESSED — broad risk-off across Japan/Korea/China"
            )

    # Asia vs US tech divergence
    if asia_vs_us["spread"] is not None:
        if asia_vs_us["spread"] > 5.0:
            signals.append(
                f"Asia tech LEADING US tech by {asia_vs_us['spread']:.1f}pp — "
                "potential rotation signal"
            )
        elif asia_vs_us["spread"] < -5.0:
            signals.append(
                f"US tech LEADING Asia tech by {abs(asia_vs_us['spread']):.1f}pp — "
                "US dominance continues"
            )

    # Volume spike detection
    high_volume_tickers = [
        d
        for d in all_valid
        if d.get("volume_ratio_5d_20d") is not None and d["volume_ratio_5d_20d"] > 1.5
    ]
    if len(high_volume_tickers) >= 3:
        tickers_str = ", ".join(d["ticker"] for d in high_volume_tickers[:5])
        signals.append(
            f"Elevated volume in {len(high_volume_tickers)} Asia tickers: {tickers_str}"
        )

    # Strong momentum convergence
    strong_pos = [
        d
        for d in all_valid
        if d["relative_strength"]["rs_momentum"] == "strong_positive"
    ]
    if len(strong_pos) >= 4:
        signals.append(
            f"{len(strong_pos)} Asia tickers showing strong_positive RS momentum — "
            "broad-based outperformance"
        )

    strong_neg = [
        d
        for d in all_valid
        if d["relative_strength"]["rs_momentum"] == "strong_negative"
    ]
    if len(strong_neg) >= 4:
        signals.append(
            f"{len(strong_neg)} Asia tickers showing strong_negative RS momentum — "
            "broad-based underperformance"
        )

    if not signals:
        signals.append("No notable cross-market divergences detected")

    return signals


# ---------------------------------------------------------------------------
# Indices Ranking
# ---------------------------------------------------------------------------


def compute_indices_ranking(indices_data: list[dict]) -> list[dict]:
    """Rank cross-market indices by composite RS score."""
    valid = [
        d
        for d in indices_data
        if "error" not in d and d["relative_strength"]["composite_rs"] is not None
    ]

    ranked = sorted(
        valid, key=lambda d: d["relative_strength"]["composite_rs"], reverse=True
    )

    ranking = []
    for i, d in enumerate(ranked):
        ranking.append(
            {
                "rank": i + 1,
                "ticker": d["ticker"],
                "label": d["label"],
                "composite_rs": d["relative_strength"]["composite_rs"],
                "rs_momentum": d["relative_strength"]["rs_momentum"],
                "return_1m": d["returns"]["1m"],
                "return_3m": d["returns"]["3m"],
            }
        )

    return ranking


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Asian market sector momentum and relative strength vs SPY"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--groups",
        default="all",
        help="Comma-separated regions: japan,korea,china,taiwan,indices (default: all)",
    )
    parser.add_argument(
        "--benchmark",
        default="SPY",
        help="Benchmark ticker for RS computation (default: SPY)",
    )
    args = parser.parse_args()

    # Parse groups
    if args.groups.lower() == "all":
        groups = {"japan", "korea", "china", "taiwan", "indices"}
    else:
        groups = {g.strip().lower() for g in args.groups.split(",")}

    # Fetch benchmark data
    sys.stderr.write(f"Fetching benchmark data ({args.benchmark})...\n")
    bench_prices = fetch_benchmark_data(args.benchmark)
    if bench_prices is None:
        sys.stderr.write(f"FATAL: Cannot fetch benchmark {args.benchmark}. Exiting.\n")
        sys.exit(1)

    output: dict = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "yfinance",
        "benchmark": args.benchmark,
    }

    # Collect all region data for cross-market analysis
    all_region_data: dict[str, list[dict]] = {}

    # --- Japan ---
    if "japan" in groups:
        sys.stderr.write("Fetching Japan data...\n")
        japan_broad = fetch_group(JAPAN_BROAD, bench_prices)
        japan_sectors = fetch_group(JAPAN_SECTORS, bench_prices)
        japan_summary = compute_region_summary(japan_broad, japan_sectors)

        output["japan"] = {
            "broad": japan_broad,
            "sectors": japan_sectors,
            "summary": japan_summary,
        }
        all_region_data["japan"] = japan_broad + japan_sectors

    # --- Korea ---
    if "korea" in groups:
        sys.stderr.write("Fetching Korea data...\n")
        korea_broad = fetch_group(KOREA_BROAD, bench_prices)
        korea_sectors = fetch_group(KOREA_SECTORS, bench_prices)
        korea_summary = compute_region_summary(korea_broad, korea_sectors)

        output["korea"] = {
            "broad": korea_broad,
            "sectors": korea_sectors,
            "summary": korea_summary,
        }
        all_region_data["korea"] = korea_broad + korea_sectors

    # --- China/HK ---
    if "china" in groups:
        sys.stderr.write("Fetching China/HK data...\n")
        china_data = fetch_group(CHINA_HK, bench_prices)
        china_summary = compute_region_summary(china_data, [])

        output["china"] = {
            "broad": china_data,
            "sectors": [],
            "summary": china_summary,
        }
        all_region_data["china"] = china_data

    # --- Taiwan ---
    if "taiwan" in groups:
        sys.stderr.write("Fetching Taiwan data...\n")
        taiwan_data = fetch_group(TAIWAN, bench_prices)
        taiwan_summary = compute_region_summary(taiwan_data, [])

        output["taiwan"] = {
            "broad": taiwan_data,
            "sectors": [],
            "summary": taiwan_summary,
        }
        all_region_data["taiwan"] = taiwan_data

    # --- Cross-Market Indices ---
    if "indices" in groups:
        sys.stderr.write("Fetching cross-market indices...\n")
        indices_data = fetch_group(CROSS_MARKET_INDICES, bench_prices)
        indices_ranking = compute_indices_ranking(indices_data)

        output["indices"] = {
            "data": indices_data,
            "ranking": indices_ranking,
        }

    # --- Cross-Market Analysis ---
    if len(all_region_data) >= 2:
        sys.stderr.write("Computing cross-market analysis...\n")
        cross_market = compute_cross_market_analysis(all_region_data, bench_prices)
        output["cross_market_analysis"] = cross_market
    elif len(all_region_data) == 1:
        # Still compute what we can with single region
        sys.stderr.write(
            "Computing cross-market analysis (limited — single region)...\n"
        )
        cross_market = compute_cross_market_analysis(all_region_data, bench_prices)
        output["cross_market_analysis"] = cross_market

    # --- Methodology ---
    output["methodology"] = {
        "composite_rs_weights": {
            "1m": "15%",
            "3m": "30%",
            "6m": "30%",
            "12m_proxy_6m": "25%",
        },
        "momentum_bonus": {
            "strong_positive": "+1.5",
            "positive": "+0.8",
            "neutral": "0",
            "negative": "-0.8",
            "strong_negative": "-1.5",
        },
        "scoring_scale": "1-10 (5.5 = neutral, >7 = outperform, <4 = underperform)",
        "rs_computation": "ETF_price / Benchmark_price normalized to 100 at period start",
        "returns": "(new/old - 1) * 100",
    }

    # --- Output ---
    json_str = json.dumps(output, indent=2, default=str)

    if args.output:
        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json_str)
        sys.stderr.write(f"Output written to: {args.output}\n")
    else:
        print(json_str)

    sys.exit(0)


if __name__ == "__main__":
    main()
