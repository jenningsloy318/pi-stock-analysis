# Roadmap — Post-Port Cleanup and Improvements

Companion to `porting-review-claude-plugin-to-pi.md`. Expands Section 5
recommendations into concrete, sequenced work items with file references,
effort estimates, code sketches, and validation criteria.

Ordered by ROI. Effort estimates assume one experienced contributor.

---

## Item A — Kill the markdown-path duplication (v0.2.0 milestone)

**Impact:** ~3 000 LOC deleted. One code path instead of two. Python
round-trip removed from the default flow. Removes the largest source of
format-drift bugs.

**Effort:** 1–2 days including a real-portfolio soak test.

**Risk:** Medium. The render path is default-ON since v0.1.4; the fallback
existed as a "revert switch" while the render path was proving out. Two
real-portfolio runs completed successfully (per CHANGELOG). This item makes the
switch permanent.

### Concrete surface to remove

| File / symbol                                    | LOC   | Reason kept until now              |
| ------------------------------------------------ | ----: | ---------------------------------- |
| `scripts/validate_report.py`                     | 1 650 | Fallback markdown-path validator   |
| `templates/equity-report.md`                     |   914 | Fallback markdown-path template    |
| `templates/screening-report.md`                  |   392 | Fallback markdown-path template    |
| `src/prompts.ts::reportWriterBody`               |   ~40 | Prompt for markdown-writer agent   |
| `src/prompts.ts::bestPicksBody`                  |   ~20 | Prompt for markdown-writer agent   |
| `src/stages/index.ts::reportWriterStage`         |    ~8 | writerTask (markdown Stage 17)     |
| `src/stages/index.ts::bestPicksStage`            |    ~8 | writerTask (markdown Stage 18)     |
| `STOCK_ANALYSIS_RENDER_REPORTS !== "0"` branches |   ~15 | Two `choose`/`branch` env checks   |
| **Total**                                        | **~3 050** |                                |

### Concrete edit plan

1. In `src/stages/index.ts`:

   ```diff
   - const gateReports = gate({...}, choose(
   -   [
   -     { when: (s) => process.env.STOCK_ANALYSIS_RENDER_REPORTS !== "0" && s.mode === "screen", run: task(screenReportsRenderStage) },
   -     { when: (s) => process.env.STOCK_ANALYSIS_RENDER_REPORTS !== "0", run: task(renderReportsStage) },
   -   ],
   -   task(reportWriterStage),
   - ));
   + const gateReports = gate({...}, choose(
   +   [{ when: (s) => s.mode === "screen", run: task(screenReportsRenderStage) }],
   +   task(renderReportsStage),
   + ));

   - const gateBestPicks = gate({...}, branch(
   -   () => process.env.STOCK_ANALYSIS_RENDER_REPORTS !== "0",
   -   { yes: bestPicksRenderStage, no: task(bestPicksStage) },
   - ));
   + const gateBestPicks = gate({...}, bestPicksRenderStage);
   ```

2. Delete `reportWriterStage`, `bestPicksStage` (writerTask definitions no
   longer referenced).

3. Delete `reportWriterBody`, `bestPicksBody` from `src/prompts.ts`. Keep
   `reportPayloadBody`, `screeningReportPayloadBody`, `bestPicksPayloadBody`.

4. Delete `scripts/validate_report.py`, `templates/equity-report.md`,
   `templates/screening-report.md`.

5. Update `agents/equity-report-writer.md`: drop the `<render-mode>` toggle
   (see Item C) since PAYLOAD MODE is now the only mode. The agent's job
   collapses to "emit the JSON payload".

6. Update `docs/template-rendering-migration-plan.md` — mark Phase 2 complete.

7. Bump to `0.2.0`. This is a breaking config change — any external caller
   pinning `STOCK_ANALYSIS_RENDER_REPORTS=0` will now error harmlessly
   (unknown env var, path unaffected).

### Validation criteria (before merging)

- All 186 hermetic tests still pass.
- One real `pipeline --universe US` run completes end-to-end and produces
  identical (or better) reports vs the current 0.1.7 render path.
- One real `screen 人形机器人` run produces a Chinese-language sector report.
- No `STOCK_ANALYSIS_RENDER_REPORTS` references remain (`ffgrep`).
- `scripts/validate_report.py` fully removed (`ffgrep`).

### Blocker checklist (soak-test artifacts to review)

- `EquityReportPayload` covers every field the markdown template exposed —
  verify by rendering one long/mid/short trio and diffing section counts.
- `BestPicksPayload` covers 核心仓位 / 成长卫星 / 期权投机 grouping, 组合互补性
  check, caution notes, and the exact disclaimer.
- `ScreeningReportPayload` covers the sector-level 三横一纵 layout.

---

## Item B — Make Stage 19 (Cleanup) deterministic

**Impact:** Removes one agent spawn from the critical path. Eliminates a
non-deterministic sweep. Makes reports directory contents contractually known.

**Effort:** ~2 hours.

**Risk:** Low. Deletes only files matched by allow-list-style patterns; the
canonical outputs (`state.reports[].path`, `HIGHLIGHTS_BEST_PICKS.md`,
`workflow-tracking.json`) are explicitly preserved.

### Current state

`src/stages/index.ts::cleanupStage` (lines ~294–302):

```ts
const cleanupStage = task({
    id: "stage-19",
    label: "Stage 19 — Cleanup",
    async run(_s, ctx) {
        ctx.log("Cleanup: removing intermediate files (stage*.md, raw-data.json, phase*.md)");
        // Actual file deletion is done by the equity-report-writer / team-lead agent
        // writing to the reports dir; the TS layer just records the phase. This
        // keeps the pipeline deterministic and testable without filesystem mutation.
        return { cleanup: "recorded" };
    },
});
```

### Replacement

```ts
import { readdirSync, unlinkSync, statSync } from "node:fs";
import { basename, join, relative } from "node:path";

const KEEP_FILES = new Set(["HIGHLIGHTS_BEST_PICKS.md", "workflow-tracking.json"]);
const DELETE_PATTERNS = [
    /^stage[-.]?\d+/i,        // stage-1.md, stage_5.json, stage6-supply.md
    /^phase[-.]?\d+/i,        // phase*.md
    /^raw[-_]data\.json$/i,
    /^raw[-_]data-.*\.json$/i, // raw-data-{ticker}.json
    /^tracking\.json$/,        // legacy tracking file (workflow-tracking.json is kept)
];

const cleanupStage = task({
    id: "stage-19",
    label: "Stage 19 — Cleanup",
    async run(state, ctx) {
        const keptPaths = new Set(state.reports.map((r) => r.path));
        let removed = 0;
        // Walk state.reportsDir recursively; delete files that match DELETE_PATTERNS
        // AND are not in keptPaths / KEEP_FILES.
        function sweep(dir: string) {
            for (const name of readdirSync(dir)) {
                const full = join(dir, name);
                const st = statSync(full);
                if (st.isDirectory()) { sweep(full); continue; }
                if (keptPaths.has(full) || KEEP_FILES.has(name)) continue;
                if (DELETE_PATTERNS.some((re) => re.test(name))) {
                    try { unlinkSync(full); removed++; } catch { /* best-effort */ }
                }
            }
        }
        sweep(state.reportsDir);
        ctx.log(`Cleanup: removed ${removed} intermediate file(s)`);
        state.tracking.completed.push("stage-19");
        return { cleanup: "done", removed };
    },
});
```

### Test coverage to add

`tests/cleanup.test.ts` — creates a temp dir with a mix of files matching /
not-matching the patterns, runs `cleanupStage`, asserts the correct set
survives. Fully hermetic (no `pi` spawns, no network).

Cases:
- Files matching `DELETE_PATTERNS` are removed.
- Files listed in `state.reports[].path` are preserved even if their name
  matches (e.g. a report at `AAPL/AAPL_long.md` is kept regardless).
- `HIGHLIGHTS_BEST_PICKS.md` and `workflow-tracking.json` are always kept.
- Nested directories (per-ticker subdirs) are swept recursively.

---

## Item C — Consolidate render-mode instructions

**Impact:** Single source of truth for the payload-mode contract. Prevents
drift between agent prompt and stage prompt. Makes the agent `.md` files
authoritative for reusable behavior (e.g. loading in Claude Code) and the
`prompts.ts` bodies authoritative for run-time behavior.

**Effort:** ~1 hour. Blocked-by / paired-with Item A (payload mode becomes the
only mode after A ships).

**Risk:** Very low — pure documentation refactor.

### Current duplication

`agents/equity-report-writer.md` (lines 20–37, added in the port):

```markdown
<render-mode>
PAYLOAD MODE (opt-in, activated by STOCK_ANALYSIS_RENDER_REPORTS=1): When your
task prompt says "Emit the JSON payload" and "Do NOT write markdown", you are in
PAYLOAD MODE — the orchestrator renders the report from a Nunjucks template.
In that mode:
- Do NOT write a .md report file. Emit ONLY a <control> JSON object.
- The control object has a "report" key matching the EquityReportPayload schema
  shown in your task prompt (…)
When NOT asked for a payload, follow the markdown report steps below as before.
</render-mode>
```

The same information — schema field list, ranking rank-1 rule, kill-switch
falsifiability — appears in `src/prompts.ts::reportPayloadBody`,
`screeningReportPayloadBody`, and `bestPicksPayloadBody`.

### Resolution

After Item A ships (payload mode is the only mode):

1. Rewrite `<render-mode>` in `agents/equity-report-writer.md` to a short
   one-paragraph description of the agent's contract:

   ```markdown
   You emit a `<control>` JSON payload matching the schema in your task
   prompt. The orchestrator validates the payload and renders the report from
   a Nunjucks template. You author CONTENT (thesis, moat, risks, executive
   summary, section bodies) as markdown strings inside payload fields; the
   template owns all structural formatting (headers, 001 ranking, 当前股价
   column, Chinese disclaimer). The task prompt shows the exact schema.
   ```

2. Delete the "PAYLOAD MODE (opt-in)" wording — it's no longer opt-in.

3. Keep `reportPayloadBody` etc. as the run-time contract (they inline the
   TypeBox schema so the agent sees the exact field list per call).

### Validation

The agent `.md` describes the *role*; the prompt body describes the *task*.
After the split, changing a schema field requires editing only `prompts.ts` +
`render-schemas.ts` — never the agent `.md`.

---

## Item D — Split `helpers.ts` into helpers + gates

**Impact:** Clearer responsibility split. Gate helpers grow in count as new
content invariants are added; keeping them alongside pure math helpers muddles
what "helper" means.

**Effort:** ~1 hour. Purely a file move.

**Risk:** Very low.

### Current layout

`src/helpers.ts` (232 LOC) mixes two concerns, but the section markers already
signal the split:

- **Pure TS helpers** (lines 22–102): `isAshTicker`, `normalizeAshTicker`,
  `normalizeTickers`, `defaultTopIndustry`, `validateParams`, `clampRange`,
  `topNByScore`.
- **Gates** (lines 104–203): `requireSource`, `gateSharedData`,
  `gateScreening`, `gateScoring`, `gateReports`, `gateBestPicks` + the
  `SYNC` dispatcher.

### Move plan

1. New file `src/gates.ts`:
   ```ts
   // Move: requireSource, gateSharedData, gateScreening, gateScoring,
   //       gateReports, gateBestPicks, SYNC (rename → GATE_DISPATCH), and the
   //       validateRenderedReport / dataFreshness / forensicChecks / factCheck
   //       glue calls that currently sit in helpers.ts.
   export const GATE_DISPATCH: Record<string, (s: Record<string, unknown>) => HelperResult> = {...};
   ```

2. `src/helpers.ts` shrinks to pure helpers + a thinner `runHelper` that
   delegates gate names to `GATE_DISPATCH` from `./gates.ts`:
   ```ts
   import { GATE_DISPATCH } from "./gates.ts";
   const SYNC: Record<string, (s: Record<string, unknown>) => HelperResult> = {
       ...GATE_DISPATCH,
       // future pure-fn helpers registered here
   };
   ```

3. `src/nodes.ts::gateValidator` unchanged — it already dispatches by name.

### Test updates

Move `tests/validators.test.ts` gate-specific cases into a new
`tests/gates.test.ts`. Pure-fn cases (ticker, clampRange) stay in the existing
files.

---

## Item E — Version-bump helper

**Impact:** Prevents version drift. **Already causing drift today**:

- `package.json` → `"version": "0.1.7"`
- `skills/stock-analysis/SKILL.md` → `version: "0.1.0"` (never updated
  since bc26bc0)

Consumers reading the SKILL description will see stale version info.

**Effort:** ~30 minutes.

**Risk:** None.

### Deliverable

`scripts/bump-version.sh`:

```bash
#!/usr/bin/env bash
# Usage: scripts/bump-version.sh 0.2.0
# Bumps the version in every manifest that ships with the package + prepends
# a CHANGELOG stub. Idempotent; safe to re-run.
set -euo pipefail

NEW="${1:?usage: bump-version.sh <new-version>}"
[[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not semver: $NEW"; exit 1; }

TODAY=$(date +%Y-%m-%d)

# package.json — canonical.
npm --no-git-tag-version version "$NEW" >/dev/null

# SKILL.md front-matter — replace the `version:` line.
sed -i.bak -E "s/^version: \".*\"$/version: \"$NEW\"/" \
    skills/stock-analysis/SKILL.md
rm -f skills/stock-analysis/SKILL.md.bak

# CHANGELOG.md — prepend a stub if this version isn't already listed.
if ! grep -q "^## \[$NEW\]" CHANGELOG.md; then
    tmp=$(mktemp)
    awk -v ver="$NEW" -v today="$TODAY" '
        NR==1 && /^# Changelog/ { print; print ""; print "## [" ver "] - " today; print ""; print "### Added"; print "- "; print ""; getline nl; print nl; next }
        { print }
    ' CHANGELOG.md > "$tmp"
    mv "$tmp" CHANGELOG.md
fi

echo "Bumped to $NEW."
echo "Next: edit the CHANGELOG.md stub, commit, tag v$NEW, publish."
```

Make executable, document in `README.md` under a "Releasing" section, and use
it for the v0.2.0 release triggered by Item A.

Immediate follow-up: run `scripts/bump-version.sh 0.1.7` now to backfill
`SKILL.md`.

---

## Item F — Recorded-fixture end-to-end test

**Impact:** Closes the largest coverage gap. 186 hermetic tests cover every
piece in isolation (nodes, prompts, validators, args, rendering), but no test
exercises the full stage-graph traversal on a realistic state.

**Effort:** 3–4 hours to build; ongoing to maintain fixtures.

**Risk:** Low. Gated by env var — won't run in normal CI unless enabled.

### Design

`tests/e2e/pipeline-analyze.test.ts`:

```ts
// Enabled by E2E=1. Uses a mock agent runner that returns pre-recorded
// responses keyed by (agent, stage) — no real `pi` spawn, no network, no `uv`.

const runId = "e2e-fixture-01";
const state = buildInitialState({
    mode: "analyze",
    tickers: ["AAPL"],
    universe: "US",
}, { extensionRoot: FAKE_ROOT, cwd: TMP });

// Fixture agent: reads pre-recorded results from tests/fixtures/e2e-01/*.json
// (one file per <agent>-<stageId> spawn).
const mockAgent: (call: AgentCall) => Promise<AgentResult> = async (call) => {
    const path = `tests/fixtures/e2e-01/${call.agent}-${call.id?.replace(/^pipeline\./, "")}.json`;
    return JSON.parse(readFileSync(path, "utf8"));
};

const summary = await runWorkflow(STOCK_ANALYSIS_WORKFLOW, state, {
    cwd: TMP,
    backend: "session",   // needed so the workflow.ts backend switch takes the mock path
    // ... hook in mockAgent (requires exposing this in RunOptions — small API change)
});

expect(summary.status).toBe("success");
expect(summary.reports.length).toBeGreaterThan(0);
// Golden-file diff: compare rendered .md files against tests/fixtures/e2e-01/golden/.
```

### Prerequisite API tweak

`RunOptions` currently only accepts `backend: "session" | "subprocess"`.
Add an optional `agentRunner?: (call: AgentCall) => Promise<AgentResult>`
override; if set, `makeContext.agent()` uses it. This is a 5-line change in
`src/workflow.ts` and unlocks arbitrary mock/record/replay strategies.

### Fixture creation workflow

1. Run one real `--mode analyze AAPL` end to end.
2. Instrument `spawnAgent` to write each `AgentResult` to
   `tests/fixtures/e2e-01/<agent>-<stageId>.json` before returning.
3. Copy the rendered reports into `tests/fixtures/e2e-01/golden/`.
4. Commit fixtures; enable the test.

### CI wiring

```json
// package.json
"scripts": {
    "test": "vitest run",
    "test:e2e": "E2E=1 vitest run tests/e2e"
}
```

Nightly CI (or on release-candidate branches) runs `test:e2e` in addition to
`test`.

---

## Item G — Architecture diagram in `docs/`

**Impact:** Onboarding time drops for anyone new to the codebase. Makes
"where does Stage 8 fit?" a look, not a search.

**Effort:** 1–2 hours.

**Risk:** None.

### Deliverable

`docs/architecture.md` with three Mermaid diagrams:

1. **Node algebra** — the primitive `Node` interface and how `sequence`,
   `map`, `retry`, `gate`, `choose`, `branch`, `parallel` compose.

2. **Per-mode stage flow** — one flowchart per mode showing the actual node
   tree from `stages/index.ts`. E.g. pipeline:

   ```mermaid
   flowchart TD
       S0[Stage 0 — Setup]
       S1[Stage 1 — Data Collection]
       G1{gate-shared-data}
       S2[Stage 2 — Sub-Industry Screening]
       S4[Stage 4 — Company Screening]
       G4{gate-screening}
       MAP[map concurrency=4 over companies]
       W1[wave 1: 5·7·9·13 parallel]
       W2[wave 2: 6·8·10·14 parallel]
       W3[wave 3: 11·12 parallel]
       W4[wave 4: 15 if ash]
       S16[Stage 16 — Scoring]
       G16{gate-scoring}
       S166[16.6 Adversarial × top-5]
       S167[16.7 Judge Panel]
       G17{gate-reports}
       R17[Stage 17 render × horizons]
       S174[17.4 Critic]
       G18{gate-best-picks}
       R18[Stage 18 render best picks]
       S19[Stage 19 — Cleanup]

       S0-->S1-->G1-->S2-->S4-->G4-->MAP
       MAP-->W1-->W2-->W3-->W4
       W4-->S16-->G16-->S166-->S167-->G17-->R17-->S174-->G18-->R18-->S19
   ```

3. **Data flow** — `state` mutations per stage. Which stage writes
   `state.subIndustries`, `state.companies`, `state.scoring`, `state.reports`?
   A table is fine here; a diagram is optional.

Link from `README.md` under an "Architecture" section.

---

## Sequencing

Suggested execution order for a single-contributor push:

| Order | Item                                    | Effort  | Blocking          |
| ----: | --------------------------------------- | ------: | ----------------- |
|     1 | **E** — Version bump script + backfill  |   30 m  | None              |
|     2 | **G** — Architecture diagram            |    2 h  | None              |
|     3 | **D** — Split helpers/gates             |    1 h  | None              |
|     4 | **B** — Deterministic Stage 19          |    2 h  | None              |
|     5 | **F** — Recorded-fixture e2e            |    4 h  | Needs a real run  |
|     6 | **A** — Kill markdown path              |  1–2 d  | (F) validates it  |
|     7 | **C** — Consolidate render-mode docs   |    1 h  | Follows A         |
| **Total** |                                     | **~2.5 d** |               |

Items 1–4 are safe, immediate, low-risk. Item 5 unlocks confidence for Item 6.
Item 7 is a natural cleanup after 6 lands.

## Out-of-scope items surfaced during review

Documented separately because they need their own investigation:

- **`agents/market-daily-orchestrator.md` and `agents/team-lead-workflow.md`
  are unreferenced from `src/`.** They arrived from the port but no code
  spawns them. Either (a) wire them up as their own mode (`--mode daily`?)
  or (b) delete them. Recommend a `git log --diff-filter=A --name-only` to
  confirm they were unwired in the original too, then delete.

- **`schemas/*.json` files are not referenced from TS.** They mirror the
  TypeBox schemas in `src/render-schemas.ts` but the TS is the source of
  truth. Options: (a) delete `schemas/*.json`, (b) generate them from the
  TypeBox schemas at build time, or (c) keep them as external documentation.
  Recommend (b) — a `schemas/generate.ts` that walks the TypeBox schema
  exports and writes JSON Schema files, so external consumers can validate
  payloads without pulling in the TS runtime.
