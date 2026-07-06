/**
 * renderDocTask — a stage that produces a document deterministically.
 *
 * Flow: agent emits a `<control>` payload → validate against a TypeBox schema →
 * render a Nunjucks template → write the `.md`. The agent fills CONTENT (data +
 * prose strings); the template owns ALL formatting — so the validator can't be
 * defeated by freeform markdown drift.
 *
 * Drop-in companion to `writerTask` (nodes.ts): same `{id,label,agent,
 * buildPrompt,controlKeys,fatal}` shape, plus `schema` + `templateName` +
 * `outputPath`. On validation/render failure it returns a structured result
 * (status=invalid|render_error|write_error) so a wrapping `retry`/`gate` can
 * re-run with the errors fed back as `state.__feedback`.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import type { StockAnalysisState, Stage, StageContext, AgentCall, Company } from "./types.ts";
import { renderDoc } from "./render.ts";
import { validatePayload } from "./render-schemas.ts";

export interface RenderDocSpec {
	id: string;
	label: string;
	agent: string;
	buildPrompt: (state: StockAnalysisState, ctx: StageContext) => string;
	/** TypeBox schema the agent's payload must satisfy. */
	schema: object;
	/** Key within `control` that holds the payload; omit to use the whole object. */
	payloadKey?: string;
	/** Template filename under <root>/templates/. */
	templateName: string;
	/** Absolute output path (under state.reportsDir). Parent dirs are created. */
	outputPath: (state: StockAnalysisState, ctx: StageContext) => string;
	/** Forwarded to ctx.agent (controls what the agent is told to emit). */
	controlKeys?: string[];
	fatal?: boolean;
}

export interface RenderDocResult {
	status: "rendered" | "invalid" | "render_error" | "write_error" | "error";
	file_path?: string;
	bytes?: number;
	errors?: string[];
	error?: string;
}

/** Build a stage that renders a schema-validated payload to a markdown file. */
export function renderDocTask(spec: RenderDocSpec): Stage {
	return {
		id: spec.id,
		label: spec.label,
		fatal: spec.fatal,
		async run(state, ctx): Promise<RenderDocResult | undefined> {
			if (!ctx.budget.check()) return undefined;
			const prompt = spec.buildPrompt(state, ctx);
			const call: AgentCall = {
				id: `pipeline.${spec.id}`,
				agent: spec.agent,
				prompt,
				controlKeys: spec.controlKeys,
			};
			const result = await ctx.agent(call);
			if (result.error) {
				ctx.log(`${spec.id}: agent error — ${result.error}`);
				return { status: "error", error: result.error };
			}
			const control = (result.control ?? {}) as Record<string, unknown>;
			const payload = spec.payloadKey ? control[spec.payloadKey] : control;
			const v = validatePayload(spec.schema, payload);
			if (!v.ok) {
				ctx.log(`${spec.id}: payload validation FAILED — ${v.errors.slice(0, 3).join("; ")}`);
				// Surface errors so a wrapping gate/retry can feed them back.
				return { status: "invalid", errors: v.errors };
			}
			const r = renderDoc({ templateName: spec.templateName, payload: payload as Record<string, unknown>, root: state.extensionRoot });
			if (!r.ok) {
				ctx.log(`${spec.id}: render FAILED — ${r.error}`);
				return { status: "render_error", error: r.error };
			}
			const out = spec.outputPath(state, ctx);
			try {
				mkdirSync(dirname(out), { recursive: true });
				writeFileSync(out, r.doc as string, "utf8");
			} catch (e) {
				ctx.log(`${spec.id}: write FAILED — ${(e as Error).message}`);
				return { status: "write_error", error: (e as Error).message };
			}
			ctx.log(`${spec.id}: rendered ${out} (${(r.doc as string).length} bytes)`);
			return { status: "rendered", file_path: out, bytes: (r.doc as string).length };
		},
	};
}

// ─── renderReportsTask: loop companies × horizons, render every report ─────────

export interface ReportJob {
	company: Company;
	horizon: "long" | "mid" | "short";
}

export interface RenderReportsSpec {
	id: string;
	label: string;
	agent: string;
	/** Per-job prompt builder (receives the current {company, horizon} job). */
	buildPrompt: (state: StockAnalysisState, ctx: StageContext, job: ReportJob) => string;
	schema: object;
	payloadKey?: string;
	/** Template filename for a given horizon (e.g. h => `equity-report-${h}.njk`). */
	templateForHorizon: (horizon: "long" | "mid" | "short") => string;
	/** Output path for a job (under state.reportsDir). Parent dirs are created. */
	outputPathFor: (state: StockAnalysisState, job: ReportJob) => string;
	controlKeys?: string[];
	horizons?: ("long" | "mid" | "short")[]; // default all three
	fatal?: boolean;
}

/** A stage that renders one report per (company × horizon). Sets
 *  state[id] = { reports: [{path, ticker, horizon}] } so the gate-reports
 *  validator + the Stage 17.4 critic (which iterate state.reports) keep working.
 *  Per-job failures are logged and skipped (non-fatal); an empty result fails
 *  the gate, which retries the whole stage. */
export function renderReportsTask(spec: RenderReportsSpec): Stage {
	const horizons = spec.horizons ?? ["long", "mid", "short"];
	return {
		id: spec.id,
		label: spec.label,
		fatal: spec.fatal,
		async run(state, ctx) {
			const companies = state.companies ?? [];
			const jobs: ReportJob[] = companies.flatMap((company) =>
				horizons.map((horizon) => ({ company, horizon })));
			const reports: { path: string; ticker: string; horizon: string }[] = [];
			for (const job of jobs) {
				if (!ctx.budget.check()) break;
				const prompt = spec.buildPrompt(state, ctx, job);
				const call: AgentCall = {
					id: `pipeline.${spec.id}.${job.company.ticker}.${job.horizon}`,
					agent: spec.agent,
					prompt,
					controlKeys: spec.controlKeys,
				};
				const result = await ctx.agent(call);
				const control = (result.control ?? {}) as Record<string, unknown>;
				const payload = spec.payloadKey ? control[spec.payloadKey] : control;
				const tag = `${job.company.ticker}/${job.horizon}`;
				const v = validatePayload(spec.schema, payload);
				if (!v.ok) {
					ctx.log(`${spec.id} ${tag}: payload INVALID — ${v.errors.slice(0, 2).join("; ")}`);
					continue;
				}
				const r = renderDoc({
					templateName: spec.templateForHorizon(job.horizon),
					payload: payload as Record<string, unknown>,
					root: state.extensionRoot,
				});
				if (!r.ok) {
					ctx.log(`${spec.id} ${tag}: render FAILED — ${r.error}`);
					continue;
				}
				const out = spec.outputPathFor(state, job);
				try {
					mkdirSync(dirname(out), { recursive: true });
					writeFileSync(out, r.doc as string, "utf8");
				} catch (e) {
					ctx.log(`${spec.id} ${tag}: write FAILED — ${(e as Error).message}`);
					continue;
				}
				reports.push({ path: out, ticker: job.company.ticker, horizon: job.horizon });
				ctx.log(`${spec.id} ${tag}: rendered ${out}`);
			}
			(state as Record<string, unknown>)[spec.id] = { reports };
			// Keep state.reports in sync for the Stage 17.4 critic + best-picks.
			(state as StockAnalysisState).reports = reports as never;
			return { reports };
		},
	};
}
