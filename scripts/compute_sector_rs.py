#!/usr/bin/env python3
"""Compute sector and sub-industry relative strength rankings against S&P 500.

Usage:
    compute_sector_rs.py                          # all 11 sectors vs SPY
    compute_sector_rs.py --sectors XLK,XLF,XLE    # specific sector ETFs
    compute_sector_rs.py --level sub-industry     # GICS Level 4 grouped by sector
    compute_sector_rs.py --level sub-industry --flat  # flat leaderboard across all
    compute_sector_rs.py --level sub-industry --sector Technology
    compute_sector_rs.py --benchmark SPY --period 1y
    compute_sector_rs.py --output ./reports/screening/sector-rs.json

Uses sector/sub-industry ETF price data (yfinance) to compute:
  - Relative strength (RS) ratio: sector ETF / benchmark
  - RS momentum across 1M, 3M, 6M, 12M timeframes
  - RS ranking (percentile vs all sectors or sub-industries)
  - RS direction (improving/deteriorating)
  - Composite RS score for sector rotation

Supports GICS Level 1 (sector) and Level 4 (sub-industry) granularity.
This feeds the 20% RS weight in short-term industry screening and the
10% RS weight in mid-term screening.
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


# GICS sector → ETF mapping (Level 1)
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

# GICS Level 4 Sub-Industry → ETF proxy mapping
# Where no pure ETF exists, uses a basket ticker or thematic ETF
SUB_INDUSTRY_ETFS: dict[str, dict[str, str | list[str]]] = {
    # --- Technology (45) ---
    "Technology": {
        "Semiconductors": "SMH",
        "Semiconductor Equipment": "SMH",
        "Application Software": "IGV",
        "Systems Software": "IGV",
        "IT Consulting & Services": "IGV",
        "Data Processing & Outsourced Services": "IPAY",
        "Communications Equipment": "XLK",
        "Technology Hardware & Peripherals": "XLK",
        "Electronic Equipment & Instruments": "XLK",
        "Electronic Components": "XLK",
        "Electronic Manufacturing Services": "XLK",
    },
    # --- Financials (40) ---
    "Financials": {
        "Diversified Banks": "XLF",
        "Regional Banks": "KRE",
        "Transaction & Payment Processing": "IPAY",
        "Consumer Finance": "XLF",
        "Asset Management & Custody Banks": "XLF",
        "Investment Banking & Brokerage": "XLF",
        "Financial Exchanges & Data": "XLF",
        "Insurance Brokers": "KIE",
        "Life & Health Insurance": "KIE",
        "Property & Casualty Insurance": "KIE",
        "Multi-line Insurance": "KIE",
        "Reinsurance": "KIE",
        "Mortgage REITs": "REM",
        "Diversified Financial Services": "XLF",
        "Specialized Finance": "XLF",
    },
    # --- Healthcare (35) ---
    "Healthcare": {
        "Biotechnology": "XBI",
        "Pharmaceuticals": "XLV",
        "Life Sciences Tools & Services": "XLV",
        "Health Care Equipment": "IHI",
        "Health Care Supplies": "IHI",
        "Managed Health Care": "IHF",
        "Health Care Distributors": "IHF",
        "Health Care Services": "IHF",
        "Health Care Facilities": "IHF",
        "Health Care Technology": "IHF",
    },
    # --- Consumer Discretionary (25) ---
    "Consumer Discretionary": {
        "Automobile Manufacturers": "CARZ",
        "Automotive Parts & Equipment": "XLY",
        "Homebuilding": "ITB",
        "Home Furnishings": "XHB",
        "Household Appliances": "XHB",
        "Leisure Products": "XLY",
        "Apparel, Accessories & Luxury Goods": "XRT",
        "Footwear": "XRT",
        "Casinos & Gaming": "BJK",
        "Hotels, Resorts & Cruise Lines": "PEJ",
        "Restaurants": "PEJ",
        "Leisure Facilities": "PEJ",
        "Education Services": "XLY",
        "Broadline Retail": "XRT",
        "Apparel Retail": "XRT",
        "Home Improvement Retail": "XHB",
        "Specialty Retail": "XRT",
        "Automotive Retail": "XRT",
        "Computer & Electronics Retail": "XRT",
    },
    # --- Communication Services (50) ---
    "Communication Services": {
        "Integrated Telecommunication Services": "XLC",
        "Wireless Telecommunication Services": "XLC",
        "Alternative Carriers": "XLC",
        "Advertising": "XLC",
        "Broadcasting": "XLC",
        "Cable & Satellite": "XLC",
        "Publishing": "XLC",
        "Movies & Entertainment": "XLC",
        "Interactive Home Entertainment": "HERO",
        "Interactive Media & Services": "XLC",
    },
    # --- Industrials (20) ---
    "Industrials": {
        "Aerospace & Defense": "ITA",
        "Building Products": "XLI",
        "Construction & Engineering": "XLI",
        "Electrical Components & Equipment": "XLI",
        "Heavy Electrical Equipment": "XLI",
        "Industrial Conglomerates": "XLI",
        "Construction Machinery & Heavy Equipment": "XLI",
        "Agricultural & Farm Machinery": "MOO",
        "Industrial Machinery & Components": "XLI",
        "Trading Companies & Distributors": "XLI",
        "Environmental & Facilities Services": "XLI",
        "Human Resource & Employment Services": "XLI",
        "Research & Consulting Services": "XLI",
        "Air Freight & Logistics": "IYT",
        "Passenger Airlines": "JETS",
        "Marine Transportation": "IYT",
        "Rail Transportation": "IYT",
        "Cargo Ground Transportation": "IYT",
        "Transportation Infrastructure": "IYT",
    },
    # --- Energy (10) ---
    "Energy": {
        "Oil & Gas Drilling": "XLE",
        "Oil & Gas Equipment & Services": "OIH",
        "Integrated Oil & Gas": "XLE",
        "Oil & Gas Exploration & Production": "XOP",
        "Oil & Gas Refining & Marketing": "CRAK",
        "Oil & Gas Storage & Transportation": "AMLP",
        "Coal & Consumable Fuels": "XLE",
    },
    # --- Consumer Staples (30) ---
    "Consumer Staples": {
        "Drug Retail": "XLP",
        "Food Distributors": "XLP",
        "Food Retail": "XLP",
        "Consumer Staples Merchandise Retail": "XLP",
        "Brewers": "XLP",
        "Distillers & Vintners": "XLP",
        "Soft Drinks & Non-alcoholic Beverages": "PBJ",
        "Agricultural Products & Services": "MOO",
        "Packaged Foods & Meats": "PBJ",
        "Tobacco": "XLP",
        "Household Products": "XLP",
        "Personal Care Products": "XLP",
    },
    # --- Utilities (55) ---
    "Utilities": {
        "Electric Utilities": "XLU",
        "Gas Utilities": "XLU",
        "Multi-Utilities": "XLU",
        "Water Utilities": "PHO",
        "Independent Power Producers": "XLU",
        "Renewable Electricity": "ICLN",
    },
    # --- Real Estate (60) ---
    "Real Estate": {
        "Diversified REITs": "VNQ",
        "Industrial REITs": "INDS",
        "Hotel & Resort REITs": "XLRE",
        "Office REITs": "XLRE",
        "Health Care REITs": "XLRE",
        "Multi-Family Residential REITs": "REZ",
        "Single-Family Residential REITs": "REZ",
        "Retail REITs": "XLRE",
        "Data Center REITs": "VNQ",
        "Self-Storage REITs": "VNQ",
        "Telecom Tower REITs": "VNQ",
        "Timber REITs": "XLRE",
        "Other Specialized REITs": "VNQ",
        "Real Estate Services": "XLRE",
    },
    # --- Materials (15) ---
    "Materials": {
        "Commodity Chemicals": "XLB",
        "Diversified Chemicals": "XLB",
        "Fertilizers & Agricultural Chemicals": "MOO",
        "Industrial Gases": "XLB",
        "Specialty Chemicals": "XLB",
        "Construction Materials": "XHB",
        "Metal & Glass Containers": "XLB",
        "Paper & Plastic Packaging": "XLB",
        "Aluminum": "XLB",
        "Diversified Metals & Mining": "XME",
        "Copper": "COPX",
        "Gold": "GDX",
        "Precious Metals & Minerals": "GDX",
        "Silver": "SIL",
        "Steel": "SLX",
        "Forest Products": "XLB",
    },
}

# Flattened sub-industry → representative stock baskets for RS when no ETF exists
SUB_INDUSTRY_BASKETS: dict[str, list[str]] = {
    "Semiconductor Equipment": ["AMAT", "LRCX", "KLAC", "ASML"],
    "Data Center REITs": ["EQIX", "DLR", "QTS"],
    "Industrial REITs": ["PLD", "REXR", "STAG"],
    "Telecom Tower REITs": ["AMT", "CCI", "SBAC"],
    "Self-Storage REITs": ["PSA", "EXR", "CUBE"],
    "Health Care REITs": ["WELL", "VTR", "OHI"],
    "Hotel & Resort REITs": ["HST", "PK", "RHP"],
    "Office REITs": ["BXP", "VNO", "SLG"],
    "Retail REITs": ["SPG", "O", "NNN"],
    "Multi-Family Residential REITs": ["EQR", "AVB", "MAA"],
    "Restaurants": ["MCD", "SBUX", "CMG", "YUM"],
    "Homebuilding": ["LEN", "DHI", "NVR", "PHM"],
    "Automobile Manufacturers": ["TSLA", "GM", "F"],
    "Renewable Electricity": ["ENPH", "FSLR", "RUN"],
    "Life Sciences Tools & Services": ["TMO", "DHR", "A"],
    "Health Care Equipment": ["SYK", "MDT", "ABT"],
    "Systems Software": ["MSFT", "ORCL", "PANW"],
    "Application Software": ["CRM", "ADBE", "NOW"],
    "IT Consulting & Services": ["ACN", "IBM", "CTSH"],
    "Financial Exchanges & Data": ["ICE", "CME", "NDAQ"],
    "Electrical Components & Equipment": ["ETN", "EMR", "ROK"],
}


def compute_rs(ticker: str, benchmark: str = "SPY", period: str = "2y") -> dict:
    """Compute relative strength for a sector ETF vs benchmark."""
    try:
        sector = yf.Ticker(ticker)
        bench = yf.Ticker(benchmark)

        sector_hist = sector.history(period=period)
        bench_hist = bench.history(period=period)

        if sector_hist.empty or bench_hist.empty:
            return {"error": f"No data for {ticker} or {benchmark}"}

        # Align dates
        common_dates = sector_hist.index.intersection(bench_hist.index)
        if len(common_dates) < 20:
            return {"error": f"Insufficient common trading days ({len(common_dates)})"}

        sector_close = sector_hist.loc[common_dates, "Close"].values
        bench_close = bench_hist.loc[common_dates, "Close"].values

        # RS ratio
        rs_ratio = sector_close / bench_close
        rs_ratio_normalized = rs_ratio / rs_ratio[0] * 100  # Base 100

        today = datetime.now().date()

        def price_at_days_ago(days: int) -> tuple:
            """Get price at approximate date N trading days ago."""
            if days >= len(sector_close):
                return None, None
            idx = len(sector_close) - 1 - days
            return float(sector_close[idx]), float(bench_close[idx])

        def compute_rs_change(trading_days: int) -> dict | None:
            """Compute RS change over a period."""
            s_now, b_now = sector_close[-1], bench_close[-1]
            if trading_days >= len(sector_close):
                return None
            s_past, b_past = (
                sector_close[-1 - trading_days],
                bench_close[-1 - trading_days],
            )
            if b_past == 0 or b_now == 0:
                return None

            rs_now = s_now / b_now
            rs_past = s_past / b_past
            rs_change = (rs_now / rs_past - 1) * 100

            sector_return = (s_now / s_past - 1) * 100
            bench_return = (b_now / b_past - 1) * 100
            excess_return = sector_return - bench_return

            return {
                "rs_change_pct": round(rs_change, 2),
                "sector_return_pct": round(sector_return, 2),
                "benchmark_return_pct": round(bench_return, 2),
                "excess_return_pct": round(excess_return, 2),
            }

        # Approximate trading day conversions
        periods = {
            "1M": 21,
            "3M": 63,
            "6M": 126,
            "12M": 252,
        }

        rs_data = {}
        for label, days in periods.items():
            change = compute_rs_change(days)
            if change:
                rs_data[label] = change

        # RS momentum: is RS accelerating or decelerating?
        rs_momentum = None
        if "1M" in rs_data and "3M" in rs_data:
            # Compare short-term RS change vs longer-term
            short = rs_data["1M"]["rs_change_pct"]
            long = rs_data["3M"]["rs_change_pct"]
            if short > 0 and long > 0:
                rs_momentum = "strong_positive" if short > long else "positive_stable"
            elif short > 0 > long:
                rs_momentum = "improving"
            elif short < 0 < long:
                rs_momentum = "deteriorating"
            elif short < 0 and long < 0:
                rs_momentum = "strong_negative" if short < long else "negative_stable"
            else:
                rs_momentum = "neutral"

        # Current RS ratio vs 1-year average
        if len(rs_ratio) >= 252:
            rs_1y_avg = np.mean(rs_ratio[-252:])
            rs_current = rs_ratio[-1]
            rs_vs_avg = (rs_current / rs_1y_avg - 1) * 100
        else:
            rs_vs_avg = None

        return {
            "ticker": ticker,
            "benchmark": benchmark,
            "period": period,
            "data_points": len(common_dates),
            "rs_data": rs_data,
            "rs_momentum": rs_momentum,
            "rs_vs_1y_avg_pct": round(rs_vs_avg, 2) if rs_vs_avg is not None else None,
            "latest_rs_ratio": round(float(rs_ratio[-1]), 6),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return {"error": str(e)}


def rank_sectors(rs_results: dict[str, dict]) -> dict:
    """Rank sectors by RS composite score."""
    scores = {}
    for sector, data in rs_results.items():
        if "error" in data:
            continue

        rs = data.get("rs_data", {})
        score = 0.0

        # Score: positive RS change = positive score
        weights = {"1M": 0.15, "3M": 0.30, "6M": 0.30, "12M": 0.25}

        for period, weight in weights.items():
            if period in rs:
                rs_change = rs[period]["rs_change_pct"]
                # Normalize: each 1% excess return = +0.5 points, capped at ±4
                period_score = min(4.0, max(-4.0, rs_change * 0.5))
                score += period_score * weight

        # Momentum bonus
        momentum = data.get("rs_momentum", "neutral")
        momentum_bonus = {
            "strong_positive": 1.5,
            "positive_stable": 0.8,
            "improving": 1.0,
            "neutral": 0.0,
            "deteriorating": -1.0,
            "negative_stable": -0.8,
            "strong_negative": -1.5,
        }
        score += momentum_bonus.get(momentum, 0)

        scores[sector] = {
            "ticker": data.get("ticker"),
            "composite_rs": round(score, 2),
            "rs_momentum": momentum,
            "rs_1m": rs.get("1M", {}).get("rs_change_pct"),
            "rs_3m": rs.get("3M", {}).get("rs_change_pct"),
            "rs_6m": rs.get("6M", {}).get("rs_change_pct"),
            "rs_12m": rs.get("12M", {}).get("rs_change_pct"),
        }

    # Rank by composite RS
    ranked = sorted(scores.items(), key=lambda x: x[1]["composite_rs"], reverse=True)

    # Percentile rank
    n = len(ranked)
    ranking = []
    for i, (sector, sdata) in enumerate(ranked):
        percentile = round((1 - i / max(n - 1, 1)) * 100, 1)
        entry = dict(sdata)
        entry["rank"] = i + 1
        entry["percentile"] = percentile
        ranking.append({"sector": sector, **entry})

    # Interpretation
    top_quartile = [r for r in ranking if r["percentile"] >= 75]
    bottom_quartile = [r for r in ranking if r["percentile"] <= 25]

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "sectors_ranked": len(ranking),
        "ranking": ranking,
        "top_quartile": [r["sector"] for r in top_quartile],
        "bottom_quartile": [r["sector"] for r in bottom_quartile],
        "methodology": "Composite RS = Σ(period RS × weight) + momentum bonus. "
        "Weights: 1M=15%, 3M=30%, 6M=30%, 12M=25%. "
        "RS change = % change in (sector ETF / SPY) over period.",
        "usage": "Feed top_quartile sectors to sector-screener for Phase 1 ranking. "
        "RS is the single most predictive signal for sector rotation.",
    }


def rank_sub_industries(rs_results: dict[str, dict], parent_sector: str) -> dict:
    """Rank sub-industries within a sector by RS composite score."""
    base = rank_sectors(rs_results)
    base["parent_sector"] = parent_sector
    base["level"] = "sub-industry"
    base["methodology"] = (
        "Sub-industry RS computed using ETF proxies or thematic ETFs. "
        "Same composite formula as sector RS. "
        "Weights: 1M=15%, 3M=30%, 6M=30%, 12M=25%. "
        "When multiple sub-industries share an ETF proxy, their RS scores "
        "will be identical — use fundamental screening to differentiate."
    )
    base["usage"] = (
        "Feed top-ranked sub-industries to sector-screener (deep-dive mode) "
        "for Phase 2 analysis. Identifies which part of a sector is leading."
    )
    # Rename 'sector' key to 'sub_industry' in ranking entries
    for entry in base.get("ranking", []):
        entry["sub_industry"] = entry.pop("sector", entry.get("sub_industry"))
    base["top_quartile_sub_industries"] = base.pop("top_quartile", [])
    base["bottom_quartile_sub_industries"] = base.pop("bottom_quartile", [])
    return base


def _average_basket_rs(basket_results: list[dict]) -> dict:
    """Average RS data across a basket of stocks to produce a synthetic RS signal."""
    periods = ["1M", "3M", "6M", "12M"]
    avg_rs_data = {}
    for p in periods:
        changes = [
            r["rs_data"][p]["rs_change_pct"]
            for r in basket_results
            if p in r.get("rs_data", {})
        ]
        if changes:
            avg_rs_data[p] = {
                "rs_change_pct": round(sum(changes) / len(changes), 2),
                "sector_return_pct": round(
                    sum(
                        r["rs_data"][p]["sector_return_pct"]
                        for r in basket_results
                        if p in r.get("rs_data", {})
                    )
                    / len(changes),
                    2,
                ),
                "benchmark_return_pct": basket_results[0]["rs_data"]
                .get(p, {})
                .get("benchmark_return_pct", 0),
                "excess_return_pct": round(
                    sum(
                        r["rs_data"][p]["excess_return_pct"]
                        for r in basket_results
                        if p in r.get("rs_data", {})
                    )
                    / len(changes),
                    2,
                ),
            }

    # Determine momentum from averaged data
    rs_momentum = "neutral"
    if "1M" in avg_rs_data and "3M" in avg_rs_data:
        short = avg_rs_data["1M"]["rs_change_pct"]
        long = avg_rs_data["3M"]["rs_change_pct"]
        if short > 0 and long > 0:
            rs_momentum = "strong_positive" if short > long else "positive_stable"
        elif short > 0 > long:
            rs_momentum = "improving"
        elif short < 0 < long:
            rs_momentum = "deteriorating"
        elif short < 0 and long < 0:
            rs_momentum = "strong_negative" if short < long else "negative_stable"

    return {"rs_data": avg_rs_data, "rs_momentum": rs_momentum}


def main():
    parser = argparse.ArgumentParser(
        description="Compute sector/sub-industry relative strength rankings"
    )
    parser.add_argument(
        "--sectors", help="Comma-separated sector ETF tickers (default: all 11 GICS)"
    )
    parser.add_argument(
        "--level",
        choices=["sector", "sub-industry"],
        default="sector",
        help="GICS granularity: 'sector' (Level 1, 11 sectors) or 'sub-industry' (Level 4)",
    )
    parser.add_argument(
        "--sector",
        help="Parent sector name for sub-industry mode (e.g., 'Technology', 'Healthcare'). "
        "If omitted in sub-industry mode, screens all sectors' sub-industries.",
    )
    parser.add_argument(
        "--benchmark", default="SPY", help="Benchmark ticker (default: SPY)"
    )
    parser.add_argument(
        "--period", default="2y", help="Lookback period for RS calculation"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--flat",
        action="store_true",
        help="(sub-industry mode only) Produce a single flat ranked leaderboard "
        "across all sub-industries instead of grouping by parent sector.",
    )
    args = parser.parse_args()

    if args.level == "sub-industry":
        # Sub-industry mode: use GICS Level 4 ETF proxies
        if args.sector:
            # Single sector's sub-industries
            sectors_to_scan = [args.sector]
        else:
            # All sectors' sub-industries
            sectors_to_scan = list(SUB_INDUSTRY_ETFS.keys())

        if args.flat:
            # Flat leaderboard: rank ALL sub-industries in one list
            all_results = {}
            for sector_name in sectors_to_scan:
                sub_map = SUB_INDUSTRY_ETFS.get(sector_name, {})
                for sub_ind, etf in sub_map.items():
                    if isinstance(etf, list):
                        etf = etf[0]
                    # Use basket if available for better differentiation
                    if sub_ind in SUB_INDUSTRY_BASKETS:
                        basket = SUB_INDUSTRY_BASKETS[sub_ind]
                        basket_results = []
                        for t in basket:
                            r = compute_rs(t, args.benchmark, args.period)
                            if "error" not in r:
                                basket_results.append(r)
                        if basket_results:
                            # Average the RS data across basket
                            avg_data = _average_basket_rs(basket_results)
                            all_results[sub_ind] = {
                                "data": avg_data,
                                "parent_sector": sector_name,
                                "proxy": f"basket({','.join(basket)})",
                            }
                            continue
                    data = compute_rs(etf, args.benchmark, args.period)
                    all_results[sub_ind] = {
                        "data": data,
                        "parent_sector": sector_name,
                        "proxy": etf,
                    }

            # Build flat ranking
            scored = []
            for sub_ind, info in all_results.items():
                data = info["data"]
                if "error" in data:
                    continue
                rs = data.get("rs_data", {})
                score = 0.0
                weights = {"1M": 0.15, "3M": 0.30, "6M": 0.30, "12M": 0.25}
                for period, weight in weights.items():
                    if period in rs:
                        rs_change = rs[period]["rs_change_pct"]
                        period_score = min(4.0, max(-4.0, rs_change * 0.5))
                        score += period_score * weight
                momentum = data.get("rs_momentum", "neutral")
                momentum_bonus = {
                    "strong_positive": 1.5,
                    "positive_stable": 0.8,
                    "improving": 1.0,
                    "neutral": 0.0,
                    "deteriorating": -1.0,
                    "negative_stable": -0.8,
                    "strong_negative": -1.5,
                }
                score += momentum_bonus.get(momentum, 0)
                scored.append(
                    {
                        "sub_industry": sub_ind,
                        "parent_sector": info["parent_sector"],
                        "proxy": info["proxy"],
                        "composite_rs": round(score, 2),
                        "rs_momentum": momentum,
                        "rs_1m": rs.get("1M", {}).get("rs_change_pct"),
                        "rs_3m": rs.get("3M", {}).get("rs_change_pct"),
                        "rs_6m": rs.get("6M", {}).get("rs_change_pct"),
                        "rs_12m": rs.get("12M", {}).get("rs_change_pct"),
                    }
                )

            scored.sort(key=lambda x: x["composite_rs"], reverse=True)
            n = len(scored)
            for i, entry in enumerate(scored):
                entry["rank"] = i + 1
                entry["percentile"] = round((1 - i / max(n - 1, 1)) * 100, 1)

            output = {
                "level": "sub-industry",
                "format": "flat_leaderboard",
                "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total_sub_industries": n,
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "ranking": scored,
                "top_quartile": [
                    e["sub_industry"] for e in scored if e["percentile"] >= 75
                ],
                "bottom_quartile": [
                    e["sub_industry"] for e in scored if e["percentile"] <= 25
                ],
                "methodology": "Flat leaderboard: all sub-industries ranked by composite RS. "
                "Composite = Σ(period RS × weight) + momentum bonus. "
                "Weights: 1M=15%, 3M=30%, 6M=30%, 12M=25%. "
                "Stock baskets used for differentiation where available.",
            }
        else:
            # Grouped mode (original): sub-industries grouped by parent sector
            output = {
                "level": "sub-industry",
                "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sectors": {},
            }

            for sector_name in sectors_to_scan:
                sub_map = SUB_INDUSTRY_ETFS.get(sector_name, {})
                if not sub_map:
                    output["sectors"][sector_name] = {
                        "error": f"No sub-industry mapping for '{sector_name}'"
                    }
                    continue

                # Deduplicate: multiple sub-industries may share an ETF
                results = {}
                for sub_ind, etf in sub_map.items():
                    if isinstance(etf, list):
                        etf = etf[0]
                    data = compute_rs(etf, args.benchmark, args.period)
                    results[sub_ind] = data

                ranking = rank_sub_industries(results, sector_name)
                output["sectors"][sector_name] = ranking

    else:
        # Sector mode (original behavior)
        if args.sectors:
            etfs = {s.strip(): s.strip() for s in args.sectors.split(",")}
        else:
            etfs = SECTOR_ETFS

        results = {}
        for sector, ticker in etfs.items():
            data = compute_rs(ticker, args.benchmark, args.period)
            results[sector] = data

        ranking = rank_sectors(results)
        output = {
            "level": "sector",
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "individual_results": results,
            "ranking": ranking,
        }

    result_json = json.dumps(output, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(result_json)
    else:
        print(result_json)
    sys.exit(0)


if __name__ == "__main__":
    main()
