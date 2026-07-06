/**
 * Phase 1: EquityReportPayload schema + equity-report.njk template +
 * renderDocTask + renderReportsTask. Proves the agent-payload → validate →
 * render → write path produces the validator-critical structure (001 ranking,
 * 当前股价 column, exact disclaimer, short-term 三轴) deterministically.
 */

import { describe, it, expect } from "vitest";
import { join } from "node:path";
import { readFileSync, rmSync } from "node:fs";
import { renderDoc } from "../src/render.ts";
import { validatePayload, EquityReportPayload } from "../src/render-schemas.ts";
import { renderDocTask, renderReportsTask, type RenderDocResult } from "../src/render-node.ts";
import { reportPayloadBody } from "../src/prompts.ts";
import { makeState, makeFakeCtx } from "./helpers/fake-context.ts";

const ROOT = join(import.meta.dirname, "..");
const OUT = "/tmp/pi-stock-test-equity-report.md";

const payload = {
	horizon: "long",
	company: { ticker: "NVDA", name: "NVIDIA", name_en: "NVIDIA Corporation", price: 128.5, currency: "USD" },
	scores: {
		composite: 9, rating: "Strong Buy", conviction: 8.5,
		components: { "财务健康 (Financial Health)": 9, "护城河 (Moat)": 10, "管理质量 (Management)": 9, "估值吸引力 (Valuation)": 7 },
	},
	executive_summary: "NVIDIA is the dominant AI compute platform.",
	thesis: "The AI compute demand super-cycle is structural, not cyclical.",
	sections: [
		{ id: "moat", title: "1. 护城河评估 (Moat Assessment)", body: "The CUDA ecosystem is a 15-year developer lock-in." },
		{ id: "risks", title: "6. 主要长期风险", body: "Cyclicality and customer concentration are the key risks." },
	],
	ranking: [
		{ rank: 1, ticker: "NVDA", name: "NVIDIA", price: 128.5, reason: "AI compute monopoly" },
		{ rank: 2, ticker: "AVGO", name: "Broadcom", price: 1650, reason: "Custom ASIC silicon" },
	],
	kill_switch: "If data-center GPU revenue declines >20% QoQ for two consecutive quarters, re-evaluate.",
	frameworks: [
		{ name: "Buffett", score: 8, verdict: "Durable moat; valuation rich" },
		{ name: "Lynch", score: 9, verdict: "Fast grower, hold" },
	],
	disagreements: ["Buffett flags valuation; Lynch sees growth runway"],
	consensus: "All frameworks agree on moat durability.",
	catalysts: [{ event: "GTC 2026", date: "2026-03", probability: "High" }],
	conclusion: { action: "加仓 (Add)", target_price: 175, upside_pct: 0.36 },
	missing: [],
};

describe("EquityReportPayload + equity-report.njk", () => {
	it("validates the realistic payload", () => {
		expect(validatePayload(EquityReportPayload, payload).ok).toBe(true);
	});

	it("renders with canonical, validator-friendly formatting", () => {
		const r = renderDoc({ templateName: "equity-report.njk", payload, root: ROOT });
		expect(r.ok, r.error).toBe(true);
		const doc = r.doc!;
		expect(doc).toContain("NVIDIA (NVDA) — 长期投资分析");      // horizon-aware title
		expect(doc).toContain("$128.50");                            // 当前股价
		expect(doc).toContain("Strong Buy");
		expect(doc).toContain("推荐标的排名");
		expect(doc).toContain("| 001 |");                            // 001 zero-padded rank
		expect(doc).toContain("| 002 |");
		expect(doc).toContain("当前股价");                            // mandatory column header
		expect(doc).toContain("CUDA ecosystem");                     // section body prose injected
		expect(doc).toContain("Buffett");                            // framework table
		expect(doc).toContain("$175.00");                            // target price
		expect(doc).toContain("36.0%");                              // upside (pct 0.36)
		expect(doc).toContain("does not constitute financial advice"); // exact disclaimer
	});

	it("renders the short-term horizon with the 三轴 section", () => {
		const shortPayload = {
			...payload, horizon: "short",
			three_axis: { direction: "Bullish", vega: "Long-gamma", asymmetry: "2:1", summary: "Asymmetric upside." },
		};
		const r = renderDoc({ templateName: "equity-report.njk", payload: shortPayload, root: ROOT });
		expect(r.ok, r.error).toBe(true);
		expect(r.doc).toContain("短期投资分析 (Short-Term)");
		expect(r.doc).toContain("三轴结构检查");
		expect(r.doc).toContain("Long-gamma");
	});

	it("rejects a payload missing required fields", () => {
		const v = validatePayload(EquityReportPayload, { horizon: "long" });
		expect(v.ok).toBe(false);
		expect(v.errors.some((e) => e.includes("company") || e.includes("scores"))).toBe(true);
	});
});

describe("renderDocTask (single report node)", () => {
	it("validates + renders + writes the file when the agent emits a valid payload", async () => {
		rmSync(OUT, { force: true });
		const state = makeState({ extensionRoot: ROOT });
		const ctx = makeFakeCtx(state, { agentResult: () => ({ text: "", control: payload }) });
		const stage = renderDocTask({
			id: "stage-17", label: "report-writer", agent: "equity-report-writer",
			buildPrompt: () => "fill the payload", schema: EquityReportPayload,
			templateName: "equity-report.njk", outputPath: () => OUT,
		});
		const r = (await stage.run(state, ctx)) as RenderDocResult;
		expect(r.status).toBe("rendered");
		expect(r.file_path).toBe(OUT);
		const doc = readFileSync(OUT, "utf8");
		expect(doc).toContain("| 001 |");
		expect(doc).toContain("does not constitute financial advice");
	});

	it("returns status=invalid (and writes nothing) when the payload fails validation", async () => {
		rmSync(OUT, { force: true });
		const state = makeState({ extensionRoot: ROOT });
		const ctx = makeFakeCtx(state, { agentResult: () => ({ text: "", control: { horizon: "long" } }) });
		const stage = renderDocTask({
			id: "stage-17", label: "report-writer", agent: "equity-report-writer",
			buildPrompt: () => "fill the payload", schema: EquityReportPayload,
			templateName: "equity-report.njk", outputPath: () => OUT,
		});
		const r = (await stage.run(state, ctx)) as RenderDocResult;
		expect(r.status).toBe("invalid");
		expect(r.errors?.length).toBeGreaterThan(0);
		expect(() => readFileSync(OUT, "utf8")).toThrow();
	});
});

describe("renderReportsTask (company × horizon loop)", () => {
	it("renders one .md per company × horizon (6 total) and sets state[id].reports", async () => {
		rmSync("/tmp/pi-stock-test-reports", { recursive: true, force: true });
		const companies = [
			{ ticker: "NVDA", name: "NVIDIA", isAsh: false, score: 9 },
			{ ticker: "AVGO", name: "Broadcom", isAsh: false, score: 8 },
		];
		const state = makeState({ extensionRoot: ROOT, companies: companies as never });
		let calls = 0;
		const ctx = makeFakeCtx(state, {
			agentResult: (call) => {
				calls++;
				const parts = call.id.split("."); // pipeline.stage-17r.TICKER.horizon
				const ticker = parts[2];
				const horizon = parts[3] as "long" | "mid" | "short";
				return { text: "", control: { report: { ...payload, horizon, company: { ...payload.company, ticker, name: ticker } } } };
			},
		});
		const stage = renderReportsTask({
			id: "stage-17r", label: "reports (rendered)", agent: "equity-report-writer",
			controlKeys: ["report"], payloadKey: "report", schema: EquityReportPayload,
			templateForHorizon: () => "equity-report.njk",
			outputPathFor: (_s, job) => `/tmp/pi-stock-test-reports/${job.company.ticker}_${job.horizon}.md`,
			buildPrompt: (_s, _c, job) => reportPayloadBody(job.company, job.horizon),
		});
		const r = (await stage.run(state, ctx)) as { reports: { path: string; horizon: string }[] };
		expect(calls).toBe(6); // 2 companies × 3 horizons
		expect(r.reports.length).toBe(6);
		expect(state.reports.length).toBe(6);
		const firstDoc = readFileSync(r.reports[0].path, "utf8");
		expect(firstDoc).toContain("| 001 |");
		expect(firstDoc).toContain("does not constitute financial advice");
		// short-horizon report includes the 三轴 section
		const shortDoc = readFileSync(r.reports.find((x) => x.horizon === "short")!.path, "utf8");
		expect(shortDoc).toContain("三轴结构检查");
	});
});
