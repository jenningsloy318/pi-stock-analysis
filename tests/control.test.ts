/**
 * Control-JSON extraction tests: tolerant parsing of `<control>` blocks, fenced
 * JSON, and the last balanced `{...}` object (used by both agent output and
 * python script stdout).
 */

import { describe, it, expect } from "vitest";
import { extractControl, findLastJsonObject, parseLastJson, extractControlKeys } from "../src/control.ts";

describe("extractControl", () => {
	it("extracts a <control> JSON object", () => {
		const text = 'some text\n<control>\n{"a": 1, "b": "x"}\n</control>\nmore';
		expect(extractControl(text)).toEqual({ a: 1, b: "x" });
	});
	it("extracts a fenced ```json block", () => {
		const text = '```json\n{"foo": true}\n```';
		expect(extractControl(text)).toEqual({ foo: true });
	});
	it("falls back to the last balanced object", () => {
		const text = 'log line\n{"final": {"nested": [1, 2, 3]}}';
		expect(extractControl(text)).toEqual({ final: { nested: [1, 2, 3] } });
	});
	it("tolerates trailing commas", () => {
		const text = '<control>\n{"a": 1, "b": 2,}\n</control>';
		expect(extractControl(text)).toEqual({ a: 1, b: 2 });
	});
	it("returns null when no object is present", () => {
		expect(extractControl("just prose, no json here")).toBeNull();
	});
	it("returns null for empty input", () => {
		expect(extractControl("")).toBeNull();
	});
	it("ignores non-object JSON arrays", () => {
		expect(extractControl('<control>[1,2,3]</control>')).toBeNull();
	});
});

describe("findLastJsonObject", () => {
	it("finds the last top-level object", () => {
		expect(findLastJsonObject('x {"a":1} y {"b":2}')).toBe('{"b":2}');
	});
	it("handles nested braces", () => {
		expect(findLastJsonObject('{"a": {"c": 3}}')).toBe('{"a": {"c": 3}}');
	});
	it("handles braces inside strings", () => {
		expect(findLastJsonObject('{"a": "has } in it"}')).toBe('{"a": "has } in it"}');
	});
	it("returns null when no object exists", () => {
		expect(findLastJsonObject("no braces")).toBeNull();
	});
});

describe("parseLastJson", () => {
	it("parses the last JSON object from a noisy blob", () => {
		const stdout = "[INFO] starting\n[INFO] done\n{ \"score\": 9, \"rating\": \"BUY\" }";
		expect(parseLastJson(stdout)).toEqual({ score: 9, rating: "BUY" });
	});
	it("returns null when no JSON is present", () => {
		expect(parseLastJson("just logs")).toBeNull();
	});
});

describe("extractControlKeys", () => {
	it("parses the control-keys declaration line", () => {
		const prompt = "do work\nOutput <control> JSON with: docPath, scenarioCount, summary.";
		expect(extractControlKeys(prompt).sort()).toEqual(["docPath", "scenarioCount", "summary"]);
	});
	it("returns [] when no declaration is present", () => {
		expect(extractControlKeys("just a task")).toEqual([]);
	});
});
