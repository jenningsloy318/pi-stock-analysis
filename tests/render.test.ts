/**
 * render.ts (Nunjucks) + render-schemas.ts (TypeBox) — hermetic engine proof.
 * Real-data validation lives in the separate `validate-real-data` exploration
 * (see docs/template-rendering-migration-plan.md).
 */

import { describe, it, expect } from "vitest";
import { join } from "node:path";
import { renderDoc, pct, pad001, fmtPrice, zhBool } from "../src/render.ts";
import { validatePayload, EcosystemHealthPayload } from "../src/render-schemas.ts";

const ROOT = join(import.meta.dirname, "..");

/** A realistic EcosystemHealth payload (matches templates/ecosystem-health.md.j2). */
const samplePayload = {
	ticker: "NVDA",
	timestamp: "2026-07-05",
	upstream: {
		companies: [{
			ticker: "TSM", name: "TSMC", relationship: "foundry",
			rev_growth_yoy: 0.21, margin_trend: "expanding", stock_6m_return: 0.34, health_score: 9,
		}],
		health_score: 8,
		trend: "positive",
	},
	downstream: {
		companies: [{
			ticker: "MSFT", name: "Microsoft", relationship: "hyperscaler customer",
			rev_growth_yoy: 0.18, margin_trend: "stable", stock_6m_return: 0.22, health_score: 9,
		}],
		health_score: 8,
		trend: "positive",
	},
	ecosystem_momentum: { score: 8, direction: "positive", convergence: true },
	propagation_risks: [{ direction: "upstream", company: "TSMC", risk: "single-foundry concentration", severity: "MEDIUM" }],
	chain_health_adjustment: 0.08,
	data_quality: { upstream_coverage: 1, downstream_coverage: 1, confidence: "high" },
};

describe("renderDoc (Nunjucks engine)", () => {
	it("renders ecosystem-health from a valid payload with canonical formatting", () => {
		const v = validatePayload(EcosystemHealthPayload, samplePayload);
		expect(v.ok).toBe(true);
		const r = renderDoc({ templateName: "ecosystem-health.md.j2", payload: samplePayload, root: ROOT });
		expect(r.ok).toBe(true);
		expect(r.doc).toBeTruthy();
		const doc = r.doc!;
		expect(doc).toContain("供应链生态系统健康度: NVDA"); // title
		expect(doc).toContain("TSMC"); // upstream company rendered
		expect(doc).toContain("21.0%"); // pct filter on rev_growth_yoy 0.21
		expect(doc).toContain("8/10"); // health scores (Nunjucks: {{ score }}/10)
		expect(doc).toContain("是"); // convergence inline if → 是
		expect(doc).toContain("single-foundry concentration"); // propagation risk row
	});

	it("returns ok:false (never throws) when a required variable is missing", () => {
		const r = renderDoc({ templateName: "ecosystem-health.md.j2", payload: { ticker: "X" }, root: ROOT });
		expect(r.ok).toBe(false);
		expect(r.error).toBeTruthy(); // throwOnUndefined surfaced the missing var
	});

	it("renders the divergent-direction branch", () => {
		const r = renderDoc({
			templateName: "ecosystem-health.md.j2",
			payload: { ...samplePayload, ecosystem_momentum: { score: 5, direction: "divergent", convergence: false } },
			root: ROOT,
		});
		expect(r.ok).toBe(true);
		expect(r.doc).toContain("生态系统分化"); // the divergent branch
	});
});

describe("filters", () => {
	it("pct tolerates decimal (0.153) and whole (15.3)", () => {
		expect(pct(0.153)).toBe("15.3%");
		expect(pct(15.3)).toBe("15.3%");
		expect(pct("x")).toBe("N/A");
	});
	it("pad001 zero-pads to 3 digits", () => {
		expect(pad001(1)).toBe("001");
		expect(pad001(12)).toBe("012");
		expect(pad001("3")).toBe("003");
	});
	it("fmtPrice uses $ or ¥ by currency", () => {
		expect(fmtPrice(123.4)).toBe("$123.40");
		expect(fmtPrice(123.4, "CN")).toBe("¥123.40");
	});
	it("zhBool → 是/否", () => {
		expect(zhBool(true)).toBe("是");
		expect(zhBool(false)).toBe("否");
	});
});

describe("validatePayload (TypeBox)", () => {
	it("accepts the sample payload", () => {
		expect(validatePayload(EcosystemHealthPayload, samplePayload).ok).toBe(true);
	});
	it("rejects a payload missing a required field, with path-tagged errors", () => {
		const v = validatePayload(EcosystemHealthPayload, { ticker: "X" });
		expect(v.ok).toBe(false);
		expect(v.errors.length).toBeGreaterThan(0);
		expect(v.errors.some((e) => e.includes("upstream") || e.includes("ecosystem_momentum"))).toBe(true);
	});
	it("rejects a wrong-type field", () => {
		const bad = { ...samplePayload, upstream: { ...samplePayload.upstream, health_score: "eight" } };
		const v = validatePayload(EcosystemHealthPayload, bad);
		expect(v.ok).toBe(false);
		expect(v.errors.some((e) => e.includes("health_score"))).toBe(true);
	});
});
