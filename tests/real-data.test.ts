/**
 * Real-data validation harness. Validates the TypeBox payload schemas against
 * ACTUAL documents produced under ~/Documents/Stock/reports. Skips entirely on
 * any machine where that path is absent (hermetic for CI / other contributors).
 *
 * This is the "thorough validation against real documents" step: it proves the
 * schemas match what the scripts emit in production and surfaces real drift.
 */

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";
import { validatePayload, EcosystemHealthPayload } from "../src/render-schemas.ts";
import { renderDoc } from "../src/render.ts";

const STOCK = "/home/jenningsl/Documents/Stock/reports";
const haveData = existsSync(STOCK);

/** Recursively collect per-company JSON files whose name matches a predicate. */
function collect(match: (name: string) => boolean): string[] {
	const out: string[] = [];
	for (const run of readdirSync(STOCK)) {
		const rd = join(STOCK, run);
		let isDir = false;
		try { isDir = statSync(rd).isDirectory(); } catch { continue; }
		if (!isDir) continue;
		for (const entry of readdirSync(rd)) {
			const ep = join(rd, entry);
			let entryIsDir = false;
			try { entryIsDir = statSync(ep).isDirectory(); } catch { continue; }
			if (!entryIsDir) continue;
			for (const f of readdirSync(ep)) {
				if (f.endsWith(".json") && match(f)) out.push(join(ep, f));
			}
		}
	}
	return out;
}

describe.skipIf(!haveData)("real-data validation (~/Documents/Stock)", () => {
	it("every real supply_chain_ecosystem instance satisfies EcosystemHealthPayload", () => {
		const files = collect((f) => f.includes("supply_chain_ecosystem"));
		expect(files.length, "no real supply_chain_ecosystem files found").toBeGreaterThan(0);
		const failures: string[] = [];
		for (const f of files) {
			let data: unknown;
			try { data = JSON.parse(readFileSync(f, "utf8")); }
			catch (e) { failures.push(`${f}: parse error ${(e as Error).message}`); continue; }
			const v = validatePayload(EcosystemHealthPayload, data);
			if (!v.ok) failures.push(`${f.split("/reports/")[1]}: ${v.errors.slice(0, 4).join("; ")}`);
		}
		// Assert with a helpful message listing every failure.
		expect(failures, failures.join("\n")).toEqual([]);
	});

	it("renders a real supply_chain_ecosystem instance through the Nunjucks template", () => {
		const files = collect((f) => f.includes("supply_chain_ecosystem"));
		if (!files.length) return;
		const ROOT = join(import.meta.dirname, "..");
		const data = JSON.parse(readFileSync(files[0], "utf8"));
		const r = renderDoc({ templateName: "ecosystem-health.md.j2", payload: data, root: ROOT });
		expect(r.ok, r.error).toBe(true);
		expect(r.doc).toContain("供应链生态系统健康度:");
	});
});
