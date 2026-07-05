#!/usr/bin/env python3
"""Audit tool calls in report generation for grounding verification.

Usage:
    audit_tool_calls.py ./reports/AAPL/audit_log.json
    audit_tool_calls.py ./reports/AAPL/audit_log.json --min-calls 3 --output ./reports/AAPL/audit_result.json

Reads a JSON audit log (produced by the report writer agent) and verifies:
1. Each section has minimum N tool calls
2. Tool diversity (not all same tool)
3. Source attribution present
4. Fact verification claims are grounded

Returns JSON with pass/fail per section and overall score.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field


@dataclass
class ToolCall:
    section: str          # which report section
    tool_name: str        # which tool/script was called
    query: str            # what was queried
    result_summary: str   # brief summary of result
    timestamp: str


@dataclass
class AuditResult:
    section: str
    tool_calls_count: int
    min_required: int
    unique_tools: int
    has_source_attribution: bool
    has_fact_verification: bool
    passes: bool
    issues: list[str] = field(default_factory=list)


# Sections considered high-impact (require min-calls threshold)
HIGH_IMPACT_SECTIONS = {
    "investment_thesis",
    "conviction_score",
    "conviction_score_decomposition",
    "risk_assessment",
    "risk",
    "valuation",
}

# Standard sections (require at least 1 tool call)
STANDARD_SECTIONS = {
    "financial_health",
    "moat",
    "moat_quality",
    "management",
    "macro",
    "macro_environment",
    "technical",
    "technical_analysis",
    "alt_data",
    "alternative_data",
    "capital_structure",
    "earnings_quality",
    "competitive_landscape",
    "industry_analysis",
    "supply_chain",
    "esg",
    "behavioral",
    "summary",
    "action",
    "kill_switch",
}


def _is_high_impact(section_name: str) -> bool:
    """Check if a section is high-impact by normalized name."""
    normalized = section_name.lower().replace(" ", "_").replace("-", "_")
    return normalized in HIGH_IMPACT_SECTIONS or any(
        kw in normalized for kw in ("investment_thesis", "conviction", "risk", "valuation")
    )


def _has_source_attribution(tool_calls: list[dict]) -> bool:
    """Check if at least one tool call includes source attribution indicators."""
    attribution_keywords = {"source", "retrieved", "fact", "interpretation", "speculation"}
    for tc in tool_calls:
        summary = tc.get("result_summary", "") or tc.get("finding", "")
        query = tc.get("query", "")
        combined = (summary + " " + query).lower()
        if any(kw in combined for kw in attribution_keywords):
            return True
    return False


def _has_fact_verification(tool_calls: list[dict]) -> bool:
    """Check if tool calls include cross-referencing or verification activity."""
    verification_keywords = {"cross-check", "crosscheck", "verify", "validate", "compare", "confirm"}
    for tc in tool_calls:
        query = tc.get("query", "").lower()
        tool = tc.get("tool", "").lower()
        combined = query + " " + tool
        if any(kw in combined for kw in verification_keywords):
            return True
    return False


def _extract_tool_calls(section_data: dict, section_name: str) -> list[dict]:
    """Extract tool call records from a section's audit data."""
    raw_calls = section_data.get("tool_calls", [])
    if not raw_calls:
        # Try alternate field name
        raw_calls = section_data.get("calls", [])
    return raw_calls


def audit_section(
    section_name: str,
    section_data: dict,
    min_calls: int,
) -> AuditResult:
    """Audit a single report section for grounding compliance."""
    tool_calls = _extract_tool_calls(section_data, section_name)
    issues: list[str] = []

    tool_calls_count = len(tool_calls)
    unique_tools = len({tc.get("tool", tc.get("tool_name", "unknown")) for tc in tool_calls}) if tool_calls else 0
    has_source_attr = _has_source_attribution(tool_calls)
    has_fact_verify = _has_fact_verification(tool_calls)

    # Determine required minimum
    is_high = _is_high_impact(section_name)
    required = min_calls if is_high else 1

    # Check minimum tool calls
    if tool_calls_count < required:
        issues.append(
            f"Insufficient tool calls: {tool_calls_count} < {required} required"
            f" (high-impact section)" if is_high else " (standard section)"
        )

    # Check tool diversity (at least 2 unique tools for high-impact)
    if is_high and unique_tools < 2 and tool_calls_count >= 2:
        issues.append(
            f"Low tool diversity: {unique_tools} unique tool(s) for high-impact section"
        )

    # Check max tool calls (avoid over-fetching)
    max_calls = 5 if is_high else 3
    if tool_calls_count > max_calls:
        issues.append(
            f"Excessive tool calls: {tool_calls_count} > {max_calls} max — possible over-fetching"
        )

    # Check source attribution for high-impact
    if is_high and not has_source_attr:
        issues.append("No source attribution detected in tool call results")

    # Check fact verification for high-impact
    if is_high and not has_fact_verify:
        issues.append("No fact verification / cross-referencing detected in tool calls")

    passes = len(issues) == 0

    return AuditResult(
        section=section_name,
        tool_calls_count=tool_calls_count,
        min_required=required,
        unique_tools=unique_tools,
        has_source_attribution=has_source_attr,
        has_fact_verification=has_fact_verify,
        passes=passes,
        issues=issues,
    )


def audit_report(audit_log_path: str, min_calls: int = 3) -> dict:
    """Main audit function. Returns dict with audit results."""
    try:
        with open(audit_log_path, "r", encoding="utf-8") as f:
            audit_log = json.load(f)
    except FileNotFoundError:
        return {
            "overall_pass": False,
            "error": f"Audit log not found: {audit_log_path}",
            "results": [],
        }
    except json.JSONDecodeError as e:
        return {
            "overall_pass": False,
            "error": f"Invalid JSON in audit log: {e}",
            "results": [],
        }

    sections = audit_log.get("sections", {})
    ticker = audit_log.get("ticker", "UNKNOWN")
    report_type = audit_log.get("report_type", "unknown")

    if not sections:
        return {
            "overall_pass": False,
            "ticker": ticker,
            "report_type": report_type,
            "error": "No sections found in audit log",
            "sections_audited": 0,
            "sections_passing": 0,
            "min_tool_calls": min_calls,
            "results": [],
            "summary": "FAIL: No sections to audit",
        }

    results: list[dict] = []
    for section_name, section_data in sections.items():
        result = audit_section(section_name, section_data, min_calls)
        results.append(asdict(result))

    sections_audited = len(results)
    sections_passing = sum(1 for r in results if r["passes"])
    grounding_score = compute_grounding_score(results)
    overall_pass = sections_passing == sections_audited and grounding_score >= 0.6

    summary_parts: list[str] = []
    if overall_pass:
        summary_parts.append(
            f"PASS: {sections_passing}/{sections_audited} sections grounded "
            f"(score: {grounding_score:.2f})"
        )
    else:
        failing = [r["section"] for r in results if not r["passes"]]
        summary_parts.append(
            f"FAIL: {sections_passing}/{sections_audited} sections grounded "
            f"(score: {grounding_score:.2f}). "
            f"Failing sections: {', '.join(failing)}"
        )

    return {
        "overall_pass": overall_pass,
        "ticker": ticker,
        "report_type": report_type,
        "sections_audited": sections_audited,
        "sections_passing": sections_passing,
        "min_tool_calls": min_calls,
        "grounding_score": round(grounding_score, 3),
        "results": results,
        "summary": " ".join(summary_parts),
    }


def compute_grounding_score(results: list[dict]) -> float:
    """Compute 0-1 grounding score across all sections.

    Weighted scoring:
    - 40%: Section pass rate (fraction of sections that pass)
    - 30%: Tool call sufficiency (average ratio of actual/min_required)
    - 20%: Tool diversity (average unique tools / tool calls count)
    - 10%: Source attribution presence
    """
    if not results:
        return 0.0

    n = len(results)

    # Pass rate component (40%)
    pass_rate = sum(1 for r in results if r["passes"]) / n

    # Tool call sufficiency (30%) — ratio of actual to required, capped at 1.0
    sufficiency_ratios = []
    for r in results:
        required = max(r["min_required"], 1)
        ratio = min(r["tool_calls_count"] / required, 1.0)
        sufficiency_ratios.append(ratio)
    sufficiency = sum(sufficiency_ratios) / n

    # Tool diversity (20%) — unique tools / total calls, only for sections with calls
    diversity_scores = []
    for r in results:
        if r["tool_calls_count"] > 0:
            diversity = min(r["unique_tools"] / r["tool_calls_count"], 1.0)
        else:
            diversity = 0.0
        diversity_scores.append(diversity)
    diversity = sum(diversity_scores) / n

    # Source attribution (10%)
    attr_rate = sum(1 for r in results if r.get("has_source_attribution")) / n

    score = (
        0.40 * pass_rate
        + 0.30 * sufficiency
        + 0.20 * diversity
        + 0.10 * attr_rate
    )

    return max(0.0, min(1.0, score))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit tool calls in report generation for grounding verification"
    )
    parser.add_argument(
        "audit_log",
        help="Path to audit_log.json produced by the report writer agent",
    )
    parser.add_argument(
        "--min-calls",
        type=int,
        default=3,
        help="Minimum tool calls required per high-impact section (default: 3)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for audit result JSON (default: stdout)",
    )

    args = parser.parse_args()
    result = audit_report(args.audit_log, min_calls=args.min_calls)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        # Also print summary to stderr for visibility
        print(result.get("summary", "Audit complete"), file=sys.stderr)
    else:
        print(output_json)

    # Exit with non-zero if audit fails (useful for CI/pipeline integration)
    if not result.get("overall_pass", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
