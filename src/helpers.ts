/**
 * Deterministic pipeline helpers — pure functions over the shared state and
 * verbatim python scripts. Mirrors the role of pi-super-dev's helpers.ts but
 * adapted for the stock-analysis domain.
 *
 * These are PURE domain helpers (ticker normalization, mode-aware defaults,
 * ranking) called directly by name from `extension.ts` (param validation /
 * normalization at Stage 0) and `stages/index.ts` (A-share predicate).
 *
 * Content gates (the validators that run between stages) live in `gates.ts`
 * and are dispatched by name via `runHelper`. Script-backed helpers
 * (`compute_scores`, `validate_report`, …) shell out to the verbatim python
 * through `scripts.ts` (DEP-003: keep python) — invoked from agent prompts,
 * not from here.
 */

import type { Mode } from "./types.ts";

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
