/**
 * A-share ticker normalization tests (Stage-0 prerequisite; drives Stage 15).
 */

import { describe, it, expect } from "vitest";
import { normalizeAshTicker, isAshTicker, normalizeTickers, defaultTopIndustry, validateParams, clampRange, topNByScore } from "../src/helpers.ts";

describe("normalizeAshTicker", () => {
	it("appends .SH to bare 6-digit codes starting 60/68/90", () => {
		expect(normalizeAshTicker("600519").ticker).toBe("600519.SH");
		expect(normalizeAshTicker("688981").ticker).toBe("688981.SH");
	});
	it("appends .SZ to bare 6-digit codes starting 00/30/20", () => {
		expect(normalizeAshTicker("000001").ticker).toBe("000001.SZ");
		expect(normalizeAshTicker("300750").ticker).toBe("300750.SZ");
	});
	it("passes already-suffixed tickers through unchanged", () => {
		expect(normalizeAshTicker("600519.SH").ticker).toBe("600519.SH");
		expect(normalizeAshTicker("000001.SZ").ticker).toBe("000001.SZ");
	});
	it("passes US tickers through uppercased", () => {
		expect(normalizeAshTicker("aapl").ticker).toBe("AAPL");
		expect(normalizeAshTicker("NVDA").ticker).toBe("NVDA");
	});
	it("flags Chinese names for akshare resolution", () => {
		const r = normalizeAshTicker("贵州茅台");
		expect(r.ticker).toBe("贵州茅台");
		expect(r.needsNameResolve).toBe(true);
	});
	it("handles empty input", () => {
		expect(normalizeAshTicker("").ticker).toBe("");
	});
});

describe("isAshTicker", () => {
	it("true for .SH / .SZ suffixes", () => {
		expect(isAshTicker("600519.SH")).toBe(true);
		expect(isAshTicker("000001.SZ")).toBe(true);
	});
	it("true for bare 6-digit codes", () => {
		expect(isAshTicker("600519")).toBe(true);
	});
	it("false for US tickers", () => {
		expect(isAshTicker("AAPL")).toBe(false);
		expect(isAshTicker("NVDA")).toBe(false);
	});
});

describe("normalizeTickers", () => {
	it("normalizes a mixed list", () => {
		expect(normalizeTickers(["600519", "AAPL", "000001"])).toEqual(["600519.SH", "AAPL", "000001.SZ"]);
	});
	it("drops empties", () => {
		expect(normalizeTickers(["", "AAPL", ""])).toEqual(["AAPL"]);
	});
});

describe("defaultTopIndustry", () => {
	it("returns mode-aware defaults", () => {
		expect(defaultTopIndustry("pipeline")).toBe(8);
		expect(defaultTopIndustry("screen")).toBe(40);
		expect(defaultTopIndustry("walk")).toBe(7);
	});
});

describe("validateParams", () => {
	it("analyze requires ≥1 ticker", () => {
		expect(validateParams({ mode: "analyze", tickers: [] })).toContain("analyze mode requires at least one ticker");
		expect(validateParams({ mode: "analyze", tickers: ["AAPL"] })).toEqual([]);
	});
	it("compare requires 2-5 tickers", () => {
		expect(validateParams({ mode: "compare", tickers: ["AAPL"] }).length).toBeGreaterThan(0);
		expect(validateParams({ mode: "compare", tickers: ["A", "B", "C", "D", "E", "F"] }).length).toBeGreaterThan(0);
		expect(validateParams({ mode: "compare", tickers: ["A", "B"] })).toEqual([]);
	});
	it("walk requires a theme", () => {
		expect(validateParams({ mode: "walk" }).length).toBeGreaterThan(0);
		expect(validateParams({ mode: "walk", theme: "robotics" })).toEqual([]);
	});
	it("pipeline needs nothing special", () => {
		expect(validateParams({ mode: "pipeline" })).toEqual([]);
	});
});

describe("clampRange", () => {
	it("clamps into range", () => {
		expect(clampRange(100, 1, 50, 15)).toBe(50);
		expect(clampRange(-3, 1, 50, 15)).toBe(1);
	});
	it("uses fallback for non-numeric", () => {
		expect(clampRange("abc", 1, 50, 15)).toBe(15);
		expect(clampRange(undefined, 1, 50, 15)).toBe(15);
	});
	it("parses numeric strings", () => {
		expect(clampRange("25", 1, 50, 15)).toBe(25);
	});
});

describe("topNByScore", () => {
	it("selects top N by score descending", () => {
		const cos = [{ ticker: "A", score: 5 }, { ticker: "B", score: 9 }, { ticker: "C", score: 7 }];
		expect(topNByScore(cos, 2)).toEqual(["B", "C"]);
	});
	it("ignores companies without a score", () => {
		const cos = [{ ticker: "A" }, { ticker: "B", score: 9 }];
		expect(topNByScore(cos, 5)).toEqual(["B"]);
	});
});
