/**
 * Prompt builders for each pipeline stage.
 *
 * Every builder injects:
 *   - EXTENSION_ROOT (so agents can `uv run python ${EXTENSION_ROOT}/scripts/...`)
 *   - the run identity slice (mode, runId, reportsDir, tickers, theme, filters)
 *   - gate feedback (state.__feedback[stageId]) so a retried agent fixes the
 *     SPECIFIC validator errors instead of blind-resampling.
 *
 * Context-eviction discipline (rule "context-eviction"): each builder includes
 * ONLY the keys its stage requires (e.g. the industry-analyst prompt never
 * receives the macro-analyst's raw output). Agents load references/templates
 * lazily per-stage.
 */

import type { StockAnalysisState, StageContext } from "./types.ts";

// EXTENSION_ROOT is resolved in extension.ts and threaded via state.extensionRoot
// (the actual absolute path), AND exported into the spawned agent's env so
// \${EXTENSION_ROOT} in agent .md files / bash commands resolves too.

/** The shared preamble every agent sees: who they are, where things live,
 *  and the run's identity. Kept tight to preserve the agent's context budget. */
export function runHeader(state: StockAnalysisState): string {
	const lines = [
		`## Run`,
		`- Mode: ${state.mode}`,
		`- Run ID: ${state.runId}`,
		`- Reports dir: ${state.reportsDir}`,
		`- Universe: ${state.universe}`,
	];
	if (state.tickers.length) lines.push(`- Tickers: ${state.tickers.join(", ")}`);
	if (state.theme) {
		lines.push(`- Theme: ${state.theme}`);
		if (state.mode === "screen" || state.mode === "pipeline") {
			lines.push(`- ⚠️ THEME-FOCUS ACTIVE: restrict the screen to the "${state.theme}" value-chain sub-industries (NOT a generic market-wide top-RS screen).`);
		}
	}
	lines.push(`- topIndustry=${state.topIndustry}, totalCompany=${state.totalCompany}, topPrice=${state.topPrice}, minHeadroom=${state.minHeadroom}, days=${state.days}`);
	lines.push("");
	lines.push(`## Resources (package root: ${state.extensionRoot})`);
	lines.push(`- Scripts:   ${state.extensionRoot}/scripts/   (invoke via: uv run python ${state.extensionRoot}/scripts/<name>.py ...)`);
	lines.push(`- References: ${state.extensionRoot}/references/`);
	lines.push(`- Templates:  ${state.extensionRoot}/templates/`);
	lines.push(`- Schemas:    ${state.extensionRoot}/schemas/`);
	lines.push(`- Assets:     ${state.extensionRoot}/assets/`);
	lines.push(`(EXTENSION_ROOT=${state.extensionRoot} is also exported in your shell env; \${EXTENSION_ROOT} expands in bash.)`);
	lines.push("");
	lines.push("## Rules (binding)");
	lines.push("- ALL reports MUST be written in Chinese (中文). Technical terms in English.");
	lines.push("- Every company in any table/list must include 当前股价.");
	lines.push("- ALWAYS produce all 3 horizons (long/mid/short). Never ask — just produce them.");
	lines.push("- Deterministic calculations run via the verbatim python scripts (uv run). Never hand-compute scores.");
	lines.push("- Write outputs under the reports dir; never write inside the package.");
	return lines.join("\n");
}

/** Gate feedback the workflow runner prepended to a retried agent's prompt.
 *  Exposed here so builders can also surface it inline. */
export function feedbackBlock(state: StockAnalysisState, feedbackKey?: string): string {
	if (!feedbackKey) return "";
	const errors = state.__feedback?.[feedbackKey];
	if (!errors?.length) return "";
	return [
		"",
		"## Previous attempt rejected — fix these",
		"The validator rejected the prior attempt for these specific reasons:",
		...errors.map((e) => `- ${e}`),
		"Address every point and re-produce the complete artifact.",
	].join("\n");
}

/** Minimal shared prompt wrapper used by stages that spawn one agent. */
export function stagePrompt(
	state: StockAnalysisState,
	stageId: string,
	body: string,
	opts: { feedbackKey?: string; controlKeys?: string[] } = {},
): string {
	const parts = [runHeader(state)];
	const fb = feedbackBlock(state, opts.feedbackKey);
	if (fb) parts.push(fb);
	parts.push("", "## Task", body);
	if (opts.controlKeys?.length) {
		parts.push("", `Output <control> JSON with: ${opts.controlKeys.join(", ")}.`);
	}
	return parts.join("\n");
}

// ─── Per-stage prompt bodies ────────────────────────────────────────────────
// Each returns the task body; stagePrompt() wraps it with the header + feedback.

export function dataCollectorBody(state: StockAnalysisState): string {
	const lines = [
		"Fetch the shared market data ONCE (macro, economic surprises, sector/sub-industry RS, market breadth, theme performance).",
		"Write each dataset to the reports dir as JSON. Record every file path you produced.",
		"Load references/gics_taxonomy.md and references/data_source_matrix.md before fetching.",
	];
	if (state.theme) {
		lines.push(
			`🎯 THEME FOCUS: the run targets theme "${state.theme}". You MUST run scripts/fetch_theme_performance.py and scripts/fetch_sub_industry_universe.py for this theme so downstream screeners can restrict to the theme's value chain. Persist their JSON output under the reports dir.`,
		);
	}
	return lines.join("\n");
}

export function sectorScreenerBody(state: StockAnalysisState): string {
	const lines = [
		`Hot-sector focus window: days=${state.days} (1=today, 5=week, 10=2 weeks, 20=month).`,
		"Process in 3 parallel batches of ~54. Deep-dive the top N (Porter, TAM, catalysts, barriers, company universe).",
	];
	if (state.theme) {
		lines.unshift(
			`🎯 THEME FOCUS: the user's target theme is "${state.theme}". You MUST restrict the screen to GICS Level-4 sub-industries that are part of this theme's value chain (upstream materials → midstream components → downstream integrators).`,
			`First identify the theme-relevant sub-industries: run scripts/fetch_sub_industry_universe.py and scripts/fetch_theme_performance.py against "${state.theme}", then map the theme to specific GICS Level-4 codes (consult references/gics_taxonomy.md). Only rank sub-industries materially relevant to "${state.theme}". Do NOT return generic top-RS sub-industries unrelated to the theme.`,
			`Then apply the 11-dimension screen to those theme-relevant sub-industries and select the top ${state.topIndustry} that ALSO score well on the 11 dimensions (don't rank by theme-relevance alone).`,
		);
	} else {
		lines.unshift(`Screen ALL 163 GICS Level-4 sub-industries on 11 dimensions; select the top ${state.topIndustry}.`);
	}
	return lines.join("\n");
}

export function companyScreenerBody(state: StockAnalysisState): string {
	const lines = [
		`Screen companies across the top sub-industries. Apply filters: price (< ${state.topPrice} ${state.topPrice === 0 ? "[DISABLED]" : ""}), Growth Headroom ≥ ${state.minHeadroom}, universe=${state.universe}.`,
		"Dual-channel FCF filter (conservative positive-FCF OR aggressive negative-FCF with 2yr runway). Cyclical adjustment at Step 3.5.",
		`Select top ${state.totalCompany} by score across ALL sub-industries (NOT quota per sub-industry).`,
	];
	if (state.theme) {
		lines.push(
			`🎯 THEME FOCUS: only screen companies within the "${state.theme}" value-chain sub-industries selected upstream. Every company in the watchlist must be materially exposed to "${state.theme}"; reject diversified names with only incidental theme exposure.`,
		);
	}
	return lines.join("\n");
}

export function roadmapWalkerBody(state: StockAnalysisState): string {
	return [
		`Bottleneck walk for theme: "${state.theme ?? "(unspecified)"}".`,
		"Anchor a quantitative dated demand roadmap, reverse-walk the chain (≥5 layers), score the 4-element chokepoint checklist per layer,",
		"identify candidates in chokepoint layers (score ≥3), run score_bottleneck_asymmetry.py for each.",
		`Return up to ${state.topIndustry} candidates by asymmetry_composite for full deep-dive.`,
	].join("\n");
}

export function perCompanyAnalystBody(stageId: string, _state: StockAnalysisState): string {
	// The current company is exposed at state.company (set by the map node).
	const map: Record<string, string> = {
		"stage-5": "Financial Health: DuPont 5-factor, Piotroski F-Score, Lynch categories, key ratios. Scripts: fetch_financials.py, calculate_metrics.py.",
		"stage-6": "Earnings Quality: Beneish M-Score, Montier C-Score, accruals, cash conversion, capital allocation, CEO quality. Scripts: fetch_capital_structure.py, calculate_earnings_quality.py, score_ceo_quality.py.",
		"stage-7": "Industry & Competitive: Porter, TAM/SAM/SOM, Morningstar moat, BCG. Reuse industry thesis from Stage 3 if available. Scripts: fetch_peer_universe.py.",
		"stage-8": "Supply Chain: Tier 1-3 mapping, HHI concentration, chokepoints, disruption scenarios. Run score_bottleneck_asymmetry.py per chokepoint. Scripts: fetch_supply_chain.py.",
		"stage-9": "Macro & Geopolitics: Dalio cycle, Druckenmiller liquidity, Four-Box, Fed stance, CRP, sanctions, currency. Reuse Stage 1 macro. Scripts: fetch_global_macro.py, fetch_currency_exposure.py.",
		"stage-10": "Valuation: DCF+Monte Carlo, comps, SOTP, LBO floor, reverse DCF, margin of safety. Serenity TAM-Adj-PEG, Bayesian intrinsic growth. Scripts: forecast.py, compute_tam_adj_peg.py, compute_bayesian_growth.py.",
		"stage-11": "Market Regime: Weinstein stage, CANSLIM, Soros reflexivity, Fama-French 5-factor, options, sentiment, GF-DMA Health Index. Scripts: fetch_technicals.py, compute_factors.py, compute_health_index.py.",
		"stage-12": "Risk: bull/base/bear scenarios, Marks 2nd-level, Burry forensic, Klarman perm/temp, kill switch, correlation regime. Scripts: fetch_credit.py, compute_correlation_regime.py.",
		"stage-13": "Alt Data & Digital: digital footprint, NLP earnings, channel checks, Serenity-Alpha elasticity. Scripts: fetch_alternatives.py, analyze_earnings_transcript.py.",
		"stage-14": "Catalyst Intelligence: calendar (FDA/earnings/product/regulatory), event probability, PEAD. Scripts: compute_earnings_edge.py, event_study.py.",
		"stage-15": "A-Share Analysis: 政策敏感性, 产业政策周期, 北向资金, 融资融券, 龙虎榜, 游资追踪. MANDATORY for .SH/.SZ.",
	};
	return map[stageId] ?? "(analyze this company on your specialist dimension; write findings to the reports dir)";
}

export function scorerBody(_state: StockAnalysisState): string {
	return [
		"Deterministic scoring via compute_scores.py for each company (11 components, composite conviction).",
		"Cross-check contradictions via cross_check.py. Calibrate conviction via calibrate_conviction.py.",
		"LLM agents may adjust Moat and Management ±2.0 based on qualitative findings. Rank by composite.",
	].join("\n");
}

export function adversarialBody(_state: StockAnalysisState): string {
	return "3 perspective-diverse skeptics (fundamentals / macro / flow). Bayesian-skeptic default — attempt to REFUTE the bull thesis. A pick survives if ≥2/3 do NOT refute.";
}

export function judgePanelBody(_state: StockAnalysisState): string {
	return "4 investment-framework lenses (Buffett / Lynch / Marks / Druckenmiller), each rates 0-10 with verdict + explicit disagreement points. Identify the top 1-2 framework disagreements per company as the real investment decision points.";
}

export function reportWriterBody(mode: string, _state: StockAnalysisState): string {
	const map: Record<string, string> = {
		pipeline: "Screening overview (3 horizons) + per-company deep-dives (3 horizons each). Fold in bear-case verdicts and panel consensus as 对手方观点 and 多框架交叉验证 sections.",
		screen: "Screening reports only (3 horizons).",
		analyze: "Per-company reports only (3 horizons each).",
		compare: "Comparison reports with ranked table. Identical valuation methodology across all.",
		walk: "Walk report + per-candidate deep-dives (3 horizons each).",
	};
	return map[mode] ?? "Produce the reports appropriate to the mode (3 horizons each).";
}

export function bestPicksBody(_state: StockAnalysisState): string {
	return [
		"Write HIGHLIGHTS_BEST_PICKS.md grouping picks by position type (core/satellite/tactical) from judge_panel.json.",
		"Sections: 核心仓位推荐, 成长卫星推荐, 期权投机推荐. Per-company: rank, ticker, name, 当前股价, composite, conviction, 2-sentence thesis, kill switch, catalyst, 框架共识, 对手方验证.",
		"End with 组合互补性检查 (industry concentration + style homogeneity). ⚠️ caution notes for flagged picks.",
	].join("\n");
}
