/**
 * Content gates — the validators that run between stages to enforce the
 * non-vacuous-pass discipline (ISS-02): a validator that produces no output is
 * a FAILURE, never a silent pass.
 *
 * Each gate reads the actual artifact a stage produced (a tracking entry, a
 * report file, or a script's structured result) and returns
 * `{ value, digest }`. `gateValidator(name, sourceKey)` in `nodes.ts` drives
 * the retry loop: on failure it writes `errors` into
 * `state.__feedback[feedbackKey]` so the next attempt's prompt can fix the
 * specific defect.
 *
 * `runHelper` is the single dispatch entry point — `HelperCall.name` resolves
 * through `GATE_DISPATCH`. Pure domain helpers (ticker normalization, ranking,
 * mode defaults) live in `helpers.ts` and are called directly by name, not
 * dispatched here.
 */

import type { ControlObj, HelperCall, HelperResult } from "./types.ts";
import { dirname } from "node:path";
import { validateRenderedReport, dataFreshness, forensicChecks, factCheck } from "./validators.ts";

const ok = (digest: string, value: ControlObj): HelperResult => ({ value, digest });
const fail = (errors: string[]): HelperResult => ({
	value: { pass: errors.length === 0, errors },
	digest: errors.length === 0 ? "PASS" : `FAIL: ${errors.length} error(s)`,
});

// ─── Gates ──────────────────────────────────────────────────────────────────

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
	const stage17 = s["stage-17"] as { reports?: Array<{ ticker?: string; horizon?: string; payload?: unknown; path?: string }> } | undefined;
	const reports = stage17?.reports;
	const errors: string[] = [];
	if (!Array.isArray(reports) || reports.length === 0) {
		errors.push("no reports generated at Stage 17");
		return fail(errors);
	}
	// Run the TS content gates (conviction consistency, kill-switch
	// falsifiability, short-term 三轴) on each report payload.
	const withPayload = reports.filter((r) => r && r.payload !== undefined);
	for (const r of withPayload) {
		const v = validateRenderedReport(r.payload);
		if (!v.ok) errors.push(`${r.ticker ?? "?"}/${r.horizon ?? "?"}: ${v.errors.slice(0, 3).join("; ")}`);
		// Data-freshness on the per-company dir (skip sector-level SCREEN reports,
		// whose dir is the whole run dir). Best-effort: missing dir ⇒ skip.
		if (r.path && r.ticker && r.ticker !== "SCREEN") {
			const f = dataFreshness(dirname(r.path));
			if (!f.ok) errors.push(`${r.ticker}: ${f.errors.join("; ")}`);
			const fc = forensicChecks(dirname(r.path));
			if (!fc.ok) errors.push(`${r.ticker} forensic: ${fc.errors.join("; ")}`);
			const fa = factCheck(dirname(r.path));
			if (!fa.ok) errors.push(`${r.ticker} fact-check: ${fa.errors.join("; ")}`);
		}
	}
	return fail(errors);
}

function gateBestPicks(s: Record<string, unknown>): HelperResult {
	const bp = requireSource(s, "stage-18");
	const errors: string[] = [];
	if (!bp) errors.push("Stage 18 best-picks output not produced");
	else if ((bp as { status?: string }).status === "rendered") {
		// Render path: renderDocTask already schema-validated the payload + wrote the file.
	}
	else {
		const picks = (bp.bestPicks as unknown[]) ?? (bp.picks as unknown[]) ?? [];
		if (picks.length === 0) errors.push("best-picks list is empty");
	}
	return fail(errors);
}

// ─── Dispatcher ─────────────────────────────────────────────────────────────

const GATE_DISPATCH: Record<string, (s: Record<string, unknown>) => HelperResult> = {
	"gate-shared-data": gateSharedData,
	"gate-screening": gateScreening,
	"gate-scoring": gateScoring,
	"gate-reports": gateReports,
	"gate-best-picks": gateBestPicks,
};

export async function runHelper(call: HelperCall): Promise<HelperResult> {
	const fn = GATE_DISPATCH[call.name];
	if (!fn) return ok(`unknown helper "${call.name}"`, { pass: false, errors: [`unknown helper: ${call.name}`] });
	return fn(call.sources);
}

export const HELPER_NAMES = Object.keys(GATE_DISPATCH);
