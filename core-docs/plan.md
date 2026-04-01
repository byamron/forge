# Plan

## Current Focus

Scoring evaluation baseline established: correction classifier recall is 13.3% (target >70%), accuracy 47.8%. The classifier is too keyword-dependent — real corrections use conversational language the keyword list doesn't cover. Next priority: threshold tuning using the 113-pair labeled dataset as a regression test. Background deep analysis (v0.3.1) partially mitigates the classifier weakness by running an LLM pass that catches patterns scripts miss.

## Handoff Notes

- Labeled data at `tests/scoring_eval/labeled/{portfolio-site,priorityapp}_pairs.json` (gitignored). 113 pairs labeled, 119 unlabeled.
- Key misclassification patterns: "that's not quite doing it" (mild correction → classified as followup), "scratch that" (reversal → new_instruction), "there absolutely is a pill" (factual correction → followup). These all need new keyword patterns or a fundamentally different approach.
- Background deep analysis is implemented but untested on a real project with `analysis_depth: "deep"` set. Should verify the `claude -p --bare` invocation works end-to-end.

## Spec & Roadmap

Original spec (`core-docs/spec.md`) and roadmap (`core-docs/roadmap.md`) are checked in. Phase/task references below map to the roadmap. Key deviations from spec:
- Three separate skills (`/forge:analyze`, `/forge:optimize`, `/forge:status`) were unified into `/forge`
- Artifact-generator agent was deleted (the `/forge` skill generates artifacts inline via Claude)
- MCP Elicitation (Task 2.6) was replaced with AskUserQuestion integration
- Ambient nudge (Task 3.2) was replaced with session-start nudge system
- Deep analysis mode was added (not in original roadmap) — background LLM pass for contextual patterns

## Active Work Items — Priority Order

### P0. Scoring evaluation infrastructure
**Status:** Infrastructure complete — ready for labeling
**Priority:** CRITICAL — this is the single biggest product risk. Without measured precision/recall, every threshold change is a guess.
**Goal:** Build tooling to extract real conversation pairs, label them, and measure classifier accuracy. Then use that data to tune thresholds.

**Why this is P0:** Forge's entire value proposition is "we detect the right patterns and suggest the right artifacts." The correction classifier and theme clustering use hard-coded thresholds (0.25 corrective classification, 3.0/6.0 theme confidence, keyword weights like 0.4 for "I told you") that were set by intuition. If these are wrong, Forge either generates noisy proposals (false positives → user loses trust) or misses real patterns (false negatives → Forge appears useless). This is the experiment that tells us whether the product works.

Scope (from `tests/SCORING_EVAL_PLAN.md`):
1. **Pair extraction script** — reads real JSONL transcripts, outputs assistant→user conversation pairs in a reviewable format
2. **Evaluation script** — runs `classify_response()` against labeled ground-truth data, reports precision/recall/F1
3. **Diagnostic review script** — reads cached transcript analysis, shows scoring details, near-misses, and threshold sensitivity
4. **Threshold tuning** — adjust weights and thresholds based on measured data, using the labeled set as a regression test

Deliverables:
- ✅ `tests/scoring_eval/extract_pairs.py` — extracts pairs from real transcripts
- ✅ `tests/scoring_eval/eval_classifier.py` — measures precision/recall/F1 against labeled data
- ✅ `tests/scoring_eval/review_diagnostics.py` — reads cached analysis, shows scores and sensitivity
- ✅ `tests/scoring_eval/labeled/README.md` — labeling guidelines and severity definitions
- ✅ `.gitignore` entry for `tests/scoring_eval/labeled/*.json`
- ✅ `tests/test_scoring_eval.py` — 17 tests for the evaluation infrastructure
- ✅ Label 113 pairs from 2 real projects (portfolio-site: 60, PriorityAppXcode: 53)
- ✅ Run eval_classifier.py — correction recall 13.3% (target >70%), accuracy 47.8%
- 🔲 Tune thresholds and keyword patterns based on measured data (use labeled set as regression test)

### P1. Artifact effectiveness tracking (Task 3.5)
**Status:** Complete (v0.3.0)
**Priority:** HIGH — closes the feedback loop. Without this, Forge can propose but can't learn whether proposals helped.
**Goal:** After deploying an artifact, track whether the triggering pattern stops appearing in subsequent sessions.

**Why this is P1:** This is the other half of the quality problem. P0 tells us if proposals are accurate; P1 tells us if they're useful. Together they form the feedback loop that makes Forge self-improving rather than static.

Scope:
- Record deployment timestamp and triggering pattern ID in `applied.json`
- On subsequent `/forge` runs, compare correction/pattern frequency before vs. after deployment
- Report effectiveness score per artifact in `/forge` health summary
- Flag artifacts where the triggering pattern persists (proposal didn't help → suggest removal or revision)
- Add effectiveness stats to `analyzer-stats.json` for aggregate tracking

### P2. Reduce SKILL.md fragility
**Status:** Not started
**Priority:** MEDIUM — the 209-line SKILL.md is a program written in prose. Ambiguity in instructions becomes runtime bugs that are hard to reproduce or test.
**Goal:** Push deterministic logic out of SKILL.md prose and into scripts. The skill should orchestrate, not compute.

**Why this is P2:** The `/forge` SKILL.md orchestrates a multi-step pipeline (resolve plugin root, run analysis, present proposals, generate artifacts, finalize) entirely through natural language instructions that the LLM interprets at runtime. Every ambiguous sentence is a potential bug that can't be caught by tests. Moving deterministic steps into scripts makes them testable and removes interpretation variance.

Scope:
- Extract proposal presentation logic into a script that formats the health table and proposal table as text (SKILL.md just prints the output)
- Extract path validation into a script (SKILL.md calls it before writing)
- Extract settings.json merge logic into a script (SKILL.md calls it instead of hand-merging)
- Reduce SKILL.md to ~100 lines of orchestration: run script → show output → ask questions → write files → finalize
- Add tests for the extracted scripts

### P3. Consolidate `find_project_root()`
**Status:** Complete (v0.3.0)
**Priority:** LOW — minor code duplication, 4 copies of ~6 lines each. No functional risk but violates DRY.
**Goal:** Move `find_project_root()` into `project_identity.py` and import from there.

Scope:
- Add `find_project_root(override: Optional[str] = None) -> Path` to `project_identity.py`
- Update `check-pending.py`, `read-settings.py`, `write-settings.py`, `background-analyze.py` to import it
- Add test coverage in `test_project_identity.py`

---

## Completed Work Items (archived)

<details>
<summary>Click to expand completed items</summary>

### User-level data storage migration
**Status:** Complete (v0.2.5)

### Tier demotion / budget rebalancing (Task 2.5)
**Status:** Complete

### Synthetic test dataset generator
**Status:** Complete

### Stale config detection (Task 3.4)
**Status:** Complete (v0.2.6)

### Agent generation (Task 2.3)
**Status:** Complete

### Reference doc extraction (Task 2.4)
**Status:** Complete

### Background deep analysis (v0.3.1)
**Status:** Complete (v0.3.1)

### Background analysis on SessionStart (Task 3.1)
**Status:** Complete (v0.2.8)

### Real-world testing via marketplace install
**Status:** Paused — blocked on P0. Running `/forge` on real projects without scoring evaluation means we can't measure whether proposals are good. Resume after P0 delivers measurable precision/recall.

</details>

---

## Phase Status

### Phase 1: Foundation (v0.1) — COMPLETE
All 11 tasks shipped. See `core-docs/history.md` for details.

### Phase 2: Full Artifact Coverage (v0.2) — COMPLETE

| Task | Status | Notes |
|------|--------|-------|
| 2.1 Skill generation | ✅ Done | Detects repeated prompts, generates SKILL.md templates |
| 2.2 Hook generation | ✅ Done | PostToolUse hooks for formatters/linters by tech stack |
| 2.3 Agent generation | ✅ Done | Workflow detection + archetype-based agent markdown generation |
| 2.4 Reference doc generation | ✅ Done | Verbose CLAUDE.md→reference + oversized rule→reference + memory→reference |
| 2.5 Tier promotion/demotion | ✅ Done | Promotion (memory→artifacts) + demotion (CLAUDE.md→rules, rules→references) |
| 2.6 MCP Elicitation | ➡️ Replaced | AskUserQuestion used instead; no MCP server |
| 2.7 Repeated prompt detection | ✅ Done | TF-IDF + Jaccard similarity, 4+ session threshold |
| 2.8 Post-action detection | ✅ Done | Write/Edit→Bash pattern detection across sessions |

### Phase 3: Proactive Intelligence (v0.3) — ~60% complete

| Task | Status | Notes |
|------|--------|-------|
| 3.1 Background analysis on SessionStart | ✅ Done | SessionStart hook + background-analyze.py, 20 tests |
| 3.2 Between-task ambient nudge | ➡️ Replaced | Session-start nudge system via settings levels |
| 3.3 Session-start passive briefing | ✅ Done | Nudge levels: quiet/balanced/eager |
| 3.4 Stale config detection | ✅ Done | Cross-references artifacts against session data; 4 matching strategies |
| 3.5 Artifact effectiveness tracking | ✅ Done | Track if corrections stop after artifact deployed; 12 tests |
| 3.6 Scoring evaluation (NEW) | 🟡 Infra done | Scripts built, 17 tests; labeling + tuning pending |

### Phase 4: Advanced (v1.0) — Not started (blocked on Phase 3 quality track)

| Task | Status | Notes |
|------|--------|-------|
| 4.1 Cross-project aggregation | ❌ Deferred | Opt-in only, requires privacy design |
| 4.2 Explain mode | ❌ Not started | "Why does this rule exist?" with evidence |
| 4.3 Self-cost tracking | ❌ Not started | Token consumption reporting |
| 4.4 Export/share | ❌ Not started | Package config as shareable zip |

---

## Recently Completed

### Background analysis on SessionStart (v0.2.8)
**Date:** 2026-03-31
SessionStart hook auto-triggers Phase A analysis when unanalyzed sessions exceed the nudge level threshold. Spawns detached background process, zero LLM token cost. Lock file prevents concurrent runs. 20 new tests (222 total).

### Transcript discovery integration tests
**Date:** 2026-03-31
30 integration tests for `find_all_project_session_dirs` covering all 5 discovery strategies, cross-project leakage prevention, subprocess timeout graceful degradation, mtime sorting, dedup, and multi-strategy composition. Total test count: 232, all passing in <0.4s.

### Proposal builder bug fixes (v0.2.7)
**Date:** 2026-03-30
Ran full pipeline on synthetic data, found and fixed 4 bugs. Added 8 regression tests.

## Backlog
- CI/CD setup (prerequisite: test suite exists ✅)
- Cross-project aggregation (Phase 4, opt-in only)
- `forge:cleanup` command — detect and remove orphaned `~/.claude/forge/projects/<hash>/` directories
- Hash collision resilience — bump project hash from 12 to 16 hex chars if user base grows
