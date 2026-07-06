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
import { dirname } from "node:path";
import type { StockAnalysisState, Stage, StageContext, AgentCall } from "./types.ts";
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
