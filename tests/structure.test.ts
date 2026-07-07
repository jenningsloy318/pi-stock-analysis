/**
 * Structural tests: the package is a clean, self-contained pi-package with no
 * dependency on @agwab/pi-workflow and the verbatim assets are present.
 */

import { describe, it, expect } from "vitest";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "..");
const readJson = (p: string) => JSON.parse(readFileSync(join(ROOT, p), "utf8")) as Record<string, unknown>;

describe("package.json", () => {
	it("has pi.extensions pointing to ./src/extension.ts", () => {
		const pkg = readJson("package.json");
		expect((pkg.pi as Record<string, unknown>).extensions).toContain("./src/extension.ts");
	});
	it("has pi.skills pointing to ./skills/stock-analysis", () => {
		const pkg = readJson("package.json");
		expect((pkg.pi as Record<string, unknown>).skills).toContain("./skills/stock-analysis");
	});
	it("has the pi-package keyword", () => {
		expect((readJson("package.json").keywords as string[])).toContain("pi-package");
	});
	it("is named pi-stock-analysis", () => {
		expect(readJson("package.json").name).toBe("pi-stock-analysis");
	});
	it("declares only nunjucks as a bundled runtime dependency", () => {
		const pkg = readJson("package.json");
		// nunjucks is the one approved runtime dep (the in-process TS renderer).
		// Everything else stays peer-only (provided by the pi host).
		expect(Object.keys(pkg.dependencies ?? {})).toEqual(["nunjucks"]);
		expect(pkg.bundledDependencies).toBeUndefined();
	});
	it("does NOT depend on @agwab/pi-workflow", () => {
		const pkg = readJson("package.json");
		const all = { ...(pkg.dependencies as Record<string, string> | undefined), ...(pkg.peerDependencies as Record<string, string> | undefined) };
		expect(all["@agwab/pi-workflow"]).toBeUndefined();
	});
	it("requires node >= 22.19", () => {
		const engines = (readJson("package.json").engines as { node?: string }).node ?? "";
		expect(engines).toMatch(/22\.19/);
	});
});

describe("self-contained engine structure", () => {
	it("has the control-flow node algebra", () => {
		expect(existsSync(join(ROOT, "src", "nodes.ts"))).toBe(true);
	});
	it("has the runner and pipeline composition", () => {
		expect(existsSync(join(ROOT, "src", "workflow.ts"))).toBe(true);
		expect(existsSync(join(ROOT, "src", "stages", "index.ts"))).toBe(true);
	});
	it("has the python bridge", () => {
		expect(existsSync(join(ROOT, "src", "scripts.ts"))).toBe(true);
	});
	it("spawns pi directly (the workflow-engine replacement)", () => {
		const src = readFileSync(join(ROOT, "src", "pi-spawn.ts"), "utf8");
		expect(src).toContain('"--mode"');
		expect(src).toContain('"-p"');
		expect(src).toContain("spawn");
	});
	it("registers the stock_analysis tool and /stock-analysis command", () => {
		const ext = readFileSync(join(ROOT, "src", "extension.ts"), "utf8");
		expect(ext).toMatch(/registerTool/);
		expect(ext).toContain('"stock_analysis"');
		expect(ext).toMatch(/registerCommand/);
	});
	it("has NO workflows/ directory (Claude Code Dynamic Workflow not ported)", () => {
		expect(existsSync(join(ROOT, "workflows"))).toBe(false);
	});
	it("has NO Claude/Codex plugin manifests", () => {
		expect(existsSync(join(ROOT, ".claude-plugin"))).toBe(false);
		expect(existsSync(join(ROOT, ".codex-plugin"))).toBe(false);
		expect(existsSync(join(ROOT, "plugin.json"))).toBe(false);
	});
});

describe("node algebra exports", () => {
	it("exports all control-flow nodes", () => {
		const src = readFileSync(join(ROOT, "src", "nodes.ts"), "utf8");
		for (const name of ["task", "sequence", "branch", "choose", "parallel", "loop", "retry", "gate", "map", "wait", "waitForEvent", "tryCatch", "noop"]) {
			expect(src).toContain(`export function ${name}`);
		}
	});
});

describe("verbatim assets present", () => {
	it("ships ≥ 22 specialist agent definitions", () => {
		const agents = readdirSync(join(ROOT, "agents")).filter((f) => f.endsWith(".md"));
		expect(agents.length).toBeGreaterThanOrEqual(22);
	});
	it("ships the 75 python scripts verbatim", () => {
		const scripts = readdirSync(join(ROOT, "scripts")).filter((f) => f.endsWith(".py"));
		expect(scripts.length).toBe(75);
	});
	it("ships ≥ 16 schemas", () => {
		const schemas = readdirSync(join(ROOT, "schemas")).filter((f) => f.endsWith(".json"));
		expect(schemas.length).toBeGreaterThanOrEqual(16);
	});
	it("ships references + templates + assets", () => {
		expect(existsSync(join(ROOT, "references"))).toBe(true);
		expect(existsSync(join(ROOT, "templates"))).toBe(true);
		expect(existsSync(join(ROOT, "assets"))).toBe(true);
	});
	it("ships pyproject.toml + uv.lock", () => {
		expect(existsSync(join(ROOT, "pyproject.toml"))).toBe(true);
		expect(existsSync(join(ROOT, "uv.lock"))).toBe(true);
	});
});

describe("agent preamble adaptation", () => {
	it("no agent references the old CLAUDE_PLUGIN_* variables", () => {
		const agents = readdirSync(join(ROOT, "agents")).filter((f) => f.endsWith(".md"));
		for (const a of agents) {
			const md = readFileSync(join(ROOT, "agents", a), "utf8");
			expect(md, `${a} still references CLAUDE_PLUGIN`).not.toMatch(/CLAUDE_PLUGIN_ROOT|CLAUDE_PLUGIN_DATA/);
		}
	});
});
