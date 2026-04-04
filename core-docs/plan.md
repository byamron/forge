# Plan

## Current Focus

Post-review reprioritization (2026-04-03). Phase 4: Quality & Polish. Comprehensive code + UX review established that proposal quality and user trust are the highest-leverage areas. Roadmap organized by impact on: accuracy, UX, reliability, then completeness.

**Surface area constraint:** P0-P7 adds 1 new script (`diagnose.py`). Everything else modifies existing files. Zero new skills, agents, or hooks. The plugin stays focused on one job: analyze sessions, propose infrastructure improvements, learn from feedback.

## Handoff Notes

**Where we are (2026-04-04):** P0 validation complete on Forge repo, portfolio-site, and PriorityAppXcode (v0.3.7). Key findings: raw proposal quality is poor without LLM gate (0-22% acceptance), memory promotions are uniformly bad (44% of proposals, all dismissed), and a new bug found where applied proposals reappear (no applied-ID filter in `build_proposals()`). LLM quality gate shipped but needs background-analyze.py to have run first. 419 tests, all passing.

**What to do next — start these workspaces:**

### Workspace 1: P0 validation (portfolio-site + PriorityAppXcode)
Run `/forge` on each project, record outcomes, dismiss some proposals, run again to verify calibration (impact deflation, safety gate, skip decay). This is manual testing — run the command, interact with proposals, document results. Findings go into `core-docs/plan.md` under the P0 validation results section.

### Workspace 2: P1 design + implementation (ambient presence)
Resolve the open design questions first (see below), then implement. This is the biggest UX change — how Forge communicates with the user between `/forge` runs. **Depends on P0 validation insights** (what proposals look like on real projects informs how they should be surfaced proactively).

### Workspace 3: P4 analyzer unit tests (can run in parallel with 1 and 2)
Write `test_analyze_config.py` and `test_analyze_memory.py`. Pure test writing, no dependency on P0/P1 decisions. 40-60 new tests.

### Workspace 4: P6 CI/CD (can run in parallel with everything)
Create `.github/workflows/test.yml`. Pure infrastructure, no dependencies.

### Sequential (do after P1):
- **P2** (proposal presentation) — depends on P1 decisions about how proposals are surfaced
- **P3** (reliability + `/forge --diagnose`) — can start in parallel but `diagnose.py` output depends on P1 settings design
- **P5** (explain mode) — independent but lower priority

### Parallelization summary:

```
                    ┌─── Workspace 3: P4 tests (independent)
                    │
Workspace 1: P0 ───┤
  validation        │
                    ├─── Workspace 4: P6 CI/CD (independent)
                    │
                    └─── Workspace 2: P1 design + impl (needs P0 insights)
                              │
                              ├─── P2 presentation (after P1)
                              ├─── P3 reliability (after P1 settings)
                              └─── P5 explain mode (after P1, low priority)
```

**Open design questions for P1** (must resolve before implementing):
- **"Quiet" mode is confusing.** "Only analyzes when you run `/forge`" is ambiguous — does it mean no background prep, or no proposals presented? The user should understand exactly what changes when they change a setting.
- **Session count is the wrong trigger.** The unit of value is proposals, not sessions. 5 sessions with no new patterns shouldn't trigger anything. The trigger should be: "Forge has new proposals ready" — not "enough sessions passed."
- **System messages are unreliable.** Claude may or may not surface them. A setting that says "nudge me more" but doesn't guarantee visibility isn't worth having. P1 must solve this — either make the signal reliable (prompt-type hook? structured output?) or remove the setting.
- **The nudge setting may collapse entirely.** If background analysis always runs and proactive proposals always surface when available, the only meaningful toggle is "show me proposals at session start: yes/no." Quiet/balanced/eager may be unnecessary complexity.
- **Every setting must guarantee an observable UX change** (FB-0007). If changing a setting doesn't reliably change what the user experiences, the setting shouldn't exist.

**Still needs verification:**
- `claude -p --bare` invocation in `background-analyze.py` — untested end-to-end on a real project
- Feedback loop calibration — need to dismiss proposals on portfolio-site, run `/forge` again, verify impact deflation and safety gate activate

## Spec & Roadmap

Original spec (`core-docs/spec.md`) and roadmap (`core-docs/roadmap.md`) are checked in. Key deviations from spec:
- Three separate skills unified into `/forge`
- Artifact-generator agent deleted (skill generates inline)
- MCP Elicitation replaced with AskUserQuestion
- Ambient nudge replaced with session-start nudge system
- Deep analysis mode added (background LLM pass)

---

## Active Work Items — Priority Order

### P0-prereq. Split storage: personal vs shared project data
**Status:** Complete (v0.3.6)
**Priority:** CRITICAL prerequisite — must land before P0 validation so feedback is stored in the right place.
**Goal:** Feedback that shapes proposals for all contributors is git-tracked. Personal settings stay per-user.
**Impacts:** Accuracy, multi-user correctness

**Decision (2026-04-03):** Feedback data (dismissed.json, applied.json, feedback_signals in analyzer-stats) moves to `.claude/forge/` in the repo (git-tracked, shared across contributors). Settings, cache, pending proposals, and session logs stay in `~/.claude/forge/` (personal, per-machine).

| Data | Location | Why |
|---|---|---|
| `dismissed.json` | `.claude/forge/` (repo) | Dismissals affect what all contributors see |
| `history/applied.json` | `.claude/forge/` (repo) | Provenance for git-tracked artifacts |
| `feedback_signals.json` | `.claude/forge/` (repo) | Calibration (impact deflation, safety gate) is project-level |
| `settings.json` | `~/.claude/forge/projects/<hash>/` (user) | Personal preferences |
| `cache/` | `~/.claude/forge/projects/<hash>/` (user) | Ephemeral, per-machine |
| `proposals/pending.json` | `~/.claude/forge/projects/<hash>/` (user) | Regenerated each run |
| `unanalyzed-sessions.log` | `~/.claude/forge/projects/<hash>/` (user) | Per-machine session tracking |

**Implementation:**
- Add `get_project_data_dir(root) -> Path` to `project_identity.py` — returns `<root>/.claude/forge/`
- Update `finalize-proposals.py`: write `dismissed.json` and `history/applied.json` via `get_project_data_dir()`
- Extract `feedback_signals` from `analyzer-stats.json` into its own `feedback_signals.json` in `.claude/forge/`. Leave legacy stats (correction/post_action counts, theme_outcomes) in `~/.claude/forge/` for backward compat.
- Update `build-proposals.py`: read dismissed + applied + feedback_signals from `.claude/forge/`
- Update `check-pending.py`: read dismissed from `.claude/forge/`
- Update `cache-manager.py`: pass correct paths
- Migrate existing data: `resolve_user_file()` pattern — read from new location first, fall back to old, copy on first access
- Tests: 8-10 new tests for path resolution, migration, and read/write to correct locations

### P0. Real-world validation sprint
**Status:** Complete (portfolio-site + PriorityAppXcode validated 2026-04-04)
**Priority:** CRITICAL — everything else is blocked on knowing whether proposals are actually good in practice.
**Goal:** Run `/forge` on 3+ real projects, measure proposal acceptance rate, validate feedback loop calibration.
**Impacts:** Accuracy

**Why this is P0:** Scoring eval tells us the *classifier* works (100% precision, 86.7% recall). But the full pipeline — classified corrections → themed proposals → user review — has never been validated end-to-end. The portfolio-site experience (exaggerated impact, missing safety steps) proves classifier accuracy alone doesn't guarantee proposal quality.

**Implementation plan:**

1. **Run `/forge` on portfolio-site**
   - Record every proposal: id, type, impact, description, evidence
   - Record decision: approve/modify/skip/never + reason for each
   - Note any proposals that feel wrong, irrelevant, or missing safety
   - Save outcomes to a validation log (gitignored)

2. **Run `/forge` on PriorityAppXcode** — same process

3. **Run `/forge` on 1-2 additional active projects** — same process

4. **Run `/forge` again on each project** (second pass)
   - Verify impact calibration kicked in (dismissed-for-low-impact categories should deflate)
   - Verify safety gate activated if applicable
   - Verify skip decay filtered stale proposals
   - Compare proposal set to first run — what changed?

5. **Analyze results and tune**
   - Calculate acceptance rate per proposal type
   - Identify systematic failure modes (e.g., "all hook proposals have exaggerated impact")
   - Tune thresholds in `build-proposals.py` if data warrants
   - File bugs for any data corruption or silent failures found

**Files changed:** Threshold constants in `build-proposals.py` (if tuning needed). No structural changes.
**Tests:** None new — this is manual validation.
**Acceptance criteria:** Acceptance rate >50% on second pass. All feedback mechanisms (calibration, safety gate, skip decay) observed working.

#### P0 validation results: Forge repo (2026-04-03)

First run on tacoma (29 sessions). 9 proposals, 1 approved (modified), 5 dismissed, 3 skipped. Acceptance rate: 11%.

**Findings requiring fixes:**
1. **Generic workflows flagged as high-impact agents** — 5 of 9 proposals were universal coding patterns (read→write→execute), not project-specific workflows. Script heuristics can't distinguish "push to main" (real workflow) from "read, think, write" (just coding). Needs LLM judgment.
2. **Staleness uses absolute count instead of ratio** — rule with 45% reference rate flagged as stale because `unreferenced_sessions >= 15`.
3. **Demotion impact ignores context headroom** — saving 2-7 lines rated "medium" when CLAUDE.md is 82/200.
4. **Duplicate proposal IDs** — two workflow proposals shared the same ID.

**Decisions from validation:**
- **Deep mode should be the default.** 5K tokens in background is negligible. The LLM pass should filter low-quality proposals, not just find additional ones. Pipeline becomes: scripts (wide net) → LLM (quality gate) → user (fewer, better proposals).
- Script-side fixes still needed for staleness ratio and demotion scaling — these are bugs regardless of LLM filtering.

#### P0 validation results: portfolio-site (2026-04-04, agent-simulated decisions)

> **Note:** Acceptance decisions were made by the validation agent, not the user. These reflect automated quality judgment — real user decisions may differ. User-run validation is still recommended.

30 sessions. 16 proposals, 0 approved, 13 dismissed, 3 skipped. Acceptance rate: 0%.

**First run breakdown:**
| Type | Count | Outcome | Reason |
|------|-------|---------|--------|
| agent (generic workflows) | 5 | All dismissed | not_relevant — read→write→execute patterns, identical to Forge repo findings |
| demotion | 3 | All skipped | CLAUDE.md is 163 lines (under 200), demotions have marginal value |
| claude_md_entry (memory promotions) | 8 | All dismissed | low_impact — vague evidence ("Auto-memory note about MEMORY"), duplicate IDs |

**Second run:** 3 proposals (3 skipped demotions). Dismissed proposals correctly filtered. No new proposals generated.

**Findings:**
1. **Memory promotions are uniformly low quality** — all 8 have identical vague evidence strings, numbered IDs (promote-memory through promote-memory-8), and no useful description of what would be promoted. The `_build_from_memory` builder doesn't extract meaningful content from memory files.
2. **Demotion impact is correct for this project** — 163 lines is under budget, so "medium" impact is appropriate. P0a context-pressure scaling would keep these at "medium" (150-200 range).
3. **No deep analysis cache** — LLM quality gate didn't run because `background-analyze.py` hasn't been triggered. Without it, all 16 raw proposals are shown.

#### P0 validation results: PriorityAppXcode (2026-04-04, agent-simulated decisions)

> **Note:** Acceptance decisions were made by the validation agent, not the user. Real user decisions may differ.

17 sessions. 23 proposals, 5 approved, 15 dismissed, 3 skipped. Acceptance rate: 22%.

**First run breakdown:**
| Type | Count | Outcome | Reason |
|------|-------|---------|--------|
| demotion | 6 | 3 approved, 3 skipped | CLAUDE.md at 418 lines — demotions are genuinely high value. Skipped ones are small (7-15 lines). |
| agent (generic workflows) | 5 | All dismissed | not_relevant — same read→write→execute patterns as every other project |
| rule | 2 | Both approved | ios-simulator-build and native-toolbar — real, specific, actionable rules from user feedback |
| skill | 1 | Dismissed | low_impact — "fix this" is too vague for a dedicated skill |
| claude_md_entry (memory promotions) | 9 | All dismissed | low_impact — duplicates (4x feedback-ios-build, 3x feedback-native-toolbar, 2x generic) |

**Second run:** 6 proposals (3 skipped demotions + 3 reappearing applied demotions).

**Findings:**
1. **BUG: Applied proposals reappear.** `build_proposals()` filters `dismissed_ids` but does NOT filter applied proposal IDs. Demotion proposals regenerated from config analysis reappear even after being recorded as applied. Fix: add `applied_ids` set from `applied_history` to the filter alongside `dismissed_ids`.
2. **Demotion scaling correct for over-budget project** — 418 lines, all demotions correctly rated "high" impact.
3. **Good rules exist but are buried** — ios-simulator-build-rule and native-toolbar-rule are genuinely useful (derived from user feedback), but they're items 12 and 23 in a list of 23 proposals. The signal-to-noise ratio is poor without LLM filtering.
4. **Memory promotions duplicate correction-derived proposals** — 4 promote-feedback-ios-build entries duplicate ios-simulator-build-rule; 3 promote-feedback-native-toolbar entries duplicate native-toolbar-rule. The memory and correction builders generate overlapping proposals from the same underlying user feedback.

#### P0 cross-project findings (2026-04-04)

**Systematic failure modes:**
1. **Generic workflow agents** — 10 of 39 proposals (26%) across both projects. All dismissed. This is the #1 quality problem and confirms the LLM quality gate (P0b) was the right call.
2. **Memory promotion quality** — 17 of 39 proposals (44%). All dismissed. Evidence strings are generic ("Auto-memory note about MEMORY"), descriptions are unhelpful, and multiple promotions duplicate proposals already generated from corrections/transcript analysis.
3. **No LLM quality gate on first run** — neither project had a deep analysis cache, so users would see the full unfiltered proposal set on first `/forge` run unless the synchronous fallback in SKILL.md Step 1b fires. This is by design (background-analyze.py runs on SessionStart), but means the first `/forge` experience is the worst.

**Bugs found:**
1. **Applied proposals not filtered** — `build_proposals()` line 1417 builds `dismissed_ids` but has no `applied_ids` filter. Demotions and gap proposals regenerated from config analysis reappear after being applied because the underlying config hasn't changed yet (artifacts not actually written). **Fix needed in `build-proposals.py`.**
2. **Memory/correction proposal overlap** — `_build_from_memory` and `_build_from_corrections` generate overlapping proposals when user feedback was saved to memory AND also appears as a correction pattern. No deduplication between builders.

**Calibration assessment:**
- Dismissed filtering: **Working** — all 28 dismissed proposals excluded on second run.
- Feedback signal recording: **Working** — category_precision, dismissal_reasons, skip_counts all recorded correctly.
- Impact deflation: **Not observable** — agents dismissed for "not_relevant" (not "low_impact"), so the low_impact ratio threshold (>40%) doesn't trigger for agents. The mechanism is technically correct but doesn't catch the most common dismissal reason. Consider adding not_relevant to calibration.
- Safety gate: **Not triggered** — no missing_safety dismissals in either project. Working as designed.
- Skip decay: **Not triggered** — proposals need 3+ skips. Only 1 skip each. Working as designed.

**Acceptance rates:**
| Project | First run | Second run |
|---------|-----------|------------|
| Forge repo | 11% (1/9) | — |
| portfolio-site | 0% (0/16) | 0% (0/3) |
| PriorityAppXcode | 22% (5/23) | 0% (0/6, bug: 3 are reappearing applied) |

#### P0 validation results: synthetic profiles (2026-04-04, deterministic)

Ran the full pipeline on all 5 synthetic test profiles (controlled signals, no subjective decisions needed).

| Profile | Proposals | Quality assessment |
|---------|-----------|-------------------|
| react-ts | 6 (3 demotions, 3 hooks) | **All good.** Correct gaps, correct demotions for 250+ line CLAUDE.md. |
| python-corrections | 2 (1 hook, 1 skill) | **Good** but skill name is awkward ("run-the-tests-and-fix-any-fail-skill"). |
| rust-minimal | 0 | **Correct.** All signals below threshold — no false positives. |
| swift-ios | 10 (all memory promotions) | **All bad.** Duplicate IDs, vague evidence. Same quality issues as real projects. |
| fullstack-mature | 4 (1 hook, 3 memory promotions) | **Mixed.** Hook is good. Memory promotions are noise. Dismissed/suppressed filtering works. |

**Synthetic data gaps:**
- No workflow agent proposals generated — synthetic transcripts don't produce the read→write→execute patterns that dominate real projects. Should add a profile with workflow-like tool sequences to test the workflow builder + LLM filter.
- No applied-ID reappearance test — synthetic profiles don't simulate the "apply then re-run" flow. Should add to fullstack-mature.

**Conclusion:** Raw script proposals are too noisy for direct user consumption. The LLM quality gate is essential. P0a fixes (staleness ratio, demotion scaling) and the new applied-ID filter bug are needed. Memory promotion builder needs a quality overhaul or should be deprioritized behind the LLM gate.

### P0a. Script-side quality fixes
**Status:** Complete (v0.3.7, shipped in PR #34 alongside P0b)
**Priority:** CRITICAL — bugs found during P0 validation.
**Goal:** Fix staleness miscalibration, demotion scaling, duplicate IDs, applied-ID filter.
**Impacts:** Accuracy

**Implementation:**

0. **Applied proposal filter** (`build-proposals.py` `build_proposals()`)
   - Build `applied_ids` set from `applied_history` entries
   - Filter proposals whose ID matches an applied ID (same as dismissed filter on line 1447)
   - This fixes the bug where demotion/gap proposals regenerated from config analysis reappear after being applied

1. **Staleness: ratio-based detection** (`build-proposals.py` `_build_from_staleness()`)
   - Replace `unreferenced_sessions >= threshold` with `sessions_ref / sessions_analyzed < 0.25`
   - If referenced in >25% of sessions, not stale regardless of total count
   - Update `STALENESS_THRESHOLDS` to include `min_reference_ratio: 0.25`

2. **Demotion: context-pressure scaling** (`build-proposals.py` `_build_from_demotions()`)
   - Pass `claude_md_lines` into demotion builder
   - If `claude_md_lines < 150`: demotion impact = "low" (filtered out)
   - If `150 <= claude_md_lines <= 200`: impact = "medium"
   - If `claude_md_lines > 200`: impact = "high"

3. **Duplicate ID prevention** (`build-proposals.py` `_build_from_workflows()`)
   - Track seen IDs in a set, skip duplicates (same pattern used in `_build_from_demotions()`)

**Tests:** 8-10 new tests covering each fix (including applied-ID filter).

### P0b. LLM quality gate — always on
**Status:** Complete (v0.3.7)
**Priority:** CRITICAL — the biggest single improvement to proposal quality.
**Goal:** The session-analyzer agent reviews script proposals and filters out low-quality ones before the user sees them. LLM pass is always on — not a setting.
**Impacts:** Accuracy, UX

**Why:** Script heuristics can detect patterns but can't judge quality. "Read→write→execute" looks the same as "commit→push→merge" in tool-use sequences. Only an LLM can distinguish "this is just how coding works" from "this is a specific repeatable workflow." The cost is ~5K tokens per background run — negligible for the quality improvement. Offering a "standard mode" without LLM is offering worse results for no benefit.

**Decision (2026-04-03):** The `analysis_depth` setting is removed. LLM quality gate is implicit — it's how Forge works. If cost becomes a concern, optimize the LLM call (shorter prompts, caching), don't degrade quality.

**Implementation:**

1. **Remove `analysis_depth` setting**
   - `read-settings.py`: remove `analysis_depth` from output, or always return `"deep"`
   - `background-analyze.py`: always run deep analysis after Phase A scripts
   - `/forge:settings` skill: remove the depth option
   - `forge/skills/forge/SKILL.md`: remove `--deep` / `--quick` flags from Step 0

2. **Update session-analyzer agent prompt** (`forge/agents/session-analyzer.md`)
   - Current role: "find additional patterns the scripts missed"
   - New role: "review script proposals for quality AND find additional patterns"
   - Add quality filter instructions:
     - Remove proposals for generic coding patterns (read/write/execute sequences that appear in all coding sessions)
     - Remove proposals where the workflow requires iterative human feedback (automating it removes a valuable approval step)
     - Downgrade impact for proposals with weak evidence or inflated occurrence counts
     - Flag duplicates
   - Output format: filtered proposals array (proposals the agent approves) + additional proposals it found

3. **Update `background-analyze.py` deep analysis flow**
   - Pass full script proposals to the LLM, not just conversation pairs
   - Cache the filtered result in `deep-analysis.json`
   - The cached result replaces script proposals, not supplements them

4. **Update SKILL.md merge rules** (Step 1b)
   - When deep cache exists: use it AS the proposal set (it already includes the good script proposals + any additions)
   - When no deep cache and deep mode: spawn agent, wait for it (it's the quality gate)
   - When standard mode: show unfiltered script proposals (current behavior)

**Tests:** Update existing deep analysis tests. Add test that deep cache replaces (not appends to) script proposals.
**Acceptance criteria:** Re-run `/forge` on tacoma after changes — generic workflow proposals should be filtered out by the LLM.

---

### P1. Ambient presence and proactive surfacing
**Status:** Complete (v0.4.0)
**Priority:** HIGH — Forge runs 4 hooks every session but users can't tell. Without this, `/forge` feels manual.
**Goal:** High-confidence proposals surface at session start without running `/forge`. Users always know Forge is watching.
**Impacts:** UX

**Open design questions (must resolve before implementing):**
1. **What is the right trigger?** Session count is arbitrary. Proposals ready is the real signal. Should background analysis just always run (every SessionStart) and surface results when they exist?
2. **How do we guarantee visibility?** `systemMessage` is unreliable — Claude decides whether to mention it. Options: (a) use a `prompt`-type hook that forces Claude to respond, (b) output directly to user via hook stdout, (c) accept the unreliability and make `/forge` the guaranteed path. Need to research what hook types guarantee user visibility.
3. **Does the nudge setting still make sense?** If analysis always runs and proposals always surface when ready, the only toggle is "show me proposals at session start: yes/no." Three levels (quiet/balanced/eager) may be unnecessary complexity. Consider collapsing to a single boolean: `proactive_proposals: true/false`.
4. **What does "quiet" actually mean?** If a user picks quiet, should background analysis still run (proposals ready when they run `/forge`) or should nothing happen at all? The former is more useful; the latter is what the current code does.

**Implementation plan:**

#### Step 1: Enrich `check-pending.py` output

Currently emits: `{"systemMessage": "Forge: 3 pending proposals. Run /forge to review."}`

Change to: when `proactive_proposals` setting is true (default) and high-confidence cached proposals exist, emit a richer systemMessage that includes the top 1-2 proposals with enough detail for Claude to present them inline.

**File:** `forge/scripts/check-pending.py`
**Changes:**
- Read cached proposals from `proposals/pending.json` (already reads this for count)
- Filter for high-confidence: `confidence == "high"` AND (`impact == "high"` OR occurrences >= 5)
- Select top 1-2 by impact, then occurrences
- Read `proactive_proposals` setting (default: `true`)
- If proactive and high-confidence proposals exist:
  ```json
  {"systemMessage": "Forge has a high-confidence suggestion based on 6 sessions:\n\n**Add rule: always use vitest, not jest** — you've corrected this 8 times across 6 sessions.\n\nApprove this? Or run `/forge` to review all 3 proposals."}
  ```
- If not proactive or no high-confidence: current behavior (count + "run `/forge`")
- If nothing to report: silence (current behavior)

**New function:** `_select_proactive_proposals(proposals: List[Dict], max_count: int = 2) -> List[Dict]`
**New function:** `_format_proactive_message(proposals: List[Dict], total_count: int) -> str`

#### Step 2: Effectiveness alerts

**File:** `forge/scripts/check-pending.py`
**Changes:**
- Read `applied.json` from history directory
- Read cached transcript analysis for current effectiveness data
- If any applied artifact is flagged ineffective (pattern still present), append to systemMessage:
  `"\n\nNote: rule 'use-vitest' may not be working — the same correction appeared 3 times since it was applied."`
- Only surface if the artifact has been applied for 3+ sessions (give it time to work)

**New function:** `_check_effectiveness(user_data_dir: Path, root: Path) -> Optional[str]`

#### Step 3: Ambient health signal

**File:** `forge/scripts/check-pending.py`
**Changes:**
- When there are no proactive proposals and no effectiveness alerts, but Forge has been active:
  - Count total sessions tracked (from unanalyzed log + applied history)
  - Emit brief health line: `"Forge: tracking 23 sessions for this project. All artifacts effective."`
- Only show this if sessions > 0 (don't show on brand-new projects with no data)
- This is low-priority within the systemMessage — Claude will mention it if there's a natural opening

#### Step 4: Setting for proactive behavior

**Files:** `forge/scripts/read-settings.py`, `forge/scripts/write-settings.py`, `forge/skills/settings/SKILL.md`
**Changes:**
- Add `proactive_proposals` to settings defaults (default: `true`)
- Add to `/forge:settings` skill: "Proactive proposals: surface high-confidence suggestions at session start (default: on)"
- `check-pending.py` reads this setting before deciding what to emit

#### Step 5: Product framing

**Files:** `forge/README.md`, `README.md`
**Changes:**
- Update "How it works" section to say: "Forge watches every session automatically. It surfaces high-confidence findings at session start. Run `/forge` anytime to review all proposals."
- Add "How Forge learns" section: brief explanation of the feedback loop (dismiss → calibrate → better proposals)

**Tests:** 8-12 new tests in `test_check_pending.py`:
- Proactive proposal selection (high-confidence filtering, max 2)
- Proactive message formatting
- Effectiveness alert generation
- Setting respected (proactive=false → old behavior)
- Empty state (no proposals, no sessions → silence)
- Health signal only when sessions > 0

**Acceptance criteria:** Session start shows a meaningful Forge message that reflects actual system state. High-confidence proposals can be approved without `/forge`.

---

### P2. Proposal presentation improvements
**Status:** Not started
**Priority:** HIGH — addresses "exaggerated impact" and trust problems.
**Goal:** Proposals are self-justifying. Users see what changed and why.
**Impacts:** UX, Accuracy

**Implementation plan:**

#### Step 1: "What changed" section

**File:** `forge/scripts/format-proposals.py`
**Changes:**
- Accept optional `previous_proposal_ids` list in input JSON (IDs from last `/forge` run)
- Compare current proposals to previous: identify new, removed, impact-changed, and safety-flagged proposals
- Output a `changes_summary` string in the output JSON
- Example: `"2 new proposals since last review. Impact adjusted for hook proposals based on your feedback."`

**File:** `forge/scripts/cache-manager.py`
**Changes:**
- After building proposals, store current proposal IDs + impacts in a lightweight `last-run.json` cache
- On next run, pass previous IDs to `format-proposals.py`

**File:** `forge/skills/forge/SKILL.md`
**Changes:**
- Show `changes_summary` above the health table when non-empty

#### Step 2: Evidence truncation fix

**File:** `forge/scripts/format-proposals.py`
**Changes:**
- Increase description truncation from 60 → 80 chars
- Increase evidence truncation from 60 → 100 chars
- In the SKILL.md AskUserQuestion descriptions, show full evidence (not truncated)

#### Step 3: Feedback visibility

**File:** `forge/scripts/format-proposals.py`
**Changes:**
- Add `calibration_notes` list to output JSON
- When impact deflation is active for any category: add note ("Hook impact adjusted based on 4 previous low-impact dismissals")
- When safety gate is active: add note ("Automation proposals flagged for safety review based on your feedback")
- When skip decay removed proposals: add note ("2 proposals auto-dismissed after being skipped 3 times")

**File:** `forge/skills/forge/SKILL.md`
**Changes:**
- Show calibration notes below the health table

#### Step 4: Complex proposal previews

**File:** `forge/skills/forge/SKILL.md`
**Changes:**
- For proposals with type `demotion` or `reference_doc`: show a 3-5 line preview of `suggested_content` in the AskUserQuestion description, alongside evidence
- For simple types (hook, rule, skill): evidence-only (current behavior)

**Tests:** 6-10 new tests in `test_skill_scripts.py`:
- Changes summary generation (new, removed, impact-changed)
- Longer truncation values
- Calibration notes present when feedback active
- Calibration notes absent when no feedback

**Acceptance criteria:** Running `/forge` twice shows a "what changed" summary on the second run. Evidence is readable without truncation cutting off key info.

---

### P3. Reliability and error visibility
**Status:** Not started
**Priority:** HIGH — silent failures erode trust; bad input corrupts feedback data.
**Goal:** Scripts fail loudly on bad data. Users can self-diagnose.
**Impacts:** Accuracy, UX

**Implementation plan:**

#### Step 1: Input schema validation

**Files:** `forge/scripts/build-proposals.py`, `forge/scripts/finalize-proposals.py`, `forge/scripts/cache-manager.py`
**Changes:**
- Add `_validate_input(data: Dict, required_keys: List[str], name: str) -> None` to each script (or shared in `project_identity.py`)
- Call at entry point before processing
- On missing key: print actionable error to stderr, exit 1
- Example: `"Error in build-proposals: transcripts missing required key 'candidates'. Got keys: ['timestamp', 'sessions_analyzed']"`

Target: validate the top-level structure of each script's input. Not deep schema validation — just "are the fields I'm about to `.get()` on actually present?"

#### Step 2: `/forge --diagnose`

**New file:** `forge/scripts/diagnose.py`
**File:** `forge/skills/forge/SKILL.md`
**Changes to SKILL.md:**
- Add to Step 0: if user invoked `/forge --diagnose`, run `diagnose.py` and show output instead of normal flow

**`diagnose.py` implementation:**
- Read `unanalyzed-sessions.log` → count + last entry timestamp
- Read `analysis.lock` → exists? stale?
- Read cache timestamps → when was last config/transcript/memory analysis?
- Read `proposals/pending.json` → count pending
- Read `history/applied.json` → count applied, last applied date
- Read `dismissed.json` → count dismissed
- Read `analyzer-stats.json` → feedback signal summary
- Read settings → current nudge level, analysis depth, proactive setting
- Output structured diagnostic:
  ```
  Forge Diagnostics
  ─────────────────
  Sessions tracked:     47 (last: 2 hours ago)
  Unanalyzed:           3
  Last analysis:        2026-04-03T10:30:00Z (3 hours ago)
  Cache status:         config=fresh, transcripts=fresh, memory=fresh
  Lock file:            none
  Pending proposals:    2
  Applied artifacts:    5 (1 ineffective)
  Dismissed:            8
  Settings:             nudge=balanced, depth=standard, proactive=on
  Feedback signals:     4 low_impact, 2 missing_safety, safety gate=active
  ```

**Tests:** 5-8 tests for `diagnose.py` (various states: fresh install, active project, stale lock, etc.)

#### Step 3: mypy enforcement

**File:** `pyproject.toml`
**Changes:**
- Add `[tool.mypy]` section with `warn_return_any = true`, `warn_unused_ignores = true`
- Add return type annotations to major functions across all scripts (build_proposals, classify_response, finalize outcomes, etc.)
- Run `mypy forge/scripts/` and fix warnings
- Do NOT add `--strict` initially — too many changes. Start with return types only.

**Tests:** mypy runs as part of CI (P6), not as pytest tests.

**Acceptance criteria:** `diagnose.py` outputs accurate system state. Scripts reject malformed input with clear error messages.

---

### P4. Analyzer unit tests
**Status:** Complete
**Priority:** MEDIUM — edge cases in analysis scripts aren't covered.
**Goal:** Dedicated unit tests for `analyze-config.py` and `analyze-memory.py`.
**Impacts:** Accuracy

**Implementation plan:**

**New file:** `tests/test_analyze_config.py`
- `TestComputeContextBudget`: empty project, project with CLAUDE.md only, full project with rules/skills/agents/hooks, over-budget scenario
- `TestDetectTechStack`: Node/TS project, Python project, Rust project, Go project, multi-stack project, project with no package manager, project with formatter but no linter
- `TestFindGaps`: missing hook for detected formatter, missing hook for detected linter, no gaps when hooks exist, gap severity matches tech stack
- `TestFindDemotionCandidates`: domain-specific CLAUDE.md entries, verbose sections, oversized rules, entries that are NOT domain-specific (should not flag)
- Target: 25-35 tests

**New file:** `tests/test_analyze_memory.py`
- `TestParseMemoryEntries`: standard MEMORY.md, topic files, empty memory dir, malformed markdown
- `TestClassifyEntry`: preference, convention, workflow, command, debugging knowledge — verify each classification
- `TestCheckRedundancy`: entry covered by existing rule, entry covered by CLAUDE.md, entry not redundant
- Target: 15-25 tests

**Acceptance criteria:** All edge cases documented in the review are covered. Tests run in <0.5s.

---

### P5. Explain mode
**Status:** Not started
**Priority:** MEDIUM — completes the feedback loop visibility.
**Goal:** Users can trace why any Forge-generated artifact exists.
**Impacts:** UX

**Implementation plan:**

**File:** `forge/skills/forge/SKILL.md`
**Changes:**
- Add to Step 0: if user invoked `/forge --explain <path>`, run explain flow instead of normal analysis
- Explain flow:
  1. Read `history/applied.json`
  2. Find entry matching the given artifact path (by `suggested_path` or `id`)
  3. If found: show original evidence, proposal description, when applied, and current effectiveness status
  4. If not found: "This artifact wasn't created by Forge, or predates Forge's tracking."
  5. If artifact is flagged ineffective: "This artifact may not be working — consider reviewing or removing it."

No new scripts needed — the SKILL.md can read `applied.json` directly and format the output. It's 10-15 lines of instruction added to Step 0.

**Tests:** None (LLM behavior, not script logic). Validated during P0 real-world testing.

**Acceptance criteria:** `/forge --explain .claude/rules/use-vitest.md` shows the original evidence and proposal.

---

### P6. CI/CD setup
**Status:** Complete
**Priority:** MEDIUM — infrastructure.
**Goal:** Automated test runs on every PR.
**Impacts:** Reliability

**Shipped:**
- `.github/workflows/test.yml` — pytest on Python 3.8 + 3.9 matrix, triggers on push and PR
- Branch protection on `main` — requires passing CI, no direct pushes
- Fixed time-rotting test in `generate_fixtures.py` (`_BASE_TIME` now relative to current time)

**Acceptance criteria:** Tests run on PR, fail blocks merge. ✅

---

### P7. Deep analysis end-to-end validation
**Status:** Not started
**Priority:** LOW — verification task.
**Goal:** Verify the always-on LLM quality gate works end-to-end.
**Impacts:** Completeness

**Implementation plan:**

1. Accumulate 5+ sessions on a real project
2. Verify `background-analyze.py` invokes `claude -p --bare --model sonnet` after Phase A
3. Verify `deep-analysis.json` cache is written with `filtered_proposals` + `additional_proposals`
4. Run `/forge` — verify filtered proposals replace raw script proposals in output
5. Document any bugs and fix

**Files changed:** Bug fixes only — no planned structural changes.

**Acceptance criteria:** `/forge` shows LLM-filtered proposals when deep cache exists. Generic workflow proposals are filtered out.

---

## Completed Work Items (archived)

<details>
<summary>Click to expand completed items</summary>

### Scoring evaluation infrastructure (Task 3.6)
**Status:** Complete (v0.3.2)

### Qualitative feedback loop (Task 3.7)
**Status:** Complete (v0.3.5)

### Artifact effectiveness tracking (Task 3.5)
**Status:** Complete (v0.3.0)

### Reduce SKILL.md fragility
**Status:** Complete (v0.3.3)

### Consolidate `find_project_root()`
**Status:** Complete (v0.3.0)

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

</details>

---

## Phase Status

### Phase 1: Foundation (v0.1) — COMPLETE
### Phase 2: Full Artifact Coverage (v0.2) — COMPLETE
### Phase 3: Proactive Intelligence (v0.3) — COMPLETE

| Task | Status | Notes |
|------|--------|-------|
| 3.1 Background analysis on SessionStart | ✅ Done | SessionStart hook + background-analyze.py, 20 tests |
| 3.2 Between-task ambient nudge | ➡️ Replaced | Session-start nudge system via settings levels |
| 3.3 Session-start passive briefing | ✅ Done | Nudge levels: quiet/balanced/eager |
| 3.4 Stale config detection | ✅ Done | Cross-references artifacts against session data |
| 3.5 Artifact effectiveness tracking | ✅ Done | Track if corrections stop after artifact deployed |
| 3.6 Scoring evaluation | ✅ Done | 100% precision, 86.7% recall, 89.4% accuracy |
| 3.7 Qualitative feedback loop | ✅ Done | Dismissal reasons, impact calibration, safety gate, skip decay |

### Phase 4: Quality & Polish (v0.4) — Active

| Task | Status | Notes |
|------|--------|-------|
| 4.0-prereq Storage split | ✅ Done | v0.3.6 — feedback data to `.claude/forge/`, personal data stays `~/.claude/forge/` |
| 4.0 Real-world validation | ✅ Done | 3 projects validated. 0-22% raw acceptance. Applied-ID filter bug found. |
| 4.0a Script quality fixes | ✅ Done | v0.3.7 — staleness ratio-based, demotion scaling by context pressure, duplicate ID prevention |
| 4.0b LLM quality gate | ✅ Done | v0.3.7 — LLM always-on, session-analyzer filters proposals, analysis_depth removed |
| 4.1 Ambient presence | ❌ P1 | Proactive proposals at session start, effectiveness alerts, health signal |
| 4.2 Proposal presentation | ❌ P2 | "What changed", evidence improvements, feedback visibility, previews |
| 4.3 Reliability & error visibility | ❌ P3 | Schema validation, /forge --diagnose, mypy |
| 4.4 Analyzer unit tests | ✅ Done | 84 new tests (53 config, 31 memory), 15 shallow tests removed from existing files, fixture timing bug fixed |
| 4.5 Explain mode | ❌ P5 | /forge --explain with evidence trail |
| 4.6 CI/CD | ✅ Done | GitHub Actions, Python 3.8 + 3.9 matrix, CI-only branch protection on main |
| 4.7 Deep analysis e2e | ❌ P7 | Verify --deep works end-to-end |

### Phase 5: Advanced (v1.0) — Not started

| Task | Status | Notes |
|------|--------|-------|
| 5.1 Cross-project aggregation | ❌ Deferred | Opt-in only, requires privacy design |
| 5.2 Self-cost tracking | ❌ Not started | Token consumption reporting |
| 5.3 Export/share | ❌ Not started | Package config as shareable zip |

---

## Recently Completed

### LLM quality gate always-on (v0.3.7)
**Date:** 2026-04-04
Session-analyzer agent now has two jobs: filter script proposals for quality (remove generic patterns, human-in-loop violations, weak evidence, duplicates) and find additional patterns. `analysis_depth` setting removed -- LLM pass is implicit. Deep analysis runs after every background analysis cycle. New output format: `{filtered_proposals, additional_proposals, removed_count, removal_reasons}`. 11 new tests for deep analysis (prompt building, result caching, legacy format handling, error cases).

### Storage split: personal vs shared project data (v0.3.6)
**Date:** 2026-04-03
Feedback data (dismissed.json, history/applied.json, feedback_signals.json) moves to `.claude/forge/` (project-level, git-tracked). Personal settings, cache, pending proposals stay in `~/.claude/forge/`. 18 new tests (399 total).

### Feedback loop bugfixes (v0.3.5)
**Date:** 2026-04-03
Fixed tracking attribution (TYPE_TO_CATEGORY), skip count cleanup, SKILL.md clarity. 5 new tests (381 total).

### Qualitative proposal feedback loop (v0.3.4)
**Date:** 2026-04-01
Dismissal reasons, modification classification, per-category precision, impact deflation, safety gate, skip decay. 37 new tests.

### Background analysis on SessionStart (v0.2.8)
**Date:** 2026-03-31
SessionStart hook auto-triggers Phase A analysis. Detached background process, zero LLM cost. 20 new tests.

## Backlog
- `forge:cleanup` command — detect and remove orphaned `~/.claude/forge/projects/<hash>/` directories
- Hash collision resilience — bump project hash from 12 to 16 hex chars if user base grows
- Centralize path encoding utility in `project_identity.py` (minor DRY improvement)
- Extract fingerprint helper in `cache-manager.py` (minor DRY improvement)
