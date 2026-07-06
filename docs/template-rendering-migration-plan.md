# Plan: Schema-driven, template-rendered stage documents

**Status:** Proposal — awaiting decision on engine + phase order
**Goal:** Replace agent-freeform documents (messy → validator fails → gate
exhaustion) with a deterministic **data payload (schema-validated) + template
→ rendered document** pipeline. Formatting becomes correct *by construction*;
the doc validator checks reliable JSON payloads instead of fragile markdown
parsing.

---

## 1. Current state (precise diagnosis)

### What exists
| Asset | Count | Role today |
|---|---|---|
| `templates/equity-report.md` | 54 kB | Plain-markdown **structural instructions** the agent reads then mimics by hand (Long/Mid/Short, 24 sections). **Not a render template.** |
| `templates/screening-report.md` | 20 kB | Same pattern (Broad/Focused/Thematic). |
| `templates/ecosystem-health.md.j2`, `industry-trajectory.md.j2` | 3–4 kB | **Real Jinja2 render templates** (`{{ ticker }}`, `{% if %}`, schema ref in header). |
| `templates/company-status.json`, `workflow-tracking.json` | — | JSON structures. |
| `schemas/*.json` | 16 | JSON-Schema (draft 2020-12) describing **stage-result metadata** (e.g. `report-result.json` = `{ticker, horizon, file_path, sections_written, validation_passed}`) — **not** the rich content needed to render a full report. |
| `scripts/validate_report.py` | — | Deterministic gates: `data_freshness`, `source_coverage`, `conviction_consistency`, `forensic_checks`, `kill_switch`, `fact_check`, `three_axis_check`. |

### The bug this solves
- **No render script exists** (`grep jinja/Template/render scripts/*.py` → nothing). Even the `.j2` templates are hand-filled by agents today.
- Agents try to reproduce 54 kB of template structure + dozens of formatting
  rules (当前股价 column, `001/002/003` ranking, exact disclaimer text,
  mandatory 三轴结构 section) **by hand** → inconsistent → `validate_report.py`'s
  **markdown-format gates** fail → gate retries 4× → 8-min agent timeouts →
  `EXHAUSTED (non-fatal)`. This is the recurring "doc format is messy, validator
  can't work" pain.
- The validator's *content* gates (freshness, conviction consistency,
  fact-check) already run on JSON files and are reliable. Only the
  **format-parse** gates are fragile.

---

## 2. Target architecture

```
┌────────────┐   schema     ┌─────────────┐  render   ┌──────────┐
│  agent     │ ───────────▶ │ JSON payload│ ────────▶ │  .md doc │
│ (fills     │  (TypeBox    │ (validated) │ (Nunjucks)│ (always  │
│  payload)  │   validate)  │             │           │  well-   │
└────────────┘              └──────┬──────┘           │  formed) │
                                   │                  └──────────┘
                                   │ also feeds
                                   ▼
                          ┌─────────────────┐
                          │ doc validator    │  ← checks payload schema +
                          │ (gate-*)         │     JSON content gates;
                          │                  │     format gates become moot
                          └─────────────────┘
```

**Principle:** the agent's job changes from *"write 54 kB of markdown"* to
*"fill this typed JSON payload."* The template + renderer own all formatting.

---

## 3. Engine & schema choices (decision needed)

### Template engine — recommendation: **Nunjucks** (TS, in-process)
| Option | Syntax | Runtime | Reuse `.j2`? | Verdict |
|---|---|---|---|---|
| **Nunjucks** | Jinja2 (`{{ }}`, `{% %}`) | **JS/TS, in-process** | ✅ verbatim | **Recommended** — Jinja2 expressiveness + TS runtime; existing `.j2` work as-is; no `uv` round-trip. |
| Jinja2 (Python) | Jinja2 | `uv run render.py` | ✅ verbatim | OK fallback — reuses `scripts.ts` bridge, but adds a subprocess per render and keeps rendering outside TS. |
| Handlebars | `{{#each}}`, logic-less | JS/TS | ❌ (port) | Clean but logic-less → needs helpers for the conditional/section logic these reports need. |
| eta / EJS | `<% %>` JS-in-template | JS/TS | ❌ (port) | Powerful but less maintainable for non-engineers editing templates. |

**Why Nunjucks over Python-Jinja2:** the user asked to lean on TS; rendering
happens in the orchestrator (no Python round-trip), TypeBox validation and
rendering share one process, and the existing Jinja2-syntax templates port
zero-effort. Dep: `nunjucks` (~1 small pure-JS package).

### Schemas — **TypeBox** (already a peer dep)
- Define a **content payload schema** per document (e.g. `EquityReportPayload`)
  in `src/render-schemas.ts` using TypeBox → compile to JSON Schema →
  (a) validate the agent's emitted payload, (b) feed the renderer, (c) serve as
  the agent's data contract (the prompt shows the schema).
- The existing `schemas/*.json` (stage-result metadata) stay as-is; the new
  TypeBox schemas are the **render-content** contracts (a new layer).

---

## 4. The build (new TS modules)

| Module | Responsibility |
|---|---|
| `src/render.ts` | `renderDoc(templateName, payload, root): string` — loads `templates/<name>.njk`, renders with Nunjucks (sandboxed, strict-on-missing). Helpers: `fmt price`, `pad001`, `mermaid` passthrough, i18n zh/en. |
| `src/render-schemas.ts` | TypeBox schemas per doc (`EquityReportPayload`, `ScreeningReportPayload`, `EcosystemHealthPayload`, …). `compile()` → JSON Schema for the agent prompt. |
| `src/nodes.ts` → `renderDocNode` | New control-flow node: runs the writer agent to produce a `<control>` JSON payload, validates against the TypeBox schema, renders the template, writes the `.md`. Retry-on-schema-error (reuses existing `retry`). |
| `src/prompts.ts` | Writer-stage bodies change: *"Emit `<control>` JSON matching this schema: … Do NOT write markdown."* Embeds the compiled JSON Schema. |

Rendered output path is unchanged (`reports/<run_id>/…/<ticker>_<horizon>.md`),
so downstream agents/validators are unaffected.

---

## 5. What each agent's job becomes

**Before:** "Read `equity-report.md` (54 kB) in FULL. Write all 3 horizons,
24 sections each, 当前股价 column, `001/002/003` ranking, exact disclaimer,
三轴结构 section, embed Mermaid…" *(agent reproduces by hand → drift)*

**After:** "Fill this payload (`EquityReportPayload`):
`{ ticker, horizon, price, scores:{composite,rating,…}, thesis_long,
ranking:[{rank,ticker,name,price,…}], sections:[{id,title,body}],
mermaid:{revenue_fcf_trend: '<graph>'}, kill_switch, missing:[]}`.
Emit `<control>` JSON. The renderer applies formatting." *(agent reasons about
content; formatting is deterministic)*

---

## 6. Validator evolution

| Gate | Today | After |
|---|---|---|
| `data_freshness`, `source_coverage`, `conviction_consistency`, `forensic_checks`, `kill_switch`, `fact_check` | JSON-file based | **Unchanged** (already reliable). |
| `three_axis_check`, 001/002/003, 当前股价 column, disclaimer exact text, "24 sections" | **Markdown parsing** (fragile) | **Moot** — guaranteed by template. Replace with a **payload-schema gate** (`gate-rendered-payload`: payload matches TypeBox schema + `missing[]` acceptable). |
| `gate-reports` (TS helper) | checks `state["stage-17"].reports[]` | Add: each report has a validated payload + rendered file. |

Net: `validate_report.py` loses its fragile markdown-parse gates; the TS
`gateValidator` gains a schema-conformance check that can't drift.

---

## 7. Migration phases

**Phase 0 — Infrastructure (est. small)**
- Add `nunjucks` dep. Implement `src/render.ts` + `src/render-schemas.ts` +
  `renderDocNode`. Unit tests (render a fake payload → assert canonical markdown
  fragments: 当前股价 column present, `001` ranking, disclaimer exact). Hermetic.

**Phase 1 — `equity-report` (highest pain, est. medium)**
- Port `templates/equity-report.md` → `templates/equity-report.njk`
  (mechanical: cut variable holes `{{ price }}`, `{% for r in ranking %}`,
  `{% if horizon == 'short' %}…三轴…{% endif %}`, Mermaid passthrough).
- Define `EquityReportPayload` (TypeBox) capturing all template variables.
- Rewire Stage 17 (report-writer) → `renderDocNode`. Agent emits payload.
- Keep free-form fallback behind a flag during burn-in.

**Phase 2 — `screening-report`** (same pattern; Broad/Focused/Thematic variants
→ Nunjucks `{% include %}` / branches).

**Phase 3 — Per-stage docs** (`ecosystem-health`, `industry-trajectory` already
`.j2` — just wire them to `renderDoc` with their existing schemas; near-zero
template work). Plus any other stage that writes a structured doc.

**Phase 4 — Retire fragile validator gates**; `validate_report.py` keeps content
gates, drops format-parse gates (now structural). Update `report-validator.md`.

**Phase 5 — Cleanup** — remove the free-form fallback flag; delete the old
"agent-mimics-template" prose from writer agent `.md` files.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Payload schema must capture ALL template variables (scores, prices, theses, ranking rows, Mermaid strings). Under-spec → `[MISSING DATA]` holes. | Schema-first design: derive payload fields from the template's variable usage; TypeBox `partial`/optional for soft fields; renderer emits `[MISSING DATA]` on null. |
| Big templates (54 kB) are tedious to port. | Mechanical extraction; do one horizon first (long-term), validate, then mid/short. Reuse `{% include %}` for shared sections (disclaimer, ranking table). |
| Mermaid diagrams from `calculate_metrics.py` are pre-rendered strings. | Pass through as opaque strings in the payload (`mermaid.revenue_fcf_trend`); renderer injects verbatim into ```` ```mermaid ```` fences. |
| Agents may still drift on the *content* (not format). | That's fine — content gates (fact-check, conviction consistency) still catch it; format is no longer the failure mode. |
| Nunjucks is lower-activity than Handlebars. | It's stable, Mozilla-maintained, pure-JS, and Jinja2-compatible (the deciding factor for reusing `.j2`). If undesired, Jinja2-via-Python is the drop-in alternative. |

---

## 9. Decision points (need from you)

1. **Engine:** Nunjucks (TS, recommended) vs Jinja2-via-Python vs Handlebars?
2. **Phase order:** equity-report first (highest validator pain) — agreed?
3. **Validator:** keep `validate_report.py` (content gates) and just drop the
   format-parse gates — or migrate all gates to TS?
4. **Scope of "every stage":** all 19 stages, or just the document-producing
   ones (Stage 4 screening, Stage 8 ecosystem, Stage 16.6/17 reports,
   Stage 18 best-picks)?

Once these are settled, Phase 0 + Phase 1 can land in one PR.
