# Spec Review — pi-stock-analysis (pi Extension)

**Reviewer:** spec-reviewer (Fagan-style content inspection)
**Artifacts reviewed:** `01-requirements.md`, `02-bdd-scenarios.md`, `03-research-report.md`, `04-code-assessment.md`, `05-design.md`, `06-specification.md`, `07-implementation-plan.md`, `08-task-list.md`
**Date:** 2026-07-05
**Task type:** refactor / port (Claude Code plugin → pi extension)
**Scope:** backend-only, no UI

---

## 0. Verdict

| Verdict | **Approved with Comments** |
|---|---|
| AC coverage | 25 / 25 = **100%** (no REJECTED trigger) |
| BDD coverage | 50 / 50 scenarios addressable |
| Grounding score | **~88%** (1 HIGH defect depresses the score; see D6) |
| Critical findings | 0 |
| High findings | 1 |
| Medium findings | 5 |
| Low findings | 4 |

The specification is internally coherent, fully traceable, and architecturally sound. AC→spec and SCENARIO→spec mappings are complete and bidirectional. The single HIGH defect (a wrong filesystem path prefix propagated across three artifacts) will block Phase 2 of the implementation plan unless corrected, but it is a one-token fix and does not invalidate the design. The remaining findings are clarifications and minor under-specifications. **Recommended action:** apply the path correction and address the Medium items, then proceed to implementation.

---

## 1. Dimension Scores (1 = severe, 5 = excellent)

| # | Dimension | Score | Notes |
|---|---|:---:|---|
| D1 | **Completeness** | **5** | Every AC-01…AC-25 has a spec section (§12.1). All 50 BDD scenarios addressable. NFR-1…7 each mapped to enforcement points (§12.2). Error paths specified (validation, gate exhaustion, timeout, abort). |
| D2 | **Consistency** | **4** | One spelling drift for the (non-)dependency name (LOW). Otherwise terminology, param names, stage IDs, gate/retry/concurrency constants are uniform across all 8 artifacts and reconciled in §16. |
| D3 | **Feasibility** | **5** | Architecture is a near-verbatim port of a proven precedent (pi-super-dev). All 14 node builders cited exist in `pi-super-dev/src/nodes.ts` (verified). Stack is sufficient; no circular deps; no invented capabilities. |
| D4 | **Testability** | **3** | Hermetic suite covers structure/algebra/dispatch/arg-parse/script-shape/ticker-normalize. **Gap:** behavioral-parity ACs (AC-22 Chinese reports, AC-23 Stage-4-only filters) cannot be exercised hermetically because they live inside agent/Python execution paths the suite mocks. Numeric thresholds present where testable. |
| D5 | **Traceability** | **5** | AC→section (§12.1) and NFR→enforcement (§12.2) matrices are complete and bidirectionally checked. Task-list PHASE→AC and SCENARIO→AC chains are intact. |
| D6 | **Grounding (CRITICAL)** | **3** | Counts verified: agents=22, scripts=76, schemas=16 (all match). Node-algebra surface verified. **BUT:** the filesystem path `~/jenningsloy318/…` used to locate BOTH reference repos is wrong — they live at `~/development/personal/jenningsloy318/…`. This propagates into the implementation task-list (Phase 2 copy source). (verified/total ≈ 88%) |
| D7 | **Complexity** | **4** | File count is proportional to scope (8 src modules + 22 agents + 76 scripts + tests). Two-dial concurrency invariant (§5.3) is justified and documented. No gold-plating; YAGNI respected (loop/wait reserved but minimal). |
| D8 | **Ambiguity** | **3** | Most schemas explicit. Three under-specified spots: (a) `top5Picks(s.scoring)` helper referenced in §8.6 but never defined; (b) adversarial "≥2/3 do NOT refute" decision combinator not specified; (c) `choose(..., otherwise: cleanupOnly)` defensive default is unreachable given enum-validated `mode` — not reconciled. |

**Aggregate:** 32 / 40.

---

## 2. Findings

### HIGH

#### H1 — Wrong reference-repo path prefix (grounding; blocks Phase 2)
- **Where:** `01-requirements.md` §2.1, §2.2, §9-A1 (4 occurrences); `06-specification.md` §1.1, §1.2 (1 occurrence); `08-task-list.md` §"Copied verbatim" (1 occurrence).
- **Issue:** The spec locates both reference repos at `~/jenningsloy318/pi-super-dev` and `~/jenningsloy318/stock-analysis-plugin`. With `~` = `/home/jenningsl`, that resolves to `/home/jenningsl/jenningsloy318/…`, which **does not exist**. The actual location is `/home/jenningsl/development/personal/jenningsloy318/…`. Requirements §9-A1 even asserts these paths were "verified during requirements gathering" — they were not verified against the live filesystem.
- **Impact:** An implementer following `08-task-list.md` Phase 2 ("Copied verbatim, byte-identical, from `~/jenningsloy318/stock-analysis-plugin/`") will hit `No such file or directory` for all 22 agents, 76 scripts, 16 schemas, and the `pi-super-dev` port source — i.e., AC-12, AC-13, AC-14, and the entire ~90% reuse claim (REC-001) become unreachable.
- **Confidence:** 100% (verified by `ls`/`find`).
- **Recommendation:** Replace every `~/jenningsloy318/` with `~/development/personal/jenningsloy318/` across requirements, spec, and task-list. Alternatively, define a single `SOURCE_ROOT` / `PRECEDENT_ROOT` variable once and reference it symbolically. Re-run `ls $SOURCE_ROOT/agents/*.py | wc -l` as the verification step.

### MEDIUM

#### M2 — `top5Picks(s.scoring)` is referenced but undefined (ambiguity)
- **Where:** `06-specification.md` §8.6 (Stage 16.6 Adversarial Verify).
- **Issue:** `map({ over: s => top5Picks(s.scoring), as: "pick", … })` calls a `top5Picks` selector that is declared nowhere in `types.ts` (§7) or `helpers.ts` (§10.5). The `ScoringResult` shape (§7.2) exposes `companies: ScoredCompany[]` but no "top-5" derivation, tie-break rule, or sort key is specified.
- **Impact:** Implementer must invent the selector; "top 5 by what?" (conviction? composite score?) is a domain decision the spec leaves open. Risks divergence from source-plugin behavior (NG-7 parity bar).
- **Confidence:** 90%.
- **Recommendation:** Define `top5Picks(scoring): BestPick[]` in §10.5 with an explicit sort key + tie-break, and cite the source SKILL.md field that drives it.

#### M3 — Adversarial-verify "≥2/3 do NOT refute" combinator unspecified (ambiguity)
- **Where:** `06-specification.md` §8.6.
- **Issue:** The node composition is `parallel([skeptic1, skeptic2, skeptic3], …)` and the prose says a pick "survives if ≥ 2/3 do NOT refute." But `parallel` returns all branch `NodeResult`s — there is no specified reduction step that (a) interprets each skeptic's output as refute/not-refute and (b) emits a boolean survive decision into state. No `gate`/`branch`/`task` wraps the `parallel` to perform this reduction.
- **Impact:** The survival logic is implicit; an implementer could place it in the scorer, in a post-`parallel` task, or omit it. Behavior parity with source is at risk.
- **Confidence:** 85%.
- **Recommendation:** Specify the reduction explicitly, e.g., wrap the `parallel` in a `task(adversarialReduceStage)` that reads the three skeptic outputs, applies the ≥2/3 rule, and writes `state.adversarial[].survived`.

#### M4 — Behavioral-parity ACs (AC-22, AC-23) are not hermetically testable (testability)
- **Where:** `06-specification.md` §8.8, §13; `02-bdd-scenarios.md` SCENARIO-042, 043.
- **Issue:** AC-22 (Chinese reports) is enforced only via "every report-writer agent prompt (preamble)"; AC-23 (filters at Stage 4 only) is enforced only via prose inside `task(stage4CompanyScreening)`. The hermetic test suite (§13) mocks agents and Python, so neither rule is exercised by any test. The traceability matrix asserts coverage, but coverage is by-addressability, not by verification.
- **Impact:** A regression that translates reports to English, or that prunes companies at Stage 2, would pass `npm test` green. The "behavior parity" success bar (NG-7) is not gated by the suite.
- **Confidence:** 85%.
- **Recommendation:** Add at least one structural assertion — e.g., a `tests/agents.test.ts` that loads each report-writer agent `.md` and asserts the Chinese-language preamble token is present; and a `tests/stages.test.ts` that asserts the Stage-2/3/4 node definitions do not reference `topPrice`/`minHeadroom`/`universe` predicates. These are hermetic and would close the gap.

#### M5 — `formatSummary` status derivation may mis-classify skipped gates (correctness)
- **Where:** `06-specification.md` §4.4.
- **Issue:** `status === "success"` requires `gates.every(g => g.passed)`. In `analyze`/`compare`/`walk` modes, the 4.5 (Screening Validation) gate is skipped (§8.2). If skipped gates are recorded in `state.tracking.gateResults` with `passed: undefined`/`false`, a fully-successful analyze run could be reported as `partial`. The spec does not state whether skipped gates are omitted from `gateResults` or recorded with a sentinel.
- **Impact:** Honest-summary guarantee (SCENARIO-012, 013) is at risk for the 3 non-pipeline modes.
- **Confidence:** 80%.
- **Recommendation:** Specify that `gateResults` contains an entry only for gates that were *executed*, and that the `success` predicate is `failed.length === 0 && executedGates.every(g => g.passed) && reports.length > 0`.

#### M6 — `tests/structure.test.ts` asserts `>= 22` agents, not `=== 22` (testability)
- **Where:** `06-specification.md` §2.6, §3.2 constraints.
- **Issue:** §2.6 resolves the 21-vs-22 conflict in favor of "ship all 22" and says the test "asserts `>= 22` agents." A `>=` assertion would pass if a stray 23rd agent file were accidentally copied, defeating AC-15's exclusion discipline.
- **Confidence:** 90%.
- **Recommendation:** Assert `=== 22` with an explicit expected-name set (or assert both `=== 22` and the absence of excluded filenames).

### LOW

#### L7 — Spelling drift for the non-dependency name (consistency)
- `01-requirements.md` NFR-4.1 writes `@agab/pi-workflow`; `06-specification.md` §1.4/§3.2 writes `@agwab/pi-workflow`. Pick one and use it in the `structure.test.ts` absence assertion.

#### L8 — `choose(..., otherwise: cleanupOnly)` defensive default is unreachable (ambiguity)
- `06-specification.md` §8.1. The `mode` parameter is Typebox-enum-validated at tool-input time (§4.2), so the `otherwise` branch of the root `choose` can never fire. Not a defect, but the spec should either state "unreachable; retained for defense-in-depth" or drop it to avoid implying a real sixth path.

#### L9 — `runScript` JSON parsing "last JSON object" semantics (ambiguity)
- §9.1 step 5: "parse last JSON object from stdout via `control.ts findLastJsonObject`." Acceptable for well-formed agent output, but if a Python script emits multiple JSON blobs (e.g., progress + result), "last" is ambiguous when interleaved with non-JSON log lines. Recommend specifying the contract the Python scripts must honor (e.g., final line is the result JSON, prefixed with a sentinel).

#### L10 — `stage 11 ← 10, 12 ← 10` dependency edge (feasibility, domain)
- §8.4 wave-3 comment says sector (11) and china-market (12) depend on risk (10). Semantically unusual (sector analysis rarely depends on risk analysis), but it is consistent between requirements DD-4 and spec §8.4, so not a contradiction. Flagging only for domain sanity-check against the source SKILL.md DAG before implementation.

---

## 3. Coverage Matrices (audit results)

### 3.1 AC → Spec section (D1, D5)
All 25 ACs map to a concrete spec section per §12.1; spot-checked AC-04→§4.2, AC-10→§8, AC-16→§9, AC-22→§8.8, AC-25→§8.4/§8.8/§10.6. **No uncovered ACs.** Completeness trigger for REJECTED does not fire.

### 3.2 SCENARIO → Spec (D1)
BDD file declares SCENARIO-001…050 (75 `###` headers counted, incl. conventions/section headers; 50 numbered scenarios per the spec's invariant). Spot-check of SCENARIO-001…007 shows clean Given/When/Then + `Reference: AC-NN`. The spec's "every scenario is addressable by a design section" invariant holds.

### 3.3 Task-list → Plan → Spec (D5)
`07-implementation-plan.md` defines 7 phases as a DAG with `depends_on` / `parallelizable_with`; `08-task-list.md` carries PHASE 1…7 with per-task AC mappings and a "Coverage Roll-up" section. Chains are intact. **Exception:** Phase 2 inherits the H1 path defect — its copy source line is wrong.

---

## 4. Grounding Audit (D6)

| Claim | Verified | Evidence |
|---|:---:|---|
| Target repo is an empty git repo on `main` | ✅ | `git status` shows only untracked `docs/` |
| `pi-super-dev` exists with `package.json` | ✅ | at `~/development/personal/jenningsloy318/pi-super-dev` (NOT `~/jenningsloy318/…`) |
| `stock-analysis-plugin` exists | ✅ | at `~/development/personal/jenningsloy318/stock-analysis-plugin` (NOT `~/jenningsloy318/…`) |
| Source has 22 agent `.md` files | ✅ | `ls agents/*.md \| wc -l` = 22 |
| Source has 76 Python scripts | ✅ | `ls scripts/*.py \| wc -l` = 76 |
| Source has 16 JSON schemas | ✅ | `ls schemas/*.json \| wc -l` = 16 |
| pi-super-dev asserts `agents.length === 21` (REC-004 basis) | ✅ | `structure.test.ts:58` |
| Node builders (task/sequence/branch/choose/parallel/loop/retry/gate/map/wait/tryCatch/noop/writerTask/helperTask/gateValidator) exist in pi-super-dev | ✅ | all 15 present in `src/nodes.ts` |
| `pi` CLI available on PATH | ✅ | `/home/jenningsl/.local/share/mise/installs/node/24.15.0/bin/pi` |
| `typebox` resolvable | ⚠️ | not found under `~/.local`; relies on pi's transitive peer — confirm at install time |
| Path prefix `~/jenningsloy318/…` | ❌ | does not exist; real prefix is `~/development/personal/jenningsloy318/…` (H1) |

**Grounding score:** 11 verified / 12 claims with concrete grounding checks + the path-prefix claim failed across all 3 artifacts that cite it. Net ≈ **88%**. The skill's "<90% = HIGH finding" threshold is met by H1.

---

## 5. Anti-Pattern Check (D7)

| Anti-pattern | Present? | Notes |
|---|---|---|
| YAGNI violation | No | `loop`/`wait`/`waitForEvent` reserved, minimal; justified by "adaptive re-runs" note. |
| Premature optimization | No | Concurrency caps are inherited from source rules, not invented. |
| Untestable requirements | Partial | AC-22, AC-23 (see M4). |
| Missing error paths | No | Validation (§4.2), gate exhaustion (§5.2/§8.5), timeout (§9.1), abort (§4.2 step 6) all specified. |
| Gold-plating | No | Scope tightly bounded by NG-1…NG-7 and explicit non-copy list (AC-15). |

---

## 6. Confidence Gate

All findings above are reported at ≥80% confidence. H1, M2, M6, L7 are at 90–100%. No finding is speculative. Zero findings would be invalid here given H1.

---

## 7. Required Actions Before Implementation

1. **(Blocking) Fix H1:** correct the reference-repo path prefix in `01-requirements.md`, `06-specification.md`, and `08-task-list.md`.
2. **(Strongly recommended) M2, M3:** define `top5Picks` and specify the adversarial-verify reduction node.
3. **(Recommended) M4, M5, M6:** add structural tests for AC-22/AC-23; clarify `gateResults` semantics for skipped gates; tighten the agent-count assertion to `=== 22`.
4. **(Optional) L7–L10:** pick a dependency-name spelling, annotate the unreachable `otherwise`, specify the Python stdout contract, sanity-check the 11←10 edge.

Once item 1 is applied, the specification is implementation-ready.
