#!/usr/bin/env python3
"""Fetch financial data for a ticker using free data sources.

Usage:
    fetch_financials.py AAPL [--years 5] [--api-key-env FMP_API_KEY]
    fetch_financials.py AAPL MSFT GOOGL --years 3
    fetch_financials.py BRK.B --output ./reports/BRK.B/raw-data.json

Market-aware fallback chain:
  China/HK tickers (.SZ, .SH, .HK, 6-digit codes) → baostock → akshare → yfinance → FMP
  US/Global tickers → yfinance → SEC EDGAR → akshare (global indices) → FMP

Output: JSON to stdout or --output file.
"""

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.stderr.write("Error: 'requests' package required. Run: pip install requests\n")
    sys.exit(1)

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

EDGAR_HEADERS = {"User-Agent": "StockAnalysisSkill/1.0 (research@example.com)"}
EDGAR_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"

_ticker_to_cik_cache: dict = {}


def validate_ticker(ticker: str) -> str:
    """Validate and normalize ticker. Accepts: AAPL, BRK.B, BF-B, 000001.SZ, etc."""
    cleaned = ticker.strip().upper()
    if not cleaned:
        raise ValueError(f"Empty ticker: {ticker}")
    # US format: AAPL, BRK.B
    if re.match(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$", cleaned):
        return cleaned
    # China format: 000001.SZ, 600000.SH, 000001, 600000
    if re.match(r"^\d{6}(\.(SZ|SH|SS|BJ|HK))?$", cleaned, re.IGNORECASE):
        return cleaned
    raise ValueError(f"Invalid ticker format: {ticker}")


def detect_market(ticker: str) -> str:
    """Detect the market from ticker format.

    Returns: 'china' | 'hongkong' | 'us'
    """
    t = ticker.upper()
    if re.match(r"^\d{6}\.(SZ|SH|SS|BJ)$", t) or re.match(r"^\d{6}$", t):
        return "china"
    if re.match(r"^\d{4,5}\.HK$", t):
        return "hongkong"
    return "us"


# ---------------------------------------------------------------------------
# Tier 0 (China/HK): akshare — wraps East Money, Sina Finance, etc.
# ---------------------------------------------------------------------------


def fetch_from_akshare(ticker: str, years: int) -> dict | None:
    """Fetch Chinese/HK stock data from akshare. Free, no API key.

    Covers: A-shares (Shanghai/Shenzhen/Beijing), Hong Kong stocks,
    and global index constituents through East Money data sources.
    """
    try:
        import akshare as ak
    except ImportError:
        return None

    try:
        market = detect_market(ticker)
        if market == "us":
            # akshare can fetch US stocks too via East Money global
            return _fetch_akshare_us(ticker, years, ak)

        result: dict = {
            "ticker": ticker,
            "source": "akshare",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "entity_name": "",
            "profile": {},
            "financials": {
                "income_statement": {
                    "revenue": [],
                    "net_income": [],
                    "operating_income": [],
                },
                "balance_sheet": {
                    "total_assets": [],
                    "total_liabilities": [],
                    "stockholders_equity": [],
                    "total_debt": [],
                    "cash": [],
                },
                "cash_flow": {
                    "operating_cash_flow": [],
                    "capex": [],
                    "free_cash_flow": [],
                },
            },
            "insider_transactions": [],
            "institutional_holdings": [],
            "segments": [],
            "years_requested": years,
        }

        code = (
            ticker.upper()
            .replace(".SZ", "")
            .replace(".SH", "")
            .replace(".BJ", "")
            .replace(".HK", "")
        )

        # -- Company profile --
        try:
            if market == "china":
                profile_df = ak.stock_individual_info_em(symbol=code)
                if profile_df is not None and not profile_df.empty:
                    pd = dict(zip(profile_df["item"], profile_df["value"]))
                    result["entity_name"] = str(pd.get("股票简称", ""))
                    result["profile"] = {
                        "sector": str(pd.get("行业", "")),
                        "market_cap": _cn_num(pd.get("总市值")),
                        "employees": _cn_int(pd.get("员工人数")),
                        "listing_date": str(pd.get("上市时间", "")),
                        "pe_ratio": _cn_num(pd.get("市盈率-动态")),
                        "pb_ratio": _cn_num(pd.get("市净率")),
                    }
            else:
                result["entity_name"] = f"{ticker} (HK)"
        except Exception:
            pass

        # -- Historical K-line for price context --
        try:
            import pandas as pd

            if market == "china":
                hist = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=f"{datetime.now().year - years}0101",
                    end_date="20991231",
                    adjust="qfq",
                )
            else:
                hist = ak.stock_hk_daily(symbol=code, adjust="qfq")

            if hist is not None and not hist.empty:
                date_c = "日期" if "日期" in hist.columns else "date"
                close_c = "收盘" if "收盘" in hist.columns else "close"
                high_c = "最高" if "最高" in hist.columns else "high"
                low_c = "最低" if "最低" in hist.columns else "low"

                last = hist.iloc[-1]
                result["profile"]["current_price"] = (
                    float(last[close_c]) if pd.notna(last[close_c]) else None
                )
                result["profile"]["52w_high"] = (
                    float(hist[high_c].max()) if high_c in hist.columns else None
                )
                result["profile"]["52w_low"] = (
                    float(hist[low_c].min()) if low_c in hist.columns else None
                )
        except Exception:
            pass

        # -- Financial statements --
        try:
            if market == "china":
                fin = ak.stock_financial_abstract(symbol=code)
                if fin is not None and not fin.empty:
                    _parse_cn_financials(fin, result["financials"], years)
            else:
                try:
                    hkf = ak.stock_hk_financial_indicator_em(symbol=code)
                    if hkf is not None and not hkf.empty:
                        _parse_hk_financials(hkf, result["financials"], years)
                except Exception:
                    pass
        except Exception:
            pass

        if not result.get("entity_name") and not result["profile"].get("current_price"):
            return None
        return result

    except Exception as e:
        sys.stderr.write(f"akshare error for {ticker}: {e}\n")
        return None


def _fetch_akshare_us(ticker: str, years: int, ak) -> dict | None:
    """Fetch US stock data via akshare (East Money global coverage)."""
    try:
        hist = ak.stock_us_daily(symbol=ticker, adjust="qfq")
        if hist is None or hist.empty:
            return None

        close_vals = hist["close"].tail(252)
        return {
            "ticker": ticker,
            "source": "akshare",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "entity_name": ticker,
            "profile": {
                "current_price": float(close_vals.iloc[-1])
                if len(close_vals) > 0
                else None,
                "52w_high": float(close_vals.max()) if len(close_vals) > 0 else None,
                "52w_low": float(close_vals.min()) if len(close_vals) > 0 else None,
            },
            "financials": {},
            "insider_transactions": [],
            "institutional_holdings": [],
            "segments": [],
            "years_requested": years,
        }
    except Exception:
        return None


def _cn_num(value) -> float | None:
    """Parse Chinese numeric: '1234.56亿', '12.34万', '%'."""
    if value is None or value in ("", "-", "—"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "").replace(" ", "")
    for unit, mult in [("亿", 1e8), ("万", 1e4), ("千", 1e3), ("%", 0.01)]:
        if unit in s:
            try:
                return float(s.replace(unit, "")) * mult
            except ValueError:
                return None
    try:
        return float(s)
    except ValueError:
        return None


def _cn_int(value) -> int | None:
    v = _cn_num(value)
    return int(v) if v is not None else None


def _parse_cn_financials(df, out: dict, years: int):
    """Parse akshare financial_abstract (wide-format) into standard JSON."""
    if df is None or df.empty:
        return

    date_cols = [c for c in df.columns if re.match(r"^\d{8}", str(c))]
    item_col = df.columns[0]

    def pick(keywords: list[str]) -> list:
        for kw in keywords:
            mask = df[item_col].astype(str).str.contains(kw, na=False)
            if mask.any():
                row = df[mask].iloc[0]
                return [
                    {
                        "period": f"{str(c)[:4]}-{str(c)[4:6]}-{str(c)[6:8]}",
                        "value": _cn_num(row[c]),
                    }
                    for c in date_cols[:years]
                ]
        return []

    out["income_statement"]["revenue"] = pick(["营业总收入", "营业收入"])
    out["income_statement"]["net_income"] = pick(["净利润"])
    out["income_statement"]["operating_income"] = pick(["营业利润"])
    out["balance_sheet"]["total_assets"] = pick(["资产总计", "总资产"])
    out["balance_sheet"]["total_liabilities"] = pick(["负债合计", "总负债"])
    out["balance_sheet"]["stockholders_equity"] = pick(["股东权益", "所有者权益"])
    out["balance_sheet"]["cash"] = pick(["货币资金"])
    out["cash_flow"]["operating_cash_flow"] = pick(
        ["经营活动产生的现金流量净额", "经营活动现金流"]
    )


def _parse_hk_financials(df, out: dict, years: int):
    """Parse HK financial indicators (East Money format)."""
    if df is None or df.empty:
        return
    try:
        cols = df.columns.tolist()
        date_cols = [c for c in cols if re.match(r"^\d{4}", str(c))]
        # Adapt to East Money HK format — columns vary by version
        for i, dc in enumerate(date_cols[:years]):
            if dc not in df.columns:
                continue
            row = df[dc]
            period = str(dc)
            val = _cn_num(row.iloc[0]) if len(row) > 0 else None
            out["income_statement"]["revenue"].append({"period": period, "value": val})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tier 1 fallback (China): baostock — official securities data, free, stable
# ---------------------------------------------------------------------------


def fetch_from_baostock(ticker: str, years: int) -> dict | None:
    """Fetch Chinese A-share data from baostock. Free, no API key, reliable."""
    try:
        import baostock as bs
    except ImportError:
        return None

    import io as _io

    market = detect_market(ticker)
    if market not in ("china", "hongkong"):
        return None

    # Suppress baostock's stdout login message
    _old_stdout = sys.stdout
    sys.stdout = _io.StringIO()
    lg = bs.login()
    sys.stdout = _old_stdout
    if lg.error_code != "0":
        sys.stderr.write(f"baostock login failed: {lg.error_msg}\n")
        return None

    bs_code = _get_baostock_code(ticker)
    if not bs_code:
        _safe_bs_logout(bs)
        return None

    result: dict = {
        "ticker": ticker,
        "source": "baostock",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "entity_name": "",
        "profile": {},
        "financials": {
            "income_statement": {
                "revenue": [],
                "net_income": [],
                "operating_income": [],
            },
            "balance_sheet": {
                "total_assets": [],
                "total_liabilities": [],
                "stockholders_equity": [],
                "total_debt": [],
                "cash": [],
            },
            "cash_flow": {
                "operating_cash_flow": [],
                "capex": [],
                "free_cash_flow": [],
            },
        },
        "insider_transactions": [],
        "institutional_holdings": [],
        "segments": [],
        "years_requested": years,
    }

    try:
        # -- Company basic info --
        try:
            rs = bs.query_stock_basic(code=bs_code)
            if rs.error_code == "0":
                while rs.next():
                    row = rs.get_row_data()
                    result["entity_name"] = row[1]
                    result["profile"]["listing_date"] = row[2]
        except Exception:
            pass

        # -- Industry classification --
        try:
            rs = bs.query_stock_industry(code=bs_code)
            if rs.error_code == "0":
                while rs.next():
                    row = rs.get_row_data()
                    result["profile"]["industry"] = row[3]
        except Exception:
            pass

        # -- Daily K-line with PE/PB/PS --
        try:
            import pandas as pd

            from datetime import date

            start = f"{date.today().year - years}-01-01"
            end = date.today().strftime("%Y-%m-%d")

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,peTTM,pbMRQ,psTTM",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code == "0":
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    cols = [
                        "date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "peTTM",
                        "pbMRQ",
                        "psTTM",
                    ]
                    hist = pd.DataFrame(rows, columns=cols)
                    for c in [
                        "open",
                        "high",
                        "low",
                        "close",
                        "peTTM",
                        "pbMRQ",
                        "psTTM",
                    ]:
                        hist[c] = pd.to_numeric(hist[c], errors="coerce")

                    last = hist.iloc[-1]
                    if pd.notna(last["close"]) and float(last["close"]) <= 0:
                        return None
                    result["profile"]["current_price"] = (
                        float(last["close"]) if pd.notna(last["close"]) else None
                    )
                    result["profile"]["pe_ratio"] = (
                        float(last["peTTM"]) if pd.notna(last["peTTM"]) else None
                    )
                    result["profile"]["pb_ratio"] = (
                        float(last["pbMRQ"]) if pd.notna(last["pbMRQ"]) else None
                    )
                    result["profile"]["52w_high"] = (
                        float(hist["high"].tail(252).max()) if len(hist) > 0 else None
                    )
                    result["profile"]["52w_low"] = (
                        float(hist["low"].tail(252).min()) if len(hist) > 0 else None
                    )
        except Exception:
            pass

        # -- Financial statements --
        try:
            _parse_baostock_financials(bs_code, result["financials"], years)
        except Exception:
            pass

    except Exception as e:
        sys.stderr.write(f"baostock data fetch error for {ticker}: {e}\n")

    _safe_bs_logout(bs)

    if not result.get("entity_name") and not result["profile"].get("current_price"):
        return None
    return result


def _get_baostock_code(ticker: str) -> str | None:
    """Convert ticker to baostock exchange-prefixed format."""
    t = ticker.upper()
    code = (
        t.replace(".SZ", "")
        .replace(".SH", "")
        .replace(".SS", "")
        .replace(".BJ", "")
        .replace(".HK", "")
    )
    if ".SZ" in t:
        return f"sz.{code}"
    elif ".SH" in t or ".SS" in t:
        return f"sh.{code}"
    elif ".BJ" in t:
        return f"bj.{code}"
    num = int(code) if code.isdigit() else None
    if num:
        if 600000 <= num <= 609999 or 688000 <= num <= 689999:
            return f"sh.{code}"
        return f"sz.{code}"
    return None


def _safe_bs_logout(bs) -> None:
    """Logout from baostock suppressing stdout noise."""
    import io as _io

    _old = sys.stdout
    sys.stdout = _io.StringIO()
    try:
        bs.logout()
    except Exception:
        pass
    sys.stdout = _old


def _parse_baostock_financials(bs_code: str, out: dict, years: int):
    """Parse baostock financial statements into standard JSON format.

    baostock provides:
      - Profit: netProfit (idx 6), MBRevenue/operating revenue (idx 8), ROE (idx 3), epsTTM (idx 7)
      - Balance: ratios only (currentRatio, liabilityToAsset, assetToEquity) — no absolute values
      - Cash flow: ratios only (CFOToNP idx 7, CFOToOR idx 6) — no absolute values

    For absolute BS/CF values, akshare's stock_financial_abstract is the primary source.
    """
    import baostock as bs
    from datetime import date

    current_year = date.today().year

    for year_offset in range(years):
        y = current_year - year_offset
        # Profit data: net profit + operating revenue
        rs = bs.query_profit_data(code=bs_code, year=y, quarter=4)
        if rs.error_code == "0":
            while rs.next():
                row = rs.get_row_data()
                period = row[2][:4] if row[2] else str(y)
                # netProfit at index 6
                if row[6]:
                    out["income_statement"]["net_income"].append(
                        {"period": period, "value": float(row[6])}
                    )
                # MBRevenue (operating revenue) at index 8
                if row[8]:
                    out["income_statement"]["revenue"].append(
                        {"period": period, "value": float(row[8])}
                    )
                # ROE at index 3
                if row[3]:
                    out["income_statement"]["operating_income"].append(
                        {
                            "period": period,
                            "value": float(row[3]),
                            "metric": "roe_avg",
                        }
                    )

        # Balance sheet: only ratios available, extract assetToEquity for leverage proxy
        rs = bs.query_balance_data(code=bs_code, year=y, quarter=4)
        if rs.error_code == "0":
            while rs.next():
                row = rs.get_row_data()
                period = row[2][:4] if row[2] else str(y)
                # assetToEquity at index 8 (equity multiplier proxy)
                if row[8]:
                    out["balance_sheet"]["stockholders_equity"].append(
                        {
                            "period": period,
                            "value": float(row[8]),
                            "metric": "asset_to_equity",
                        }
                    )
                # liabilityToAsset at index 7
                if row[7]:
                    out["balance_sheet"]["total_liabilities"].append(
                        {
                            "period": period,
                            "value": float(row[7]),
                            "metric": "liability_to_asset",
                        }
                    )

        # Cash flow ratios
        rs = bs.query_cash_flow_data(code=bs_code, year=y, quarter=4)
        if rs.error_code == "0":
            while rs.next():
                row = rs.get_row_data()
                period = row[2][:4] if row[2] else str(y)
                # CFOToNP at index 7
                if row[7]:
                    out["cash_flow"]["operating_cash_flow"].append(
                        {
                            "period": period,
                            "value": float(row[7]),
                            "metric": "cfo_to_net_profit",
                        }
                    )


# ---------------------------------------------------------------------------
# Tier 2 fallback: yfinance (free, no API key, wraps Yahoo Finance)
# ---------------------------------------------------------------------------


def fetch_from_yfinance(ticker: str, years: int) -> dict | None:
    """Fetch from Yahoo Finance via yfinance library. Free, no API key needed."""
    try:
        import yfinance as yf
        import _yfinance_patch  # noqa: F401  # TickFlow OHLCV patch
    except ImportError:
        sys.stderr.write("yfinance not installed. Install: pip install yfinance\n")
        return None

    try:
        # yfinance uses .SS for Shanghai stocks, not .SH
        yf_ticker = (
            ticker.replace(".SH", ".SS") if ticker.upper().endswith(".SH") else ticker
        )
        stock = yf.Ticker(yf_ticker)
        info = stock.info or {}

        if not info or info.get("regularMarketPrice") is None:
            # Ticker might be invalid
            if not info:
                return None

        # Annual financial statements
        income_stmt = stock.financials  # columns = fiscal year ends
        balance_sheet = stock.balance_sheet
        cash_flow = stock.cashflow

        def df_to_series(df, field: str) -> list:
            """Extract a single line from a DataFrame into [{period, value}]."""
            if df is None or df.empty or field not in df.index:
                return []
            row = df.loc[field]
            return [
                {
                    "period": str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "value": float(row[idx])
                    if pd.notna(row[idx]) and not math.isinf(float(row[idx]))
                    else None,
                }
                for idx in row.index[:years]
            ]

        import pandas as pd

        revenue = df_to_series(income_stmt, "Total Revenue")
        net_income = df_to_series(income_stmt, "Net Income")
        operating_income = df_to_series(income_stmt, "Operating Income")
        gross_profit = df_to_series(income_stmt, "Gross Profit")

        total_assets = df_to_series(balance_sheet, "Total Assets")
        total_liabilities = df_to_series(
            balance_sheet, "Total Liabilities Net Minority Interest"
        )
        stockholders_equity = df_to_series(balance_sheet, "Stockholders Equity")
        total_debt = df_to_series(balance_sheet, "Total Debt") or df_to_series(
            balance_sheet, "Long Term Debt"
        )
        cash_equiv = df_to_series(balance_sheet, "Cash And Cash Equivalents")
        inventory = df_to_series(balance_sheet, "Inventory")
        accounts_receivable = df_to_series(
            balance_sheet, "Accounts Receivable"
        ) or df_to_series(balance_sheet, "Receivables")
        accounts_payable = df_to_series(balance_sheet, "Accounts Payable")
        current_assets = df_to_series(balance_sheet, "Current Assets")
        current_liabilities = df_to_series(balance_sheet, "Current Liabilities")
        retained_earnings = df_to_series(balance_sheet, "Retained Earnings")
        cost_of_revenue = df_to_series(income_stmt, "Cost Of Revenue")
        pretax_income = df_to_series(income_stmt, "Pretax Income") or df_to_series(
            income_stmt, "Income Before Tax"
        )

        ocf = df_to_series(cash_flow, "Operating Cash Flow")
        capex = df_to_series(cash_flow, "Capital Expenditure")

        # Compute FCF = OCF - capex
        fcf_series = []
        for o, c in zip(ocf, capex):
            if o.get("value") is not None and c.get("value") is not None:
                fcf_series.append(
                    {
                        "period": o["period"],
                        "value": o["value"] - abs(c["value"]),
                    }
                )

        # Quarterly data for recent trend
        quarterly_income = stock.quarterly_income_stmt
        # Fall back to legacy quarterly_financials if income_stmt is unavailable
        if quarterly_income is None or (
            hasattr(quarterly_income, "empty") and quarterly_income.empty
        ):
            quarterly_income = stock.quarterly_financials
        quarterly_revenue = (
            df_to_series(quarterly_income, "Total Revenue")
            if quarterly_income is not None
            else []
        )
        quarterly_eps = (
            (
                df_to_series(quarterly_income, "Diluted EPS")
                or df_to_series(quarterly_income, "Basic EPS")
                or []
            )
            if quarterly_income is not None
            else []
        )

        # Insider transactions
        insider_txns = []
        try:
            insider_raw = stock.insider_transactions
            if insider_raw is not None and not insider_raw.empty:
                for _, row in insider_raw.head(30).iterrows():
                    insider_txns.append(
                        {
                            "name": str(row.get("Insider", "")),
                            "transaction_type": str(row.get("Transaction", "")),
                            "shares": row.get("Shares"),
                            "value": row.get("Value"),
                            "date": str(row.get("Start Date", "")),
                        }
                    )
        except Exception:
            pass

        # Institutional holders
        inst_holders = []
        try:
            inst_raw = stock.institutional_holders
            if inst_raw is not None and not inst_raw.empty:
                for _, row in inst_raw.head(20).iterrows():
                    inst_holders.append(
                        {
                            "holder": str(row.get("Holder", "")),
                            "shares": row.get("Shares"),
                            "date_reported": str(row.get("Date Reported", "")),
                            "pct_out": row.get("% Out")
                            if "% Out" in row.index
                            else None,
                        }
                    )
        except Exception:
            pass

        # Profile info
        def _safe_float(v):
            """Return None for None/NaN/Inf/string-Infinity values."""
            if v is None:
                return None
            if isinstance(v, str):
                if v.lower() in ("inf", "-inf", "infinity", "-infinity", "nan"):
                    return None
                try:
                    v = float(v)
                except (ValueError, TypeError):
                    return None
            if isinstance(v, (int, float)):
                if math.isnan(v) or math.isinf(v):
                    return None
                return float(v)
            return None

        profile = {
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "employees": info.get("fullTimeEmployees"),
            "website": info.get("website", ""),
            "description": info.get("longBusinessSummary", "")[:500],
            "market_cap": _safe_float(info.get("marketCap")),
            "enterprise_value": _safe_float(info.get("enterpriseValue")),
            "shares_outstanding": _safe_float(info.get("sharesOutstanding")),
            "current_price": _safe_float(
                info.get("regularMarketPrice") or info.get("currentPrice")
            ),
            "beta": _safe_float(info.get("beta")),
            "52w_high": _safe_float(info.get("fiftyTwoWeekHigh")),
            "52w_low": _safe_float(info.get("fiftyTwoWeekLow")),
            "pe_ratio": _safe_float(info.get("trailingPE")),
            "forward_pe": _safe_float(info.get("forwardPE")),
            "peg_ratio": _safe_float(info.get("pegRatio")),
            "dividend_yield": _safe_float(info.get("dividendYield")),
            "payout_ratio": _safe_float(info.get("payoutRatio")),
        }

        return {
            "ticker": ticker,
            "source": "yfinance",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "entity_name": info.get("longName") or info.get("shortName", ""),
            "profile": profile,
            "financials": {
                "income_statement": {
                    "revenue": revenue,
                    "net_income": net_income,
                    "operating_income": operating_income,
                    "gross_profit": gross_profit,
                    "cost_of_revenue": cost_of_revenue,
                    "pretax_income": pretax_income,
                },
                "balance_sheet": {
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "stockholders_equity": stockholders_equity,
                    "total_debt": total_debt,
                    "cash": cash_equiv,
                    "inventory": inventory,
                    "accounts_receivable": accounts_receivable,
                    "accounts_payable": accounts_payable,
                    "current_assets": current_assets,
                    "current_liabilities": current_liabilities,
                    "retained_earnings": retained_earnings,
                },
                "cash_flow": {
                    "operating_cash_flow": ocf,
                    "capex": capex,
                    "free_cash_flow": fcf_series,
                },
            },
            "quarterly": {
                "revenue": quarterly_revenue[:8],
                "eps": quarterly_eps[:8],
            },
            "insider_transactions": insider_txns,
            "institutional_holdings": inst_holders,
            "segments": [],
            "years_requested": years,
        }

    except Exception as e:
        sys.stderr.write(f"yfinance error for {ticker}: {e}\n")
        return None


# ---------------------------------------------------------------------------
# Tier 2 fallback: SEC EDGAR (free, no API key)
# ---------------------------------------------------------------------------


def _load_cik_mapping() -> dict:
    """Load SEC EDGAR ticker-to-CIK mapping."""
    global _ticker_to_cik_cache
    if _ticker_to_cik_cache:
        return _ticker_to_cik_cache
    try:
        resp = requests.get(
            EDGAR_COMPANY_TICKERS_URL, headers=EDGAR_HEADERS, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        for entry in data.values():
            t = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", ""))
            if t and cik:
                _ticker_to_cik_cache[t] = cik.zfill(10)
        return _ticker_to_cik_cache
    except Exception:
        return {}


def _get_cik(ticker: str) -> str | None:
    """Resolve ticker to CIK number."""
    mapping = _load_cik_mapping()
    return mapping.get(ticker) or mapping.get(ticker.replace(".", "").replace("-", ""))


def fetch_from_edgar(ticker: str, years: int) -> dict | None:
    """Fetch from SEC EDGAR companyfacts API (free, no key required)."""
    cik = _get_cik(ticker)
    if not cik:
        return None

    try:
        time.sleep(0.15)
        facts_resp = requests.get(
            EDGAR_COMPANYFACTS_URL.format(cik=cik),
            headers=EDGAR_HEADERS,
            timeout=20,
        )
        if facts_resp.status_code != 200:
            return None

        facts = facts_resp.json()
        us_gaap = facts.get("facts", {}).get("us-gaap", {})

        def extract_annual(concept: str, unit: str = "USD") -> list:
            entries = us_gaap.get(concept, {}).get("units", {}).get(unit, [])
            annual = [e for e in entries if e.get("form") in ("10-K", "10-KT")]
            annual.sort(key=lambda x: x.get("end", ""), reverse=True)
            return annual[:years]

        revenue = extract_annual("Revenues") or extract_annual(
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        )
        net_income = extract_annual("NetIncomeLoss")
        total_assets = extract_annual("Assets")
        total_liabilities = extract_annual("Liabilities")
        stockholders_equity = extract_annual("StockholdersEquity")
        operating_income = extract_annual("OperatingIncomeLoss")
        cash_from_ops = extract_annual("NetCashProvidedByUsedInOperatingActivities")
        capex = extract_annual("PaymentsToAcquirePropertyPlantAndEquipment")
        total_debt = extract_annual("LongTermDebt") or extract_annual(
            "LongTermDebtNoncurrent"
        )
        cash = extract_annual("CashAndCashEquivalentsAtCarryingValue")
        inventory = extract_annual("InventoryNet") or extract_annual("Inventories")
        accounts_receivable = extract_annual(
            "AccountsReceivableNetCurrent"
        ) or extract_annual("AccountsReceivableNet")
        accounts_payable = extract_annual("AccountsPayableCurrent")
        current_assets = extract_annual("AssetsCurrent")
        current_liabilities = extract_annual("LiabilitiesCurrent")
        retained_earnings = extract_annual("RetainedEarningsAccumulatedDeficit")
        cost_of_revenue = extract_annual(
            "CostOfGoodsAndServicesSold"
        ) or extract_annual("CostOfRevenue")
        pretax_income = extract_annual(
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
        )

        result = {
            "ticker": ticker,
            "cik": cik,
            "source": "sec_edgar_companyfacts",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "entity_name": facts.get("entityName", ""),
            "financials": {
                "income_statement": {
                    "revenue": [
                        {"period": e.get("end"), "value": e.get("val")} for e in revenue
                    ],
                    "net_income": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in net_income
                    ],
                    "operating_income": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in operating_income
                    ],
                    "cost_of_revenue": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in cost_of_revenue
                    ],
                    "pretax_income": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in pretax_income
                    ],
                },
                "balance_sheet": {
                    "total_assets": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in total_assets
                    ],
                    "total_liabilities": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in total_liabilities
                    ],
                    "stockholders_equity": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in stockholders_equity
                    ],
                    "total_debt": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in total_debt
                    ],
                    "cash": [
                        {"period": e.get("end"), "value": e.get("val")} for e in cash
                    ],
                    "inventory": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in inventory
                    ],
                    "accounts_receivable": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in accounts_receivable
                    ],
                    "accounts_payable": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in accounts_payable
                    ],
                    "current_assets": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in current_assets
                    ],
                    "current_liabilities": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in current_liabilities
                    ],
                    "retained_earnings": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in retained_earnings
                    ],
                },
                "cash_flow": {
                    "operating_cash_flow": [
                        {"period": e.get("end"), "value": e.get("val")}
                        for e in cash_from_ops
                    ],
                    "capex": [
                        {"period": e.get("end"), "value": e.get("val")} for e in capex
                    ],
                    "free_cash_flow": [
                        {
                            "period": ops.get("end"),
                            "value": (ops.get("val") or 0) - abs(cx.get("val") or 0),
                        }
                        for ops, cx in zip(cash_from_ops, capex)
                    ]
                    if cash_from_ops and capex
                    else [],
                },
            },
            "insider_transactions": [],
            "institutional_holdings": [],
            "segments": [],
            "years_requested": years,
        }

        time.sleep(0.15)
        sub_resp = requests.get(
            EDGAR_SUBMISSIONS_URL.format(cik=cik),
            headers=EDGAR_HEADERS,
            timeout=15,
        )
        if sub_resp.status_code == 200:
            sub_data = sub_resp.json()
            result["entity_name"] = sub_data.get("name", result["entity_name"])
            result["sic"] = sub_data.get("sic", "")
            result["sic_description"] = sub_data.get("sicDescription", "")
            recent = sub_data.get("filings", {}).get("recent", {})
            if recent:
                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                result["recent_filings"] = [
                    {"form": f, "date": d} for f, d in zip(forms[:20], dates[:20])
                ]

        return result
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Tier 3 fallback: Financial Modeling Prep (premium, API key required)
# ---------------------------------------------------------------------------


def fetch_from_fmp(ticker: str, api_key: str, years: int) -> dict | None:
    """Fetch from Financial Modeling Prep API."""
    try:
        results = {
            "source": "fmp",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

        income_resp = requests.get(
            f"{FMP_BASE_URL}/income-statement/{ticker}",
            params={"period": "annual", "limit": years, "apikey": api_key},
            timeout=15,
        )
        if income_resp.status_code == 200:
            results["income_statement"] = income_resp.json()
        else:
            return None

        time.sleep(0.3)
        balance_resp = requests.get(
            f"{FMP_BASE_URL}/balance-sheet-statement/{ticker}",
            params={"period": "annual", "limit": years, "apikey": api_key},
            timeout=15,
        )
        if balance_resp.status_code == 200:
            results["balance_sheet"] = balance_resp.json()

        time.sleep(0.3)
        cf_resp = requests.get(
            f"{FMP_BASE_URL}/cash-flow-statement/{ticker}",
            params={"period": "annual", "limit": years, "apikey": api_key},
            timeout=15,
        )
        if cf_resp.status_code == 200:
            results["cash_flow"] = cf_resp.json()

        time.sleep(0.3)
        ratios_resp = requests.get(
            f"{FMP_BASE_URL}/ratios/{ticker}",
            params={"period": "annual", "limit": years, "apikey": api_key},
            timeout=15,
        )
        if ratios_resp.status_code == 200:
            results["ratios"] = ratios_resp.json()

        time.sleep(0.3)
        profile_resp = requests.get(
            f"{FMP_BASE_URL}/profile/{ticker}",
            params={"apikey": api_key},
            timeout=15,
        )
        if profile_resp.status_code == 200:
            results["profile"] = profile_resp.json()

        # FMP profile is a list; normalize to dict with standard keys for schema consistency
        # FMP schema differs from yfinance: profile is a list of dicts with keys like
        # 'price', 'mktCap', 'peRatio' instead of 'current_price', 'market_cap', 'pe_ratio'
        if isinstance(results.get("profile"), list) and results["profile"]:
            fmp_prof = results["profile"][0]
            results["profile"] = {
                "current_price": fmp_prof.get("price"),
                "market_cap": fmp_prof.get("mktCap"),
                "pe_ratio": fmp_prof.get("peRatio")
                if fmp_prof.get("peRatio")
                else None,
                "sector": fmp_prof.get("sector", ""),
                "industry": fmp_prof.get("industry", ""),
                "_raw_fmp_profile": fmp_prof,
            }
        elif "profile" not in results:
            results["profile"] = {
                "current_price": None,
                "market_cap": None,
                "pe_ratio": None,
            }

        time.sleep(0.3)
        insider_resp = requests.get(
            f"{FMP_BASE_URL}/insider-trading",
            params={"symbol": ticker, "limit": 50, "apikey": api_key},
            timeout=15,
        )
        if insider_resp.status_code == 200:
            results["insider_transactions"] = insider_resp.json()

        time.sleep(0.3)
        inst_resp = requests.get(
            f"{FMP_BASE_URL}/institutional-holder/{ticker}",
            params={"apikey": api_key},
            timeout=15,
        )
        if inst_resp.status_code == 200:
            results["institutional_holdings"] = inst_resp.json()

        return results
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Fetch financial data for stock tickers"
    )
    parser.add_argument(
        "tickers", nargs="+", help="Ticker symbols (e.g., AAPL MSFT BRK.B)"
    )
    parser.add_argument(
        "--years", type=int, default=5, help="Years of historical data (default: 5)"
    )
    parser.add_argument(
        "--api-key-env", default="FMP_API_KEY", help="Env var for premium API key"
    )
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    results = {}
    for raw_ticker in args.tickers:
        try:
            ticker = validate_ticker(raw_ticker)
        except ValueError as e:
            results[raw_ticker] = {"error": str(e)}
            continue

        data = None

        # Market-aware fallback chain
        market = detect_market(ticker)
        if market in ("china", "hongkong"):
            # China/HK: baostock → akshare → yfinance → FMP
            # baostock preferred as primary: more reliable (official exchange data)
            # akshare as fallback: broadest coverage but web-scraping based
            data = fetch_from_baostock(ticker, args.years)
            if data is None:
                data = fetch_from_akshare(ticker, args.years)
            if data is None:
                data = fetch_from_yfinance(ticker, args.years)
            if data is None:
                api_key = os.environ.get(args.api_key_env)
                if api_key:
                    data = fetch_from_fmp(ticker, api_key, args.years)
        else:
            # US/Global: yfinance first, then SEC EDGAR, then akshare, then FMP
            data = fetch_from_yfinance(ticker, args.years)
            if data is None:
                data = fetch_from_edgar(ticker, args.years)
            if data is None:
                data = fetch_from_akshare(ticker, args.years)
            if data is None:
                api_key = os.environ.get(args.api_key_env)
                if api_key:
                    data = fetch_from_fmp(ticker, api_key, args.years)

        if data is None:
            data = {
                "ticker": ticker,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source": "unavailable",
                "error": f"Could not fetch data for {ticker}. Ensure ticker is valid and internet is accessible.",
                "financials": {
                    "income_statement": {},
                    "balance_sheet": {},
                    "cash_flow": {},
                },
            }

        data["years_requested"] = args.years
        # Staleness check: warn if data retrieval is >7 days old or missing
        try:
            retrieved = data.get("retrieved_at", "")
            if retrieved:
                retrieved_dt = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_diff = (now - retrieved_dt).days
                if days_diff > 7:
                    data["stale_warning"] = True
            else:
                # No retrieved_at timestamp — treat as potentially stale
                data["stale_warning"] = True
        except Exception:
            pass
        results[ticker] = data

    # Sanitize NaN/Infinity values that produce non-standard JSON
    def _sanitize(obj):
        if _HAS_NUMPY:
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                if np.isnan(obj) or np.isinf(obj):
                    return None
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        return obj

    results = _sanitize(results)

    output = json.dumps(results, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
    else:
        print(output)

    if all(v.get("source") == "unavailable" for v in results.values()):
        sys.stderr.write("Warning: Could not fetch data for any ticker.\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
