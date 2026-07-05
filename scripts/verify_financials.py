#!/usr/bin/env python3
"""Financial verification toolkit using exact decimal arithmetic.

Usage:
    uv run python scripts/verify_financials.py verify-market-cap --price 510 --shares 9.11e9 --reported 4.65e12 --currency HKD
    uv run python scripts/verify_financials.py verify-valuation --price 510 --eps 23.5 --bvps 120 --fcf-per-share 18
    uv run python scripts/verify_financials.py cross-validate --field revenue --values '{"Yahoo": 7518, "SEC": 7500, "StockAnalysis": 7520}' --unit 亿
    uv run python scripts/verify_financials.py benford --data '[1234, 2345, 3456, 4567, 5678]'

All calculations use decimal.Decimal with Context(prec=28, rounding=ROUND_HALF_EVEN)
to avoid floating-point drift in financial math. Output is JSON to stdout.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from decimal import Decimal, Context, ROUND_HALF_EVEN, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# Exact Decimal Engine
# ---------------------------------------------------------------------------

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _exact(value: Any) -> Decimal:
    """Convert any numeric to exact Decimal, avoiding float traps."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def _to_json_number(d: Decimal) -> float | str:
    """Convert Decimal to JSON-safe number (float if finite, str otherwise)."""
    if d.is_finite():
        return float(d)
    return str(d)


# ---------------------------------------------------------------------------
# 1. Market Cap Verification
# ---------------------------------------------------------------------------


def verify_market_cap(price: str, shares: str, reported: str, currency: str = "") -> dict:
    """Verify market cap = price x shares, compare with reported value.

    Args:
        price: Stock price as string (supports scientific notation).
        shares: Total shares outstanding as string (supports scientific notation).
        reported: Reported market cap as string.
        currency: Currency label (e.g., HKD, USD, CNY).

    Returns:
        dict with calculated_market_cap, reported, deviation_pct, pass/fail.
    """
    p = _exact(price)
    s = _exact(shares)
    r = _exact(reported)

    calculated = _CTX.multiply(p, s)

    if r == 0:
        deviation_pct = Decimal("0")
    else:
        diff = _CTX.subtract(calculated, r)
        abs_diff = _CTX.copy_abs(diff)
        deviation_pct = _CTX.multiply(_CTX.divide(abs_diff, r), Decimal("100"))

    threshold = Decimal("5")
    passed = deviation_pct <= threshold

    return {
        "subcommand": "verify-market-cap",
        "inputs": {
            "price": _to_json_number(p),
            "shares": _to_json_number(s),
            "reported_market_cap": _to_json_number(r),
            "currency": currency,
        },
        "calculated_market_cap": _to_json_number(calculated),
        "reported_market_cap": _to_json_number(r),
        "deviation_pct": round(float(deviation_pct), 4),
        "threshold_pct": 5.0,
        "pass": passed,
        "verdict": "✅ PASS" if passed else "❌ FAIL",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 2. Valuation Metrics Verification
# ---------------------------------------------------------------------------


def verify_valuation(
    price: str,
    eps: str | None = None,
    bvps: str | None = None,
    fcf_per_share: str | None = None,
    dividend: str | None = None,
) -> dict:
    """Calculate precise valuation ratios from raw inputs.

    Args:
        price: Current stock price.
        eps: Earnings per share (TTM).
        bvps: Book value per share.
        fcf_per_share: Free cash flow per share.
        dividend: Annual dividend per share.

    Returns:
        dict with PE, PB, FCF Yield, Dividend Yield (all exact).
    """
    p = _exact(price)
    ratios: dict[str, Any] = {}

    if eps is not None:
        e = _exact(eps)
        if e != 0:
            pe = _CTX.divide(p, e)
            ratios["pe_ratio"] = _to_json_number(pe)
            ratios["earnings_yield_pct"] = round(float(_CTX.multiply(_CTX.divide(e, p), Decimal("100"))), 4)
        else:
            ratios["pe_ratio"] = None
            ratios["pe_note"] = "EPS is zero; PE undefined"

    if bvps is not None:
        b = _exact(bvps)
        if b != 0:
            pb = _CTX.divide(p, b)
            ratios["pb_ratio"] = _to_json_number(pb)
        else:
            ratios["pb_ratio"] = None
            ratios["pb_note"] = "BVPS is zero; PB undefined"

    if fcf_per_share is not None:
        f = _exact(fcf_per_share)
        if p != 0:
            fcf_yield = _CTX.multiply(_CTX.divide(f, p), Decimal("100"))
            ratios["fcf_yield_pct"] = round(float(fcf_yield), 4)
        else:
            ratios["fcf_yield_pct"] = None

    if dividend is not None:
        d = _exact(dividend)
        if p != 0:
            div_yield = _CTX.multiply(_CTX.divide(d, p), Decimal("100"))
            ratios["dividend_yield_pct"] = round(float(div_yield), 4)
        else:
            ratios["dividend_yield_pct"] = None

    return {
        "subcommand": "verify-valuation",
        "inputs": {
            "price": _to_json_number(p),
            "eps": eps,
            "bvps": bvps,
            "fcf_per_share": fcf_per_share,
            "dividend": dividend,
        },
        "ratios": ratios,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 3. Cross-Validation (multi-source comparison)
# ---------------------------------------------------------------------------


def cross_validate(field: str, values: dict[str, float], unit: str = "") -> dict:
    """Compare multiple source values for the same metric.

    Calculates deviation from median, flags >1% outliers.

    Args:
        field: Name of the financial field (e.g., "revenue").
        values: Dict of {source_name: value}.
        unit: Unit label (e.g., "亿", "M").

    Returns:
        dict with median, deviations per source, outliers flagged.
    """
    if not values:
        return {"error": "No values provided", "pass": False}

    # Convert all to Decimal
    decimal_values: dict[str, Decimal] = {}
    for source, val in values.items():
        decimal_values[source] = _exact(val)

    # Calculate median
    sorted_vals = sorted(decimal_values.values())
    n = len(sorted_vals)
    if n % 2 == 1:
        median = sorted_vals[n // 2]
    else:
        mid = n // 2
        median = _CTX.divide(_CTX.add(sorted_vals[mid - 1], sorted_vals[mid]), Decimal("2"))

    # Calculate deviations from median
    threshold = Decimal("1")  # 1% threshold
    source_analysis: list[dict] = []
    outliers: list[str] = []

    for source, val in decimal_values.items():
        if median == 0:
            dev_pct = Decimal("0")
        else:
            diff = _CTX.subtract(val, median)
            dev_pct = _CTX.multiply(_CTX.divide(diff, median), Decimal("100"))

        is_outlier = _CTX.copy_abs(dev_pct) > threshold
        entry = {
            "source": source,
            "value": _to_json_number(val),
            "deviation_from_median_pct": round(float(dev_pct), 4),
            "is_outlier": is_outlier,
        }
        source_analysis.append(entry)
        if is_outlier:
            outliers.append(source)

    passed = len(outliers) == 0

    return {
        "subcommand": "cross-validate",
        "field": field,
        "unit": unit,
        "median": _to_json_number(median),
        "source_count": len(values),
        "sources": source_analysis,
        "outliers": outliers,
        "outlier_count": len(outliers),
        "threshold_pct": 1.0,
        "pass": passed,
        "verdict": "✅ PASS — all sources within 1% of median" if passed else f"❌ FAIL — {len(outliers)} outlier(s): {', '.join(outliers)}",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 4. Benford's Law First-Digit Test
# ---------------------------------------------------------------------------

# Expected Benford frequencies for digits 1-9
_BENFORD_EXPECTED = {
    1: Decimal("0.30103"),
    2: Decimal("0.17609"),
    3: Decimal("0.12494"),
    4: Decimal("0.09691"),
    5: Decimal("0.07918"),
    6: Decimal("0.06695"),
    7: Decimal("0.05799"),
    8: Decimal("0.05115"),
    9: Decimal("0.04576"),
}


def benford_test(data: list[float | int]) -> dict:
    """Test first-digit distribution against Benford's Law.

    Uses chi-square goodness-of-fit test.

    Args:
        data: List of numeric values to test.

    Returns:
        dict with observed/expected frequencies, chi-square statistic, p-value, verdict.
    """
    if not data:
        return {"error": "No data provided", "pass": False}

    # Extract first digits
    first_digits: list[int] = []
    for val in data:
        s = str(abs(val)).lstrip("0").lstrip(".")
        # Remove leading zeros after decimal
        s = s.lstrip("0")
        if s and s[0].isdigit() and s[0] != "0":
            first_digits.append(int(s[0]))

    if len(first_digits) < 10:
        return {
            "subcommand": "benford",
            "error": "Insufficient data points (need >= 10 non-zero values)",
            "data_count": len(data),
            "valid_digits": len(first_digits),
            "pass": False,
        }

    n = len(first_digits)

    # Count observed frequencies
    observed: dict[int, int] = {d: 0 for d in range(1, 10)}
    for d in first_digits:
        observed[d] += 1

    # Chi-square test
    chi_square = Decimal("0")
    digit_analysis: list[dict] = []

    for digit in range(1, 10):
        obs = Decimal(str(observed[digit]))
        exp = _CTX.multiply(_BENFORD_EXPECTED[digit], Decimal(str(n)))

        obs_freq = float(obs) / n
        exp_freq = float(_BENFORD_EXPECTED[digit])

        if exp > 0:
            diff = _CTX.subtract(obs, exp)
            diff_sq = _CTX.multiply(diff, diff)
            contribution = _CTX.divide(diff_sq, exp)
            chi_square = _CTX.add(chi_square, contribution)
        else:
            contribution = Decimal("0")

        digit_analysis.append({
            "digit": digit,
            "observed_count": int(obs),
            "expected_count": round(float(exp), 2),
            "observed_freq": round(obs_freq, 4),
            "expected_freq": round(exp_freq, 4),
            "chi_sq_contribution": round(float(contribution), 4),
        })

    # Degrees of freedom = 8 (9 digits - 1)
    # Critical value at alpha=0.05 for df=8 is 15.507
    chi_sq_float = float(chi_square)
    critical_value = 15.507
    passed = chi_sq_float <= critical_value

    # Approximate p-value using incomplete gamma function (stdlib math)
    # For chi-square with df=8: p = 1 - regularized_incomplete_gamma(4, chi_sq/2)
    try:
        # Use scipy-free approximation
        p_value = _chi2_survival(chi_sq_float, 8)
    except Exception:
        p_value = None

    return {
        "subcommand": "benford",
        "data_count": len(data),
        "valid_first_digits": n,
        "chi_square_statistic": round(chi_sq_float, 4),
        "degrees_of_freedom": 8,
        "critical_value_alpha_05": critical_value,
        "p_value": round(p_value, 4) if p_value is not None else None,
        "pass": passed,
        "verdict": (
            "✅ PASS — first-digit distribution consistent with Benford's Law"
            if passed
            else "❌ FAIL — distribution deviates from Benford's Law (possible data manipulation)"
        ),
        "digit_analysis": digit_analysis,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _chi2_survival(x: float, df: int) -> float:
    """Compute 1 - CDF of chi-square distribution (survival function).

    Uses the regularized incomplete gamma function via series expansion.
    P(chi2 > x | df) = 1 - gamma_inc(df/2, x/2) / gamma(df/2)
    """
    if x <= 0:
        return 1.0

    a = df / 2.0
    z = x / 2.0

    # Regularized lower incomplete gamma via series
    # P(a, z) = sum_{k=0}^{inf} (-1)^k * z^(a+k) / (k! * (a+k))  /  Gamma(a)
    # Using the more stable series: e^{-z} * z^a * sum_{k=0} z^k / (a*(a+1)*...*(a+k))
    if z > a + 50:
        # For large z, use continued fraction (upper incomplete gamma)
        return _upper_gamma_cf(a, z)

    # Series expansion for lower regularized gamma
    term = 1.0 / a
    total = term
    for k in range(1, 300):
        term *= z / (a + k)
        total += term
        if abs(term) < 1e-15 * abs(total):
            break

    log_p = a * math.log(z) - z - math.lgamma(a) + math.log(total)
    lower_gamma_reg = math.exp(log_p) if log_p < 700 else 1.0
    return max(0.0, min(1.0, 1.0 - lower_gamma_reg))


def _upper_gamma_cf(a: float, z: float) -> float:
    """Upper regularized incomplete gamma via continued fraction (Lentz algorithm)."""
    # Q(a, z) = e^{-z} * z^a / Gamma(a) * CF
    f = 1e-30
    c = 1e-30
    d = 1.0 / (z + 1.0 - a)
    f = d
    for i in range(1, 200):
        an = i * (a - i)
        bn = z + 2.0 * i + 1.0 - a
        d = 1.0 / (bn + an * d)
        c = bn + an / c
        delta = c * d
        f *= delta
        if abs(delta - 1.0) < 1e-15:
            break

    log_q = a * math.log(z) - z - math.lgamma(a) + math.log(f)
    return math.exp(log_q) if log_q < 700 else 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Financial verification toolkit using exact decimal arithmetic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- verify-market-cap ---
    p_mc = subparsers.add_parser(
        "verify-market-cap",
        help="Verify market cap = price × shares vs reported value",
    )
    p_mc.add_argument("--price", required=True, help="Stock price")
    p_mc.add_argument("--shares", required=True, help="Total shares outstanding (supports 9.11e9)")
    p_mc.add_argument("--reported", required=True, help="Reported market cap")
    p_mc.add_argument("--currency", default="", help="Currency label (e.g., HKD, USD)")

    # --- verify-valuation ---
    p_val = subparsers.add_parser(
        "verify-valuation",
        help="Calculate precise valuation ratios",
    )
    p_val.add_argument("--price", required=True, help="Current stock price")
    p_val.add_argument("--eps", default=None, help="Earnings per share (TTM)")
    p_val.add_argument("--bvps", default=None, help="Book value per share")
    p_val.add_argument("--fcf-per-share", default=None, help="Free cash flow per share")
    p_val.add_argument("--dividend", default=None, help="Annual dividend per share")

    # --- cross-validate ---
    p_cv = subparsers.add_parser(
        "cross-validate",
        help="Cross-validate a metric across multiple data sources",
    )
    p_cv.add_argument("--field", required=True, help="Field name (e.g., revenue)")
    p_cv.add_argument("--values", required=True, help='JSON dict of source:value pairs')
    p_cv.add_argument("--unit", default="", help="Unit label (e.g., 亿)")

    # --- benford ---
    p_bf = subparsers.add_parser(
        "benford",
        help="Benford's Law first-digit distribution test",
    )
    p_bf.add_argument("--data", required=True, help="JSON array of numeric values")

    args = parser.parse_args()

    try:
        if args.command == "verify-market-cap":
            result = verify_market_cap(
                price=args.price,
                shares=args.shares,
                reported=args.reported,
                currency=args.currency,
            )
        elif args.command == "verify-valuation":
            result = verify_valuation(
                price=args.price,
                eps=args.eps,
                bvps=args.bvps,
                fcf_per_share=args.fcf_per_share,
                dividend=args.dividend,
            )
        elif args.command == "cross-validate":
            values = json.loads(args.values)
            if not isinstance(values, dict):
                print(json.dumps({"error": "--values must be a JSON object"}), file=sys.stderr)
                sys.exit(1)
            result = cross_validate(
                field=args.field,
                values=values,
                unit=args.unit,
            )
        elif args.command == "benford":
            data = json.loads(args.data)
            if not isinstance(data, list):
                print(json.dumps({"error": "--data must be a JSON array"}), file=sys.stderr)
                sys.exit(1)
            result = benford_test(data)
        else:
            parser.print_help()
            sys.exit(1)

        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result.get("pass", True) else 1)

    except (InvalidOperation, ValueError) as e:
        print(json.dumps({"error": f"Invalid numeric input: {e}"}), file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
