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

<!-- Add new entries below this line, newest first. -->
