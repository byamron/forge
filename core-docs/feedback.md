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

### FB-0007: Settings must guarantee a UX change or they aren't worth having
**Date:** 2026-04-03
**Source:** user direction

**What was said:** Three issues with the nudge/eagerness setting: (1) "only analyzes when you run /forge" is ambiguous — unclear if it means no background prep or no presentation; (2) session count is the wrong unit — the unit of value is proposals, not sessions; (3) "Claude may or may not surface it" means the setting doesn't guarantee any UX change, which makes it not worth having. If changing a setting doesn't reliably change what the user experiences, the setting shouldn't exist.

**Synthesized rule:** Every user-facing setting must have a clear, observable effect. If the user changes a setting and can't tell the difference, the setting is broken. For Forge: the trigger should be proposal-based (not session-count-based), the notification must be reliable (not dependent on Claude's discretion), and "quiet" must mean something specific and useful. Consider collapsing quiet/balanced/eager into a single boolean if the complexity isn't justified.

**Applies to:** nudge_level setting, check-pending.py, P1 ambient presence design, settings philosophy

### FB-0008: Memory promotions are uniformly low quality
**Date:** 2026-04-04
**Source:** review feedback

**What was said:** P0 validation across 3 real projects and 5 synthetic profiles found that memory promotion proposals are the #1 noise source. 44% of all real-project proposals were memory promotions — all dismissed. Evidence strings are generic ("Auto-memory note about MEMORY"), IDs are numbered duplicates (promote-memory, promote-memory-2, ...), descriptions don't explain what content would be promoted, and many duplicate proposals already generated by the correction builder from the same underlying user feedback.

**Synthesized rule:** The `_build_from_memory` builder needs a quality overhaul: (1) evidence must include actual memory content, not just the filename; (2) deduplicate against correction-derived proposals (same user feedback shouldn't generate both a rule proposal and a memory promotion); (3) numbered IDs are a sign the builder is emitting duplicates that should be consolidated. Until the builder is fixed, the LLM quality gate is the only defense against memory noise.

**Applies to:** _build_from_memory() in build-proposals.py, memory analysis pipeline, LLM quality gate

### FB-0009: Applied proposals reappear due to missing filter
**Date:** 2026-04-04
**Source:** review feedback

**What was said:** P0 validation found that proposals marked as "applied" via finalize-proposals.py reappear on the next `/forge` run if the underlying analysis still detects the same pattern. Specifically, demotion proposals regenerated from config analysis come back because `build_proposals()` filters `dismissed_ids` but has no `applied_ids` filter. The 3 demotions approved on PriorityAppXcode all reappeared on the second run.

**Synthesized rule:** Any proposal filter that checks dismissed IDs must also check applied IDs. When a proposal is applied, it should not resurface until the user explicitly re-runs analysis or the underlying pattern changes (e.g., CLAUDE.md is modified after the demotion is actually performed). This is a bug — add to P0a fix list.

**Applies to:** build_proposals() in build-proposals.py, specifically the dismissed_ids filter block (~line 1444)

### FB-0010: Synthetic test profiles should cover workflow agents
**Date:** 2026-04-04
**Source:** review feedback

**What was said:** Generic workflow agents (read→write→execute) are the #2 noise source on real projects (26% of proposals), but the synthetic test profiles don't generate any workflow proposals because their transcripts don't produce the tool-use sequences that trigger workflow detection. This means the workflow builder and the LLM quality filter for workflows have zero integration test coverage.

**Synthesized rule:** Add a synthetic profile (or extend an existing one) that generates tool-use sequences long enough to trigger workflow detection. The profile should produce at least one generic workflow pattern (read→write→execute at >80% frequency) so tests can verify the LLM gate filters it, and one project-specific workflow so tests can verify it passes.

**Applies to:** tests/generate_fixtures.py, test_integration_pipeline.py

### FB-0011: Clearly label agent-simulated vs user decisions in validation data
**Date:** 2026-04-04
**Source:** review feedback

**What was said:** P0 validation acceptance rates (0%, 22%) were computed from agent-simulated decisions, not real user choices. This wasn't initially clear in the documentation, risking confusion about whether the numbers reflect actual user experience.

**Synthesized rule:** When validation involves simulated decisions (an agent choosing accept/dismiss rather than the user), always label the results as "agent-simulated" in the documentation. Real user decisions are the ground truth — simulated decisions are useful for systematic analysis but should never be presented as user acceptance data without qualification.

**Applies to:** plan.md validation results, any future automated testing that produces acceptance metrics

<!-- Add new entries below this line, newest first. -->
