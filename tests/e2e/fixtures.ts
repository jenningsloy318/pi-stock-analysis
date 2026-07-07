/**
 * Recorded-fixture mock for the pipeline-analyze e2e test.
 *
 * Returns canned `<control>` responses keyed by `call.id`, so the full
 * stage-graph traverses end-to-end with no `pi` spawns, no network, no `uv`.
 *
 * To regenerate from a REAL run: instrument `spawnAgent` (or set
 * `agentRunner`) to write each `AgentResult` to
 * `tests/e2e/fixtures/<id>.json` before returning, then load them here. This
 * hand-built fixture is the seed.
 */

import type { AgentCall, AgentResult } from "../../src/types.ts";

// ─── valid EquityReportPayload (passes schema + content gates) ───────────────

function equityPayload(horizon: "long" | "mid" | "short", ticker = "AAPL", name = "Apple Inc.", price = 195.5) {
	return {
		horizon,
		company: { ticker, name, name_en: name, price, currency: "USD" as const },
		scores: {
			composite: 8,
			rating: "Buy",
			conviction: "High",
			components: { moat: 8, financials: 8, valuation: 7, growth: 9 },
		},
		executive_summary: `${name} is a dominant platform with durable cash flows.`,
		thesis: `Services-driven margin expansion and a loyal device installed base underpin a ${horizon}-term compounding thesis.`,
		sections: [
			{ id: "moat", title: "Moat", body: "Ecosystem lock-in via iOS/App Store." },
			{ id: "financials", title: "Financial Health", body: "Net cash, AAA balance sheet." },
		],
		ranking: [
			{ rank: 1, ticker, name, price, reason: "Best-in-class margins and buyback discipline." },
		],
		kill_switch: `If Services revenue growth falls below 5% YoY for 2 consecutive quarters, re-evaluate the thesis.`,
		frameworks: [
			{ name: "Buffett", score: 8, verdict: "Strong consumer moat with recurring revenue." },
		],
		conclusion: {
			action: "加仓",
			target_price: 240,
			upside_pct: 22.5,
		},
		...(horizon === "short"
			? {
					three_axis: {
						direction: "多头排列",
						vega: "隐含波动率偏低",
						asymmetry: "上行空间大于下行风险",
						summary: "Short-term momentum favorable with low implied vol.",
					},
				}
			: {}),
	};
}

// ─── valid BestPicksPayload ──────────────────────────────────────────────────

function bestPicksPayload() {
	return {
		groups: [
			{
				type: "core" as const,
				label: "核心仓位",
				picks: [
					{
						rank: 1,
						ticker: "AAPL",
						name: "Apple Inc.",
						price: 195.5,
						currency: "USD" as const,
						composite: 8,
						conviction: "High",
						thesis: "Services margin expansion compounding thesis.",
						kill_switch: "If Services revenue growth falls below 5% YoY for 2 consecutive quarters, re-evaluate.",
						catalyst: "Q4 services revenue print.",
						framework_consensus: "Buffett/Lynch agree on moat durability.",
					},
				],
			},
		],
		complementarity: {
			industry_concentration: "Low — single name, no overlap.",
			style_homogeneity: "N/A for single pick.",
		},
	};
}

// ─── the mock agent runner ───────────────────────────────────────────────────

export async function mockAgent(call: AgentCall): Promise<AgentResult> {
	const id = (call.id ?? "").replace(/^pipeline\./, "");

	// Stage 1 — data-collector (must pass gate-shared-data).
	if (id === "stage-1") {
		return { text: "ok", control: { status: "ok", files: ["raw-data.json"], notes: "" } };
	}

	// Stages 5-14 — per-company analysts (no individual gate; just findings).
	if (/^stage-(5|6|7|8|9|10|11|12|13|14)$/.test(id)) {
		return { text: "ok", control: { findings: `${id}: analysis complete for current company.` } };
	}

	// Stage 16 — scorer (must pass gate-scoring: composite 1-10).
	if (id === "stage-16") {
		return {
			text: "ok",
			control: {
				companies: [
					{ ticker: "AAPL", composite: 8, rating: "Buy", components: { moat: 8, financials: 8 } },
				],
			},
		};
	}

	// Stage 16.6 — adversarial verify (top-5).
	if (id === "stage-16.6") {
		return {
			text: "ok",
			control: { survived: true, skeptics: [{ verdict: "upheld", reasoning: "Thesis holds under stress." }] },
		};
	}

	// Stage 16.7 — judge panel.
	if (id === "stage-16.7") {
		return {
			text: "ok",
			control: {
				lenses: [{ name: "Buffett", score: 8, verdict: "Strong moat." }],
				disagreements: [],
				positionType: "core",
			},
		};
	}

	// Stage 17 — equity-report-writer (render path; per company × horizon).
	if (id.startsWith("stage-17.")) {
		const parts = id.split(".");
		const horizon = parts[parts.length - 1] as "long" | "mid" | "short";
		const ticker = parts.length >= 3 ? parts[parts.length - 2] : "AAPL";
		return { text: "ok", control: { report: equityPayload(horizon, ticker) } };
	}

	// Stage 17.4 — completeness critic.
	if (id.startsWith("stage-17.4")) {
		return { text: "ok", control: { findings: [], severity: "LOW" } };
	}

	// Stage 18 — best-picks (render path).
	if (id === "stage-18") {
		return { text: "ok", control: { bestPicks: bestPicksPayload() } };
	}

	// Defensive fallback.
	return { text: "ok", control: {} };
}
