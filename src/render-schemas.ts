/**
 * TypeBox payload schemas — the data contract each agent fills. The payload is
 *   (a) validated before rendering (validatePayload),
 *   (b) fed to the renderer (render.ts),
 *   (c) shown to the agent as the spec of what to emit.
 *
 * Add one schema per document-producing stage (scope = "every stage"). Fields
 * mirror the variables in the matching template under templates/, so template
 * and schema evolve together.
 *
 * TypeBox 1.3 API: `Type` from "typebox"; the JIT validator `Compile` from
 * "typebox/compile" returns `{ Check(value), Errors(value) }`.
 */

import { Type, type Static } from "typebox";
import { Compile } from "typebox/compile";

// ─── validation helper ──────────────────────────────────────────────────────

export interface PayloadValidation {
	ok: boolean;
	/** Human-readable error list (empty when ok). */
	errors: string[];
}

/** Compiled validators are cached per schema object (schemas are module-level
 *  constants, so this memoizes one JIT check per schema). */
const cache = new WeakMap<object, ReturnType<typeof Compile>>();

/** Validate `value` against a TypeBox schema. Returns {ok, errors}; never throws. */
export function validatePayload(schema: object, value: unknown): PayloadValidation {
	let check = cache.get(schema);
	if (!check) {
		check = Compile(schema as never);
		cache.set(schema, check);
	}
	if (check.Check(value as never)) return { ok: true, errors: [] };
	const errors = [...check.Errors(value as never)].map((e) => {
		const ee = e as { instancePath?: string; schemaPath?: string; message?: string };
		// TypeBox 1.3 uses JSON-Pointer-style paths; instancePath is the data
		// location (e.g. "/upstream/health_score"), schemaPath the schema location.
		const where = ee.instancePath || ee.schemaPath?.replace(/^#\//, "") || "(root)";
		return `${where}: ${ee.message}`;
	});
	return { ok: false, errors };
}

// ─── shared building blocks ─────────────────────────────────────────────────

const Trend = Type.Union([
	Type.Literal("positive"),
	Type.Literal("negative"),
	Type.Literal("mixed"),
	Type.Literal("unknown"),
]);

/** A score that may be null when the source script had no coverage
 *  (fetch_supply_chain_ecosystem.py emits null upstream/downstream health when
 *  no suppliers/customers were resolved). */
const NullableNumber = Type.Union([Type.Number(), Type.Null()]);

const EcosystemCompany = Type.Object({
	ticker: Type.String(),
	name: Type.String(),
	relationship: Type.String(),
	rev_growth_yoy: Type.Number(),
	margin_trend: Type.String(),
	stock_6m_return: Type.Number(),
	health_score: NullableNumber,
});

// ─── EcosystemHealth payload (templates/ecosystem-health.md.j2) ─────────────
/** Stage 8 (supply-chain-analyst) / Stage 4 light check. Validated against the
 *  real `supply_chain_ecosystem.json` files under ~/Documents/Stock. */

export const EcosystemHealthPayload = Type.Object({
	ticker: Type.String(),
	timestamp: Type.String(),
	upstream: Type.Object({
		companies: Type.Array(EcosystemCompany),
		health_score: NullableNumber,
		trend: Trend,
	}),
	downstream: Type.Object({
		companies: Type.Array(EcosystemCompany),
		health_score: NullableNumber,
		trend: Trend,
	}),
	ecosystem_momentum: Type.Object({
		score: NullableNumber,
		direction: Type.Union([
			Type.Literal("positive"),
			Type.Literal("negative"),
			Type.Literal("mixed"),
			Type.Literal("divergent"),
			Type.Literal("unknown"),
		]),
		convergence: Type.Boolean(),
	}),
	propagation_risks: Type.Optional(
		Type.Array(
			Type.Object({
				direction: Type.Union([Type.Literal("upstream"), Type.Literal("downstream")]),
				company: Type.String(),
				risk: Type.String(),
				severity: Type.Union([Type.Literal("HIGH"), Type.Literal("MEDIUM"), Type.Literal("LOW")]),
			}),
		),
	),
	chain_health_adjustment: Type.Number(),
	data_quality: Type.Object({
		upstream_coverage: Type.Number(),
		downstream_coverage: Type.Number(),
		confidence: Type.Union([Type.Literal("high"), Type.Literal("medium"), Type.Literal("low")]),
	}),
});

export type EcosystemHealth = Static<typeof EcosystemHealthPayload>;

// ─── EquityReport payload (templates/equity-report-long.njk) ────────────────
/** Stage 17 report-writer. Hybrid contract: structured fields for everything
 *  the validator checks (ranking rows, scores, 当前股价, disclaimer) + a
 *  `sections[]` array of {id,title,body} where the agent supplies qualitative
 *  prose (thesis, moat narrative, risks…). The template enforces structure /
 *  order / formatting; the schema enforces presence. */

const ReportSection = Type.Object({
	id: Type.String(),			     // stable id, e.g. "moat", "management"
	title: Type.String(),		     // rendered heading
	body: Type.String(),		     // markdown prose authored by the agent
});

const RankingRow = Type.Object({
	rank: Type.Number(),			 // rendered zero-padded to 001/002/003
	ticker: Type.String(),
	name: Type.String(),
	price: Type.Number(),		     // 当前股价
	reason: Type.String(),		     // one-line 推荐理由
});

const FrameworkLens = Type.Object({
	name: Type.String(),		     // Buffett / Lynch / Marks / Druckenmiller
	score: Type.Number(),		     // 0-10
	verdict: Type.String(),
});

const CatalystRow = Type.Object({
	event: Type.String(),
	date: Type.String(),
	probability: Type.Optional(Type.String()),
});

export const EquityReportPayload = Type.Object({
	horizon: Type.Union([Type.Literal("long"), Type.Literal("mid"), Type.Literal("short")]),
	company: Type.Object({
		ticker: Type.String(),
		name: Type.String(),
		name_en: Type.Optional(Type.String()),
		price: Type.Number(),
		currency: Type.Union([Type.Literal("USD"), Type.Literal("CN"), Type.Literal("HK")]),
	}),
	scores: Type.Object({
		composite: Type.Number(),		     // 1-10
		rating: Type.String(),		     // Strong Buy / Buy / Hold / Sell / Strong Sell
		conviction: Type.Optional(Type.Number()),
		components: Type.Record(Type.String(), Type.Number()), // dimension → 1-10
	}),
	executive_summary: Type.String(),
	thesis: Type.String(),
	sections: Type.Array(ReportSection),
	ranking: Type.Array(RankingRow),
	kill_switch: Type.String(),
	frameworks: Type.Optional(Type.Array(FrameworkLens)),
	disagreements: Type.Optional(Type.Array(Type.String())),
	consensus: Type.Optional(Type.String()),
	catalysts: Type.Optional(Type.Array(CatalystRow)),
	conclusion: Type.Object({
		action: Type.String(),		     // 加仓/持有/减持/规避
		target_price: Type.Optional(Type.Number()),
		upside_pct: Type.Optional(Type.Number()),
	}),
	missing: Type.Optional(Type.Array(Type.String())),  // sections with [MISSING DATA]
	mermaid: Type.Optional(Type.Record(Type.String(), Type.String())), // pre-rendered graph strings
	three_axis: Type.Optional(Type.Object({
		direction: Type.String(),
		vega: Type.String(),
		asymmetry: Type.String(),
		summary: Type.String(),
	})), // short-term only (Stage 11 options/breadth)
});

export type EquityReport = Static<typeof EquityReportPayload>;

// ─── ScreeningReport payload (templates/screening-report.njk) ───────────────
/** Stage 17 screen-mode. A sector-level screening report (NOT per-company):
 *  top sub-industries + a ranked watchlist. One report per horizon. */

const SubIndustryRow = Type.Object({
	name: Type.String(),
	score: Type.Optional(Type.Number()),
	reason: Type.String(),
	topCompanies: Type.Optional(Type.Array(Type.Object({
		ticker: Type.String(), name: Type.String(),
	}))),
});

const WatchlistRow = Type.Object({
	rank: Type.Number(),
	ticker: Type.String(),
	name: Type.String(),
	price: Type.Number(),
	currency: Type.Union([Type.Literal("USD"), Type.Literal("CN"), Type.Literal("HK")]),
	composite: Type.Optional(Type.Number()),
	subIndustry: Type.Optional(Type.String()),
	reason: Type.String(),
});

export const ScreeningReportPayload = Type.Object({
	horizon: Type.Union([Type.Literal("long"), Type.Literal("mid"), Type.Literal("short")]),
	scope: Type.Object({
		universe: Type.String(),
		theme: Type.Optional(Type.String()),
		topIndustry: Type.Optional(Type.Number()),
		days: Type.Optional(Type.Number()),
	}),
	summary: Type.String(),
	subIndustries: Type.Array(SubIndustryRow),
	watchlist: Type.Array(WatchlistRow),
	missing: Type.Optional(Type.Array(Type.String())),
});

export type ScreeningReport = Static<typeof ScreeningReportPayload>;
