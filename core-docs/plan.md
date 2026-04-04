# Plan

## Current Focus

Post-review reprioritization (2026-04-03). Phase 4: Quality & Polish. Comprehensive code + UX review established that proposal quality and user trust are the highest-leverage areas. Roadmap organized by impact on: accuracy, UX, reliability, then completeness.

**Surface area constraint:** P0-P7 adds 1 new script (`diagnose.py`). Everything else modifies existing files. Zero new skills, agents, or hooks. The plugin stays focused on one job: analyze sessions, propose infrastructure improvements, learn from feedback.

## Handoff Notes

- Background deep analysis is implemented but untested end-to-end with `analysis_depth: "deep"`. Should verify the `claude -p --bare` invocation works on a real project.
- Labeled eval data at `tests/scoring_eval/labeled/*.json` (gitignored). 113 pairs labeled, classifier tuned to 100% precision / 86.7% recall.
- The feedback loop (v0.3.5) needs real-world validation — run `/forge` on a project, dismiss/modify proposals, then run `/forge` again to verify the calibration kicks in.
- Code review consensus: architecture is sound (B+ to A-), main gaps are error handling, test coverage for analyzers, and UX observability.

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
**Status:** Not started
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

---

### P1. Ambient presence and proactive surfacing
**Status:** Not started
**Priority:** HIGH — Forge runs 4 hooks every session but users can't tell. Without this, `/forge` feels manual.
**Goal:** High-confidence proposals surface at session start without running `/forge`. Users always know Forge is watching.
**Impacts:** UX

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
**Status:** Not started
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
**Status:** Not started
**Priority:** MEDIUM — infrastructure.
**Goal:** Automated test runs on every PR.
**Impacts:** Reliability

**Implementation plan:**

**New file:** `.github/workflows/test.yml`
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.8", "3.9"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install pytest
      - run: python -m pytest tests/ -v
```

**Acceptance criteria:** Tests run on PR, fail blocks merge.

---

### P7. Deep analysis end-to-end validation
**Status:** Not started
**Priority:** LOW — opt-in feature.
**Goal:** Verify `--deep` works end-to-end.
**Impacts:** Completeness

**Implementation plan:**

1. Enable `analysis_depth: "deep"` via `/forge:settings` on a real project
2. Accumulate 5+ sessions
3. Verify `background-analyze.py` invokes `claude -p --bare --model sonnet`
4. Verify `deep-analysis.json` cache is written
5. Run `/forge` — verify deep proposals merge into output
6. Test the two-phase question flow (script proposals presented first, deep proposals second)
7. Document any bugs and fix

**Files changed:** Bug fixes only — no planned structural changes.

**Acceptance criteria:** Deep proposals appear in `/forge` output after background analysis runs.

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
| 4.0 Real-world validation | ❌ P0 | Run /forge on 3+ real projects, measure acceptance rate |
| 4.1 Ambient presence | ❌ P1 | Proactive proposals at session start, effectiveness alerts, health signal |
| 4.2 Proposal presentation | ❌ P2 | "What changed", evidence improvements, feedback visibility, previews |
| 4.3 Reliability & error visibility | ❌ P3 | Schema validation, /forge --diagnose, mypy |
| 4.4 Analyzer unit tests | ❌ P4 | analyze-config.py and analyze-memory.py edge cases |
| 4.5 Explain mode | ❌ P5 | /forge --explain with evidence trail |
| 4.6 CI/CD | ❌ P6 | GitHub Actions, Python 3.8 + 3.9 matrix |
| 4.7 Deep analysis e2e | ❌ P7 | Verify --deep works end-to-end |

### Phase 5: Advanced (v1.0) — Not started

| Task | Status | Notes |
|------|--------|-------|
| 5.1 Cross-project aggregation | ❌ Deferred | Opt-in only, requires privacy design |
| 5.2 Self-cost tracking | ❌ Not started | Token consumption reporting |
| 5.3 Export/share | ❌ Not started | Package config as shareable zip |

---

## Recently Completed

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
