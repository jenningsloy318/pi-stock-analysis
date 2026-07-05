/**
 * In-process specialist execution via the pi SDK (`createAgentSession`) — the
 * session backend (opt-in via STOCK_ANALYSIS_BACKEND=session).
 *
 * This is the alternative to {@link spawnAgent} (raw `pi` subprocess). It runs
 * a specialist in-process, in-memory, and captures its result via a
 * `structured_output` tool (schema-validated) instead of parsing `<control>`
 * text from subprocess stdout. Same return contract as spawnAgent
 * ({@link SpawnResult}) so the workflow engine is unchanged.
 *
 * Select at runtime via `ctx.agent` (see workflow.ts).
 */

import {
	createAgentSession,
	createCodingTools,
	defineTool,
	getAgentDir,
	type ToolDefinition,
	SessionManager,
	SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { loadAgentPrompt } from "./agents.ts";
import { extractControl } from "./control.ts";
import { summarizeToolCall } from "./pi-spawn.ts";
import type { AgentProgress, SpawnResult } from "./types.ts";

export interface SessionAgentOptions {
	agent: string;
	prompt: string;
	cwd: string;
	model?: string;
	signal?: AbortSignal;
	id?: string;
	timeoutMs?: number;
	controlKeys?: string[];
	onProgress?: AgentProgress;
}

/** Build the structured_output schema. Declares each expected key so the model
 *  treats it as part of the contract and fills it. Keys stay Optional so tool
 *  validation never rejects a partially-filled object; completeness is enforced
 *  by the corrective re-prompt. */
function controlSchema(keys: string[]) {
	const props: Record<string, ReturnType<typeof Type.Any>> = {};
	for (const k of keys) props[k] = Type.Optional(Type.Any());
	return Type.Object(props, { additionalProperties: true });
}

export function missingKeys(captured: Record<string, unknown> | null | undefined, keys: string[]): string[] {
	if (!captured) return keys;
	return keys.filter((k) => {
		const v = captured[k];
		return v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
	});
}

interface Capture {
	called: boolean;
	value: unknown;
}

function structuredOutputTool(capture: Capture, keys: string[]): ToolDefinition {
	const fieldList = keys.length ? keys.join(", ") : "the fields the task requested";
	return defineTool({
		name: "structured_output",
		label: "Structured Output",
		description: `Return the final result object. It MUST include every one of these keys: ${fieldList}.`,
		promptSnippet: "Return final machine-readable result",
		promptGuidelines: [
			`structured_output is the final answer channel; call it exactly once when the task is complete. Your object MUST contain ALL of: ${fieldList}.`,
			"Do not write a prose final answer after calling structured_output.",
		],
		parameters: controlSchema(keys),
		async execute(_toolCallId, params) {
			capture.value = { ...(capture.value as Record<string, unknown> | undefined), ...params };
			capture.called = true;
			return {
				content: [{ type: "text", text: "Structured output received." }],
				details: params,
				terminate: true,
			};
		},
	});
}

function forwardProgress(session: { subscribe(listener: (e: unknown) => void): () => void }, onProgress: AgentProgress): () => void {
	let turns = 0;
	let lastText = "";
	return session.subscribe((event: unknown) => {
		const e = event as { type?: string; toolName?: string; args?: Record<string, unknown>; assistantMessageEvent?: { type?: string; partial?: { content?: Array<{ type: string; text?: string }> } } };
		if (!e?.type) return;
		if (e.type === "tool_execution_start" && e.toolName) {
			lastText = "";
			onProgress.event(`→ ${summarizeToolCall(e.toolName, e.args)}`);
		} else if (e.type === "turn_start") {
			if (++turns > 1) onProgress.event(`turn ${turns}`);
		} else if (e.type === "message_update") {
			const a = e.assistantMessageEvent;
			if (a?.type === "text_delta" || a?.type === "text_end") {
				const text = (a.partial?.content ?? []).filter((p) => p.type === "text").map((p) => p.text ?? "").join("");
				const clean = text.replace(/<control>[\s\S]*?<\/control>/gi, "").trim();
				if (clean && clean !== lastText) {
					lastText = clean;
					onProgress.text(clean);
				}
			}
		}
	});
}

function lastAssistantText(messages: Array<{ role?: string; content?: Array<{ type: string; text?: string }> }>): string {
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i];
		if (m?.role !== "assistant" || !Array.isArray(m.content)) continue;
		const t = m.content.filter((p) => p.type === "text" && typeof p.text === "string").map((p) => p.text as string).join("");
		if (t.trim()) return t;
	}
	return "";
}

/** Run a specialist in-process and return its result (SpawnResult contract). */
export async function runAgentViaSession(opts: SessionAgentOptions): Promise<SpawnResult> {
	const systemPrompt = loadAgentPrompt(opts.agent);
	const keys = opts.controlKeys ?? [];
	const capture: Capture = { called: false, value: undefined };
	const timeoutMs = opts.timeoutMs ?? 480_000;

	const agentDir = getAgentDir();
	const { session } = await createAgentSession({
		cwd: opts.cwd,
		agentDir,
		sessionManager: SessionManager.inMemory(opts.cwd),
		settingsManager: SettingsManager.create(opts.cwd, agentDir),
		customTools: [...createCodingTools(opts.cwd), structuredOutputTool(capture, keys)],
	});

	const unsub = opts.onProgress ? forwardProgress(session, opts.onProgress) : undefined;
	let timedOut = false;
	const onAbort = () => void session.abort();
	const timer = setTimeout(() => {
		timedOut = true;
		try { void session.abort(); } catch { /* ignore */ }
	}, timeoutMs);
	opts.signal?.addEventListener("abort", onAbort, { once: true });

	const finalOutputLine = keys.length
		? `When the task is complete, call the \`structured_output\` tool exactly once with an object containing ALL of these keys: ${keys.join(", ")}. Do not omit any.`
		: "When the task is complete, call the `structured_output` tool exactly once with the fields requested above.";
	const deliveryDiscipline = [
		"## Delivery discipline",
		"You have a LIMITED time budget. The ONLY deliverable that matters is the written output + your structured_output call.",
		"- Bound exploration to ~6 tool calls. Start writing once you have the gist.",
		"- After writing, immediately call structured_output and STOP.",
	].join("\n");
	const task = [systemPrompt, "", "## Task", opts.prompt, "", deliveryDiscipline, "", "## Final output", finalOutputLine].join("\n");

	try {
		try {
			await session.prompt(task);
		} catch (err) {
			if (!timedOut && !opts.signal?.aborted) throw err;
		}

		// Self-heal: if the model called structured_output but omitted declared
		// keys, send ONE corrective turn in the same session naming what's missing.
		const afterFirst = capture.called ? (capture.value as Record<string, unknown> | undefined) : undefined;
		const missing = missingKeys(afterFirst, keys);
		if (capture.called && missing.length > 0 && !timedOut && !opts.signal?.aborted) {
			opts.onProgress?.event(`↻ ${opts.id ?? opts.agent}: corrective re-prompt (missing: ${missing.join(", ")})`);
			const fix = `Your previous structured_output was missing required keys: ${missing.join(", ")}. Call structured_output AGAIN with ALL of these keys filled: ${keys.join(", ")}.`;
			try {
				await session.prompt(fix);
			} catch (err) {
				if (!timedOut && !opts.signal?.aborted) throw err;
			}
		}

		const text = lastAssistantText(session.messages as Parameters<typeof lastAssistantText>[0]);
		const control = capture.called ? (capture.value as Record<string, unknown>) : extractControl(text);
		return { text, control: control ?? null, error: timedOut ? `timed out after ${Math.round(timeoutMs / 1000)}s${capture.called ? " (structured_output captured before abort)" : ""}` : undefined };
	} catch (err) {
		return { text: "", control: null, error: err instanceof Error ? err.message : String(err) };
	} finally {
		clearTimeout(timer);
		opts.signal?.removeEventListener("abort", onAbort);
		unsub?.();
		session.dispose();
	}
}
