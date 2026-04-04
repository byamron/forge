# Feedback Log

User feedback synthesized into actionable guidance. When the user gives feedback -- corrections, preferences, reactions, direction changes -- the relevant insight is captured here so it shapes all future work.

This is not a transcript. Each entry distills feedback into a rule or preference that applies going forward.

---

## How to Write an Entry

```
### FB-XXXX: [Short summary of the feedback]
**Date:** YYYY-MM-DD
**Source:** user correction | user preference | user direction | review feedback

**What was said:** Brief, factual summary of the feedback.

**Synthesized rule:** The actionable takeaway -- what to do differently going forward.

**Applies to:** [areas this affects: ux, code, architecture, workflow, etc.]
```

### Numbering
Increment from the last entry. Use `FB-0001`, `FB-0002`, etc.

### Source types
- **user correction** -- user fixed something you did wrong
- **user preference** -- user expressed a stylistic or process preference
- **user direction** -- user set strategic direction or priorities
- **review feedback** -- issues found during code/design review

---

## Entries

### FB-0001: Proposals need qualitative feedback loop
**Date:** 2026-04-01
**Source:** user direction

**What was said:** User reported that in their portfolio site project, Forge proposals don't reach a high enough threshold (impact is exaggerated) and automation proposals skip important steps like human approval. Rejecting these proposals had no effect — similar proposals kept appearing because Forge only recorded the exact ID, not the reason for rejection.

**Synthesized rule:** Forge must learn from *why* proposals are rejected, not just *that* they were. Dismissal reasons, modification patterns, and conversation signals should feed back into proposal generation to improve quality over time. Automation proposals (hooks, agents) need special scrutiny for human-in-the-loop steps.

**Applies to:** proposal pipeline, impact scoring, artifact generation, SKILL.md review flow

### FB-0002: Forge should feel like a living system, not a manual tool
**Date:** 2026-04-03
**Source:** user direction

**What was said:** User doesn't know if Forge is working. Unclear whether to run `/forge` every session or wait. The session-start nudge (systemMessage) is too quiet — Claude may ignore it. User wants Forge framed as "agentic AI documentation as a living body" — always watching, always proposing when infrastructure can be improved. The current experience feels manual despite background hooks running every session.

**Synthesized rule:** Forge's proactive behavior must be visible and self-explanatory. Users should never wonder "is this thing doing anything?" The ambient signals (session-start nudge, background analysis, effectiveness tracking) exist in the data layer but aren't surfaced assertively enough. High-confidence findings should be presented proactively, not gated behind a manual `/forge` invocation. The product framing should communicate that Forge accumulates value over time — more sessions = better proposals — and that the user reviews on their schedule, not on a cadence.

**Applies to:** UX, session-start hooks, nudge system, product framing, README

### FB-0003: Generic workflow patterns should not become agent proposals
**Date:** 2026-04-03
**Source:** user direction

**What was said:** P0 validation on the Forge repo produced 5 agent proposals that were all generic coding patterns (read→write→execute, read→execute→read) occurring in every session. User dismissed all as "not relevant" — they're not project-specific workflows, they're just how coding works. Furthermore, automating these removes the human from the loop, which isn't desired. Two proposals had duplicate IDs.

**Synthesized rule:** Workflow detection must distinguish project-specific workflows from universal coding patterns. If a tool-use sequence appears in >80% of sessions, it's not a workflow worth automating — it's baseline coding behavior. Agent proposals should also be scrutinized for human-in-the-loop: if the workflow involves iterative feedback (read→write→get feedback→revise), automating it removes a valuable approval step.

**Applies to:** workflow detection in analyze-transcripts.py, agent proposal generation in build-proposals.py, impact scoring

### FB-0004: Staleness detection uses wrong metric
**Date:** 2026-04-03
**Source:** review feedback

**What was said:** Rule 'python-scripts' was flagged as stale with "13 references in 29 sessions" — that's a 45% reference rate, which is healthy. The staleness detector counts absolute unreferenced sessions (29-13=16 >= threshold 15) instead of checking the reference ratio. A rule referenced in nearly half of all sessions is clearly not stale.

**Synthesized rule:** Staleness should be based on reference *ratio* (references/sessions), not absolute unreferenced count. A rule referenced in >25% of sessions is not stale regardless of total session count. The current absolute threshold breaks as session count grows.

**Applies to:** _build_from_staleness() in build-proposals.py, STALENESS_THRESHOLDS

### FB-0005: Demotion impact should scale with context pressure
**Date:** 2026-04-03
**Source:** user direction

**What was said:** Two demotion proposals (save 2 lines, save 7 lines) were rated "medium" impact when CLAUDE.md is at 82/200 lines — well under budget. User skipped both because the impact didn't justify the action. If context isn't under pressure, moving a few lines isn't worth the churn.

**Synthesized rule:** Demotion impact should be "low" (filtered out) when CLAUDE.md is well under budget (<150 lines). Only escalate to "medium" when approaching budget (150-200 lines) or "high" when over budget. The current scoring doesn't account for headroom.

**Applies to:** _score_impact() and _build_from_demotions() in build-proposals.py

### FB-0006: LLM quality judgment should be implicit, not a setting
**Date:** 2026-04-03
**Source:** user direction

**What was said:** During P0 review, Claude actively recommended against several proposals (noting they were generic or duplicates). User found this helpful and suggested: if Claude would recommend against a proposal, it shouldn't be shown. When asked whether LLM analysis should be a setting (standard vs deep), user said: "is there a reason to not have deep mode on? should that be a feature we offer, or should LLM use be implied?" The answer is implied — offering "no LLM" mode is offering worse results.

**Synthesized rule:** The LLM quality gate is not optional — it's how Forge works. Don't expose implementation details (script-only vs LLM) as user settings. If something improves quality at acceptable cost (~5K tokens), just do it. Settings should be for genuine user preferences (nudge frequency, proactive behavior), not for degrading quality. If cost becomes a concern, optimize the call, don't let users opt out of quality.

**Applies to:** analysis_depth setting (remove it), session-analyzer agent role, pipeline architecture, settings design philosophy

<!-- Add new entries below this line, newest first. -->
