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
