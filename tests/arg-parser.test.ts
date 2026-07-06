/**
 * /stock-analysis arg-parser tests: flag forms, JSON escape hatch,
 * trigger-phrase fallback, positional extraction per mode.
 */

import { describe, it, expect } from "vitest";
import { parseStockAnalysisArgs, parseFlags, inferMode, extractTickers, tokenize } from "../src/args.ts";

describe("tokenize", () => {
	it("splits on whitespace", () => {
		expect(tokenize("a b c")).toEqual(["a", "b", "c"]);
	});
	it("respects double-quoted phrases", () => {
		expect(tokenize('--mode walk "humanoid robotics"')).toEqual(["--mode", "walk", "humanoid robotics"]);
	});
	it("respects single-quoted phrases", () => {
		expect(tokenize("--mode walk 'rare earth'")).toEqual(["--mode", "walk", "rare earth"]);
	});
});

describe("parseFlags", () => {
	it("parses --key value pairs", () => {
		expect(parseFlags(["--top-industry", "40", "--days", "5"])).toEqual({
			flags: { topIndustry: "40", days: "5" },
			positional: [],
		});
	});
	it("parses --key=value form", () => {
		expect(parseFlags(["--universe=CN"]).flags).toEqual({ universe: "CN" });
	});
	it("collects non-flag tokens as positional", () => {
		expect(parseFlags(["AAPL", "--mode", "analyze", "MSFT"]).positional).toEqual(["AAPL", "MSFT"]);
	});
});

describe("inferMode", () => {
	it("walk trigger phrases", () => {
		expect(inferMode("walk the chain for humanoid robotics").mode).toBe("walk");
		expect(inferMode("瓶颈分析 人形机器人").mode).toBe("walk");
	});
	it("compare trigger phrases", () => {
		expect(inferMode("NVDA vs AMD").mode).toBe("compare");
		expect(inferMode("compare NVDA and AMD").mode).toBe("compare");
	});
	it("analyze trigger phrases", () => {
		expect(inferMode("deep dive AAPL").mode).toBe("analyze");
		expect(inferMode("valuation of TSLA").mode).toBe("analyze");
	});
	it("screen trigger phrases", () => {
		expect(inferMode("screen sectors").mode).toBe("screen");
		expect(inferMode("best industries").mode).toBe("screen");
	});
	it("defaults to pipeline", () => {
		expect(inferMode("find best stocks").mode).toBe("pipeline");
		expect(inferMode("anything else").mode).toBe("pipeline");
	});
});

describe("extractTickers", () => {
	it("extracts uppercase tickers", () => {
		expect(extractTickers("analyze AAPL and MSFT")).toEqual(["AAPL", "MSFT"]);
	});
	it("extracts suffixed and 6-digit tickers", () => {
		expect(extractTickers("compare 600519.SH and AAPL")).toEqual(["600519.SH", "AAPL"]);
	});
});

describe("parseStockAnalysisArgs", () => {
	it("--mode analyze with positional tickers", () => {
		const r = parseStockAnalysisArgs("--mode analyze AAPL MSFT");
		expect(r.mode).toBe("analyze");
		expect(r.tickers).toEqual(["AAPL", "MSFT"]);
	});
	it("--mode compare with comma list", () => {
		const r = parseStockAnalysisArgs("--mode compare NVDA,AMD,INTC");
		expect(r.mode).toBe("compare");
		expect(r.tickers).toEqual(["NVDA", "AMD", "INTC"]);
	});
	it("--mode walk with quoted theme", () => {
		const r = parseStockAnalysisArgs('--mode walk "humanoid robotics"');
		expect(r.mode).toBe("walk");
		expect(r.theme).toBe("humanoid robotics");
	});
	it("--mode screen with options", () => {
		const r = parseStockAnalysisArgs("--mode screen --top-industry 40 --days 5");
		expect(r.mode).toBe("screen");
		expect(r.topIndustry).toBe(40);
		expect(r.days).toBe(5);
	});
	it("universe flag", () => {
		const r = parseStockAnalysisArgs("--mode pipeline --universe CN");
		expect(r.universe).toBe("CN");
	});
	it("trigger-phrase fallback when no --mode", () => {
		const r = parseStockAnalysisArgs("deep dive AAPL");
		expect(r.mode).toBe("analyze");
		expect(r.tickers).toEqual(["AAPL"]);
	});
	it("defaults to pipeline for bare requests", () => {
		const r = parseStockAnalysisArgs("find best stocks");
		expect(r.mode).toBe("pipeline");
	});
	it("JSON escape hatch", () => {
		const r = parseStockAnalysisArgs('{"mode":"analyze","tickers":["AAPL"]}');
		expect(r.mode).toBe("analyze");
		expect(r.tickers).toEqual(["AAPL"]);
	});
	it("preserves the original query for logging", () => {
		const r = parseStockAnalysisArgs("analyze AAPL");
		expect(r.query).toContain("analyze AAPL");
	});
	it("empty input → pipeline", () => {
		expect(parseStockAnalysisArgs("").mode).toBe("pipeline");
	});
});

describe("theme capture (regression: theme must reach screen/pipeline, not be dropped)", () => {
	it("--mode screen <theme> captures the theme (the 2026-07-05 bug)", () => {
		const r = parseStockAnalysisArgs("--mode screen 人形机器人");
		expect(r.mode).toBe("screen");
		expect(r.theme).toBe("人形机器人");
	});
	it("--mode screen with no positional → broad screen (no theme)", () => {
		const r = parseStockAnalysisArgs("--mode screen --top-industry 40");
		expect(r.mode).toBe("screen");
		expect(r.theme).toBeUndefined();
	});
	it("--mode pipeline <theme> captures the theme (narrows the pipeline)", () => {
		const r = parseStockAnalysisArgs("--mode pipeline AI chips");
		expect(r.mode).toBe("pipeline");
		expect(r.theme).toBe("AI chips");
	});
	it("inferMode: bare descriptive theme → pipeline narrowed to it", () => {
		const r = inferMode("人形机器人");
		expect(r.mode).toBe("pipeline");
		expect(r.theme).toBe("人形机器人");
	});
	it("inferMode: 'screen <theme>' → screen narrowed to the theme", () => {
		const r = inferMode("screen EV battery");
		expect(r.mode).toBe("screen");
		expect(r.theme).toBe("EV battery");
	});
	it("inferMode: 'screen' alone → broad screen (no theme)", () => {
		const r = inferMode("screen sectors");
		expect(r.mode).toBe("screen");
	});
	it("inferMode: broad pipeline trigger stays unfiltered (no theme)", () => {
		const r = inferMode("find best stocks");
		expect(r.mode).toBe("pipeline");
		expect(r.theme).toBeUndefined();
	});
});
