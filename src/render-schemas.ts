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
