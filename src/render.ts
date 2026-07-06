/**
 * Deterministic document rendering: a TypeBox-validated JSON payload rendered
 * through a Nunjucks (Jinja2-syntax) template into a well-formed markdown doc.
 *
 * This replaces the prior pattern where agents hand-wrote ~54 kB of markdown
 * (→ format drift → doc-validator exhaustion). Here the agent fills a typed
 * payload (see render-schemas.ts) and the TEMPLATE owns ALL formatting, so the
 * output is correct by construction.
 *
 * Nunjucks runs in-process (no `uv` round-trip); templates live under
 * `<root>/templates/`. `throwOnUndefined: true` surfaces an under-specified
 * payload as a render error instead of silently emitting blanks.
 *
 * Filters (registered on every env): pct, fmt_price, pad001, zh_bool.
 */

import nunjucks from "nunjucks";
import { join } from "node:path";

export interface RenderOptions {
	/** Template filename under <root>/templates/, e.g. "ecosystem-health.md.j2". */
	templateName: string;
	/** The validated payload (shape must satisfy the template's variables). */
	payload: Record<string, unknown>;
	/** Package root (EXTENSION_ROOT) — templates/ is resolved under it. */
	root: string;
}

export interface RenderResult {
	ok: boolean;
	doc?: string;
	error?: string;
}

// ─── template filters (semantic formatting, locale-aware) ───────────────────

/** Format a fraction/whole as a percentage: 0.153 → "15.3%", 15.3 → "15.3%".
 *  Tolerates either convention (data sources differ). */
export function pct(n: unknown): string {
	const v = typeof n === "number" ? n : Number(n);
	if (!Number.isFinite(v)) return "N/A";
	const asPct = Math.abs(v) <= 1 ? v * 100 : v;
	return `${asPct.toFixed(1)}%`;
}

/** Format a price with a currency symbol: 123.4 → "$123.40" (or "¥123.40"). */
export function fmtPrice(v: unknown, ccy: string = "USD"): string {
	const val = typeof v === "number" ? v : Number(v);
	if (!Number.isFinite(val)) return "N/A";
	const sym = ccy === "CN" || ccy === "CNY" ? "¥" : "$";
	return `${sym}${val.toFixed(2)}`;
}

/** Zero-pad an index to 3 digits: 1 → "001" (the 推荐标的排名 format). */
export function pad001(n: unknown): string {
	const v = typeof n === "number" ? n : parseInt(String(n), 10);
	if (!Number.isFinite(v)) return "000";
	return String(v).padStart(3, "0");
}

/** Boolean → Chinese 是/否. */
export function zhBool(b: unknown): string {
	return b ? "是" : "否";
}

/** Build a fresh, self-contained Nunjucks env (no global state). */
function makeEnv(root: string): nunjucks.Environment {
	const env = new nunjucks.Environment(
		new nunjucks.FileSystemLoader(join(root, "templates"), { noCache: true }),
		{
			autoescape: false, // markdown, not HTML — never entity-escape
			throwOnUndefined: true, // missing var = render error (surfaces under-spec)
			trimBlocks: true,
			lstripBlocks: true,
		},
	);
	env.addFilter("pct", pct);
	env.addFilter("fmt_price", fmtPrice);
	env.addFilter("pad001", pad001);
	env.addFilter("zh_bool", zhBool);
	return env;
}

/** Render a payload through a template. Never throws — returns {ok, doc|error}. */
export function renderDoc(opts: RenderOptions): RenderResult {
	try {
		const doc = makeEnv(opts.root).render(opts.templateName, opts.payload);
		return { ok: true, doc };
	} catch (e) {
		return { ok: false, error: (e as Error).message };
	}
}
