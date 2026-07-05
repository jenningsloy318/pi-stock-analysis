/**
 * Pure argument parser for the `/stock-analysis` command.
 *
 * Dispatch order (spec §4.3):
 *   1. Structured-JSON escape hatch (OQ-7): if the arg string parses as JSON
 *      with a `mode` key, return it directly.
 *   2. `--mode <name>` is authoritative. Positional args after it depend on
 *      mode: analyze → whitespace tickers; compare → comma tickers; walk → theme.
 *   3. Trigger-phrase fallback (no --mode): infer mode from the request text.
 *   4. Default: pipeline.
 *
 * Pure + synchronous (no I/O) so it is fully unit-testable.
 */

import type { Mode, Universe } from "./types.ts";

export interface ParsedArgs {
	mode: Mode;
	tickers?: string[];
	theme?: string;
	topIndustry?: number;
	totalCompany?: number;
	topPrice?: number;
	minHeadroom?: number;
	days?: number;
	universe?: Universe;
	query?: string;
	model?: string;
	maxAgents?: number;
}

const MODES: Mode[] = ["pipeline", "screen", "analyze", "compare", "walk"];

/** kebab-case --flag → camelCase key. */
function flagToKey(flag: string): string {
	return flag.replace(/-([a-z])/g, (_m, c: string) => c.toUpperCase());
}

/** Parse `--key value` and `--key=value` flags from a token list. Returns the
 *  map of found flags (camelCase keys) and the remaining positional tokens. */
export function parseFlags(tokens: string[]): { flags: Record<string, string>; positional: string[] } {
	const flags: Record<string, string> = {};
	const positional: string[] = [];
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok === "--") { positional.push(...tokens.slice(i + 1)); break; }
		const eq = tok.indexOf("=");
		if (tok.startsWith("--") && eq > 2) {
			flags[flagToKey(tok.slice(2, eq))] = tok.slice(eq + 1);
			continue;
		}
		if (tok.startsWith("--")) {
			const key = flagToKey(tok.slice(2));
			const next = tokens[i + 1];
			if (next !== undefined && !next.startsWith("--")) {
				flags[key] = next;
				i++;
			} else {
				flags[key] = "true";
			}
			continue;
		}
		positional.push(tok);
	}
	return { flags, positional };
}

/** Trigger-phrase → mode inference (no --mode present). */
export function inferMode(text: string): { mode: Mode; tickers?: string[]; theme?: string } {
	const t = text.toLowerCase();
	if (/\b(walk|trace|map out)\b.*\b(chain|roadmap|ecosystem|bottleneck)\b/i.test(text) || /瓶颈分析/.test(text)) {
		const theme = text.replace(/["']/g, "").trim();
		return { mode: "walk", theme: theme || undefined };
	}
	if (/\bvs\.?\b|\bversus\b|\bcompare\b|\bcomparison\b/i.test(text)) {
		const tickers = extractTickers(text);
		return { mode: "compare", tickers: tickers.length >= 2 ? tickers : undefined };
	}
	if (/\b(deep[ -]?dive|analyze|analyse|investment thesis|valuation of|due diligence|dcf)\b/i.test(text)) {
		const tickers = extractTickers(text);
		return { mode: "analyze", tickers: tickers.length >= 1 ? tickers : undefined };
	}
	if (/\b(screen|screener|sector scan|best industries|industry screening)\b/i.test(text) || /筛选行业/.test(text)) {
		return { mode: "screen" };
	}
	// pipeline triggers + default
	return { mode: "pipeline" };
}

/** Extract likely ticker tokens (1-6 upper-case letters, optional .suffix, or
 *  6-digit A-share code with optional .SH/.SZ suffix). */
export function extractTickers(text: string): string[] {
	const matches = text.match(/\b(?:[A-Z]{1,6}|\d{6})(?:\.[A-Z]{1,2})?\b/g) ?? [];
	// keep real tickers: ≥2 letters (or 6-digit) with optional suffix; drop
	// single-letter noise.
	return matches.filter((m) => /^[A-Z]{2,6}(?:\.[A-Z]{1,2})?$/.test(m) || /^\d{6}(?:\.[A-Z]{1,2})?$/.test(m));
}

function parseNumber(v: string | undefined): number | undefined {
	if (v === undefined) return undefined;
	const n = Number(v);
	return Number.isFinite(n) ? n : undefined;
}

/** Parse the full `/stock-analysis` arg string into structured params. */
export function parseStockAnalysisArgs(argString: string): ParsedArgs {
	const trimmed = argString.trim();
	if (!trimmed) return { mode: "pipeline" };

	// 1. JSON escape hatch
	if (trimmed.startsWith("{")) {
		try {
			const obj = JSON.parse(trimmed) as Record<string, unknown>;
			if (typeof obj.mode === "string" && MODES.includes(obj.mode as Mode)) {
				return { ...(obj as unknown as ParsedArgs) };
			}
		} catch { /* not JSON — fall through */ }
	}

	// Tokenize (respect quoted strings for themes).
	const tokens = tokenize(trimmed);
	const { flags, positional } = parseFlags(tokens);

	const rawMode = flags.mode ?? flags.m;
	let mode: Mode;
	let tickers: string[] | undefined;
	let theme: string | undefined;

	if (typeof rawMode === "string" && MODES.includes(rawMode.toLowerCase() as Mode)) {
		mode = rawMode.toLowerCase() as Mode;
		// positional meaning depends on mode
		if (mode === "analyze") {
			tickers = positional.length > 0 ? positional : undefined;
		} else if (mode === "compare") {
			// comma-list possibly split across positional tokens
			const joined = positional.join(" ");
			tickers = joined.split(/[,\s]+/).filter(Boolean);
			if (tickers.length === 0) tickers = undefined;
		} else if (mode === "walk") {
			theme = positional.join(" ").trim() || undefined;
		}
	} else {
		// 3. trigger-phrase fallback
		const inferred = inferMode(trimmed);
		mode = inferred.mode;
		tickers = inferred.tickers;
		theme = inferred.theme;
		// mode-independent flags from parseFlags still apply
		if (flags.topIndustry) tickers = tickers; // no-op, keeps linter calm
	}

	const result: ParsedArgs = { mode, query: trimmed };
	if (tickers?.length) result.tickers = tickers;
	if (theme) result.theme = theme;
	if (flags.topIndustry) result.topIndustry = parseNumber(flags.topIndustry);
	if (flags.totalCompany) result.totalCompany = parseNumber(flags.totalCompany);
	if (flags.topPrice) result.topPrice = parseNumber(flags.topPrice);
	if (flags.minHeadroom) result.minHeadroom = parseNumber(flags.minHeadroom);
	if (flags.days) result.days = parseNumber(flags.days);
	if (flags.universe && ["US", "CN", "ALL"].includes(flags.universe.toUpperCase())) result.universe = flags.universe.toUpperCase() as Universe;
	if (flags.model) result.model = flags.model;
	if (flags.maxAgents) result.maxAgents = parseNumber(flags.maxAgents);
	return result;
}

/** Tokenize respecting single/double quotes (for multi-word themes). */
export function tokenize(s: string): string[] {
	const tokens: string[] = [];
	let cur = "";
	let quote: string | null = null;
	for (let i = 0; i < s.length; i++) {
		const ch = s[i];
		if (quote) {
			if (ch === quote) { quote = null; continue; }
			cur += ch;
		} else if (ch === '"' || ch === "'") {
			quote = ch;
		} else if (/\s/.test(ch)) {
			if (cur) { tokens.push(cur); cur = ""; }
		} else {
			cur += ch;
		}
	}
	if (cur) tokens.push(cur);
	return tokens;
}
