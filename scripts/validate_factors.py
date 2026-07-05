#!/usr/bin/env python3
"""AST-based safety validator for alpha factor expressions.

Usage:
    validate_factors.py "rank(ts_delta(close, 10))"
    validate_factors.py --batch expressions.txt
    validate_factors.py --batch expressions.txt --output validated.json

Validates that factor expressions are safe to evaluate by:
  - Parsing with Python's ast module (never eval)
  - Whitelisting only allowed AST node types
  - Whitelisting only the 19 base operator function names
  - Blocking dangerous names (import, exec, eval, open, compile, ...)
  - Blocking attribute access beyond .shift()
  - Checking for lookahead bias when data_alignment info is provided
"""

import argparse
import ast
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

# ============================================================================
# Operator registry (mirrors alpha_factor_zoo.py)
# ============================================================================

ALLOWED_OPERATORS = frozenset(
    {
        # Time-series
        "ts_delta",
        "ts_mean",
        "ts_std",
        "ts_sum",
        "ts_max",
        "ts_min",
        "ts_rank",
        "ts_corr",
        "ts_cov",
        "ts_decay_linear",
        # Cross-sectional
        "rank",
        "zscore",
        "scale",
        "sign",
        "power",
        # Arithmetic
        "add",
        "subtract",
        "multiply",
        "divide",
    }
)

# Data column names commonly used (informational only for lookahead checks)
COMMON_PRICE_COLUMNS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
    }
)
COMMON_FUNDAMENTAL_COLUMNS = frozenset(
    {
        "eps",
        "bps",
        "ev",
        "ebitda",
        "fcf",
        "market_cap",
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "total_assets",
        "total_debt",
        "book_equity",
        "operating_income_tax_adjusted",
        "invested_capital",
        "current_assets",
        "current_liabilities",
        "working_capital",
        "retained_earnings",
        "cogs",
        "inventory",
        "accounts_receivable",
        "capex",
        "rd_expense",
        "sga_expense",
        "dividend_per_share",
        "share_repurchase",
        "sbc_expense",
        "ocf",
        "interest_expense",
        "income_accruals",
    }
)

# ============================================================================
# Allowed / blocked definitions
# ============================================================================

_ALLOWED_AST_TYPES = frozenset(
    {
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.Expression,
        # Binary operators
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        # Unary operators
        ast.USub,
        ast.UAdd,
        ast.Not,
        # Comparison operators
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Eq,
        ast.NotEq,
        # Attribute access for .shift()
        ast.Attribute,
        # Expression context nodes (attached by parser to every Name/Attribute)
        ast.Load,
    }
)

# NOTE: "open" is NOT blocked because it's a standard OHLCV data column.
# Dangerous builtins used as function calls are caught by the ALLOWED_OPERATORS
# whitelist in _collect_info.
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
        "print",
        "__builtins__",
        "__name__",
        "__file__",
        "__doc__",
    }
)

_ALLOWED_ATTRIBUTES = frozenset({"shift"})


# ============================================================================
# Validation functions
# ============================================================================


def _collect_info(node: ast.AST) -> tuple[list[str], list[str], list[str]]:
    """Walk AST to collect operators, names, and errors."""
    operators_used: list[str] = []
    names_used: list[str] = []
    errors: list[str] = []

    for child in ast.walk(node):
        # Check for disallowed node types
        if not isinstance(child, tuple(_ALLOWED_AST_TYPES)):
            errors.append(f"Disallowed AST node: {type(child).__name__}")

        # Check function calls
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                fname = func.id
                if fname in ALLOWED_OPERATORS:
                    operators_used.append(fname)
                elif fname in _BLOCKED_NAMES:
                    errors.append(f"Blocked function name: '{fname}'")
                else:
                    # Could be a data column used as a function (typo)
                    errors.append(
                        f"Unknown function '{fname}'. "
                        f"Allowed operators: {sorted(ALLOWED_OPERATORS)}"
                    )

            # Check method calls (.shift())
            if isinstance(func, ast.Attribute):
                if func.attr not in _ALLOWED_ATTRIBUTES:
                    errors.append(
                        f"Attribute access '.{func.attr}' is not allowed. "
                        f"Allowed: {sorted(_ALLOWED_ATTRIBUTES)}"
                    )
                else:
                    operators_used.append(f".{func.attr}")

        # Check names
        if isinstance(child, ast.Name):
            names_used.append(child.id)
            if child.id in _BLOCKED_NAMES:
                errors.append(f"Blocked name: '{child.id}'")

        # Check all attribute accesses (not just those inside Call nodes)
        if isinstance(child, ast.Attribute):
            if child.attr not in _ALLOWED_ATTRIBUTES:
                errors.append(
                    f"Attribute access '.{child.attr}' is not allowed. "
                    f"Allowed: {sorted(_ALLOWED_ATTRIBUTES)}"
                )

    return operators_used, names_used, errors


def validate_expression(expression: str) -> dict[str, Any]:
    """Validate a factor expression is safe to evaluate.

    Parameters
    ----------
    expression : str
        Factor expression string.

    Returns
    -------
    dict
        Keys: valid (bool), errors (list), operators_used (list),
        names_used (list), expression (str).
    """
    result: dict[str, Any] = {
        "expression": expression,
        "valid": False,
        "errors": [],
        "operators_used": [],
        "names_used": [],
    }

    # Step 1: Syntax check
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        result["errors"].append(f"SyntaxError: {e}")
        return result

    # Step 2: Walk and validate
    operators_used, names_used, errors = _collect_info(tree)

    # Step 3: Check for empty expression
    if not operators_used and not names_used:
        errors.append(
            "Expression is empty or contains only a literal value (no operators or data references)."
        )

    # Step 4: Check that all data names are not operator names being misused
    # (This is informational only -- names like 'close' are data references)

    result["operators_used"] = sorted(set(operators_used))
    result["names_used"] = sorted(set(names_used))
    result["errors"] = errors
    result["valid"] = len(errors) == 0

    return result


def check_lookahead_bias(
    expression: str,
    data_alignment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Check if an expression could introduce lookahead bias.

    Lookahead bias occurs when future data is used to compute a present value.
    In factor expressions, this typically happens when:
      - Positive shift values are used (shift(-N) = look ahead N rows)
      - Future-looking functions are applied to price data without lag

    Parameters
    ----------
    expression : str
        Factor expression string.
    data_alignment : dict, optional
        Mapping of column name to its frequency or alignment
        (e.g., {"close": "daily", "eps": "quarterly"}).

    Returns
    -------
    dict
        Keys: has_lookahead_risk (bool), warnings (list), expression (str).
    """
    result: dict[str, Any] = {
        "expression": expression,
        "has_lookahead_risk": False,
        "warnings": [],
        "info": [],
    }

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        result["warnings"].append(f"Cannot parse expression: {e}")
        result["has_lookahead_risk"] = True
        return result

    # Walk AST looking for potential lookahead issues
    for node in ast.walk(tree):
        # Check .shift() calls with negative arguments (look ahead)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "shift" and len(node.args) == 1:
                shift_arg = node.args[0]
                if isinstance(shift_arg, ast.UnaryOp) and isinstance(
                    shift_arg.op, ast.USub
                ):
                    result["warnings"].append(
                        "Negative shift argument detected: shift(-N) uses future data. "
                        "This introduces lookahead bias."
                    )
                    result["has_lookahead_risk"] = True
                elif isinstance(shift_arg, ast.Constant):
                    val = shift_arg.value
                    if isinstance(val, (int, float)) and val < 0:
                        result["warnings"].append(
                            f"Negative shift argument ({val}): uses future data."
                        )
                        result["has_lookahead_risk"] = True

    # Check for cross-frequency alignment issues if data_alignment is provided
    if data_alignment:
        frequencies = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in data_alignment:
                frequencies.add(data_alignment[node.id])

        if len(frequencies) > 1:
            result["warnings"].append(
                f"Mixed data frequencies detected: {frequencies}. "
                f"Ensure proper alignment to avoid lookahead bias "
                f"(e.g., daily price vs quarterly fundamental data)."
            )
            result["has_lookahead_risk"] = True

    # Informational: check for forward-looking patterns in names
    forward_indicators = {"expected_eps", "forward_pe", "forward_eps", "next_earnings"}
    names_used = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
    for name in names_used:
        if name in forward_indicators:
            result["info"].append(
                f"Column '{name}' may contain forward-looking estimates. "
                f"Ensure data is point-in-time."
            )

    return result


def validate_batch(expressions: list[str]) -> dict[str, Any]:
    """Validate a batch of expressions.

    Returns
    -------
    dict
        Summary with per-expression results.
    """
    results = []
    for expr in expressions:
        expr = expr.strip()
        if not expr or expr.startswith("#"):
            continue
        results.append(validate_expression(expr))

    valid_count = sum(1 for r in results if r["valid"])
    return {
        "total": len(results),
        "valid": valid_count,
        "invalid": len(results) - valid_count,
        "results": results,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="AST-based safety validator for alpha factor expressions",
    )
    parser.add_argument(
        "expression",
        nargs="?",
        help="Factor expression to validate (e.g., 'rank(ts_delta(close, 10))')",
    )
    parser.add_argument(
        "--batch",
        help="Path to a file with one expression per line",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--check-lookahead",
        action="store_true",
        help="Also check for lookahead bias",
    )
    parser.add_argument(
        "--data-alignment",
        help="JSON file mapping column names to their frequency "
        "(for lookahead bias check)",
    )
    args = parser.parse_args()

    if not args.expression and not args.batch:
        parser.error("Provide an expression or use --batch <file>")

    # Load data alignment if provided
    data_alignment = None
    if args.data_alignment:
        try:
            with open(args.data_alignment) as f:
                data_alignment = json.load(f)
        except Exception as e:
            result = {"error": f"Failed to load data alignment: {e}"}
            _output(result, args.output)
            sys.exit(1)

    # Single expression mode
    if args.expression:
        validation = validate_expression(args.expression)
        output = validation

        if args.check_lookahead:
            lookahead = check_lookahead_bias(args.expression, data_alignment)
            output["lookahead_check"] = lookahead

        output["validated_at"] = datetime.now(timezone.utc).isoformat()
        _output(output, args.output)
        sys.exit(0 if validation["valid"] else 1)

    # Batch mode
    if args.batch:
        if not os.path.exists(args.batch):
            result = {"error": f"File not found: {args.batch}"}
            _output(result, args.output)
            sys.exit(1)

        with open(args.batch) as f:
            lines = f.readlines()

        expressions = [
            line.strip() for line in lines if line.strip() and not line.startswith("#")
        ]
        batch_result = validate_batch(expressions)

        if args.check_lookahead:
            lookahead_results = {}
            for expr in expressions:
                lookahead_results[expr] = check_lookahead_bias(expr, data_alignment)
            batch_result["lookahead_checks"] = lookahead_results

        _output(batch_result, args.output)
        sys.exit(0 if batch_result["invalid"] == 0 else 1)


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
