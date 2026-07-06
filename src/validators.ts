/**
 * Pure-TS report validators — the render-path replacement for the content gates
 * in scripts/validate_report.py. They operate on the EquityReportPayload the
 * agent emitted (stored in state by renderReportsTask), so there is no Python
 * round-trip and no markdown parsing: the format gates (001 ranking, 当前股价
 * column, disclaimer) are already guaranteed by the Nunjucks template, leaving
 * only the CONTENT gates to enforce here.
 *
 * Ports:
 *   - expectedRating / convictionConsistency  ← gate_conviction_consistency
 *   - killSwitchFalsifiable                   ← gate_kill_switch (payload form)
 *   - validateRenderedReport                  ← the full per-report gate
 */

import { validatePayload, EquityReportPayload } from "./render-schemas.ts";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

// From validate_report.py RATING_BRACKETS.
const RATING_BRACKETS: [number, string][] = [
	[9.0, "Strong Buy"],
	[7.5, "Buy"],
	[6.0, "Hold / Accumulate"],
	[4.0, "Hold / Reduce"],
	[2.0, "Sell"],
	[0.0, "Strong Sell"],
];

export function expectedRating(score: number): string {
	for (const [threshold, label] of RATING_BRACKETS) if (score >= threshold) return label;
	return "Strong Sell";
}

export interface ValidationOutcome {
	ok: boolean;
	errors: string[];
}

type Payload = Record<string, unknown> & {
	scores?: { composite?: unknown; rating?: unknown; components?: Record<string, unknown> };
	horizon?: string;
	kill_switch?: unknown;
	three_axis?: unknown;
};

/** Composite in 1-10, rating bracket coherence, and the component-override rule
 *  (any component ≤3 → composite must be <6 / capped at Hold). */
export function convictionConsistency(payload: Payload): ValidationOutcome {
	const errors: string[] = [];
	const scores = payload.scores ?? {};
	const composite = scores.composite;
	if (typeof composite !== "number" || composite < 1 || composite > 10) {
		errors.push(`composite score ${String(composite)} out of 1-10 range`);
	} else if (typeof scores.rating === "string" && scores.rating.trim()) {
		const expected = expectedRating(composite);
		const e = expected.toLowerCase();
		const r = scores.rating.toLowerCase();
		// Partial match (mirrors the Python gate's tolerance).
		if (!e.includes(r) && !r.includes(e)) {
			errors.push(`rating '${scores.rating}' inconsistent with composite ${composite} (expected '${expected}')`);
		}
	}
	const components = scores.components ?? {};
	const low = Object.entries(components)
		.filter(([, v]) => typeof v === "number" && v <= 3)
		.map(([k]) => k);
	if (low.length && typeof composite === "number" && composite >= 6) {
		errors.push(
			`composite ${composite} ≥6 but component(s) ≤3: ${low.join(", ")} (override rule: any component ≤3 → max Hold)`,
		);
	}
	return { ok: errors.length === 0, errors };
}

/** Kill-switch must be specific (a quantifiable trigger), not boilerplate. */
const VAGUE = ["monitor", "watch closely", "re-evaluate if necessary", "as needed", "stay tuned"];
export function killSwitchFalsifiable(text: unknown): ValidationOutcome {
	const errors: string[] = [];
	const t = typeof text === "string" ? text.trim() : "";
	if (t.length < 20) {
		errors.push("kill_switch too short / missing");
	} else if (!/\d/.test(t)) {
		errors.push("kill_switch lacks a quantifiable trigger (no number/percent/price/quarter)");
	} else if (VAGUE.some((v) => t.toLowerCase().includes(v)) && t.length < 40) {
		errors.push("kill_switch too vague (generic phrasing)");
	}
	return { ok: errors.length === 0, errors };
}

/** Full per-report render-path gate: schema + conviction + kill-switch + the
 *  short-term 三轴 requirement. Content checks run only if the schema passed
 *  (so the payload is well-shaped). */
export function validateRenderedReport(payload: unknown): ValidationOutcome {
	const errors: string[] = [];
	const schema = validatePayload(EquityReportPayload, payload);
	if (!schema.ok) {
		errors.push(...schema.errors.map((e) => `schema: ${e}`));
		return { ok: false, errors };
	}
	const p = payload as Payload;
	const cc = convictionConsistency(p);
	if (!cc.ok) errors.push(...cc.errors);
	const ks = killSwitchFalsifiable(p.kill_switch);
	if (!ks.ok) errors.push(...ks.errors);
	if (p.horizon === "short" && !p.three_axis) {
		errors.push("short-term report missing three_axis");
	}
	return { ok: errors.length === 0, errors };
}

// ─── dataFreshness: port of gate_data_freshness ─────────────────────────────
/** Scan a company/report dir's *.json files and flag any whose
 *  `retrieved_at`/`computed_at`/`generated_at` is older than `maxDays`. Tolerant:
 *  a few stale files pass; a majority-stale dir fails (a data-quality signal). */
export function dataFreshness(companyDir: string, opts: { maxDays?: number; now?: number } = {}): ValidationOutcome {
	const maxDays = opts.maxDays ?? 14;
	const now = opts.now ?? Date.now();
	let files: string[];
	try {
		files = readdirSync(companyDir).filter((f) => f.endsWith(".json"));
	} catch {
		return { ok: true, errors: [] }; // dir absent → nothing to check
	}
	let checked = 0;
	let stale = 0;
	const staleFiles: string[] = [];
	for (const f of files) {
		let d: Record<string, unknown>;
		try {
			d = JSON.parse(readFileSync(join(companyDir, f), "utf8"));
		} catch {
			continue;
		}
		const ts = (d.retrieved_at ?? d.computed_at ?? d.generated_at) as string | undefined;
		if (!ts) continue;
		const t = Date.parse(ts);
		if (Number.isNaN(t)) continue;
		checked++;
		const ageDays = (now - t) / 86_400_000;
		if (ageDays > maxDays) {
			stale++;
			if (staleFiles.length < 3) staleFiles.push(`${f}:${ageDays.toFixed(0)}d`);
		}
	}
	if (checked === 0 || stale === 0) return { ok: true, errors: [] };
	const ok = stale <= checked * 0.5;
	return {
		ok,
		errors: ok ? [] : [`${stale}/${checked} data files >${maxDays}d old: ${staleFiles.join(", ")}${stale > staleFiles.length ? " …" : ""}`],
	};
}

// ─── forensicChecks: port of gate_forensic_checks ───────────────────────────
/** Reads metrics.json's Beneish/Altman/Piotroski scores. Matching the Python
 *  gate, this PASSES iff all three are present (absence blocks); threshold
 *  breaches (Beneish > -1.78, Altman < 1.81) are warnings surfaced in the data,
 *  not blocking. metrics.json missing ⇒ skip (not a report-time failure). */
export function forensicChecks(companyDir: string): ValidationOutcome {
	let metrics: Record<string, unknown>;
	try {
		metrics = JSON.parse(readFileSync(join(companyDir, "metrics.json"), "utf8"));
	} catch {
		return { ok: true, errors: [] };
	}
	const m = (metrics.beneish_mscore as { mscore?: number } | undefined)?.mscore;
	const z = (metrics.altman_zscore as { zscore?: number } | undefined)?.zscore;
	const f = (metrics.piotroski_fscore as { fscore?: number } | undefined)?.fscore;
	const errors: string[] = [];
	if (m === undefined) errors.push("Beneish M-Score not computed");
	if (z === undefined) errors.push("Altman Z-Score not computed");
	if (f === undefined) errors.push("Piotroski F-Score not computed");
	return { ok: errors.length === 0, errors };
}

// ─── factCheck: port of gate_fact_check (hallucination / cross-reference) ────
/** Cross-references raw-data.json vs metrics.json (revenue, market cap, P/E,
 *  FCF sign, D/E direction). Tolerant: each check is neutral when the data is
 *  absent; only real discrepancies fail. Files missing ⇒ skip (non-blocking). */
function firstNum(entries: unknown): number | null {
	if (typeof entries === "number") return entries;
	if (Array.isArray(entries) && entries.length) {
		const e = entries[0] as Record<string, unknown> | number;
		return typeof e === "number" ? e : typeof e?.value === "number" ? e.value : null;
	}
	return null;
}
function relDiff(a: number, b: number): number {
	return Math.abs(a - b) / Math.max(Math.abs(a), 1);
}

export function factCheck(companyDir: string): ValidationOutcome {
	let raw: Record<string, any>;
	let metrics: Record<string, any>;
	try {
		raw = JSON.parse(readFileSync(join(companyDir, "raw-data.json"), "utf8"));
		metrics = JSON.parse(readFileSync(join(companyDir, "metrics.json"), "utf8"));
	} catch {
		return { ok: true, errors: [] }; // files missing → skip
	}
	const errors: string[] = [];
	const ratios = (metrics.ratios ?? {}) as Record<string, number>;
	const fin = (raw.financials ?? raw) as Record<string, any>;
	const income = (fin.income_statement ?? {}) as Record<string, unknown>;
	const cashflow = (fin.cash_flow ?? {}) as Record<string, unknown>;

	// 1. Revenue consistency (<5%)
	const rawRev = firstNum(income.revenue);
	const metricsRev = (metrics.revenue as number | undefined) ?? ratios.revenue;
	if (rawRev != null && metricsRev != null && relDiff(rawRev, metricsRev) > 0.05) {
		errors.push(`revenue: raw ${rawRev} vs metrics ${metricsRev} (>5%)`);
	}
	// 2. Market-cap consistency (<10%)
	const rawMc = (raw.market_cap as number | undefined) ?? (raw.profile as { market_cap?: number } | undefined)?.market_cap;
	const metricsMc = (metrics.market_cap as number | undefined) ?? ratios.market_cap;
	if (rawMc != null && metricsMc != null && relDiff(rawMc, metricsMc) > 0.10) {
		errors.push(`market_cap: raw ${rawMc} vs metrics ${metricsMc} (>10%)`);
	}
	// 3. P/E internal consistency (EPS × PE ≈ price, <15%)
	const pe = ratios.pe_ratio;
	const eps = ratios.eps;
	const price = (raw.price as number | undefined) ?? (raw.profile as { price?: number } | undefined)?.price;
	if (pe && eps && price && price > 0) {
		const implied = pe * eps;
		if (relDiff(implied, price) > 0.15) errors.push(`P/E: PE×EPS=${implied.toFixed(2)} vs price=${price} (>15%)`);
	}
	// 4. FCF sign vs FCF yield sign
	const fcf = firstNum(cashflow.free_cash_flow);
	const fcfYield = ratios.fcf_yield;
	if (fcf != null && fcfYield != null && (fcf >= 0) !== (fcfYield >= 0)) {
		errors.push(`FCF sign: FCF=${fcf} vs FCF yield=${fcfYield}`);
	}
	// 5. D/E direction vs net debt
	const de = ratios.debt_to_equity;
	const nd = ratios.net_debt;
	if (de != null && nd != null) {
		const dirOk = (de > 0) === (nd > 0) || (de === 0 && nd <= 0);
		if (!dirOk) errors.push(`D/E direction: D/E=${de} vs net_debt=${nd}`);
	}
	return { ok: errors.length === 0, errors };
}
