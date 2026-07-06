/**
 * Phase 1 #3: TS validator gates (conviction consistency, kill-switch
 * falsifiability, schema, short-term 三轴) + the gate-reports helper wired to
 * run them on render-path report payloads.
 */

import { describe, it, expect } from "vitest";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import {
	expectedRating,
	convictionConsistency,
	killSwitchFalsifiable,
	validateRenderedReport,
	dataFreshness,
	forensicChecks,
} from "../src/validators.ts";
import { runHelper } from "../src/helpers.ts";

const goodPayload = {
	horizon: "long",
	company: { ticker: "NVDA", name: "NVIDIA", price: 128.5, currency: "USD" },
	scores: { composite: 9, rating: "Strong Buy", components: { moat: 9, financials: 8 } },
	executive_summary: "Dominant AI compute platform.",
	thesis: "Structural AI demand super-cycle.",
	sections: [{ id: "moat", title: "Moat", body: "CUDA lock-in." }],
	ranking: [{ rank: 1, ticker: "NVDA", name: "NVIDIA", price: 128.5, reason: "AI compute monopoly" }],
	kill_switch: "If data-center GPU revenue declines >20% QoQ for two consecutive quarters, re-evaluate.",
	conclusion: { action: "加仓" },
};

describe("expectedRating (ported RATING_BRACKETS)", () => {
	it("maps composite → rating bracket", () => {
		expect(expectedRating(9.5)).toBe("Strong Buy");
		expect(expectedRating(8)).toBe("Buy");
		expect(expectedRating(6)).toBe("Hold / Accumulate");
		expect(expectedRating(4)).toBe("Hold / Reduce");
		expect(expectedRating(2)).toBe("Sell");
		expect(expectedRating(1)).toBe("Strong Sell");
	});
});

describe("convictionConsistency", () => {
	it("passes a coherent payload", () => {
		expect(convictionConsistency(goodPayload).ok).toBe(true);
	});
	it("flags a rating inconsistent with the composite", () => {
		const v = convictionConsistency({ ...goodPayload, scores: { composite: 5, rating: "Strong Buy", components: {} } });
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/inconsistent/);
	});
	it("flags composite ≥6 when any component ≤3 (override rule)", () => {
		const v = convictionConsistency({ ...goodPayload, scores: { composite: 7, rating: "Buy", components: { risk: 2 } } });
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/≤3|override/);
	});
	it("flags an out-of-range composite", () => {
		const v = convictionConsistency({ scores: { composite: 15, rating: "Strong Buy", components: {} } });
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/out of 1-10/);
	});
});

describe("killSwitchFalsifiable", () => {
	it("passes a specific, quantifiable kill switch", () => {
		expect(killSwitchFalsifiable(goodPayload.kill_switch).ok).toBe(true);
	});
	it("rejects a short / missing kill switch", () => {
		expect(killSwitchFalsifiable("monitor it").ok).toBe(false);
	});
	it("rejects a kill switch with no quantifiable trigger", () => {
		expect(killSwitchFalsifiable("Re-evaluate if risks materialize and conditions change over time").ok).toBe(false);
	});
});

describe("validateRenderedReport (full per-report gate)", () => {
	it("passes a valid long-term payload", () => {
		expect(validateRenderedReport(goodPayload).ok).toBe(true);
	});
	it("fails a short-term payload missing three_axis", () => {
		const v = validateRenderedReport({ ...goodPayload, horizon: "short" });
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/three_axis/);
	});
	it("passes a short-term payload with three_axis", () => {
		const v = validateRenderedReport({ ...goodPayload, horizon: "short", three_axis: { direction: "Bull", vega: "Long", asymmetry: "2:1", summary: "ok" } });
		expect(v.ok).toBe(true);
	});
	it("fails on schema violation", () => {
		const v = validateRenderedReport({ horizon: "long" });
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/schema/);
	});
});

describe("gate-reports helper (render path)", () => {
	it("passes when every report payload validates", async () => {
		const r = await runHelper({ name: "gate-reports", sources: { "stage-17": { reports: [
			{ ticker: "NVDA", horizon: "long", payload: goodPayload },
		] } } });
		expect(r.value.pass).toBe(true);
	});
	it("fails when a report payload fails a content gate", async () => {
		const bad = { ...goodPayload, scores: { composite: 5, rating: "Strong Buy", components: {} } };
		const r = await runHelper({ name: "gate-reports", sources: { "stage-17": { reports: [
			{ ticker: "NVDA", horizon: "long", payload: bad },
		] } } });
		expect(r.value.pass).toBe(false);
		expect((r.value.errors as string[]).join(" ")).toMatch(/inconsistent/);
	});
	it("passes the markdown path (no payloads) on a non-empty reports list", async () => {
		const r = await runHelper({ name: "gate-reports", sources: { "stage-17": { reports: [
			{ path: "/tmp/x.md" },
		] } } });
		expect(r.value.pass).toBe(true);
	});
	it("fails when no reports were generated", async () => {
		const r = await runHelper({ name: "gate-reports", sources: { "stage-17": { reports: [] } } });
		expect(r.value.pass).toBe(false);
	});
});

describe("dataFreshness (ported gate_data_freshness)", () => {
	it("passes a dir of fresh files", () => {
		const dir = "/tmp/pi-stock-fresh";
		rmSync(dir, { recursive: true, force: true });
		mkdirSync(dir, { recursive: true });
		const now = new Date().toISOString();
		writeFileSync(`${dir}/a.json`, JSON.stringify({ retrieved_at: now }));
		writeFileSync(`${dir}/b.json`, JSON.stringify({ computed_at: now }));
		expect(dataFreshness(dir).ok).toBe(true);
	});
	it("fails when a majority of timestamped files are stale", () => {
		const dir = "/tmp/pi-stock-stale";
		rmSync(dir, { recursive: true, force: true });
		mkdirSync(dir, { recursive: true });
		const stale = new Date(Date.now() - 30 * 86_400_000).toISOString(); // 30d ago
		writeFileSync(`${dir}/a.json`, JSON.stringify({ retrieved_at: stale }));
		writeFileSync(`${dir}/b.json`, JSON.stringify({ retrieved_at: stale }));
		writeFileSync(`${dir}/c.json`, JSON.stringify({ retrieved_at: stale }));
		const v = dataFreshness(dir, { maxDays: 14 });
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/>\d+d|stale|old/);
	});
	it("skips a missing dir (best-effort)", () => {
		expect(dataFreshness("/nonexistent-dir-xyz-456").ok).toBe(true);
	});
	it("ignores files with no timestamp", () => {
		const dir = "/tmp/pi-stock-nots";
		rmSync(dir, { recursive: true, force: true });
		mkdirSync(dir, { recursive: true });
		writeFileSync(`${dir}/a.json`, JSON.stringify({ foo: 1 }));
		expect(dataFreshness(dir).ok).toBe(true);
	});
});

describe("forensicChecks (ported gate_forensic_checks)", () => {
	it("passes when Beneish/Altman/Piotroski are all present", () => {
		const dir = "/tmp/pi-stock-forensic-ok";
		rmSync(dir, { recursive: true, force: true });
		mkdirSync(dir, { recursive: true });
		writeFileSync(`${dir}/metrics.json`, JSON.stringify({ beneish_mscore: { mscore: -2.5 }, altman_zscore: { zscore: 3.2 }, piotroski_fscore: { fscore: 7 } }));
		expect(forensicChecks(dir).ok).toBe(true);
	});
	it("fails when a score is absent", () => {
		const dir = "/tmp/pi-stock-forensic-miss";
		rmSync(dir, { recursive: true, force: true });
		mkdirSync(dir, { recursive: true });
		writeFileSync(`${dir}/metrics.json`, JSON.stringify({ beneish_mscore: { mscore: -2.5 } }));
		const v = forensicChecks(dir);
		expect(v.ok).toBe(false);
		expect(v.errors.join(" ")).toMatch(/Altman|Piotroski/);
	});
	it("skips when metrics.json is absent", () => {
		expect(forensicChecks("/nonexistent-forensic-xyz-789").ok).toBe(true);
	});
});
