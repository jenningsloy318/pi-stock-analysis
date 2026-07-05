# BDD Behavior Scenarios — pi-stock-analysis (pi Extension)

**Feature:** `pi-stock-analysis` — self-contained pi control-flow workflow extension for unified equity research
**Task type:** refactor / port (re-implement orchestration of an existing Claude Code plugin as a pi extension)
**Author:** bdd-scenario-writer
**Status:** ready for pipeline gate review
**Requirements traceability:** scenarios map to acceptance criteria in `01-requirements.md` (AC-01 … AC-25)

---

## Conventions

- Each scenario has a stable `SCENARIO-NNN` id, a title, `Given / When / Then` steps, and an `Reference:` line citing the mapped acceptance criterion (AC-NN).
- Style is **declarative** (behavior expected, not the mechanism implementing it) and uses **business language** (domain terms a stakeholder recognizes).
- One behavior per scenario. "Golden" = happy path; "Alternative" = a valid secondary path; "Error" = a failure or invalid input the system must handle gracefully.
- Edge cases (boundaries, empty/null, mode-specific conditions) are grouped under "Edge cases".

---

## 1. Package & Manifest

### SCENARIO-001 — Package is recognized as a valid pi extension
**Type:** Golden
- **Given** the `pi-finance` repository is loaded by pi as an extension source
- **When** pi inspects the package manifest
- **Then** the package is recognized as a valid pi extension exposing the `stock_analysis` capability
- **And** the manifest declares the extension entry point and the stock-analysis skill
- **And** the package declares pi and its type system as runtime peers
- **Reference:** AC-01

### SCENARIO-002 — Package ships all required runtime assets
**Type:** Golden
- **Given** the packaged extension bundle is inspected
- **When** the set of included directories and files is enumerated
- **Then** the source code, specialist agents, skill pointer, analysis scripts, reference data, report templates, schemas, and style assets are all present
- **And** the public module entry points (extension, node algebra, runner, pipeline, manifest) are exported
- **Reference:** AC-02

### SCENARIO-003 — Repository is configured for build, type-check, and test
**Type:** Golden
- **Given** the repository is freshly cloned
- **When** a contributor runs the standard build, type-check, and test workflows
- **Then** the workflows execute using the declared TypeScript, test-runner, and ignore-file configuration
- **And** generated artifacts and local report output are excluded from version control
- **Reference:** AC-03

### SCENARIO-004 — Package name follows the pi extension convention
**Type:** Edge case
- **Given** the package is named consistently with the established pi extension family
- **When** the manifest name is read
- **Then** the name unambiguously identifies it as a stock-analysis pi extension
- **And** the repository directory name is unaffected by the published package name
- **Reference:** AC-01, OQ-1

---

## 2. Tool & Command Registration

### SCENARIO-005 — Stock analysis tool exposes the full parameter set
**Type:** Golden
- **Given** the `stock_analysis` tool is registered
- **When** its parameter contract is inspected
- **Then** it accepts the execution mode, the target tickers, the walk theme, and the screening and universe controls
- **And** the model and agent-count overrides are accepted as pass-through options
- **Reference:** AC-04

### SCENARIO-006 — Tool rejects an invalid execution mode
**Type:** Error
- **Given** a caller invokes the stock analysis tool
- **When** the requested execution mode is not one of the five supported modes
- **Then** the invocation is rejected before any stage begins
- **And** a descriptive validation message is returned
- **Reference:** AC-04

### SCENARIO-007 — Tool enforces per-mode input requirements
**Type:** Error
- **Given** a caller selects a mode that requires specific inputs
- **When** the required inputs are missing or out of range (no tickers for deep-dive, fewer than two or more than five tickers for comparison, no theme for a walk, out-of-range screening controls)
- **Then** the invocation is rejected with a message stating the unmet requirement
- **Reference:** AC-04

### SCENARIO-008 — Command resolves an explicit mode flag
**Type:** Golden
- **Given** a user issues the `/stock-analysis` command with an explicit mode selection
- **When** the command interprets the request
- **Then** the explicitly selected mode takes precedence over any other inference
- **And** the accompanying tickers, theme, and screening options are extracted from the request
- **Reference:** AC-05

### SCENARIO-009 — Command infers the mode from natural-language intent
**Type:** Alternative
- **Given** a user issues the `/stock-analysis` command without an explicit mode
- **When** the request matches a recognized intent phrase
- **Then** the command selects the mode implied by that intent
- **And** when no intent is recognized, the default pipeline mode is selected
- **Reference:** AC-05

### SCENARIO-010 — Command accepts a fully-structured request
**Type:** Edge case
- **Given** a power-user issues the `/stock-analysis` command with a structured request body
- **When** that body already conforms to the tool's parameter contract
- **Then** the structured values are used directly without further natural-language parsing
- **Reference:** AC-05, OQ-7

### SCENARIO-011 — Progress is streamed and a run log is written
**Type:** Golden
- **Given** a stock-analysis run is in progress
- **When** each stage and each per-company wave advances
- **Then** the user sees live, rolling progress describing what is running, what completed, and what was skipped
- **And** a persistent run log is written for later inspection
- **Reference:** AC-06

### SCENARIO-012 — Honest summary is returned on a partially completed run
**Type:** Error
- **Given** a run in which one or more non-fatal stages could not complete
- **When** the run finishes
- **Then** the final summary honestly reports the run as partial
- **And** the summary names the completed, skipped, and failed stages
- **Reference:** AC-06

### SCENARIO-013 — A fully successful run reports success
**Type:** Golden
- **Given** a run in which every stage completed
- **When** the run finishes
- **Then** the final summary reports the run as successful
- **And** the completed stages and produced reports are listed
- **Reference:** AC-06

---

## 3. Control-Flow Algebra & Runner

### SCENARIO-014 — The workflow offers the full set of control-flow constructs
**Type:** Golden
- **Given** the node algebra is available to the pipeline author
- **When** the set of composing constructs is enumerated
- **Then** task sequencing, conditional branching, mode selection, parallel execution, iteration, retry, validation gating, mapping over collections, waiting, and fault containment are all available
- **Reference:** AC-07

### SCENARIO-015 — The algebra has no external workflow-engine dependency
**Type:** Edge case
- **Given** the extension is installed in a clean environment
- **When** its dependencies are resolved
- **Then** no third-party workflow or orchestration engine is required
- **And** the control-flow behavior is fully self-contained within the extension
- **Reference:** AC-07, NFR-4

### SCENARIO-016 — A composed pipeline evaluates itself to completion
**Type:** Golden
- **Given** a pipeline composed as a tree of control-flow nodes
- **When** the runner is asked to execute the tree against a run state
- **Then** the nodes evaluate in their composed order, threading the run state between them
- **And** the final accumulated state and a run summary are returned
- **Reference:** AC-08

### SCENARIO-017 — Domain run-state captures stock-analysis concerns
**Type:** Golden
- **Given** the domain state model is defined
- **When** its fields are inspected
- **Then** it captures the execution mode, the run identifier, the target tickers and theme, the screening and universe controls, the per-company working set, the shared data, the produced reports, and the run tracking bookkeeping
- **Reference:** AC-09

---

## 4. Pipeline Composition

### SCENARIO-018 — Each execution mode follows its prescribed stage sequence
**Type:** Golden
- **Given** a run is started in one of the five execution modes
- **When** the mode is resolved
- **Then** the pipeline selects the exact stage sequence prescribed for that mode
- **And** stages that do not belong to the selected mode are skipped
- **Reference:** AC-10

### SCENARIO-019 — Conditional stages run only when their mode applies
**Type:** Alternative
- **Given** a mode whose definition includes optional stages (screening-only stages, the walk replacement, the A-share stage)
- **When** the pipeline reaches the decision point for such a stage
- **Then** the stage runs only when its applicability condition holds for the current run
- **And** it is otherwise skipped without error
- **Reference:** AC-10

### SCENARIO-020 — Validation gates guard the five quality checkpoints
**Type:** Golden
- **Given** the pipeline contains five validation checkpoints
- **When** the run reaches a checkpoint after data collection, after screening, after scoring, after report authoring, and after best-picks authoring
- **Then** each checkpoint validates its preceding output before allowing the dependent downstream work to proceed
- **Reference:** AC-10

### SCENARIO-021 — Per-company analysis runs as bounded-concurrency waves
**Type:** Golden
- **Given** a run with a set of selected companies to analyze in depth
- **When** the per-company stage executes
- **Then** each company is analyzed through its dependency-ordered wave sequence
- **And** companies are processed concurrently up to the configured ceiling, with new companies starting as earlier ones finish
- **Reference:** AC-10, AC-25

### SCENARIO-022 — Adversarial verification and the judge panel run concurrently
**Type:** Alternative
- **Given** the top candidate picks have been scored
- **When** the verification and judgment stages execute
- **Then** multiple perspective-diverse skeptics examine each top pick concurrently
- **And** multiple framework lenses render judgment concurrently
- **Reference:** AC-10

### SCENARIO-023 — Setup failure aborts the entire run
**Type:** Error
- **Given** a run has begun but the initial setup could not be completed
- **When** setup fails
- **Then** the run is aborted immediately with a clear message
- **And** no downstream stages are attempted
- **Reference:** AC-11

### SCENARIO-024 — Non-setup stage failure is tolerated
**Type:** Error
- **Given** a run in which a stage after setup fails
- **When** the failure is observed
- **Then** the failure is recorded in the run tracking
- **And** the run continues toward cleanup using whatever partial data is available
- **And** the run always reaches the final cleanup stage unless setup itself failed
- **Reference:** AC-11, NFR-2

---

## 5. Domain Assets

### SCENARIO-025 — Specialist agents are available with pi-compatible invocation
**Type:** Golden
- **Given** the specialist agent definitions have been brought into the extension
- **When** an agent is invoked
- **Then** the invocation uses the pi mechanism rather than the original host's mechanism
- **And** the agent's analytical framework, persona, and output contract are unchanged from the source
- **Reference:** AC-12

### SCENARIO-026 — All specialist agents are carried over
**Type:** Edge case
- **Given** the source plugin defines a full roster of specialist agents
- **When** the extension's agent roster is enumerated
- **Then** every specialist from the source is present, including any not wired into the main pipeline
- **Reference:** AC-12, OQ-2

### SCENARIO-027 — Analysis scripts are preserved unchanged
**Type:** Golden
- **Given** the source plugin contains a suite of deterministic analysis scripts and their dependency manifests
- **When** they are brought into the extension
- **Then** their contents are identical to the source
- **And** the pinned dependency manifest is preserved so reproducible execution is possible
- **Reference:** AC-13

### SCENARIO-028 — Reference data, templates, schemas, and styles are preserved
**Type:** Golden
- **Given** the source plugin ships domain reference data, report templates, data schemas, and style assets
- **When** they are brought into the extension
- **Then** they are present and identical to the source
- **Reference:** AC-14

### SCENARIO-029 — Original host's plugin machinery is excluded
**Type:** Error
- **Given** the source plugin contains host-specific manifests, generated report output, and ad-hoc scripts
- **When** the extension is assembled
- **Then** none of the host-specific manifests, generated reports, or ad-hoc scripts are carried over
- **Reference:** AC-15

---

## 6. Deterministic-Script Invocation

### SCENARIO-030 — A deterministic calculation is executed and its result returned
**Type:** Golden
- **Given** an agent requires a deterministic calculation provided by a bundled script
- **When** the calculation is requested by name with arguments
- **Then** the corresponding bundled script is executed in its managed environment
- **And** the structured result is parsed and returned to the caller
- **Reference:** AC-16

### SCENARIO-031 — A failing calculation returns a structured error, not a crash
**Type:** Error
- **Given** a requested deterministic calculation fails or times out
- **When** the failure is observed
- **Then** a structured failure result is returned describing the error and exit status
- **And** the requesting tolerant stage is able to continue without aborting the run
- **Reference:** AC-16, NFR-2

### SCENARIO-032 — Only bundled scripts may be invoked
**Type:** Edge case
- **Given** a request names a calculation outside the bundled script directory
- **When** the request is validated
- **Then** the request is rejected before any execution occurs
- **Reference:** AC-16, NFR-7

---

## 7. Supporting Modules & Skill Pointer

### SCENARIO-033 — Supporting orchestration modules are present and domain-adapted
**Type:** Golden
- **Given** the extension's supporting modules are inspected
- **When** their responsibilities are enumerated
- **Then** agent loading, agent spawning (with a selectable backend), in-process execution, control-signal extraction, deterministic helpers (including A-share ticker normalization), and prompt construction are all available
- **And** each is adapted to the stock-analysis domain rather than the original pipeline's domain
- **Reference:** AC-17

### SCENARIO-034 — The skill pointer is concise and defers to the documentation
**Type:** Golden
- **Given** the registered stock-analysis skill is inspected
- **When** its content is read
- **Then** it is a short pointer describing the command, the five modes, and the keep-script contract
- **And** it directs the reader to the architecture documentation rather than duplicating the orchestration
- **Reference:** AC-18

---

## 8. Tests & Verification

### SCENARIO-035 — The test suite is hermetic and fast
**Type:** Golden
- **Given** the test suite is run in a clean environment
- **When** the tests execute
- **Then** no external agent process is spawned, no network call is made, and no analysis script is executed
- **And** the suite completes in seconds
- **Reference:** AC-19, NFR-5

### SCENARIO-036 — The suite validates control-flow semantics
**Type:** Golden
- **Given** the suite covers the node algebra
- **When** a composed control-flow tree is exercised
- **Then** sequencing, branching, mode selection, parallelism, iteration, retry, gating, and fault containment behave as specified
- **Reference:** AC-19

### SCENARIO-037 — The suite validates mode dispatch and request parsing
**Type:** Golden
- **Given** the suite covers the command and dispatcher
- **When** each of the five modes and each request form is exercised
- **Then** the correct stage sequence is selected and the request is parsed into the expected parameters
- **And** A-share ticker normalization and the script-invocation wrapper (mocked) behave as specified
- **Reference:** AC-19

### SCENARIO-038 — The suite validates package structure and exports
**Type:** Golden
- **Given** the suite includes a structure test
- **When** the package layout is validated
- **Then** the required directories, manifest configuration, and public exports are all present and correct
- **Reference:** AC-19

### SCENARIO-039 — Type-checking and tests pass on a clean install
**Type:** Golden
- **Given** a clean install of the package
- **When** the type-check and the full test suite are run
- **Then** both complete successfully with a passing status
- **Reference:** AC-20

---

## 9. Documentation

### SCENARIO-040 — Documentation covers installation and per-mode usage
**Type:** Golden
- **Given** a new user reads the documentation
- **When** they look for how to install and how to use the extension
- **Then** installation instructions and a usage example for each of the five modes are provided
- **Reference:** AC-21

### SCENARIO-041 — Documentation explains the architecture and the Python decision
**Type:** Alternative
- **Given** a maintainer reads the documentation
- **When** they look for the architecture rationale
- **Then** a control-flow construct reference and a per-mode pipeline diagram are provided
- **And** the explicit decision to keep the analysis scripts (with the no-JavaScript-equivalent rationale) is documented
- **And** the mechanism by which agents invoke the scripts is described
- **Reference:** AC-21

---

## 10. Behavioral Parity (rules preserved from the source)

### SCENARIO-042 — Reports are authored in Chinese
**Type:** Golden
- **Given** a run produces reports
- **When** the reports are written
- **Then** their language is Chinese throughout
- **Reference:** AC-22

### SCENARIO-043 — Screening filters are applied only at the screening stage
**Type:** Golden
- **Given** a pipeline run with price, headroom, and universe constraints configured
- **When** the run progresses through the early stages
- **Then** those constraints are applied solely at the company-screening stage
- **And** earlier stages do not prune candidates on those constraints
- **Reference:** AC-23

### SCENARIO-044 — A-share analysis is mandatory for A-share tickers
**Type:** Golden
- **Given** a company whose ticker identifies it as a China A-share
- **When** the per-company stage reaches the A-share step
- **Then** the A-share analysis is performed for that company
- **Reference:** AC-24

### SCENARIO-045 — A-share analysis is skipped for non-A-share tickers
**Type:** Alternative
- **Given** a company whose ticker is not a China A-share
- **When** the per-company stage reaches the A-share step
- **Then** the A-share analysis is skipped for that company
- **And** the company otherwise proceeds through its waves
- **Reference:** AC-24

### SCENARIO-046 — Per-company concurrency is capped
**Type:** Golden
- **Given** a run analyzing many companies in depth
- **When** the per-company stage schedules work
- **Then** no more than four companies are analyzed at the same time
- **Reference:** AC-25

### SCENARIO-047 — Transient empty results are retried up to the limit
**Type:** Alternative
- **Given** an analyst produces an empty result
- **When** the retry policy evaluates the result
- **Then** the analyst is retried up to the configured attempt limit before the stage is marked failed
- **Reference:** AC-25

### SCENARIO-048 — Shared data is fetched once and reused
**Type:** Golden
- **Given** a run has collected shared market data at the data-collection stage
- **When** later stages and per-company waves need that data
- **Then** the already-collected shared data is reused
- **And** it is not re-fetched for each company
- **Reference:** AC-25

### SCENARIO-049 — The run never pauses for user input
**Type:** Golden
- **Given** a run is in progress
- **When** the pipeline advances between stages and waves
- **Then** the run proceeds without stopping to wait for user input
- **Reference:** AC-25

### SCENARIO-050 — Context is contained between waves
**Type:** Edge case
- **Given** a run progressing through the per-company waves
- **When** each analyst begins its work
- **Then** the analyst receives only the context required for its own stage
- **And** context from unrelated stages is not carried forward unnecessarily
- **Reference:** AC-25

---

## Coverage Summary

| Acceptance Criterion | Scenario(s) |
|---|---|
| AC-01 (valid pi extension manifest) | SCENARIO-001, SCENARIO-004 |
| AC-02 (files array + exports) | SCENARIO-002 |
| AC-03 (repo-root config files) | SCENARIO-003 |
| AC-04 (tool parameters + validation) | SCENARIO-005, SCENARIO-006, SCENARIO-007 |
| AC-05 (command arg parser + fallback) | SCENARIO-008, SCENARIO-009, SCENARIO-010 |
| AC-06 (progress + run log + honest summary) | SCENARIO-011, SCENARIO-012, SCENARIO-013 |
| AC-07 (node algebra constructs, no external engine) | SCENARIO-014, SCENARIO-015 |
| AC-08 (self-evaluating runner) | SCENARIO-016 |
| AC-09 (domain state shapes) | SCENARIO-017 |
| AC-10 (5-mode / 19-stage composition) | SCENARIO-018, SCENARIO-019, SCENARIO-020, SCENARIO-021, SCENARIO-022 |
| AC-11 (setup fatal, others tolerant) | SCENARIO-023, SCENARIO-024 |
| AC-12 (agents copied + adapted) | SCENARIO-025, SCENARIO-026 |
| AC-13 (scripts verbatim) | SCENARIO-027 |
| AC-14 (references/templates/schemas/assets) | SCENARIO-028 |
| AC-15 (excluded artifacts absent) | SCENARIO-029 |
| AC-16 (runScript helper) | SCENARIO-030, SCENARIO-031, SCENARIO-032 |
| AC-17 (supporting modules) | SCENARIO-033 |
| AC-18 (short skill pointer) | SCENARIO-034 |
| AC-19 (hermetic test coverage) | SCENARIO-035, SCENARIO-036, SCENARIO-037, SCENARIO-038 |
| AC-20 (typecheck + test pass) | SCENARIO-039 |
| AC-21 (README documentation) | SCENARIO-040, SCENARIO-041 |
| AC-22 (Chinese reports) | SCENARIO-042 |
| AC-23 (filters at Stage 4 only) | SCENARIO-043 |
| AC-24 (A-share mandatory/skipped) | SCENARIO-044, SCENARIO-045 |
| AC-25 (concurrency, retry, shared-data, no-pause, context) | SCENARIO-021, SCENARIO-046, SCENARIO-047, SCENARIO-048, SCENARIO-049, SCENARIO-050 |

**Every acceptance criterion (AC-01 … AC-25) is covered by at least one scenario.**
