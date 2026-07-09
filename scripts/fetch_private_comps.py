#!/usr/bin/env python3
"""M&A probability, LBO affordability model, and activist investor probability.

Usage:
    fetch_private_comps.py AAPL [--sector 45] [--output ./reports/AAPL/private_comps.json]

Computes:
  1. Acquisition Target Probability Score (0-100)
  2. LBO Affordability Floor (max PE buyout price at 20% IRR)
  3. Activist Investor Probability Score (0-100)
  4. Precedent Transaction Premium Range

Deterministic calculations only. No LLM involvement in math.
Output includes methodology attribution for every calculation.
"""

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np

try:
    import yfinance as yf
    import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


def safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


# ---------------------------------------------------------------------------
# 1. Acquisition Target Probability Score
# ---------------------------------------------------------------------------

def compute_acquisition_target_score(info: dict, financials: dict, sector_median: dict) -> dict:
    """Score 10 characteristics that make a company an acquisition target (0-100)."""
    scores: dict[str, float] = {}
    reasons: list[str] = []

    market_cap = info.get("marketCap")
    ev = info.get("enterpriseValue")
    ebitda = info.get("ebitda")
    total_debt = info.get("totalDebt", 0)
    total_cash = info.get("totalCash", 0)
    net_debt = (total_debt or 0) - (total_cash or 0)
    fcf = info.get("freeCashflow")

    # 1. Below-peer valuation (EV/EBITDA vs sector median)
    ev_ebitda = safe_div(ev, ebitda)
    sector_ev_ebitda = sector_median.get("ev_ebitda")
    if ev_ebitda is not None and sector_ev_ebitda is not None and sector_ev_ebitda > 0:
        discount_pct = (sector_ev_ebitda - ev_ebitda) / sector_ev_ebitda
        scores["below_peer_valuation"] = min(10, max(0, discount_pct * 33.3))
        reasons.append(f"EV/EBITDA {ev_ebitda:.1f}x vs sector {sector_ev_ebitda:.1f}x → {discount_pct:.0%} discount")
    else:
        scores["below_peer_valuation"] = 0
        reasons.append("EV/EBITDA comparison unavailable")

    # 2. Strategic asset value (qualitative — default mid-score, agent adjusts)
    scores["strategic_asset_value"] = 5.0
    reasons.append("Strategic asset value: default 5/10 (agent adjusts based on qualitative research)")

    # 3. Buyable size (market cap < $50B)
    if market_cap is not None:
        if market_cap < 5e9:
            scores["buyable_size"] = 10.0
        elif market_cap < 10e9:
            scores["buyable_size"] = 9.0
        elif market_cap < 25e9:
            scores["buyable_size"] = 7.0
        elif market_cap < 50e9:
            scores["buyable_size"] = 5.0
        elif market_cap < 100e9:
            scores["buyable_size"] = 2.0
        else:
            scores["buyable_size"] = 0.0
        reasons.append(f"Market cap ${market_cap/1e9:.1f}B")
    else:
        scores["buyable_size"] = 0
        reasons.append("Market cap unavailable")

    # 4. Clean balance sheet (net debt/EBITDA < 2x)
    nd_ebitda = safe_div(net_debt, ebitda)
    if nd_ebitda is not None:
        if nd_ebitda < 0:
            scores["clean_balance_sheet"] = 10.0
        elif nd_ebitda < 1.0:
            scores["clean_balance_sheet"] = 9.0
        elif nd_ebitda < 2.0:
            scores["clean_balance_sheet"] = 7.0
        elif nd_ebitda < 3.0:
            scores["clean_balance_sheet"] = 4.0
        elif nd_ebitda < 4.0:
            scores["clean_balance_sheet"] = 2.0
        else:
            scores["clean_balance_sheet"] = 0.0
        reasons.append(f"Net Debt/EBITDA: {nd_ebitda:.1f}x")
    else:
        scores["clean_balance_sheet"] = 0
        reasons.append("Net Debt/EBITDA unavailable")

    # 5. Stable/predictable FCF (FCF margin > 10%)
    revenue = info.get("totalRevenue")
    fcf_margin = safe_div(fcf, revenue)
    if fcf_margin is not None:
        if fcf_margin > 0.20:
            scores["stable_fcf"] = 10.0
        elif fcf_margin > 0.15:
            scores["stable_fcf"] = 8.0
        elif fcf_margin > 0.10:
            scores["stable_fcf"] = 6.0
        elif fcf_margin > 0.05:
            scores["stable_fcf"] = 4.0
        elif fcf_margin > 0:
            scores["stable_fcf"] = 2.0
        else:
            scores["stable_fcf"] = 0.0
        reasons.append(f"FCF margin: {fcf_margin:.1%}")
    else:
        scores["stable_fcf"] = 0
        reasons.append("FCF margin unavailable")

    # 6. Consolidating industry (qualitative — default mid-score)
    scores["consolidating_industry"] = 5.0
    reasons.append("Consolidating industry: default 5/10 (agent adjusts based on sector M&A research)")

    # 7. No anti-takeover provisions (qualitative — default mid-score)
    scores["no_anti_takeover"] = 5.0
    reasons.append("Anti-takeover provisions: default 5/10 (agent adjusts from proxy/governance research)")

    # 8. Low insider ownership
    insider_pct = info.get("heldPercentInsiders")
    if insider_pct is not None:
        if insider_pct < 0.03:
            scores["low_insider_ownership"] = 10.0
        elif insider_pct < 0.05:
            scores["low_insider_ownership"] = 8.0
        elif insider_pct < 0.10:
            scores["low_insider_ownership"] = 6.0
        elif insider_pct < 0.20:
            scores["low_insider_ownership"] = 4.0
        elif insider_pct < 0.30:
            scores["low_insider_ownership"] = 2.0
        else:
            scores["low_insider_ownership"] = 0.0
        reasons.append(f"Insider ownership: {insider_pct:.1%}")
    else:
        scores["low_insider_ownership"] = 5.0
        reasons.append("Insider ownership data unavailable")

    # 9. Recent activist 13D (qualitative — agent fills from research)
    scores["activist_13d_present"] = 0.0
    reasons.append("Activist 13D: default 0/10 (agent adjusts if 13D filing detected)")

    # 10. Conglomerate discount (qualitative — agent fills from SOTP)
    scores["conglomerate_discount"] = 0.0
    reasons.append("Conglomerate discount: default 0/10 (agent adjusts if SOTP > market cap by 20%+)")

    composite = sum(scores.values())

    return {
        "methodology": "Acquisition Target Probability: 10 factors scored 0-10 each, sum to 0-100",
        "composite_score": round(composite, 1),
        "interpretation": "High" if composite > 70 else "Moderate" if composite > 40 else "Low",
        "component_scores": {k: round(v, 1) for k, v in scores.items()},
        "evidence": reasons,
        "agent_adjustable_fields": [
            "strategic_asset_value", "consolidating_industry",
            "no_anti_takeover", "activist_13d_present", "conglomerate_discount"
        ],
    }


# ---------------------------------------------------------------------------
# 2. LBO Affordability Model
# ---------------------------------------------------------------------------

def compute_lbo_floor(info: dict, ticker: str) -> dict:
    """Compute max PE buyout price at 20% IRR over 5 years."""
    ebitda = info.get("ebitda")
    market_cap = info.get("marketCap")
    shares = info.get("sharesOutstanding")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    total_debt = info.get("totalDebt", 0)
    total_cash = info.get("totalCash", 0)
    fcf = info.get("freeCashflow")

    if not all([ebitda, market_cap, shares, current_price]):
        return {"error": "Insufficient data for LBO model (need EBITDA, market cap, shares, price)"}

    if ebitda <= 0:
        return {"error": "Negative EBITDA — LBO model not applicable"}

    # Estimate EBITDA growth (use trailing growth if available, cap at 15%)
    try:
        stock = yf.Ticker(ticker)
        hist_financials = stock.quarterly_income_stmt
        if hist_financials is not None and not hist_financials.empty:
            if "EBITDA" in hist_financials.index:
                ebitda_series = hist_financials.loc["EBITDA"].dropna().sort_index()
                if len(ebitda_series) >= 5:
                    recent_4q = ebitda_series.iloc[-4:].sum()
                    prior_4q = ebitda_series.iloc[-8:-4].sum()
                    if prior_4q > 0 and recent_4q > 0:
                        yoy_growth = (recent_4q / prior_4q) - 1
                    else:
                        yoy_growth = 0.05
                else:
                    yoy_growth = 0.05
            else:
                yoy_growth = 0.05
        else:
            yoy_growth = 0.05
    except Exception:
        yoy_growth = 0.05

    ebitda_growth = max(0.0, min(0.15, yoy_growth))

    # FCF as % of EBITDA (for debt paydown estimation)
    fcf_ebitda_ratio = safe_div(fcf, ebitda) if fcf else 0.5
    if fcf_ebitda_ratio is None or fcf_ebitda_ratio <= 0:
        fcf_ebitda_ratio = 0.5

    target_irr = 0.20
    hold_years = 5
    transaction_costs_pct = 0.03
    debt_paydown_pct = 0.50

    results = {}

    for leverage in [4.0, 4.5, 5.0, 5.5, 6.0]:
        for exit_multiple_delta in [-0.5, 0.0, 1.0]:
            # Forward EBITDA at exit
            exit_ebitda = ebitda * ((1 + ebitda_growth) ** hold_years)

            # Try different entry multiples to find one that yields 20% IRR
            best_entry_ev = None
            for entry_multiple in np.arange(6.0, 25.0, 0.5):
                entry_ev = entry_multiple * ebitda
                entry_equity = entry_ev * (1 + transaction_costs_pct) - (leverage * ebitda)

                if entry_equity <= 0:
                    continue

                # Debt at entry
                entry_debt = leverage * ebitda

                # Debt paydown over hold period
                total_debt_paydown = 0
                current_ebitda_yr = ebitda
                for yr in range(1, hold_years + 1):
                    current_ebitda_yr *= (1 + ebitda_growth)
                    yr_fcf = current_ebitda_yr * fcf_ebitda_ratio
                    total_debt_paydown += yr_fcf * debt_paydown_pct

                exit_debt = max(0, entry_debt - total_debt_paydown)

                # Exit
                exit_multiple = entry_multiple + exit_multiple_delta
                exit_ev = exit_multiple * exit_ebitda
                exit_equity = exit_ev - exit_debt

                if exit_equity <= 0:
                    continue

                # IRR
                irr = (exit_equity / entry_equity) ** (1 / hold_years) - 1

                if abs(irr - target_irr) < 0.02:
                    best_entry_ev = entry_ev
                    break
                elif irr > target_irr:
                    best_entry_ev = entry_ev

            if best_entry_ev is not None:
                # Convert EV to per-share price
                implied_equity_value = best_entry_ev - (total_debt or 0) + (total_cash or 0)
                implied_price = safe_div(implied_equity_value, shares)

                key = f"leverage_{leverage:.1f}x_exit_delta_{exit_multiple_delta:+.1f}x"
                results[key] = {
                    "entry_ev": round(best_entry_ev / 1e9, 2),
                    "implied_price_per_share": round(implied_price, 2) if implied_price else None,
                    "premium_to_current": round((implied_price / current_price - 1) * 100, 1) if implied_price and current_price else None,
                }

    # Extract the base case (5.0x leverage, 0.0 exit delta)
    base_key = "leverage_5.0x_exit_delta_+0.0x"
    base_case = results.get(base_key, {})
    lbo_floor_price = base_case.get("implied_price_per_share")

    return {
        "methodology": "LBO Affordability: solve for max entry price yielding 20% equity IRR over 5yr hold. Assumptions: 50% FCF to debt paydown, 3% transaction costs.",
        "assumptions": {
            "target_irr": "20%",
            "hold_period": "5 years",
            "ebitda_growth_rate": f"{ebitda_growth:.1%}",
            "fcf_ebitda_conversion": f"{fcf_ebitda_ratio:.0%}",
            "debt_paydown_pct_of_fcf": "50%",
            "transaction_costs": "3%",
        },
        "current_price": current_price,
        "lbo_floor_price": lbo_floor_price,
        "premium_to_current": round((lbo_floor_price / current_price - 1) * 100, 1) if lbo_floor_price and current_price else None,
        "interpretation": (
            "PE floor ABOVE current price — valuation support exists"
            if lbo_floor_price and current_price and lbo_floor_price > current_price
            else "PE floor BELOW current price — no private market floor"
        ),
        "sensitivity_table": results,
    }


# ---------------------------------------------------------------------------
# 3. Activist Investor Probability Score
# ---------------------------------------------------------------------------

def compute_activist_probability(info: dict, sector_median: dict) -> dict:
    """Score 7 characteristics that attract activist investors (0-100)."""
    scores: dict[str, float] = {}
    reasons: list[str] = []

    market_cap = info.get("marketCap")
    total_cash = info.get("totalCash", 0)
    op_margin = info.get("operatingMargins")
    pe_ratio = info.get("trailingPE")
    insider_pct = info.get("heldPercentInsiders")

    sector_pe = sector_median.get("pe_ratio")
    sector_op_margin = sector_median.get("op_margin")

    # 1. Undervalued vs peers (P/E below sector median) — 15 pts
    if pe_ratio is not None and sector_pe is not None and sector_pe > 0:
        discount = (sector_pe - pe_ratio) / sector_pe
        scores["undervalued_vs_peers"] = min(15, max(0, discount * 60))
        reasons.append(f"P/E {pe_ratio:.1f}x vs sector {sector_pe:.1f}x")
    else:
        scores["undervalued_vs_peers"] = 0
        reasons.append("P/E comparison unavailable")

    # 2. Excess cash (cash > 20% of market cap) — 15 pts
    cash_pct = safe_div(total_cash, market_cap)
    if cash_pct is not None:
        if cash_pct > 0.30:
            scores["excess_cash"] = 15.0
        elif cash_pct > 0.20:
            scores["excess_cash"] = 12.0
        elif cash_pct > 0.10:
            scores["excess_cash"] = 6.0
        else:
            scores["excess_cash"] = 0.0
        reasons.append(f"Cash/Market Cap: {cash_pct:.1%}")
    else:
        scores["excess_cash"] = 0
        reasons.append("Cash data unavailable")

    # 3. Below-peer margins — 15 pts
    if op_margin is not None and sector_op_margin is not None:
        margin_gap = sector_op_margin - op_margin
        if margin_gap > 0.10:
            scores["below_peer_margins"] = 15.0
        elif margin_gap > 0.05:
            scores["below_peer_margins"] = 10.0
        elif margin_gap > 0.02:
            scores["below_peer_margins"] = 5.0
        else:
            scores["below_peer_margins"] = 0.0
        reasons.append(f"Op margin {op_margin:.1%} vs sector {sector_op_margin:.1%}")
    else:
        scores["below_peer_margins"] = 0
        reasons.append("Operating margin comparison unavailable")

    # 4. Low insider ownership — 15 pts
    if insider_pct is not None:
        if insider_pct < 0.03:
            scores["low_insider_ownership"] = 15.0
        elif insider_pct < 0.05:
            scores["low_insider_ownership"] = 12.0
        elif insider_pct < 0.10:
            scores["low_insider_ownership"] = 8.0
        elif insider_pct < 0.20:
            scores["low_insider_ownership"] = 4.0
        else:
            scores["low_insider_ownership"] = 0.0
        reasons.append(f"Insider ownership: {insider_pct:.1%}")
    else:
        scores["low_insider_ownership"] = 7.5
        reasons.append("Insider ownership unavailable — using midpoint")

    # 5. No anti-takeover provisions — 10 pts (qualitative)
    scores["no_anti_takeover"] = 5.0
    reasons.append("Anti-takeover: default 5/10 (agent adjusts from proxy research)")

    # 6. Conglomerate structure — 15 pts (qualitative)
    scores["conglomerate_structure"] = 0.0
    reasons.append("Conglomerate structure: default 0/15 (agent adjusts if multi-segment)")

    # 7. Recent underperformance — 15 pts
    # Computed from 1-year return vs sector (requires historical data)
    try:
        stock = yf.Ticker(info.get("symbol", ""))
        hist = stock.history(period="1y")
        if hist is not None and len(hist) > 20:
            stock_return = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1
            # Compare to SPY as proxy for sector
            spy = yf.Ticker("SPY").history(period="1y")
            if spy is not None and len(spy) > 20:
                market_return = (spy["Close"].iloc[-1] / spy["Close"].iloc[0]) - 1
                underperf = market_return - stock_return
                if underperf > 0.30:
                    scores["recent_underperformance"] = 15.0
                elif underperf > 0.20:
                    scores["recent_underperformance"] = 12.0
                elif underperf > 0.10:
                    scores["recent_underperformance"] = 8.0
                elif underperf > 0.05:
                    scores["recent_underperformance"] = 4.0
                else:
                    scores["recent_underperformance"] = 0.0
                reasons.append(f"1yr return: {stock_return:.1%} vs market {market_return:.1%}")
            else:
                scores["recent_underperformance"] = 0
                reasons.append("Market return data unavailable")
        else:
            scores["recent_underperformance"] = 0
            reasons.append("Stock return data unavailable")
    except Exception:
        scores["recent_underperformance"] = 0
        reasons.append("Return calculation failed")

    composite = sum(scores.values())

    return {
        "methodology": "Activist Probability: 7 factors weighted 10-15 pts each, sum to 0-100",
        "composite_score": round(composite, 1),
        "interpretation": "High" if composite > 65 else "Moderate" if composite > 35 else "Low",
        "component_scores": {k: round(v, 1) for k, v in scores.items()},
        "evidence": reasons,
        "agent_adjustable_fields": ["no_anti_takeover", "conglomerate_structure"],
    }


# ---------------------------------------------------------------------------
# 4. Precedent Transaction Premium Range
# ---------------------------------------------------------------------------

SECTOR_PREMIUMS = {
    45: {"low": 0.30, "mid": 0.40, "high": 0.50, "sector": "Technology/Software"},
    35: {"low": 0.40, "mid": 0.50, "high": 0.60, "sector": "Healthcare/Pharma"},
    20: {"low": 0.20, "mid": 0.28, "high": 0.35, "sector": "Industrials"},
    25: {"low": 0.25, "mid": 0.33, "high": 0.40, "sector": "Consumer Discretionary"},
    30: {"low": 0.25, "mid": 0.33, "high": 0.40, "sector": "Consumer Staples"},
    40: {"low": 0.15, "mid": 0.23, "high": 0.30, "sector": "Financial Services"},
    10: {"low": 0.20, "mid": 0.28, "high": 0.35, "sector": "Energy"},
    50: {"low": 0.25, "mid": 0.35, "high": 0.45, "sector": "Communication Services"},
    55: {"low": 0.15, "mid": 0.25, "high": 0.35, "sector": "Utilities"},
    60: {"low": 0.15, "mid": 0.20, "high": 0.30, "sector": "Real Estate"},
    15: {"low": 0.20, "mid": 0.30, "high": 0.40, "sector": "Materials"},
}


def compute_precedent_premium(info: dict, gics_sector: int | None) -> dict:
    """Estimate takeout price range based on sector-typical acquisition premiums."""
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not current_price:
        return {"error": "Current price unavailable"}

    sector = gics_sector or 45  # Default to tech if unknown
    premiums = SECTOR_PREMIUMS.get(sector, {"low": 0.20, "mid": 0.30, "high": 0.40, "sector": "Unknown"})

    return {
        "methodology": f"Precedent transaction premium range for {premiums['sector']} sector based on historical M&A data",
        "current_price": current_price,
        "sector": premiums["sector"],
        "premium_range": {
            "low_premium": f"{premiums['low']:.0%}",
            "mid_premium": f"{premiums['mid']:.0%}",
            "high_premium": f"{premiums['high']:.0%}",
        },
        "implied_takeout_range": {
            "low": round(current_price * (1 + premiums["low"]), 2),
            "mid": round(current_price * (1 + premiums["mid"]), 2),
            "high": round(current_price * (1 + premiums["high"]), 2),
        },
        "note": "Agent should search for actual recent precedent transactions in the sector to refine these estimates",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fetch_private_comps(ticker: str, gics_sector: int | None = None) -> dict:
    """Run all private market and M&A analyses for a ticker."""
    if not YFINANCE_AVAILABLE:
        return {"error": "yfinance not installed. Run: pip install yfinance"}

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception as e:
        return {"error": f"Failed to fetch data for {ticker}: {str(e)}"}

    if not info or info.get("regularMarketPrice") is None:
        return {"error": f"No valid data returned for ticker {ticker}"}

    info["symbol"] = ticker

    # Build sector medians (rough estimates; agent should refine from peer data)
    sector_median = {
        "ev_ebitda": 12.0,
        "pe_ratio": 20.0,
        "op_margin": 0.15,
    }

    results = {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gics_sector": gics_sector,
    }

    # 1. Acquisition Target Score
    try:
        results["acquisition_target"] = compute_acquisition_target_score(info, {}, sector_median)
    except Exception as e:
        results["acquisition_target"] = {"error": str(e)}

    # 2. LBO Floor
    try:
        results["lbo_model"] = compute_lbo_floor(info, ticker)
    except Exception as e:
        results["lbo_model"] = {"error": str(e)}

    # 3. Activist Probability
    try:
        results["activist_probability"] = compute_activist_probability(info, sector_median)
    except Exception as e:
        results["activist_probability"] = {"error": str(e)}

    # 4. Precedent Transaction Premiums
    try:
        results["precedent_transactions"] = compute_precedent_premium(info, gics_sector)
    except Exception as e:
        results["precedent_transactions"] = {"error": str(e)}

    return results


def main():
    parser = argparse.ArgumentParser(description="M&A probability, LBO floor, and activist investor analysis")
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument("--sector", type=int, default=None, help="GICS sector code (e.g., 45 for IT)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    results = fetch_private_comps(args.ticker.upper(), args.sector)

    output = json.dumps(results, indent=2, default=str)
    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
