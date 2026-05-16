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
**Status:** Complete (v0.4.0). Directive-style systemMessage added in v0.4.1 to improve delivery reliability.
**Priority:** HIGH — Forge runs 4 hooks every session but users can't tell. Without this, `/forge` feels manual.
**Goal:** High-confidence proposals surface at session start without running `/forge`. Users always know Forge is watching.
**Impacts:** UX

**Design questions (resolved):**
1. **What is the right trigger?** Proposals ready is the signal. Background analysis runs every SessionStart; proposals surface when they exist.
2. **How do we guarantee visibility?** Resolved (2026-04-05). The `systemMessage` from SessionStart hooks is displayed directly in the Claude Code terminal UI as a startup notification — the user always sees it. The concern was about Claude not *mentioning* it in conversation, but that's irrelevant since the terminal notification is the guaranteed channel. Simplified the message to a concise notification: `"Forge has 3 proposals. Run /forge to review."` Stop hook and directive approaches were prototyped and rejected — see history.md.
3. **Does the nudge setting still make sense?** Collapsed to `proactive_proposals: true/false`.
4. **What does "quiet" actually mean?** Background analysis always runs. Quiet suppresses the ambient health signal but not proactive proposals or effectiveness alerts.

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

#### Step 6: Concise terminal notification for proposals (v0.4.1)

**Investigation (2026-04-05):** Researched Claude Code hook types. Key discovery: `systemMessage` from SessionStart hooks is displayed directly in the Claude Code terminal UI as a startup notification line — the user sees it without Claude needing to relay anything. This is already a guaranteed visibility channel. Stop hook (`decision: "block"`) and directive-style systemMessage were both prototyped and rejected — see history.md for details.

**File:** `forge/scripts/check-pending.py`
**Changes:**
- Simplified `_format_proactive_message()` to a concise terminal notification
- Before: multi-line message with proposal descriptions, evidence, occurrence counts (verbose, intended for Claude to relay in conversation)
- After: `"Forge has 3 proposals. Run /forge to review."` (clean, reads well in the terminal notification line)
- Proactive selection gate (`_select_proactive_proposals`) unchanged — notification only fires when high-confidence proposals exist

---

### P2. Proposal presentation improvements
**Status:** Complete (v0.4.3, reworked from v0.3.8)
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

### P8. Context-aware confidence scoring
**Status:** Not started
**Priority:** LOW — quality refinement. Current confidence gate works well but uses static thresholds.
**Goal:** Confidence scores account for context pressure, so proposals that matter more under pressure get surfaced.
**Impacts:** Accuracy

**Background:**
v0.4.2 added a confidence gate that filters `confidence != "high"`. This removed 55% of proposals — almost entirely noise (memory promotions, generic workflow agents). But the gate also filters proposals that *could* be valuable depending on context:

- **Rule-to-reference demotions** are always `"medium"` confidence. A 120-line rule is clearly worth extracting when CLAUDE.md is at 450/500 lines, but not worth the churn at 80/200. The confidence should depend on context pressure.
- **Verbose CLAUDE.md section demotions** (<8 lines) are `"medium"`. FB-0005 established that small demotions aren't worth it when CLAUDE.md has headroom, but should escalate when approaching budget.
- **Skills from repeated prompts** need 6+ occurrences for high confidence. A skill with 4 occurrences might still be valuable if the project has very few sessions (4/5 = strong signal vs 4/50 = weak signal).

**Key context for future implementation:**
- Anthropic's official guidance: ~200 lines for CLAUDE.md (upper bound ~500). No specific limit for individual rule files. Forge's 50-100 line rule budget is our convention, not Anthropic's.
- FB-0005: "Demotion impact should scale with context pressure." Currently partially addressed — impact scales with `over_budget` flag, but confidence does not.
- The confidence gate is binary (high or filtered). A future version could use a scoring function that weighs evidence strength against context state (CLAUDE.md line count, total rules count, etc.) to produce a continuous score, then apply a threshold.
- `analyze-config.py` already computes `context_budget` with line counts. This data is available to `build-proposals.py` but not currently used for confidence scoring.

**Possible implementation:**
1. Pass `context_budget` from config analysis into `build_proposals()`
2. Add a `_score_confidence()` function that takes evidence + context state
3. Demotion confidence scales with `budget_used / budget_target` ratio
4. Skill/agent confidence scales with `occurrences / total_sessions` ratio
5. Replace hardcoded `"high"/"medium"` assignments with `_score_confidence()` calls

**Not in scope:** Changing the gate itself. The binary high/medium split works — the improvement is in how proposals earn "high" confidence.

---

### P9. Session health analysis
**Status:** Not started
**Priority:** LOW — not blocking anything, but a genuine differentiator. Complements Claude Code's native `/usage` command and aligns with Anthropic's emphasis on session management as the #1 lever for Claude Code effectiveness.
**Goal:** Detect session health patterns from transcript data and generate fully actionable proposals — Forge reads the files, drafts the rules, and presents them for approval. Opt-in deep mode with higher LLM budget, justified by long-term token savings.
**Impacts:** UX, Accuracy

**Relationship to 5.2 Self-Cost Tracking:** 5.2 is introspection ("how much does Forge cost?"). P9 is user-facing value ("how can your sessions be more effective?"). They are orthogonal.

**Background:**
Recent Anthropic staff guidance (May 2026) positions session management as the primary lever for Claude Code effectiveness. Key points: context rot degrades performance around ~300-400k tokens; starting fresh sessions for new tasks is critical; rewind is preferred over correction; subagents are a context management tool. Claude Code's `/usage` command shows token consumption with generic tips. Forge can detect project-specific patterns and generate concrete artifacts to address them.

**Core principle:** Informational signals without actionable proposals don't meet Forge's bar. Forge's value is in doing the work: analyze, propose, apply. P9 must generate fully drafted artifacts the user can approve — not dashboards the user has to interpret.

**Positioning:** `/usage` says "you're using a lot of tokens." Generic guidance says "start new sessions for new tasks." Forge says "Claude reads `src/config.ts` in 87% of your sessions — here's a scoped rule summarizing its key facts so Claude doesn't need to re-read it. Approve?"

**Design decisions:**

1. **`intra_session_reread` signal cut.** Re-reading a file 3+ times within a session is normal read-modify-verify behavior, not waste (FB-0008 risk).

2. **`session_tool_paths` does not measure reads.** `_extract_file_paths()` pulls paths from all tools. P9 needs Read-specific tracking via tool name filtering.

3. **No new proposal type.** Frequent-read proposals use `type: "rule"`, sidechain proposals use `type: "agent"`. Reuses existing feedback calibration.

4. **One builder per LLM pass.** Both frequent-read rule proposals and sidechain-derived agent proposals come from the same `_run_session_health_analysis()` LLM invocation, so they are handled by a single builder (`_build_from_frequent_reads`) — kept separate from other builders, but unified for proposals sourced from the same cache. The builder dispatches on proposal `type` to apply the appropriate validation (rule vs agent paths).

5. **Two-tier architecture: regular + deep.** Regular mode (zero LLM cost) computes signals in Phase A scripts. Deep session health mode (opt-in, ~15-25K additional tokens) runs a second LLM pass that reads frequently-accessed files and drafts proposals. This mirrors the original regular/deep split but for a different purpose: the always-on quality gate filters proposals, the opt-in deep session analysis generates new ones from file access patterns.

6. **ROI justification for deep mode.** Reading a ~500-line file costs ~1-2K tokens once. A good scoped rule (3-5 lines) that prevents re-reading that file saves ~500-2K tokens per session. Over 10 sessions, that's 5-20K tokens saved. The deep analysis pass costs ~15-25K tokens and covers multiple files — ROI is positive within 1-2 analysis cycles if even one rule is useful.

7. **Sidechain counting architecture.** `parse_transcript()` doesn't know the session_id. Counting happens in `main()` via lightweight second pass. Deep mode additionally reads sidechain tool names (not full content) to determine purpose.

**Signals and their remedies:**

| Signal | Detection (regular, zero cost) | Remedy (deep, opt-in LLM) |
|--------|-------------------------------|---------------------------|
| Frequently-read files | Track Read tool paths across sessions | LLM reads the file, drafts a scoped rule summarizing key facts |
| Sidechain tool patterns | Count `isSidechain` entries per session; extract sidechain tool names | LLM examines tool patterns, determines if a purpose-built agent would consolidate repeated patterns |

**Signals dropped from earlier drafts:**
- **Session length (turn count):** No automatable remedy — Forge can't make a user start new sessions.
- **Context budget utilization:** Already covered by demotion proposals.
- **Early-turn corrections:** Overlaps with the existing correction builder (`_build_from_corrections`). The correction builder already detects repeated corrections and proposes rules. Adding turn-position weighting could be a future refinement to that builder, not a new signal.

**Implementation plan:**

#### Step 1: Signal detection (Phase A, zero cost)

**File:** `forge/scripts/analyze-transcripts.py`
**Changes:**
- Add `_extract_read_paths(tool_uses: list) -> List[str]` — like `_extract_file_paths` but filtered to `name == "Read"`. Existing function unchanged.
- Add `_extract_sidechain_summary(filepath: Path) -> Dict` — lightweight second pass over a JSONL file that, for entries with `isSidechain == True`, extracts only `tool_uses[].name` (not full content) and the user message text (truncated to 200 chars for context). Returns `{"count": int, "tool_names": List[str], "first_user_text": str}`. The first user text helps the LLM understand sidechain purpose without exposing full content.
- In `main()` output building, compute new fields:
  - `read_file_frequency: Dict[str, Dict]` — file path → `{"sessions": int, "total_sessions": int, "ratio": float}`. No pre-filter threshold.
  - `sidechain_summary: Dict[str, Dict]` — session_id → `{"count": int, "tool_names": List[str], "first_user_text": str}`. Computed from `_extract_sidechain_summary` per session file. ~50ms for 30 sessions.
- Existing `parse_transcript()` sidechain skip unchanged — sidechains remain excluded from correction/workflow analysis (regular pipeline). Only the new extraction function reads sidechain content for the deep analysis prompt.

#### Step 2: Deep session health analysis (opt-in LLM pass)

**New setting:** `session_health_analysis: true/false` (default: `false`). Configured via `/forge:settings`.

**File:** `forge/scripts/background-analyze.py`
**Changes:**
- After `_run_deep_analysis()` (the quality gate), check `session_health_analysis` setting.
- If enabled, call new `_run_session_health_analysis()`:
  1. Read cached `read_file_frequency` from transcripts cache
  2. Select top N files (N ≤ 5) with read ratio > 0.6 and sessions ≥ 3
  3. Read cached `sidechain_summary` — compute aggregate stats (avg count, total sessions with sidechains, common tool names)
  4. Build a prompt for a second `claude -p --bare --model sonnet` invocation:
     - Include the file paths and their read ratios
     - Include sidechain summary (avg count, session count)
     - Instruct the LLM: "Read each listed file. For each, determine if a scoped rule (3-5 lines, with `paths` frontmatter) summarizing its key facts would prevent Claude from needing to re-read it. Consider: what information does Claude typically need from this file? Is it stable enough that a rule won't go stale? Only draft a rule if the file contains stable configuration, conventions, or structure that Claude repeatedly needs. Output JSON with proposals matching the standard schema."
     - For sidechains: "Given the sidechain counts, if you detect patterns in tool usage, suggest a purpose-built agent. Otherwise, omit."
  5. Cache result as `session-health.json` alongside `deep-analysis.json`
  6. Timeout: 120s (same as existing deep analysis)

**File:** `forge/scripts/cache-manager.py`
**Changes:**
- When reading proposals (`--proposals`), load `session-health.json` if it exists and append its `additional_proposals` array to the proposal set. The deep analysis cache (`deep-analysis.json`) replaces script proposals (existing behavior). Session health proposals are additive — they don't replace anything. Order: deep-filtered script proposals first, then session-health additions, then deduplicated against dismissed/applied IDs by `build-proposals.py`.

**File:** `forge/scripts/build-proposals.py`
**Changes:**
- Add `_validate_session_health_proposal(proposal: Dict) -> bool` — validates LLM-drafted proposals before they enter the pipeline:
  1. Path security: must be within `.claude/rules/` (use `validate-paths.py` helper)
  2. Filename: kebab-case, ends in `.md`
  3. YAML frontmatter parses cleanly
  4. `paths` field is set (otherwise the rule loads in tier 1, defeating the purpose of the analysis)
  5. `suggested_content` non-empty and ≤ 100 lines (rules budget)
  6. Sanitize content via existing `_sanitize_text` (control char strip)
- Add `_build_from_frequent_reads(session_health_cache: Optional[Dict], existing_rules: List[Dict], existing_agents: List[Dict]) -> List[Dict]` — called when session-health cache exists. Reads proposals from cache, runs `_validate_session_health_proposal` on each, dispatches on proposal `type`:
  - `type: "rule"` → validate against `.claude/rules/`, dedup against `existing_rules` by `paths` overlap
  - `type: "agent"` → validate against `.claude/agents/`, dedup against `existing_agents` by name
  - Returns validated proposals with `origin: "session_health"`.
- Extend `build_proposals()` signature to accept `session_health_cache: Optional[Dict] = None` (keyword arg with default for backward compatibility). Caller (`cache-manager.py`) loads the cache and passes it in. Register the builder call in `build_proposals()`, gated on cache existence.

**File:** `forge/scripts/format-proposals.py`
**Changes:**
- Add origin handling for `origin: "session_health"` in `_extract_origin()`: "file access patterns (session health analysis)".

**File:** `forge/skills/settings/SKILL.md`
**Changes:**
- Add `session_health_analysis` option: "Deep session health analysis: reads your most-accessed files and drafts rules to reduce re-reading. Runs in background, costs ~15-25K tokens per cycle. Off by default."

**File:** `forge/scripts/read-settings.py`, `forge/scripts/write-settings.py`
**Changes:**
- Add `session_health_analysis: False` to the `DEFAULTS` dict in `read-settings.py` (line 17). The existing settings system filters unknown keys (line 44-45), so the key must be in `DEFAULTS` to be persisted.

#### Step 3: Tests

**File:** `tests/test_analyze_transcripts.py` — new tests:
- `test_extract_read_paths_filters_by_tool_name` — only Read tools
- `test_read_file_frequency_computation` — correct ratio across sessions
- `test_read_file_frequency_empty_sessions` — no tool uses → empty output
- `test_sidechain_summary_extraction` — correct count, tool names, truncated user text
- `test_sidechain_summary_truncates_user_text` — text capped at 200 chars
- `test_sidechain_still_skipped_for_analysis` — excluded from correction/workflow analysis (regression)

**File:** `tests/test_background_analyze.py` — new tests:
- `test_session_health_skipped_when_disabled` — setting off → no invocation
- `test_session_health_runs_when_enabled` — setting on → invocation attempted
- `test_session_health_selects_top_files` — only files above ratio threshold
- `test_session_health_cache_written` — result cached as session-health.json
- `test_session_health_timeout_handled` — timeout doesn't crash

**File:** `tests/test_build_proposals.py` — new tests:
- `test_frequent_read_proposal_uses_rule_type` — `type` is `"rule"`
- `test_frequent_read_deduplicates_against_existing_rules` — no proposal if rule exists for that file's path
- `test_session_health_proposal_validation_path_security` — paths outside `.claude/rules/` rejected
- `test_session_health_proposal_validation_filename` — non-kebab-case filenames rejected
- `test_session_health_proposal_validation_frontmatter` — proposals without `paths` field rejected
- `test_session_health_proposal_validation_content_length` — proposals over 100 lines rejected
- `test_session_health_proposals_merge_with_pipeline` — proposals appear in final output alongside normal proposals

Target: ~17 new tests.

**Version bump:** Required (changes to files under `forge/`).

**Token budget:**
- Regular mode (signal detection): 0 additional tokens
- Deep session health (opt-in): ~15-25K tokens per analysis cycle
  - File reads: ~5-15K (3-5 files × 1-3K each)
  - LLM reasoning + rule drafting: ~5-10K
  - Runs in background, same cadence as existing deep analysis

#### Step 4: Real-world validation (before declaring P9 complete)

P0 validation taught that classifier accuracy alone doesn't guarantee proposal quality (FB-0008). Before P9 is considered shipped:

1. Enable `session_health_analysis` on 2-3 real projects with established session history (Forge repo, portfolio-site, PriorityAppXcode, or similar).
2. Run background analysis. Wait for `session-health.json` cache to populate.
3. Run `/forge`. Record every session-health proposal: file targeted, drafted content, decision (approve/modify/skip/dismiss), reason if dismissed.
4. Compute acceptance rate. Target: >50% approval rate. If below, identify failure mode (e.g., volatile files, generic content, paths frontmatter issues) and tune the prompt.
5. Document validation results in plan.md under a P9 validation results section, mirroring the P0 validation results format.
6. Mark validation results clearly as agent-simulated vs user-decided per FB-0011.

**Acceptance criteria:**
- Regular mode: `read_file_frequency` and `sidechain_summary` computed correctly in transcript analysis output. Zero cost.
- Deep mode: when `session_health_analysis` is enabled, Forge reads frequently-accessed files, drafts scoped rules, and presents them as standard proposals in `/forge`.
- LLM-drafted proposals pass validation: valid path, kebab-case filename, parseable frontmatter with `paths` field, content non-empty and ≤ 100 lines.
- Proposals use `type: "rule"` (or `type: "agent"` for sidechain-derived) and integrate with existing feedback calibration (dismiss, approve, skip).
- A drafted rule for a frequently-read config file is specific to the file's actual content — not generic advice.
- Real-world validation: >50% approval rate across 2-3 real projects.
- All new tests pass, no existing tests regressed.
- Signal detection adds <100ms. Deep analysis runs within 120s timeout.

**Alignment notes:**
- **FB-0006 (LLM gate not optional):** P9 doesn't make the quality gate optional. The session-analyzer runs unchanged. P9 adds a *separate* opt-in feature with its own LLM budget. Quality is never degraded.
- **FB-0008 (memory promotion noise):** The validation step (Step 4) exists specifically to catch this failure mode. Drafted content that's generic or duplicates existing rules must be filtered before shipping.
- **FB-0011 (label simulated decisions):** Validation results must label whether decisions are agent-simulated.

**Open questions for implementation:**
- What is the right read-frequency threshold? >60% for deep analysis selection, >80% for high confidence? Needs real-world data.
- How to handle files that change frequently? A rule summarizing a volatile file will go stale. The LLM prompt should instruct: "Only draft rules for files with stable content (configuration, conventions, structure). Skip files that change frequently."
- Should the deep analysis prompt include the file's git change frequency to help the LLM decide? `git log --oneline <path> | wc -l` would add this signal cheaply.
- Can transcript data detect compaction events? If so, compaction frequency would be a high-value signal for a future iteration.

---

### P10. Synthesis boundaries (detect-always, surface-rarely)
**Status:** Not started
**Priority:** HIGH — biggest single insight transferred from Designer-Noticed. Resolves a long-standing UX pain: Forge re-evaluates and re-surfaces at every SessionStart, which makes the nudge frequency setting feel meaningless and trains users to ignore the terminal notification.
**Goal:** Split *detection* (background analysis, runs every SessionStart) from *surfacing* (terminal notification, fires only at meaningful boundaries). Proposals are always computed and cached; the notification only appears when a boundary has been crossed.
**Impacts:** UX, trust

**Origin:** Designer-Noticed splits its pipeline at a synthesis boundary — detectors fire on every event, but `AppCore::synthesize_pending()` only runs on track completion (debounced 30s) or first workspace-home view of the day per project. The result is a calmer feed where each notification reflects a genuine change in state. Forge has all the same primitives (background analysis on SessionStart, pending proposals cache, last-run cache from P2) but lacks the boundary gate.

**Design:**

Boundary triggers (any one fires the notification):
1. **New high-confidence proposals appeared** since last surface — strongest signal. Compare current pending IDs to `last-surfaced.json`.
2. **N new analyzed sessions** since last surface (default `5`) — accumulating evidence even if proposal set is unchanged.
3. **First session per UTC day** for this project — a daily check-in cadence, mirrors Designer's "first-daily-view" trigger.
4. **Effectiveness alert** for a previously applied artifact — already supported by P1 Step 2.

If none fire, `check-pending.py` stays silent even when pending proposals exist. The user can still run `/forge` manually any time — the cached proposals are not gated, only the notification is.

**Implementation plan:**

#### Step 1: Boundary state tracking

**New file:** `~/.claude/forge/projects/<hash>/last-surfaced.json`
```json
{
  "timestamp": 1730000000,
  "utc_date": "2026-05-16",
  "session_count_at_surface": 23,
  "proposal_ids": ["demote-claude-md-1", "rule-use-vitest"]
}
```

**File:** `forge/scripts/check-pending.py`
**Changes:**
- Add `load_last_surfaced(user_data_dir: Path) -> Dict` — reads the file, returns empty dict if missing.
- Add `write_last_surfaced(user_data_dir: Path, ...)` — atomic write, called only when a notification is actually emitted.

#### Step 2: Boundary gate

**File:** `forge/scripts/check-pending.py`
**Changes:**
- Add `_boundary_crossed(pending: List[Dict], last_surfaced: Dict, session_count: int, settings: Dict) -> Tuple[bool, str]` — returns `(should_surface, reason)`. Checks the four triggers in order, returns the first match. Reason string is for telemetry/debug, not user-facing.
- In `main()`: after computing `pending_count`, call `_boundary_crossed()`. If false, suppress the proposal notification (health signal still allowed per existing nudge_level logic).
- The deep-analysis-cache check stays in place (no notification until quality gate has run).

#### Step 3: Settings

**Files:** `forge/scripts/read-settings.py`, `forge/scripts/write-settings.py`, `forge/skills/settings/SKILL.md`
**Changes:**
- Add to `DEFAULTS`:
  - `surface_boundary_sessions: 5` — N new sessions trigger
  - `surface_boundary_daily: True` — first-of-day trigger on/off
- `nudge_level: "eager"` overrides the boundary gate (always surface when proposals exist, current behavior preserved as opt-in).
- `nudge_level: "quiet"` continues to suppress everything including boundary-triggered notifications.
- `nudge_level: "balanced"` (default) honors the boundary gate.

#### Step 4: Mark surface on `/forge` invocation

**File:** `forge/skills/forge/SKILL.md`
**Changes:**
- After Step 1 (loading proposals), record a surface event — even if the user runs `/forge` manually, that counts as having seen the current proposal set. Prevents the next SessionStart from immediately re-surfacing the same IDs.
- Implementation: small inline call to `check-pending.py --mark-surfaced` (new flag) or a dedicated `mark-surfaced.py` helper. Prefer the flag to avoid a new script.

**Tests:** ~8-10 new tests in `test_check_pending.py`:
- Boundary not crossed → no notification even with pending proposals
- New high-confidence proposal → surfaces
- N new sessions threshold → surfaces
- First-of-day → surfaces
- Same proposals + same day + < N sessions → silent (the new default behavior)
- `nudge_level: "eager"` bypasses boundary gate
- `nudge_level: "quiet"` suppresses everything
- `mark-surfaced` flag updates the state file correctly
- Effectiveness alert is independent of the boundary gate

**Files changed:** `check-pending.py`, `read-settings.py`, `write-settings.py`, `forge/skills/settings/SKILL.md`, `forge/skills/forge/SKILL.md`. Version bump required.

**Acceptance criteria:**
- Running with no changes between SessionStarts produces zero notifications.
- A genuinely new proposal triggers exactly one notification, not one per subsequent SessionStart.
- The daily check-in fires once per UTC date per project.
- Existing P1 effectiveness alerts continue to surface independently.

---

### P11. `window_digest` dedup across builders
**Status:** Not started
**Priority:** MEDIUM — incremental quality fix. Designer's per-detector window hash is cleaner than Forge's current ID-based dedup and catches "same evidence, slightly different proposal text" cases that today produce near-duplicates.
**Goal:** Every builder attaches a `window_digest` to each proposal. The pipeline dedupes on `(builder, window_digest)` before applying the existing dismissed/applied filters.
**Impacts:** Accuracy

**Origin:** Designer's `Finding` carries `window_digest: String` — a deterministic hash over the input window for that detector version. Two findings with the same digest are silently no-ops. This avoids the class of bug where two pipeline runs produce proposals with subtly different IDs but identical underlying evidence.

**Why this matters for Forge:** P0 validation found memory promotions duplicating correction-derived proposals (4× `promote-feedback-ios-build` duplicating `ios-simulator-build-rule`). The current ID-based dedup doesn't catch this because the IDs differ. A content-addressed digest does.

**Design:**

`_window_digest(builder_name: str, *evidence_parts: str) -> str` — SHA-1 of `builder_name | "|".join(evidence_parts)`, hex-truncated to 12 chars. Builder name is included so two builders generating semantically different proposals from the same evidence don't collide.

Each builder computes the digest from its stable input — e.g., the corrections builder uses the correction theme + the most-cited evidence line; the demotion builder uses the file path + start/end line range; the memory builder uses the memory entry's content hash.

**Implementation plan:**

#### Step 1: Add the helper

**File:** `forge/scripts/build-proposals.py`
**Changes:**
- Add `_window_digest(builder: str, *parts: str) -> str` near the top of the file (alongside existing helpers).
- Standard library only (`hashlib.sha1`).

#### Step 2: Attach digest in every builder

For each `_build_from_*` function (demotions, gaps, repeated_prompts, corrections, memory, workflows, staleness):
- Compute `window_digest = _window_digest(builder_name, *evidence_parts)` per proposal.
- Set `proposal["window_digest"] = window_digest`.

The choice of evidence parts is per-builder and documented in a docstring on each:
- `demotions`: `claude_md_section_id`
- `gaps`: `gap_type + tech_stack_signature`
- `repeated_prompts`: `prompt_theme + sorted(top_evidence_ids)`
- `corrections`: `correction_theme + sorted(top_evidence_ids)`
- `memory`: `entry_path + sha1(entry_content)[:8]`
- `workflows`: `sorted(tool_sequence)`
- `staleness`: `artifact_path`

#### Step 3: Dedup in `build_proposals()`

**File:** `forge/scripts/build-proposals.py` `build_proposals()` (line 1406)
**Changes:**
- Build `seen_digests: Set[str]` while iterating.
- If `p["window_digest"]` already in `seen_digests`, skip with a debug stderr line.
- Apply this filter *before* the existing `dismissed_ids` / `applied_ids` filters (faster; also dedup must be deterministic regardless of feedback state).

#### Step 4: Persist digest in dismissed and applied records

**File:** `forge/scripts/finalize-proposals.py`
**Changes:**
- When writing `dismissed.json` and `history/applied.json`, include `window_digest` on each entry.
- This unblocks a future change: dedup against dismissed/applied by digest rather than ID, so renaming a proposal doesn't bypass dismissal. Not in scope for P11 — just record the field now so historical data is usable later.

**Tests:** ~4-6 new tests in `test_build_proposals.py`:
- Same evidence in two builders → different digests (builder name disambiguates)
- Same evidence in two runs → same digest (deterministic)
- Two builders produce the same proposal kind from the same evidence → second one filtered
- Memory promotion + correction proposal targeting the same theme → digests differ (different builder names, different evidence parts) — confirms this is a separate problem, not solved by P11 alone (motivates P12-adjacent cleanup if data shows this is still common after P10/P11 ship)

**Files changed:** `build-proposals.py`, `finalize-proposals.py`. Version bump required.

**Acceptance criteria:**
- All proposals in `pending.json` have a `window_digest` field.
- Re-running `/forge` produces the same digests for unchanged evidence.
- Synthetic test profile that produces duplicate workflow proposals (today) produces one after P11.

---

### P12. New proposal kinds: removal & conflict-resolution
**Status:** Not started
**Priority:** MEDIUM — fills two real gaps in Forge's proposal taxonomy that Designer-Noticed exposed.
**Goal:** Two new builders covering pruning (`RemovalCandidate`) and contradiction detection (`ConflictResolution`). Both reuse existing proposal types where possible — no new types in the schema, just new origins.
**Impacts:** Accuracy, completeness

**Origin:** Designer's `ProposalKind` enum includes `RemovalCandidate`, `Demotion`, and `ConflictResolution`. Forge today has demotion only — and demotion fires only when CLAUDE.md is over-budget. Stale rules with low reference rate get *flagged* (staleness builder) but never proactively *removed*. And no builder detects when two rules contradict each other.

**Design:**

These are two independent builders that ship together for narrative cohesion. Either can be deferred individually.

**A. Removal candidate builder**

Today: `_build_from_staleness()` produces a "this rule is stale" notice but no removal proposal — the user has to act manually. Result: stale rules accumulate.

Change: when a rule meets stricter thresholds (reference ratio < 0.10 AND sessions_analyzed ≥ 10 AND age ≥ 30 days), emit a `type: "removal"` proposal with full `suggested_path` and the existing rule content as `current_content` (so the user sees what's being removed). Status: `pending`; on approve, `finalize-proposals.py` deletes the file (this is one of the two exceptions to the never-delete rule — must be added to `.claude/rules/security.md` with explicit gating).

Gating:
- Only files Forge generated (must appear in `history/applied.json`). Forge never proposes removal of user-authored content.
- User confirmation requires typing the rule filename — defense-in-depth against accidental approval. Implemented in `forge/skills/forge/SKILL.md` Step where removals are presented.

**B. Conflict resolution builder**

New builder `_build_from_conflicts(config: Dict, transcripts: Dict) -> List[Dict]`. Detects:
- Two rules with overlapping `paths` frontmatter that contain contradictory directives (LLM judgment required — runs as a small sub-task of the session-analyzer agent, not in Phase A).
- A CLAUDE.md entry contradicted by a more recent correction theme (e.g., CLAUDE.md says "use jest" but corrections show user always changes jest → vitest).

Output: `type: "rule"` proposal with `origin: "conflict_resolution"` and an explicit `resolves_conflict_between: [path1, path2]` field. The proposed rule synthesizes a single consistent directive; applying it doesn't auto-delete the conflicting rule, but the proposal description surfaces "Applying this also recommends removing/editing X".

**Implementation plan:**

#### Step 1: Removal candidate builder

**File:** `forge/scripts/build-proposals.py`
**Changes:**
- Add `_build_from_removals(config: Dict, transcripts: Dict, applied_history: List[Dict]) -> List[Dict]`.
- Threshold constants at top of file: `REMOVAL_REF_RATIO_MAX = 0.10`, `REMOVAL_MIN_SESSIONS = 10`, `REMOVAL_MIN_AGE_DAYS = 30`.
- Gate: only rules with `id` matching an entry in `applied_history`.
- Register in `build_proposals()` after the staleness builder.

**File:** `forge/scripts/finalize-proposals.py`
**Changes:**
- Handle `type: "removal"` in the apply path: validate the path is within `.claude/`, validate it appears in `applied_history`, then `Path.unlink()`.
- Record removal in `history/applied.json` with `action: "removed"` and original content snapshot in the record (for audit/recovery).

**File:** `forge/skills/forge/SKILL.md`
**Changes:**
- New section for removal proposals: show full content preview, require confirmation step. Don't bundle removals with other proposals in the same AskUserQuestion — present one at a time.

**File:** `.claude/rules/security.md`
**Changes:**
- Add removal proposals as the second explicit deletion exception (alongside the existing legacy `.claude/commands/*.md` migration).
- Document the gating rules: Forge-generated only, user re-confirms by typing filename, full content preserved in applied history.

#### Step 2: Conflict resolution builder

**File:** `forge/agents/session-analyzer.md`
**Changes:**
- Add a new task block to the prompt: "Detect contradictions between rules (overlapping `paths`, opposite directives) and between CLAUDE.md and recent correction themes. Output as proposals with `origin: 'conflict_resolution'`."
- This piggybacks on the existing deep-analysis LLM pass — no new LLM invocation.

**File:** `forge/scripts/build-proposals.py`
**Changes:**
- Add `_build_from_conflicts()` that reads the agent's output (already cached in `deep-analysis.json`), validates the structure, and emits proposals with `origin: "conflict_resolution"` and `resolves_conflict_between` metadata.

**File:** `forge/scripts/format-proposals.py`
**Changes:**
- New origin string for `conflict_resolution`: "contradiction with existing rule".
- When `resolves_conflict_between` is present, show "Applying this resolves a conflict with: X, Y" in the proposal description.

**Tests:** ~10-15 new tests:
- `test_removal_only_for_applied_rules` — user-authored rules never proposed for removal
- `test_removal_thresholds` — below thresholds → no proposal
- `test_removal_apply_unlinks_file` — file actually removed on approve
- `test_removal_apply_records_content_snapshot` — recovery data preserved
- `test_removal_path_traversal_rejected` — security boundary
- `test_conflict_resolution_origin` — origin string surfaces correctly
- `test_conflict_resolution_validates_agent_output` — malformed agent output dropped

**Files changed:** `build-proposals.py`, `finalize-proposals.py`, `format-proposals.py`, `forge/agents/session-analyzer.md`, `forge/skills/forge/SKILL.md`, `.claude/rules/security.md`. Version bump required.

**Acceptance criteria:**
- Removal proposals only target Forge-generated artifacts.
- Approval requires typing the filename; no bulk removal.
- Conflict resolution proposals identify the conflicting rules by path.
- Removed files are recoverable from `history/applied.json` content snapshots.

---

### P13. First-class signal events for threshold retuning
**Status:** Not started
**Priority:** LOW-MEDIUM — no immediate behavior change, but unlocks future threshold tuning (P8) and acceptance-rate analysis. Cheap to ship.
**Goal:** Add a lightweight append-only signal log (`signals.jsonl`) capturing every user interaction with a proposal (approve, dismiss with reason, skip, snooze, modify). Existing aggregate `feedback_signals.json` is preserved for backward compat; the new log gives per-event detail.
**Impacts:** Future accuracy, telemetry

**Origin:** Designer logs `FindingSignaled`, `ProposalSignaled`, and `ProposalResolved` as separate events with `(timestamp, finding_id, signal_type, reason)` tuples. Phase B reads the event stream to retune detector thresholds. Forge's `feedback_signals.json` is aggregate — useful for the safety gate but loses the per-event detail needed to answer "did this category's acceptance rate improve after we shipped X?".

**Design:**

**New file:** `.claude/forge/signals.jsonl` (project-level, git-tracked alongside other feedback data).

One JSON object per line:
```json
{"ts": 1730000000, "proposal_id": "rule-use-vitest", "window_digest": "abc123def456", "builder": "corrections", "type": "rule", "category": "rule", "signal": "approved", "modification": null}
{"ts": 1730000100, "proposal_id": "demote-claude-md-1", "window_digest": "...", "builder": "demotions", "type": "demotion", "category": "demotion", "signal": "dismissed", "reason": "low_impact"}
{"ts": 1730000200, "proposal_id": "agent-read-write-run", "window_digest": "...", "builder": "workflows", "type": "agent", "category": "agent", "signal": "skipped"}
```

Append-only. Never rewrites. File size cap: rotate to `signals.<n>.jsonl` at 5MB (uncompressed JSONL is small per event — this holds ~50k+ events).

**Implementation plan:**

#### Step 1: Append helper

**File:** `forge/scripts/finalize-proposals.py`
**Changes:**
- Add `_append_signal(project_root: Path, proposal: Dict, signal: str, reason: Optional[str] = None, modification: Optional[str] = None) -> None`.
- Atomic append: `open(..., "a")` with explicit `flush()`. JSONL doesn't need full atomicity since each line is self-contained.
- Path: `get_project_data_dir(project_root) / "signals.jsonl"`.

#### Step 2: Wire into outcome processing

**File:** `forge/scripts/finalize-proposals.py`
**Changes:**
- In the outcome loop where `_update_feedback_signals` is called, also call `_append_signal()` per outcome.
- Pass through `window_digest` (now present from P11) so the log entry is content-addressable.

#### Step 3: Rotation

**File:** `forge/scripts/finalize-proposals.py`
**Changes:**
- Before appending, check file size. If > 5MB, rename to `signals.<utc_date>.jsonl` and start a new file.

#### Step 4: Read helper (for future P8 use)

**File:** `forge/scripts/build-proposals.py`
**Changes:**
- Add `_load_recent_signals(project_root: Path, days: int = 90) -> List[Dict]` — reads `signals.jsonl` and any rotated files within the time window. Returns flat list.
- Not used in P13 itself. Adds the read path so P8 (context-aware confidence scoring) can consume it without further plumbing.

**Tests:** ~4-6 new tests in `test_finalize_proposals.py`:
- `test_signal_append_writes_jsonl` — file exists, each line is valid JSON
- `test_signal_includes_window_digest` — digest present
- `test_signal_rotation_at_5mb` — rotation triggers, new file empty
- `test_load_recent_signals_filters_by_age` — read helper respects window
- `test_signal_append_atomic_under_concurrent_writes` — two finalizers don't corrupt the log

**Files changed:** `finalize-proposals.py`, `build-proposals.py`. No version bump beyond what P10-P12 already required.

**Acceptance criteria:**
- Every proposal interaction produces exactly one line in `signals.jsonl`.
- The aggregate `feedback_signals.json` continues to be written (no behavior regression).
- `_load_recent_signals()` returns parseable data ready for P8 consumption.

---

### P14. Designer co-installation probe (defensive)
**Status:** Deferred indefinitely (Designer is not shipping in its current form per 2026-05-16 direction change)
**Priority:** SKIP unless Designer ships a learning layer that overlaps with Forge's detectors.
**Goal:** When Designer is installed and emitting findings for overlapping detectors, Forge defers to avoid double-surfacing.

**Origin:** Designer-Noticed includes a Forge probe (`if ~/.claude/plugins/forge/ exists, disable overlapping detectors`). Symmetric: Forge could probe for Designer. Not worth implementing speculatively.

If revisited: probe `~/.designer/` or whatever Designer's install path becomes, read its detector manifest, suppress matching Forge builders for that project. ~20 LOC + 3 tests.

---

## Native Build Possibilities

The work on Designer-Noticed surfaced architectural patterns that Forge can't fully adopt as a plugin but should consider if Forge ever moves into a native runtime. These possibilities and migration considerations are documented in `core-docs/native-build-possibilities.md`.

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
| 4.8 Context-aware confidence | ❌ P8 | Confidence scoring accounts for context pressure |
| 4.9 Session health analysis | ❌ P9 | Opt-in deep analysis of file access patterns → LLM-drafted rules |
| 4.10 Synthesis boundaries | ❌ P10 | Detect-always, surface-rarely (ported from Designer-Noticed) |
| 4.11 Window digest dedup | ❌ P11 | Per-builder content-addressed dedup (ported from Designer-Noticed) |
| 4.12 Removal & conflict resolution kinds | ❌ P12 | New builders for proactive pruning + rule contradictions |
| 4.13 First-class signal events | ❌ P13 | Append-only signals.jsonl for future threshold retuning |
| 4.14 Designer co-installation probe | ⏸ Deferred | Skip unless Designer ships a learning layer |

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
