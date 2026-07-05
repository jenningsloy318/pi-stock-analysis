/**
 * Deterministic pipeline helpers — pure functions over the shared state and
 * verbatim python scripts. Mirrors the role of pi-super-dev's helpers.ts but
 * adapted for the stock-analysis domain.
 *
 * `runHelper(call)` dispatches by `call.name`. Two families:
 *   - Pure TS helpers (ticker normalization, mode-aware defaults, ranking).
 *   - Script-backed helpers (compute_scores, validate_report, …) that shell out
 *     to the verbatim python via `scripts.ts` (DEP-003: keep python).
 */

import type { ControlObj, HelperCall, HelperResult, Mode, Universe } from "./types.ts";

const ok = (digest: string, value: ControlObj): HelperResult => ({ value, digest });
const fail = (errors: string[]): HelperResult => ({
	value: { pass: errors.length === 0, errors },
	digest: errors.length === 0 ? "PASS" : `FAIL: ${errors.length} error(s)`,
});

// ─── A-share ticker normalization (AC-25 prerequisite, Stage 0) ──────────────

/** True for China A-share tickers (.SH / .SZ suffix or bare 6-digit code). */
export function isAshTicker(ticker: string): boolean {
	const t = String(ticker ?? "").trim().toUpperCase();
	if (t.endsWith(".SH") || t.endsWith(".SZ")) return true;
	if (/^\d{6}$/.test(t)) return true; // bare 6-digit → A-share
	return false;
}

/**
 * Normalize a bare or named A-share ticker to a suffixed form.
 *   - "600519"      → "600519.SH"  (6/68 → .SH; 00/30 → .SZ)
 *   - "000001"      → "000001.SZ"
 *   - "600519.SH"   → pass-through
 *   - "AAPL"        → pass-through (non-numeric)
 *   - "贵州茅台"      → would resolve via akshare; here we return the input
 *                       unchanged and flag it for the data-collector agent to
 *                       resolve (name lookup is a data-fetch, not pure TS).
 *
 * Pure + synchronous: no network. Name resolution is deferred to the
 * data-collector agent (which has `uv run python scripts/resolve_tickers.py`).
 */
export function normalizeAshTicker(input: string): { ticker: string; needsNameResolve: boolean } {
	const raw = String(input ?? "").trim();
	if (!raw) return { ticker: raw, needsNameResolve: false };
	// Already suffixed → pass through.
	if (/\.(SH|SZ|HK|SS)$/i.test(raw)) return { ticker: raw.toUpperCase(), needsNameResolve: false };
	// Bare 6-digit → assign exchange by leading digits.
	if (/^\d{6}$/.test(raw)) {
		const suffix = /^(60|68|90)/.test(raw) ? "SH" : /^(00|30|20)/.test(raw) ? "SZ" : "SH";
		return { ticker: `${raw}.${suffix}`, needsNameResolve: false };
	}
	// 8-9 digit or contains CJK → likely a Chinese name; defer to akshare.
	if (/[\u4e00-\u9fff]/.test(raw)) return { ticker: raw, needsNameResolve: true };
	// Otherwise (US ticker, etc.) → pass through unchanged.
	return { ticker: raw.toUpperCase(), needsNameResolve: false };
}

/** Normalize a list of tickers for analyze/compare modes. */
export function normalizeTickers(tickers: string[]): string[] {
	return (tickers ?? []).map((t) => normalizeAshTicker(t).ticker).filter(Boolean);
}

// ─── Mode-aware defaults (Stage 0) ──────────────────────────────────────────

export function defaultTopIndustry(mode: Mode): number {
	switch (mode) {
		case "pipeline": return 8;
		case "screen": return 40;
		case "walk": return 7;
		default: return 8;
	}
}

/** Validate the per-mode parameter contract BEFORE any stage runs (ISS-04). */
export function validateParams(p: {
	mode: Mode;
	tickers?: string[];
	theme?: string;
}): string[] {
	const errors: string[] = [];
	if (p.mode === "analyze") {
		if (!p.tickers || p.tickers.length < 1) errors.push("analyze mode requires at least one ticker");
	}
	if (p.mode === "compare") {
		const n = p.tickers?.length ?? 0;
		if (n < 2) errors.push("compare mode requires 2-5 tickers (got " + n + ")");
		if (n > 5) errors.push("compare mode allows at most 5 tickers (got " + n + ")");
	}
	if (p.mode === "walk") {
		if (!p.theme || !p.theme.trim()) errors.push("walk mode requires a theme");
	}
	return errors;
}

export function clampRange(n: unknown, min: number, max: number, fallback: number): number {
	const v = typeof n === "number" ? n : typeof n === "string" ? Number(n) : NaN;
	if (!Number.isFinite(v)) return fallback;
	return Math.min(max, Math.max(min, Math.trunc(v)));
}

// ─── Gates ──────────────────────────────────────────────────────────────────
// Non-vacuous-pass discipline (ISS-02): a validator that produces no output is
// a FAILURE, never a silent pass. Each gate reads the actual artifact produced
// (a tracking entry, a report file, or a script's structured result).

function requireSource(s: Record<string, unknown>, key: string): ControlObj | null {
	const v = s[key];
	if (!v || (typeof v === "object" && Object.keys(v as object).length === 0)) return null;
	return v as ControlObj;
}

function gateSharedData(s: Record<string, unknown>): HelperResult {
	const shared = requireSource(s, "stage-1");
	const errors: string[] = [];
	if (!shared) errors.push("Stage 1 shared data not produced (data-collector returned nothing)");
	else {
		const status = (shared.status as string) ?? (shared as { sharedData?: { status?: string } }).sharedData?.status;
		if (status === "failed") errors.push("shared data status is 'failed'");
		const files = (shared.files as string[]) ?? (shared as { sharedData?: { files?: string[] } }).sharedData?.files ?? [];
		if (files.length === 0) errors.push("no shared data files recorded");
	}
	return fail(errors);
}

function gateScreening(s: Record<string, unknown>): HelperResult {
	const screen = requireSource(s, "stage-4");
	const errors: string[] = [];
	if (!screen) errors.push("Stage 4 screening output not produced");
	else {
		const companies = (screen.companies as unknown[]) ?? [];
		const subIndustries = (screen.subIndustries as unknown[]) ?? [];
		if (companies.length < 1) errors.push("company watchlist is empty");
		if (subIndustries.length < 1 && screen.subIndustriesMissing !== true) errors.push("sub-industry leaderboard is empty");
		if (screen.priceFilterApplied !== true && screen.priceFilterDisabled !== true) errors.push("price filter was not applied");
		if (screen.headroomFilterApplied !== true && screen.headroomFilterDisabled !== true) errors.push("growth-headroom filter was not applied");
	}
	return fail(errors);
}

function gateScoring(s: Record<string, unknown>): HelperResult {
	const scoring = requireSource(s, "stage-16");
	const errors: string[] = [];
	if (!scoring) errors.push("Stage 16 scoring output not produced");
	else {
		const companies = (scoring.companies as Array<{ composite?: number; components?: Record<string, number> }>) ?? [];
		if (companies.length === 0) errors.push("no scored companies");
		for (const c of companies) {
			if (typeof c.composite !== "number" || c.composite < 1 || c.composite > 10) {
				errors.push(`composite score out of 1-10 range for ${JSON.stringify(c).slice(0, 60)}`);
				break;
			}
		}
	}
	return fail(errors);
}

function gateReports(s: Record<string, unknown>): HelperResult {
	const reports = (s["stage-17"] as { reports?: unknown[] } | undefined)?.reports;
	const errors: string[] = [];
	if (!Array.isArray(reports) || reports.length === 0) errors.push("no reports generated at Stage 17");
	return fail(errors);
}

function gateBestPicks(s: Record<string, unknown>): HelperResult {
	const bp = requireSource(s, "stage-18");
	const errors: string[] = [];
	if (!bp) errors.push("Stage 18 best-picks output not produced");
	else {
		const picks = (bp.bestPicks as unknown[]) ?? (bp.picks as unknown[]) ?? [];
		if (picks.length === 0) errors.push("best-picks list is empty");
	}
	return fail(errors);
}

// ─── Ranking / selection (Stage 16 input shaping) ───────────────────────────

/** Select the top-N companies by composite score (adversarial verify +
 *  judge panel operate on the top 5). Pure + deterministic. */
export function topNByScore(companies: Array<{ ticker: string; score?: number }>, n: number): string[] {
	return [...companies]
		.filter((c) => typeof c.score === "number")
		.sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
		.slice(0, n)
		.map((c) => c.ticker);
}

// ─── Dispatcher ─────────────────────────────────────────────────────────────

const SYNC: Record<string, (s: Record<string, unknown>) => HelperResult> = {
	"gate-shared-data": gateSharedData,
	"gate-screening": gateScreening,
	"gate-scoring": gateScoring,
	"gate-reports": gateReports,
	"gate-best-picks": gateBestPicks,
};

export async function runHelper(call: HelperCall): Promise<HelperResult> {
	const fn = SYNC[call.name];
	if (!fn) return ok(`unknown helper "${call.name}"`, { pass: false, errors: [`unknown helper: ${call.name}`] });
	return fn(call.sources);
}

export const HELPER_NAMES = Object.keys(SYNC);
