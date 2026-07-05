#!/usr/bin/env python3
"""Alpha factor zoo: composable factor expressions with AST-safe evaluation.

Usage:
    alpha_factor_zoo.py ./reports/AAPL/raw-data.json --zoo technical
    alpha_factor_zoo.py ./reports/AAPL/raw-data.json --all
    alpha_factor_zoo.py ./reports/AAPL/raw-data.json --factor alpha_001
    alpha_factor_zoo.py ./reports/AAPL/raw-data.json --zoo technical --output ./reports/AAPL/alpha_factors.json

Provides 19 composable base operators and 4 factor zoos (technical,
fundamental, macro, alternative) totaling 120+ named factors.  Expression
evaluation uses Python's ``ast`` module -- never ``eval()``.
"""

import argparse
import ast
import json
import os
import sys
import warnings
from datetime import datetime, timezone
from typing import Any

try:
    import numpy as np
    import pandas as pd
except ImportError:
    sys.stderr.write(
        "Error: numpy and pandas required. Run: pip install numpy pandas\n"
    )
    sys.exit(1)


# ============================================================================
# 19 Base Operators
# ============================================================================

# -- Time-series operators (10) ------------------------------------------------


def ts_delta(series: pd.Series, period: int) -> pd.Series:
    """series - series.shift(period)"""
    return series - series.shift(period)


def ts_mean(series: pd.Series, period: int) -> pd.Series:
    """Rolling mean."""
    return series.rolling(window=period, min_periods=1).mean()


def ts_std(series: pd.Series, period: int) -> pd.Series:
    """Rolling standard deviation."""
    return series.rolling(window=period, min_periods=1).std()


def ts_sum(series: pd.Series, period: int) -> pd.Series:
    """Rolling sum."""
    return series.rolling(window=period, min_periods=1).sum()


def ts_max(series: pd.Series, period: int) -> pd.Series:
    """Rolling max."""
    return series.rolling(window=period, min_periods=1).max()


def ts_min(series: pd.Series, period: int) -> pd.Series:
    """Rolling min."""
    return series.rolling(window=period, min_periods=1).min()


def ts_rank(series: pd.Series, period: int) -> pd.Series:
    """Rolling percentile rank (0-1)."""
    return series.rolling(window=period, min_periods=1).rank(pct=True)


def ts_corr(x: pd.Series, y: pd.Series, period: int) -> pd.Series:
    """Rolling Pearson correlation."""
    return x.rolling(window=period, min_periods=2).corr(y)


def ts_cov(x: pd.Series, y: pd.Series, period: int) -> pd.Series:
    """Rolling covariance."""
    return x.rolling(window=period, min_periods=2).cov(y)


def ts_decay_linear(series: pd.Series, period: int) -> pd.Series:
    """Weighted moving average with linearly decaying weights (most recent = highest)."""
    weights = np.arange(1, period + 1, dtype=float)
    weights = weights / weights.sum()
    return series.rolling(window=period, min_periods=1).apply(
        lambda w: np.dot(w, weights[: len(w)]) if len(w) > 0 else np.nan,
        raw=True,
    )


# -- Cross-sectional operators (5) ---------------------------------------------


def cs_rank(series: pd.Series) -> pd.Series:
    """Cross-sectional rank (percentile)."""
    return series.rank(pct=True)


def zscore(series: pd.Series) -> pd.Series:
    """(x - mean) / std cross-sectional z-score."""
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def scale(series: pd.Series) -> pd.Series:
    """Normalize so that sum(abs(x)) = 1."""
    abs_sum = series.abs().sum()
    if abs_sum == 0 or pd.isna(abs_sum):
        return pd.Series(0.0, index=series.index)
    return series / abs_sum


def sign(series: pd.Series) -> pd.Series:
    """Sign function."""
    return np.sign(series)


def power(series: pd.Series, exp: float) -> pd.Series:
    """Element-wise power."""
    return series**exp


# -- Arithmetic operators (4) --------------------------------------------------


def add(a: pd.Series, b: pd.Series) -> pd.Series:
    return a + b


def subtract(a: pd.Series, b: pd.Series) -> pd.Series:
    return a - b


def multiply(a: pd.Series, b: pd.Series) -> pd.Series:
    return a * b


def divide(a: pd.Series, b: pd.Series) -> pd.Series:
    """Division with zero-division guard."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = a / b.replace(0, np.nan)
    return result


# Operator registry: maps operator names to callables
OPERATOR_REGISTRY: dict[str, Any] = {
    # Time-series
    "ts_delta": ts_delta,
    "ts_mean": ts_mean,
    "ts_std": ts_std,
    "ts_sum": ts_sum,
    "ts_max": ts_max,
    "ts_min": ts_min,
    "ts_rank": ts_rank,
    "ts_corr": ts_corr,
    "ts_cov": ts_cov,
    "ts_decay_linear": ts_decay_linear,
    # Cross-sectional
    "rank": cs_rank,
    "zscore": zscore,
    "scale": scale,
    "sign": sign,
    "power": power,
    # Arithmetic
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}


# ============================================================================
# AST-safe Expression Evaluator
# ============================================================================

# Allowed AST node types for safe parsing
# Includes expression-context nodes (Load, Store) that Python's parser
# attaches to every Name/Attribute node.
_ALLOWED_AST_NODES = (
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Expression,
    ast.Attribute,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
    ast.Load,
)

# Blocked dangerous names (used as Name nodes in AST).
# NOTE: "open" is intentionally NOT blocked here because it's a standard
# OHLCV data column.  Dangerous builtins are caught at Call-node level in
# _eval_ast_node where only OPERATOR_REGISTRY functions are allowed.
_BLOCKED_NAMES = frozenset(
    {
        "import",
        "__import__",
        "exec",
        "eval",
        "compile",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "type",
        "object",
        "class",
        "exit",
        "quit",
        "breakpoint",
        "input",
        "memoryview",
    }
)

# Attribute access whitelist -- only .shift() allowed on series
_ALLOWED_ATTRS = frozenset({"shift"})


class _UnsafeExpressionError(ValueError):
    """Raised when an expression contains disallowed AST nodes or names."""


def _validate_ast_node(node: ast.AST) -> None:
    """Recursively walk the AST tree, rejecting disallowed node types."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            if child.attr not in _ALLOWED_ATTRS:
                raise _UnsafeExpressionError(
                    f"Attribute access '.{child.attr}' is not allowed. "
                    f"Allowed: {sorted(_ALLOWED_ATTRS)}"
                )
        if isinstance(child, ast.Name) and child.id in _BLOCKED_NAMES:
            raise _UnsafeExpressionError(f"Name '{child.id}' is blocked for security.")
        if not isinstance(child, _ALLOWED_AST_NODES):
            raise _UnsafeExpressionError(
                f"AST node type {type(child).__name__} is not allowed "
                f"in factor expressions."
            )


def _eval_ast_node(
    node: ast.AST,
    data: dict[str, pd.Series],
) -> pd.Series | float | int:
    """Recursively evaluate an AST node against a data dict."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body, data)

    if isinstance(node, ast.Constant):
        # Numeric literal
        return node.value

    if isinstance(node, ast.Name):
        name = node.id
        if name in data:
            return data[name]
        # Return NaN series as fallback
        warnings.warn(f"Column '{name}' not found in data; using NaN.", stacklevel=2)
        return pd.Series(np.nan)

    if isinstance(node, ast.Call):
        func = node.func
        # Handle attribute call: series.shift(N)
        if isinstance(func, ast.Attribute):
            if func.attr == "shift":
                obj = _eval_ast_node(func.value, data)
                args = [_eval_ast_node(a, data) for a in node.args]
                if isinstance(obj, pd.Series) and len(args) == 1:
                    return obj.shift(int(args[0]))
            raise _UnsafeExpressionError(f"Method call .{func.attr}() is not allowed.")
        # Regular function call
        if isinstance(func, ast.Name):
            fname = func.id
            if fname not in OPERATOR_REGISTRY:
                raise _UnsafeExpressionError(
                    f"Unknown operator '{fname}'. "
                    f"Available: {sorted(OPERATOR_REGISTRY.keys())}"
                )
            args = [_eval_ast_node(a, data) for a in node.args]
            return OPERATOR_REGISTRY[fname](*args)
        raise _UnsafeExpressionError(f"Unsupported call type: {type(func).__name__}")

    if isinstance(node, ast.BinOp):
        left = _eval_ast_node(node.left, data)
        right = _eval_ast_node(node.right, data)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if isinstance(right, pd.Series):
                return left / right.replace(0, np.nan)
            elif right == 0:
                return np.nan
            return left / right
        raise _UnsafeExpressionError(
            f"Binary operator {type(node.op).__name__} not supported."
        )

    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast_node(node.operand, data)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return ~operand.astype(bool)
        raise _UnsafeExpressionError(
            f"Unary operator {type(node.op).__name__} not supported."
        )

    if isinstance(node, ast.Compare):
        left = _eval_ast_node(node.left, data)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_ast_node(comparator, data)
            if isinstance(op, ast.Lt):
                left = left < right
            elif isinstance(op, ast.LtE):
                left = left <= right
            elif isinstance(op, ast.Gt):
                left = left > right
            elif isinstance(op, ast.GtE):
                left = left >= right
            elif isinstance(op, ast.Eq):
                left = left == right
            elif isinstance(op, ast.NotEq):
                left = left != right
            else:
                raise _UnsafeExpressionError(
                    f"Comparison {type(op).__name__} not supported."
                )
        return left

    raise _UnsafeExpressionError(
        f"Cannot evaluate AST node type: {type(node).__name__}"
    )


# ============================================================================
# Factor Definitions
# ============================================================================


def _build_technical_factors() -> dict[str, dict]:
    """Build technical factor zoo (~35 factors)."""
    factors = {}
    cat = "technical"

    # --- Trend ---
    factors["alpha_001"] = {
        "expression": "rank(ts_delta(close, 10))",
        "category": cat,
        "subcategory": "trend",
        "description": "10日价格动量排名",
    }
    factors["alpha_002"] = {
        "expression": "rank(ts_corr(close, volume, 10))",
        "category": cat,
        "subcategory": "trend",
        "description": "10日量价相关性排名",
    }
    factors["alpha_003"] = {
        "expression": "rank(ts_delta(close, 5))",
        "category": cat,
        "subcategory": "trend",
        "description": "5日短期动量排名",
    }
    factors["alpha_004"] = {
        "expression": "rank(divide(ts_mean(close, 10), close))",
        "category": cat,
        "subcategory": "trend",
        "description": "均值偏离度 (mean reversion signal)",
    }
    factors["alpha_005"] = {
        "expression": "rank(divide(volume, ts_mean(volume, 20)))",
        "category": cat,
        "subcategory": "trend",
        "description": "成交量异常比率排名",
    }

    # --- Momentum ---
    factors["alpha_006"] = {
        "expression": "rank(subtract(close, ts_min(close, 5)))",
        "category": cat,
        "subcategory": "momentum",
        "description": "价格距5日低点的位置",
    }
    factors["alpha_007"] = {
        "expression": "rank(ts_delta(close, 20))",
        "category": cat,
        "subcategory": "momentum",
        "description": "20日中期动量排名",
    }
    factors["alpha_008"] = {
        "expression": "rank(ts_corr(high, volume, 10))",
        "category": cat,
        "subcategory": "momentum",
        "description": "10日最高价与成交量相关性",
    }
    factors["alpha_009"] = {
        "expression": "rank(subtract(close, ts_min(close, 20)))",
        "category": cat,
        "subcategory": "momentum",
        "description": "价格距20日低点的位置",
    }
    factors["alpha_010"] = {
        "expression": "rank(divide(subtract(close, ts_min(close, 10)), subtract(ts_max(close, 10), ts_min(close, 10))))",
        "category": cat,
        "subcategory": "momentum",
        "description": "10日区间位置 (0-1 振荡器)",
    }

    # --- Volatility ---
    factors["alpha_011"] = {
        "expression": "rank(multiply(-1, ts_std(close, 20)))",
        "category": cat,
        "subcategory": "volatility",
        "description": "低波动率因子 (负波动率排名)",
    }
    factors["alpha_012"] = {
        "expression": "rank(ts_corr(close, volume, 5))",
        "category": cat,
        "subcategory": "volatility",
        "description": "5日短期量价相关性",
    }
    factors["alpha_013"] = {
        "expression": "divide(ts_std(close, 20), ts_mean(close, 20))",
        "category": cat,
        "subcategory": "volatility",
        "description": "20日变异系数 (CV)",
    }
    factors["alpha_014"] = {
        "expression": "rank(ts_std(volume, 20))",
        "category": cat,
        "subcategory": "volatility",
        "description": "成交量波动率排名",
    }
    factors["alpha_015"] = {
        "expression": "rank(multiply(-1, ts_delta(ts_std(close, 10), 5)))",
        "category": cat,
        "subcategory": "volatility",
        "description": "波动率收缩因子",
    }

    # --- Volume ---
    factors["alpha_016"] = {
        "expression": "rank(ts_delta(volume, 5))",
        "category": cat,
        "subcategory": "volume",
        "description": "5日成交量变化排名",
    }
    factors["alpha_017"] = {
        "expression": "rank(divide(volume, ts_mean(volume, 10)))",
        "category": cat,
        "subcategory": "volume",
        "description": "成交量相对10日均值比率",
    }
    factors["alpha_018"] = {
        "expression": "rank(multiply(volume, ts_delta(close, 1)))",
        "category": cat,
        "subcategory": "volume",
        "description": "量价联合动量",
    }
    factors["alpha_019"] = {
        "expression": "rank(ts_corr(ts_delta(close, 1), ts_delta(volume, 1), 10))",
        "category": cat,
        "subcategory": "volume",
        "description": "10日价格变化与成交量变化相关性",
    }
    factors["alpha_020"] = {
        "expression": "rank(multiply(volume, subtract(close, open)))",
        "category": cat,
        "subcategory": "volume",
        "description": "日内资金流向强度",
    }

    # --- Mean reversion ---
    factors["alpha_021"] = {
        "expression": "rank(multiply(-1, ts_delta(close, 5)))",
        "category": cat,
        "subcategory": "mean_reversion",
        "description": "5日反转因子",
    }
    factors["alpha_022"] = {
        "expression": "rank(subtract(ts_mean(close, 5), ts_mean(close, 20)))",
        "category": cat,
        "subcategory": "mean_reversion",
        "description": "短期均线偏离长期均线 (均线交叉信号)",
    }
    factors["alpha_023"] = {
        "expression": "rank(multiply(-1, ts_delta(close, 10)))",
        "category": cat,
        "subcategory": "mean_reversion",
        "description": "10日反转因子",
    }
    factors["alpha_024"] = {
        "expression": "rank(divide(subtract(ts_max(close, 20), close), subtract(ts_max(close, 20), ts_min(close, 20))))",
        "category": cat,
        "subcategory": "mean_reversion",
        "description": "价格距20日高点距离 (反转潜力)",
    }

    # --- Trend strength ---
    factors["alpha_025"] = {
        "expression": "rank(ts_decay_linear(close, 10))",
        "category": cat,
        "subcategory": "trend_strength",
        "description": "10日线性加权均值 (趋势强度)",
    }
    factors["alpha_026"] = {
        "expression": "rank(divide(ts_decay_linear(close, 20), close))",
        "category": cat,
        "subcategory": "trend_strength",
        "description": "线性加权均值偏离当前价格",
    }
    factors["alpha_027"] = {
        "expression": "rank(ts_corr(close, ts_decay_linear(volume, 10), 10))",
        "category": cat,
        "subcategory": "trend_strength",
        "description": "价格与加权成交量的10日相关性",
    }
    factors["alpha_028"] = {
        "expression": "rank(subtract(ts_max(high, 10), ts_min(low, 10)))",
        "category": cat,
        "subcategory": "trend_strength",
        "description": "10日价格范围排名",
    }
    factors["alpha_029"] = {
        "expression": "rank(divide(subtract(close, open), subtract(high, low)))",
        "category": cat,
        "subcategory": "trend_strength",
        "description": "日内价格效率 (实体/振幅比率)",
    }

    # --- Extended technicals ---
    factors["alpha_030"] = {
        "expression": "rank(ts_delta(ts_mean(close, 5), 3))",
        "category": cat,
        "subcategory": "trend",
        "description": "5日均线的3日变化率",
    }
    factors["alpha_031"] = {
        "expression": "rank(ts_corr(open, close, 10))",
        "category": cat,
        "subcategory": "momentum",
        "description": "10日开盘价与收盘价相关性",
    }
    factors["alpha_032"] = {
        "expression": "rank(divide(subtract(high, low), ts_mean(subtract(high, low), 20)))",
        "category": cat,
        "subcategory": "volatility",
        "description": "日内振幅相对20日均值的比率",
    }
    factors["alpha_033"] = {
        "expression": "rank(ts_sum(multiply(volume, sign(subtract(close, close.shift(1)))), 20))",
        "category": cat,
        "subcategory": "volume",
        "description": "20日方向性成交量累计",
    }
    factors["alpha_034"] = {
        "expression": "rank(divide(close, ts_mean(close, 60)))",
        "category": cat,
        "subcategory": "trend",
        "description": "价格相对60日均线位置",
    }
    factors["alpha_035"] = {
        "expression": "rank(multiply(-1, divide(subtract(close, close.shift(5)), close.shift(5))))",
        "category": cat,
        "subcategory": "mean_reversion",
        "description": "5日收益率反转因子",
    }

    return factors


def _build_fundamental_factors() -> dict[str, dict]:
    """Build fundamental factor zoo (~35 factors)."""
    factors = {}
    cat = "fundamental"

    # --- Value ---
    factors["pe_ratio"] = {
        "expression": "divide(close, eps)",
        "category": cat,
        "subcategory": "value",
        "description": "市盈率 P/E",
    }
    factors["pb_ratio"] = {
        "expression": "divide(close, bps)",
        "category": cat,
        "subcategory": "value",
        "description": "市净率 P/B",
    }
    factors["ev_ebitda"] = {
        "expression": "divide(ev, ebitda)",
        "category": cat,
        "subcategory": "value",
        "description": "EV/EBITDA 企业价值倍数",
    }
    factors["fcf_yield"] = {
        "expression": "divide(fcf, market_cap)",
        "category": cat,
        "subcategory": "value",
        "description": "自由现金流收益率",
    }
    factors["earnings_yield"] = {
        "expression": "divide(eps, close)",
        "category": cat,
        "subcategory": "value",
        "description": "收益率 Earnings Yield",
    }
    factors["sales_to_ev"] = {
        "expression": "divide(revenue, ev)",
        "category": cat,
        "subcategory": "value",
        "description": "营收/企业价值比率",
    }
    factors["book_to_market"] = {
        "expression": "divide(bps, close)",
        "category": cat,
        "subcategory": "value",
        "description": "账面市值比 (B/M)",
    }

    # --- Quality ---
    factors["roic"] = {
        "expression": "divide(operating_income_tax_adjusted, invested_capital)",
        "category": cat,
        "subcategory": "quality",
        "description": "投入资本回报率 ROIC",
    }
    factors["gross_margin"] = {
        "expression": "divide(gross_profit, revenue)",
        "category": cat,
        "subcategory": "quality",
        "description": "毛利率",
    }
    factors["operating_margin"] = {
        "expression": "divide(operating_income, revenue)",
        "category": cat,
        "subcategory": "quality",
        "description": "营业利润率",
    }
    factors["fcf_margin"] = {
        "expression": "divide(fcf, revenue)",
        "category": cat,
        "subcategory": "quality",
        "description": "自由现金流利润率",
    }
    factors["net_margin"] = {
        "expression": "divide(net_income, revenue)",
        "category": cat,
        "subcategory": "quality",
        "description": "净利润率",
    }
    factors["accrual_ratio"] = {
        "expression": "divide(income_accruals, total_assets)",
        "category": cat,
        "subcategory": "quality",
        "description": "应计比率 (低值=高质量盈余)",
    }
    factors["asset_turnover"] = {
        "expression": "divide(revenue, total_assets)",
        "category": cat,
        "subcategory": "quality",
        "description": "资产周转率",
    }
    factors["roe"] = {
        "expression": "divide(net_income, book_equity)",
        "category": cat,
        "subcategory": "quality",
        "description": "净资产收益率 ROE",
    }
    factors["cash_conversion"] = {
        "expression": "divide(ocf, net_income)",
        "category": cat,
        "subcategory": "quality",
        "description": "现金转化率 (经营现金流/净利润)",
    }

    # --- Growth ---
    factors["revenue_growth_qoq"] = {
        "expression": "divide(ts_delta(revenue, 1), revenue.shift(1))",
        "category": cat,
        "subcategory": "growth",
        "description": "营收季度环比增长率",
    }
    factors["eps_growth_qoq"] = {
        "expression": "divide(ts_delta(eps, 1), eps.shift(1))",
        "category": cat,
        "subcategory": "growth",
        "description": "EPS季度环比增长率",
    }
    factors["margin_expansion"] = {
        "expression": "ts_delta(divide(operating_income, revenue), 1)",
        "category": cat,
        "subcategory": "growth",
        "description": "营业利润率环比变化",
    }
    factors["fcf_growth"] = {
        "expression": "divide(ts_delta(fcf, 1), fcf.shift(1))",
        "category": cat,
        "subcategory": "growth",
        "description": "自由现金流环比增长率",
    }
    factors["gross_margin_trend"] = {
        "expression": "ts_delta(divide(gross_profit, revenue), 4)",
        "category": cat,
        "subcategory": "growth",
        "description": "毛利率同比变化 (4个季度)",
    }

    # --- Leverage / Safety ---
    factors["debt_to_equity"] = {
        "expression": "divide(total_debt, book_equity)",
        "category": cat,
        "subcategory": "safety",
        "description": "债务权益比 D/E",
    }
    factors["interest_coverage"] = {
        "expression": "divide(ebitda, interest_expense)",
        "category": cat,
        "subcategory": "safety",
        "description": "利息保障倍数",
    }
    factors["current_ratio"] = {
        "expression": "divide(current_assets, current_liabilities)",
        "category": cat,
        "subcategory": "safety",
        "description": "流动比率",
    }
    factors["altman_z_signal"] = {
        "expression": "add(add(divide(working_capital, total_assets), divide(retained_earnings, total_assets)), divide(ebitda, total_assets))",
        "category": cat,
        "subcategory": "safety",
        "description": "Altman Z-score简化信号 (3项)",
    }

    # --- Efficiency ---
    factors["inventory_turnover"] = {
        "expression": "divide(cogs, inventory)",
        "category": cat,
        "subcategory": "efficiency",
        "description": "存货周转率",
    }
    factors["receivables_turnover"] = {
        "expression": "divide(revenue, accounts_receivable)",
        "category": cat,
        "subcategory": "efficiency",
        "description": "应收账款周转率",
    }
    factors["capex_to_revenue"] = {
        "expression": "divide(capex, revenue)",
        "category": cat,
        "subcategory": "efficiency",
        "description": "资本支出占营收比率",
    }
    factors["rd_to_revenue"] = {
        "expression": "divide(rd_expense, revenue)",
        "category": cat,
        "subcategory": "efficiency",
        "description": "研发支出占营收比率",
    }
    factors["sga_to_revenue"] = {
        "expression": "divide(sga_expense, revenue)",
        "category": cat,
        "subcategory": "efficiency",
        "description": "销售管理费用占营收比率",
    }

    # --- Capital allocation ---
    factors["dividend_yield"] = {
        "expression": "divide(dividend_per_share, close)",
        "category": cat,
        "subcategory": "capital_allocation",
        "description": "股息率",
    }
    factors["buyback_yield"] = {
        "expression": "divide(share_repurchase, market_cap)",
        "category": cat,
        "subcategory": "capital_allocation",
        "description": "回购收益率",
    }
    factors["sbc_dilution"] = {
        "expression": "divide(sbc_expense, revenue)",
        "category": cat,
        "subcategory": "capital_allocation",
        "description": "股权激励费用占营收比率 (稀释指标)",
    }

    return factors


def _build_macro_factors() -> dict[str, dict]:
    """Build macro factor zoo (~30 factors)."""
    factors = {}
    cat = "macro"

    # --- Interest rate sensitivity ---
    factors["rate_sensitivity_60"] = {
        "expression": "ts_corr(close, treasury_10y, 60)",
        "category": cat,
        "subcategory": "rate_sensitivity",
        "description": "60日股价与10年期国债收益率相关性",
    }
    factors["rate_sensitivity_20"] = {
        "expression": "ts_corr(close, treasury_10y, 20)",
        "category": cat,
        "subcategory": "rate_sensitivity",
        "description": "20日短期利率敏感度",
    }
    factors["rate_delta_impact"] = {
        "expression": "ts_corr(ts_delta(close, 5), ts_delta(treasury_10y, 5), 20)",
        "category": cat,
        "subcategory": "rate_sensitivity",
        "description": "利率变化对股价变化的影响",
    }
    factors["real_rate_impact"] = {
        "expression": "ts_corr(close, real_rate, 60)",
        "category": cat,
        "subcategory": "rate_sensitivity",
        "description": "60日实际利率敏感度",
    }

    # --- Inflation ---
    factors["inflation_beta"] = {
        "expression": "ts_corr(close, cpi_yoy, 12)",
        "category": cat,
        "subcategory": "inflation",
        "description": "通胀Beta (12月相关性)",
    }
    factors["inflation_surprise_impact"] = {
        "expression": "ts_corr(close, cpi_surprise, 6)",
        "category": cat,
        "subcategory": "inflation",
        "description": "通胀意外对股价的影响",
    }
    factors["breakeven_correlation"] = {
        "expression": "ts_corr(close, breakeven_inflation, 20)",
        "category": cat,
        "subcategory": "inflation",
        "description": "盈亏平衡通胀率相关性",
    }

    # --- Dollar / FX ---
    factors["dollar_beta"] = {
        "expression": "ts_corr(close, dxy, 20)",
        "category": cat,
        "subcategory": "fx",
        "description": "美元指数Beta (20日)",
    }
    factors["dollar_beta_60"] = {
        "expression": "ts_corr(close, dxy, 60)",
        "category": cat,
        "subcategory": "fx",
        "description": "美元指数Beta (60日)",
    }
    factors["em_fx_sensitivity"] = {
        "expression": "ts_corr(close, em_fx_index, 20)",
        "category": cat,
        "subcategory": "fx",
        "description": "新兴市场外汇敏感度",
    }

    # --- Credit ---
    factors["credit_spread_impact"] = {
        "expression": "ts_corr(close, credit_spread_baa, 20)",
        "category": cat,
        "subcategory": "credit",
        "description": "信用利差对股价的影响",
    }
    factors["credit_spread_change"] = {
        "expression": "ts_delta(credit_spread_baa, 20)",
        "category": cat,
        "subcategory": "credit",
        "description": "20日信用利差变化",
    }
    factors["term_spread_impact"] = {
        "expression": "ts_corr(close, term_spread, 20)",
        "category": cat,
        "subcategory": "credit",
        "description": "期限利差对股价的影响",
    }

    # --- Yield curve ---
    factors["yield_curve_factor"] = {
        "expression": "ts_delta(subtract(treasury_10y, treasury_2y), 20)",
        "category": cat,
        "subcategory": "yield_curve",
        "description": "20日期限利差变化 (2Y-10Y)",
    }
    factors["yield_curve_level"] = {
        "expression": "subtract(treasury_10y, treasury_2y)",
        "category": cat,
        "subcategory": "yield_curve",
        "description": "当前期限利差水平",
    }
    factors["yield_curve_steepness_trend"] = {
        "expression": "ts_delta(subtract(treasury_10y, treasury_2y), 60)",
        "category": cat,
        "subcategory": "yield_curve",
        "description": "60日期限利差趋势",
    }

    # --- Economic cycle ---
    factors["ism_impact"] = {
        "expression": "ts_corr(close, ism_pmi, 12)",
        "category": cat,
        "subcategory": "cycle",
        "description": "ISM PMI对股价的相关性",
    }
    factors["jobs_report_impact"] = {
        "expression": "ts_corr(close, nfp_change, 6)",
        "category": cat,
        "subcategory": "cycle",
        "description": "非农就业数据对股价的影响",
    }
    factors["lei_impact"] = {
        "expression": "ts_corr(close, lei, 12)",
        "category": cat,
        "subcategory": "cycle",
        "description": "领先经济指标相关性",
    }

    # --- Volatility regime ---
    factors["vix_impact"] = {
        "expression": "ts_corr(close, vix, 20)",
        "category": cat,
        "subcategory": "volatility_regime",
        "description": "VIX与股价相关性 (风险情绪)",
    }
    factors["vix_level_signal"] = {
        "expression": "multiply(-1, divide(vix, ts_mean(vix, 60)))",
        "category": cat,
        "subcategory": "volatility_regime",
        "description": "VIX相对60日均值比率 (取反)",
    }

    # --- Commodity ---
    factors["oil_beta"] = {
        "expression": "ts_corr(close, oil_price, 20)",
        "category": cat,
        "subcategory": "commodity",
        "description": "油价敏感度",
    }
    factors["copper_beta"] = {
        "expression": "ts_corr(close, copper_price, 20)",
        "category": cat,
        "subcategory": "commodity",
        "description": "铜价敏感度 (经济景气指标)",
    }
    factors["commodity_index_impact"] = {
        "expression": "ts_corr(close, commodity_index, 20)",
        "category": cat,
        "subcategory": "commodity",
        "description": "大宗商品指数敏感度",
    }

    # --- Housing / Real economy ---
    factors["housing_sensitivity"] = {
        "expression": "ts_corr(close, housing_index, 12)",
        "category": cat,
        "subcategory": "real_economy",
        "description": "房价指数敏感度 (12月)",
    }
    factors["consumer_confidence_impact"] = {
        "expression": "ts_corr(close, consumer_confidence, 12)",
        "category": cat,
        "subcategory": "real_economy",
        "description": "消费者信心指数对股价的影响",
    }

    return factors


def _build_alternative_factors() -> dict[str, dict]:
    """Build alternative data factor zoo (~25 factors)."""
    factors = {}
    cat = "alternative"

    # --- Sentiment ---
    factors["sentiment_momentum_5"] = {
        "expression": "ts_delta(sentiment_score, 5)",
        "category": cat,
        "subcategory": "sentiment",
        "description": "5日情绪动量",
    }
    factors["sentiment_momentum_20"] = {
        "expression": "ts_delta(sentiment_score, 20)",
        "category": cat,
        "subcategory": "sentiment",
        "description": "20日情绪动量",
    }
    factors["sentiment_vs_price"] = {
        "expression": "ts_corr(sentiment_score, close, 10)",
        "category": cat,
        "subcategory": "sentiment",
        "description": "情绪与价格10日相关性",
    }
    factors["sentiment_divergence"] = {
        "expression": "subtract(rank(ts_delta(sentiment_score, 10)), rank(ts_delta(close, 10)))",
        "category": cat,
        "subcategory": "sentiment",
        "description": "情绪-价格背离度",
    }
    factors["social_volume_ratio"] = {
        "expression": "divide(social_mentions, ts_mean(social_mentions, 20))",
        "category": cat,
        "subcategory": "sentiment",
        "description": "社交提及量相对20日均值比率",
    }

    # --- News ---
    factors["news_volume_ratio"] = {
        "expression": "divide(news_count, ts_mean(news_count, 20))",
        "category": cat,
        "subcategory": "news",
        "description": "新闻量相对20日均值比率 (关注激增)",
    }
    factors["news_sentiment_score"] = {
        "expression": "rank(ts_delta(news_sentiment, 5))",
        "category": cat,
        "subcategory": "news",
        "description": "5日新闻情绪变化排名",
    }
    factors["news_coverage_spike"] = {
        "expression": "divide(news_count, ts_mean(news_count, 60))",
        "category": cat,
        "subcategory": "news",
        "description": "新闻覆盖激增指数 (相对60日均值)",
    }

    # --- Insider ---
    factors["insider_buy_ratio"] = {
        "expression": "divide(insider_buys, add(insider_buys, insider_sells))",
        "category": cat,
        "subcategory": "insider",
        "description": "内部人买入比率",
    }
    factors["insider_net_activity"] = {
        "expression": "subtract(insider_buys, insider_sells)",
        "category": cat,
        "subcategory": "insider",
        "description": "内部人净买卖量",
    }
    factors["insider_momentum"] = {
        "expression": "ts_delta(divide(insider_buys, add(insider_buys, insider_sells)), 10)",
        "category": cat,
        "subcategory": "insider",
        "description": "10日内部人买入比率变化",
    }

    # --- Short interest ---
    factors["short_interest_change"] = {
        "expression": "ts_delta(short_interest_pct, 5)",
        "category": cat,
        "subcategory": "short_interest",
        "description": "5日空头仓位变化",
    }
    factors["short_squeeze_potential"] = {
        "expression": "multiply(short_interest_pct, divide(volume, ts_mean(volume, 20)))",
        "category": cat,
        "subcategory": "short_interest",
        "description": "轧空潜力 (空头比 * 成交量异常)",
    }
    factors["short_interest_vs_price"] = {
        "expression": "ts_corr(short_interest_pct, close, 20)",
        "category": cat,
        "subcategory": "short_interest",
        "description": "空头仓位与价格20日相关性",
    }

    # --- Earnings ---
    factors["earnings_surprise"] = {
        "expression": "divide(subtract(actual_eps, expected_eps), expected_eps)",
        "category": cat,
        "subcategory": "earnings",
        "description": "盈余惊喜幅度",
    }
    factors["post_earnings_drift"] = {
        "expression": "ts_delta(close, 5)",
        "category": cat,
        "subcategory": "earnings",
        "description": "盈余后漂移 (PEAD proxy)",
    }
    factors["earnings_quality_trend"] = {
        "expression": "ts_delta(earnings_quality_score, 4)",
        "category": cat,
        "subcategory": "earnings",
        "description": "盈余质量趋势 (4个季度)",
    }

    # --- Analyst ---
    factors["analyst_revision"] = {
        "expression": "ts_delta(mean_target_price, 10)",
        "category": cat,
        "subcategory": "analyst",
        "description": "10日分析师目标价修正",
    }
    factors["analyst_consensus_change"] = {
        "expression": "ts_delta(analyst_rating, 20)",
        "category": cat,
        "subcategory": "analyst",
        "description": "20日分析师评级变化",
    }
    factors["target_upside"] = {
        "expression": "divide(subtract(mean_target_price, close), close)",
        "category": cat,
        "subcategory": "analyst",
        "description": "目标价上行空间",
    }
    factors["revision_breadth"] = {
        "expression": "divide(upward_revisions, add(upward_revisions, downward_revisions))",
        "category": cat,
        "subcategory": "analyst",
        "description": "修正广度 (上调/总修正)",
    }

    # --- Digital footprint ---
    factors["web_traffic_momentum"] = {
        "expression": "ts_delta(web_visits, 4)",
        "category": cat,
        "subcategory": "digital",
        "description": "网站访问量变化动量 (4周)",
    }
    factors["app_rank_momentum"] = {
        "expression": "multiply(-1, ts_delta(app_rank, 4))",
        "category": cat,
        "subcategory": "digital",
        "description": "App排名提升动量 (排名下降=正向)",
    }
    factors["hiring_signal"] = {
        "expression": "divide(job_postings, ts_mean(job_postings, 12))",
        "category": cat,
        "subcategory": "digital",
        "description": "招聘信号 (职位发布相对12月均值)",
    }
    factors["patent_momentum"] = {
        "expression": "ts_delta(patent_count, 4)",
        "category": cat,
        "subcategory": "digital",
        "description": "专利申请动量 (季度)",
    }
    factors["glassdoor_rating_trend"] = {
        "expression": "ts_delta(glassdoor_rating, 4)",
        "category": cat,
        "subcategory": "digital",
        "description": "Glassdoor评分趋势 (季度变化)",
    }

    return factors


# ============================================================================
# Factor Zoo Registry
# ============================================================================


def _build_all_zoos() -> dict[str, dict[str, dict]]:
    """Build all factor zoos."""
    return {
        "technical": _build_technical_factors(),
        "fundamental": _build_fundamental_factors(),
        "macro": _build_macro_factors(),
        "alternative": _build_alternative_factors(),
    }


def _build_flat_factor_index(zoos: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """Create a flat name -> factor dict across all zoos."""
    index = {}
    for zoo_name, zoo_factors in zoos.items():
        for factor_name, factor_def in zoo_factors.items():
            index[factor_name] = {
                **factor_def,
                "zoo": zoo_name,
            }
    return index


# ============================================================================
# FactorEngine
# ============================================================================


class FactorEngine:
    """Parse and evaluate factor expressions against a DataFrame.

    Parameters
    ----------
    data : pd.DataFrame
        DataFrame with columns that factor expressions reference
        (e.g., close, volume, eps, revenue, treasury_10y, sentiment_score).
    """

    def __init__(self, data: pd.DataFrame):
        self._raw_data = data.copy()
        self._zoos = _build_all_zoos()
        self._factor_index = _build_flat_factor_index(self._zoos)
        self._cache: dict[str, pd.Series] = {}

    def _get_data_dict(self) -> dict[str, pd.Series]:
        """Convert DataFrame columns to a dict of Series for expression eval."""
        return {col: self._raw_data[col] for col in self._raw_data.columns}

    def compute_factor(self, expression: str) -> pd.Series:
        """Parse and evaluate a factor expression using AST-safe evaluation.

        Parameters
        ----------
        expression : str
            Factor expression, e.g. ``"rank(ts_delta(close, 10))"``

        Returns
        -------
        pd.Series
            Computed factor values.  NaN where inputs are missing.

        Raises
        ------
        _UnsafeExpressionError
            If the expression contains disallowed AST nodes.
        """
        if expression in self._cache:
            return self._cache[expression].copy()

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            warnings.warn(
                f"Syntax error in expression '{expression}': {e}", stacklevel=2
            )
            return pd.Series(np.nan, index=self._raw_data.index)

        _validate_ast_node(tree)

        data = self._get_data_dict()
        try:
            result = _eval_ast_node(tree, data)
        except _UnsafeExpressionError:
            raise
        except Exception as e:
            warnings.warn(f"Error evaluating '{expression}': {e}", stacklevel=2)
            return pd.Series(np.nan, index=self._raw_data.index)

        if not isinstance(result, pd.Series):
            # scalar broadcast
            result = pd.Series(result, index=self._raw_data.index)

        self._cache[expression] = result.copy()
        return result

    def compute_named_factor(self, factor_name: str) -> pd.Series:
        """Compute a named factor from the zoo."""
        if factor_name not in self._factor_index:
            raise KeyError(
                f"Unknown factor '{factor_name}'. "
                f"Available: {sorted(self._factor_index.keys())}"
            )
        expression = self._factor_index[factor_name]["expression"]
        return self.compute_factor(expression)

    def compute_zoo(self, zoo_name: str) -> pd.DataFrame:
        """Compute all factors in a zoo.

        Parameters
        ----------
        zoo_name : str
            One of 'technical', 'fundamental', 'macro', 'alternative'.

        Returns
        -------
        pd.DataFrame
            DataFrame where each column is a computed factor.
        """
        if zoo_name not in self._zoos:
            raise KeyError(
                f"Unknown zoo '{zoo_name}'. " f"Available: {sorted(self._zoos.keys())}"
            )

        results = {}
        for factor_name, factor_def in self._zoos[zoo_name].items():
            expression = factor_def["expression"]
            try:
                series = self.compute_factor(expression)
                results[factor_name] = series
            except Exception as e:
                warnings.warn(f"Factor '{factor_name}' failed: {e}", stacklevel=2)
                results[factor_name] = pd.Series(np.nan, index=self._raw_data.index)

        return pd.DataFrame(results, index=self._raw_data.index)

    def compute_all(self) -> dict[str, pd.DataFrame]:
        """Compute all factors across all zoos.

        Returns
        -------
        dict[str, pd.DataFrame]
            Mapping of zoo name to its computed factors DataFrame.
        """
        output = {}
        for zoo_name in self._zoos:
            output[zoo_name] = self.compute_zoo(zoo_name)
        return output

    def get_factor_info(self, factor_name: str) -> dict:
        """Get metadata for a specific factor."""
        if factor_name not in self._factor_index:
            raise KeyError(
                f"Unknown factor '{factor_name}'. "
                f"Available: {sorted(self._factor_index.keys())}"
            )
        return self._factor_index[factor_name].copy()

    def list_factors(self, zoo_name: str | None = None) -> list[dict]:
        """List available factors, optionally filtered by zoo.

        Returns
        -------
        list[dict]
            Each dict has keys: name, expression, category, subcategory, description, zoo.
        """
        if zoo_name is not None and zoo_name not in self._zoos:
            raise KeyError(
                f"Unknown zoo '{zoo_name}'. Available: {sorted(self._zoos.keys())}"
            )

        results = []
        for name, info in self._factor_index.items():
            if zoo_name is not None and info["zoo"] != zoo_name:
                continue
            results.append({"name": name, **info})
        return results

    @property
    def zoo_names(self) -> list[str]:
        return sorted(self._zoos.keys())

    @property
    def factor_count(self) -> int:
        return len(self._factor_index)


# ============================================================================
# Helper: load data from various sources
# ============================================================================


def _load_dataframe(path: str) -> pd.DataFrame:
    """Load a DataFrame from JSON or CSV path."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):
        with open(path) as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        elif isinstance(raw, dict):
            # May be nested; try to find a tabular key
            for key in ("data", "records", "rows", "prices", "history"):
                if key in raw and isinstance(raw[key], list):
                    return pd.DataFrame(raw[key])
            # Try treating the dict as column -> values
            return pd.DataFrame(raw)
        return pd.DataFrame(raw)
    elif ext in (".csv",):
        return pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Use .json or .csv")


def _series_to_json_safe(series: pd.Series) -> list:
    """Convert a Series to a JSON-serializable list."""
    return [
        None
        if pd.isna(v)
        else round(float(v), 6)
        if isinstance(v, (float, np.floating))
        else v
        for v in series
    ]


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Alpha factor zoo: compute factor expressions via AST-safe evaluation",
    )
    parser.add_argument(
        "data_path",
        help="Path to data file (JSON or CSV) with OHLCV + fundamental + macro + alt columns",
    )
    parser.add_argument(
        "--zoo",
        choices=["technical", "fundamental", "macro", "alternative"],
        help="Compute all factors in a specific zoo",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="compute_all",
        help="Compute all factors across all zoos",
    )
    parser.add_argument(
        "--factor",
        help="Compute a single named factor (e.g., alpha_001)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_factors",
        help="List available factors and exit",
    )
    parser.add_argument(
        "--list-zoo",
        choices=["technical", "fundamental", "macro", "alternative"],
        help="List factors in a specific zoo",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    # Load data
    try:
        data = _load_dataframe(args.data_path)
    except (FileNotFoundError, ValueError) as e:
        result = {"error": str(e)}
        _output(result, args.output)
        sys.exit(1)

    engine = FactorEngine(data)

    # List mode
    if args.list_factors or args.list_zoo:
        factors = engine.list_factors(zoo_name=args.list_zoo)
        result = {
            "total_factors": len(factors),
            "factors": factors,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        _output(result, args.output)
        sys.exit(0)

    # Compute mode
    if args.factor:
        # Single factor
        try:
            info = engine.get_factor_info(args.factor)
        except KeyError as e:
            result = {"error": str(e)}
            _output(result, args.output)
            sys.exit(1)
        values = engine.compute_named_factor(args.factor)
        result = {
            "factor": args.factor,
            "expression": info["expression"],
            "category": info["category"],
            "subcategory": info["subcategory"],
            "description": info["description"],
            "zoo": info["zoo"],
            "values": _series_to_json_safe(values),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
    elif args.zoo:
        # Single zoo
        df = engine.compute_zoo(args.zoo)
        result = {
            "zoo": args.zoo,
            "factor_count": len(df.columns),
            "factors": {col: _series_to_json_safe(df[col]) for col in df.columns},
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
    elif args.compute_all:
        # All zoos
        all_results = engine.compute_all()
        result = {
            "zoos": {},
            "total_factors": engine.factor_count,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        for zoo_name, df in all_results.items():
            result["zoos"][zoo_name] = {
                "factor_count": len(df.columns),
                "factors": {col: _series_to_json_safe(df[col]) for col in df.columns},
            }
    else:
        parser.error("Specify --zoo, --all, --factor, or --list")

    _output(result, args.output)
    sys.exit(0)


def _output(result: dict, output_path: str | None) -> None:
    """Write result as JSON to file or stdout."""
    text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
