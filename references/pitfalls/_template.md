---
title: <one-sentence rule, imperative or declarative>
severity: HIGH | MEDIUM | LOW
appliesTo: <stage names or scenario tags, comma-separated>
tags: <topic tags, comma-separated>
---

## <Title>

<2–4 sentence statement of the rule. State it as a hard rule, not a suggestion. Name the specific failure mode it prevents.>

**Why it matters**: <Why violating this rule produces a wrong analysis. Include the mechanism — what specific score / target / recommendation gets corrupted.>

**Concrete failure** (optional but preferred): <One specific dated case where this pitfall produced a wrong answer. Format: ticker, date, what was claimed, what actually happened, magnitude of error.>

**How to apply**:

1. <Numbered steps, each one a concrete check or action.>
2. <Make them executable — what to compute, what threshold to compare against, what file to load.>
3. <Cite the script / agent / stage that should enforce the check.>

**When the rule does NOT apply**:
- <Edge case 1 — explicit exception with reason>
- <Edge case 2>

**Cross-references**:
- Pitfall NN — <related pitfall, why related>
- `references/<file>.md` — <related framework>
- Stage NN (`agents/<agent>.md`) — <enforcement point>
