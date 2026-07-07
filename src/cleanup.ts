/**
 * Stage 19 — deterministic cleanup of intermediate pipeline artifacts.
 *
 * Replaces the old "agent sweeps its own dir" approach with an allow-list sweep:
 * the TS layer walks `state.reportsDir` and deletes files whose names match
 * known intermediate-artifact patterns, while preserving final reports and
 * bookkeeping files. This makes Stage 19's effect contractually known and
 * testable without any agent spawn.
 *
 * Safety model (defense in depth):
 *   1. DELETE_PATTERNS only match `stage*` / `phase*` / `raw-data*` names — a
 *      final report named `AAPL_long.md` never matches.
 *   2. KEEP_FILES is a basename allow-list (`HIGHLIGHTS_BEST_PICKS.md`,
 *      `workflow-tracking.json`) preserved even if a pattern somehow matched.
 *   3. keepPaths is an absolute-path allow-list built from
 *      `state.reports[].path` — the canonical final outputs, preserved
 *      unconditionally.
 *   4. Directories are never deleted; the sweep is file-only and recursive.
 */

import { readdirSync, unlinkSync, statSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

/** Basenames always preserved, regardless of pattern match. */
export const KEEP_FILES = new Set([
	"HIGHLIGHTS_BEST_PICKS.md",
	"workflow-tracking.json",
]);

/** Name patterns for intermediate artifacts that should be swept.
 *  Matched against the basename (case-insensitive). */
export const DELETE_PATTERNS: readonly RegExp[] = [
	/^stage[-_.]?\d/i, // stage-1.md, stage_5.json, stage-16.6.md, stage5-supply.md
	/^phase[-_.]?\d/i, // phase-1.md, phase_2.md
	/^raw[-_]data/i, // raw-data.json, raw_data-AAPL.json
];

export interface SweepResult {
	/** Absolute paths of files removed. */
	removed: string[];
	/** Absolute paths of files preserved (for diagnostics). */
	kept: string[];
}

/**
 * Walk `dir` recursively; delete files whose basename matches a DELETE_PATTERN,
 * unless the file is in `keepPaths` (by absolute path) or `KEEP_FILES` (by
 * basename). Directories are traversed but never removed. Unreadable/unlinkable
 * files are skipped (best-effort).
 *
 * All path comparisons use absolute paths (resolved against `process.cwd()`),
 * so callers may pass relative or absolute paths interchangeably.
 */
export function sweepIntermediateFiles(
	dir: string,
	keepPaths: Iterable<string> = [],
): SweepResult {
	const removed: string[] = [];
	const kept: string[] = [];
	if (!existsSync(dir)) return { removed, kept };

	const keep = new Set([...keepPaths].map((p) => resolve(p)));

	function walk(d: string): void {
		let entries: string[];
		try {
			entries = readdirSync(d);
		} catch {
			return; // unreadable dir — skip
		}
		for (const name of entries) {
			const full = join(d, name);
			let st;
			try {
				st = statSync(full);
			} catch {
				continue; // stat failed — skip
			}
			if (st.isDirectory()) {
				walk(full);
				continue;
			}
			// Safety nets first: explicit keep-list always wins.
			if (keep.has(resolve(full)) || KEEP_FILES.has(name)) {
				kept.push(full);
				continue;
			}
			if (DELETE_PATTERNS.some((re) => re.test(name))) {
				try {
					unlinkSync(full);
					removed.push(full);
				} catch {
					kept.push(full); // unlink failed (permissions?) — leave it
				}
			} else {
				kept.push(full);
			}
		}
	}

	walk(resolve(dir));
	return { removed, kept };
}
