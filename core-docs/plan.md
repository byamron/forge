# Plan

## Current Focus

Parallel tracks: (1) real-world testing of Forge v0.2.6 via private marketplace install, (2) continuing development on remaining Phase 2 + Phase 3 features, and (3) synthetic test dataset infrastructure for pipeline integration testing.

## Handoff Notes

None.

## Spec & Roadmap

Original spec (`core-docs/spec.md`) and roadmap (`core-docs/roadmap.md`) are checked in. Phase/task references below map to the roadmap. Key deviations from spec:
- Three separate skills (`/forge:analyze`, `/forge:optimize`, `/forge:status`) were unified into `/forge`
- Artifact-generator agent was deleted (the `/forge` skill generates artifacts inline via Claude)
- MCP Elicitation (Task 2.6) was replaced with AskUserQuestion integration
- Ambient nudge (Task 3.2) was replaced with session-start nudge system
- Deep analysis mode was added (not in original roadmap) — background LLM pass for contextual patterns

## Active Work Items

### 0. User-level data storage migration
**Status:** Complete
**Goal:** Eliminate `.claude/forge/` from the project directory entirely. All Forge runtime data (decisions, caches, session log) stored in `~/.claude/forge/projects/<hash>/`, shared across worktrees, invisible to git.

Implemented:
- `project_identity.py` — shared module for project hash (git remote URL → SHA-256) and user data dir resolution
- All scripts updated: `finalize-proposals.py`, `cache-manager.py`, `read-settings.py`, `write-settings.py`, `check-pending.py`, `log-session.sh`
- Transparent migrate-on-read from legacy `.claude/forge/` location
- `project_identity.py` CLI for shell script interop
- 13 new tests in `test_project_identity.py`, cache manager tests updated
- Version bumped to 0.2.5

### 1. Real-world testing via marketplace install
**Status:** Starting
**Goal:** Validate the full plugin experience as a marketplace user, not a developer running `--plugin-dir`.

Testing surface:
- Install from private marketplace UI
- `/forge` — config health audit + pattern detection on real projects
- `/forge --deep` — LLM-enhanced analysis (background agent, proposal merging)
- Proposal review flow — approve/modify/skip/never decisions, artifact generation
- `/forge:settings` — nudge level and analysis depth configuration
- `/forge:version` — installed version and freshness reporting
- SessionEnd hooks — session logging and background cache warming
- Nudge behavior — session-start nudges based on unanalyzed session count

What to watch for:
- False positives/negatives in pattern detection
- UX friction (confusing output, too many steps, unclear proposals)
- Bugs in cross-worktree transcript discovery
- Generated artifact quality (rules, skills, hooks, CLAUDE.md entries)
- Performance (scripts should complete in <2s, deep mode <10s)
- Python 3.8 compat on target machines

### 2. Tier demotion / budget rebalancing (Task 2.5)
**Status:** Complete
**Goal:** Complete the tier management system — Forge can promote content up and now suggests moving bloated content down.

Implemented:
- Domain classifier groups placement issues by domain (react, python, testing, etc.)
- `find_demotion_candidates()` in analyze-config.py groups domain-specific CLAUDE.md entries and detects oversized rules (>80 lines)
- `_build_from_demotions()` in build-proposals.py creates `demotion` proposals with `demotion_detail` for two-step execution
- Budget-aware impact scoring (high when CLAUDE.md >200 lines, medium otherwise)
- SKILL.md updated with demotion handling: create new file + replace source content with one-line pointer
- `finalize-proposals.py` tracks `demotion` type under `tier_management` category
- 30 new tests covering domain classification, grouping, proposal generation, and budget rebalancing

### 3. Synthetic test dataset generator
**Status:** Complete
**Goal:** Create a Python test infrastructure that generates realistic project fixtures (files, transcripts, memory) exercising the full analysis pipeline, enabling fast integration testing across different project profiles.

Implemented:
- `tests/generate_fixtures.py` — generator with 5 profiles (swift-ios, react-ts, python-corrections, rust-minimal, fullstack-mature)
- `tests/test_integration_pipeline.py` — 39 integration tests running full pipeline on each profile
- `tests/conftest.py` — session-scoped fixtures for each profile
- Total test count: 119 → 160, all passing in <0.3s
- Standalone CLI for manual fixture generation

### 4. Stale config detection (Task 3.4)
**Status:** Done (v0.2.6)
**Goal:** Detect rules, skills, and CLAUDE.md entries that haven't been relevant in recent sessions.

Shipped:
- Cross-references existing artifacts against recent session transcripts via session text index + tool paths
- Flags artifacts not referenced in 15+ sessions (name match, keyword co-occurrence, slash-command match, glob-based path matching)
- Proposes archiving/removing stale content as `stale_artifact` proposals
- Reports stale artifact count in `/forge` health summary table
- Requires 10+ sessions minimum before running staleness analysis

### 5. Agent generation (Task 2.3)
**Status:** Done
**Goal:** Generate actual agent markdown from detected multi-phase workflow patterns.

Completed:
- Wired up `_build_from_workflows()` in `build_proposals()` (was defined but never called)
- Added descriptive workflow names via `_WORKFLOW_NAMES` lookup (plan-implement-verify, diagnose-and-fix, etc.)
- Replaced generic step descriptions with archetype-based templates (7 archetypes covering common patterns)
- Generated agents include proper frontmatter, tool constraints, evidence, and workflow steps
- 24 new tests covering the full pipeline

### 6. Reference doc extraction (Task 2.4)
**Status:** Partial (memory→reference works)
**Goal:** Auto-detect verbose CLAUDE.md entries and rules, extract to Tier 3 references.

Scope:
- Detect CLAUDE.md entries >3 lines that could be extracted
- Detect rule files exceeding budget (~50-100 lines)
- Generate reference doc with extracted content
- Replace original with a one-line pointer to the reference

### 7. Background analysis on SessionStart (Task 3.1)
**Status:** Not started
**Goal:** Auto-trigger analysis when enough unanalyzed sessions accumulate.

Scope:
- SessionStart hook checks unanalyzed session count against threshold
- Spawns background script-only analysis (no LLM tokens)
- Must not block session start or noticeably impact quota

### 8. Artifact effectiveness tracking (Task 3.5)
**Status:** Not started
**Goal:** After deploying an artifact, track whether the triggering pattern stops appearing.

Scope:
- Compare correction/pattern frequency before vs. after artifact deployment
- Report effectiveness in `/forge` health summary
- Suggest removing ineffective artifacts

---

## Phase Status

### Phase 1: Foundation (v0.1) — COMPLETE
All 11 tasks shipped. See `core-docs/history.md` for details.

### Phase 2: Full Artifact Coverage (v0.2) — ~70% complete

| Task | Status | Notes |
|------|--------|-------|
| 2.1 Skill generation | ✅ Done | Detects repeated prompts, generates SKILL.md templates |
| 2.2 Hook generation | ✅ Done | PostToolUse hooks for formatters/linters by tech stack |
| 2.3 Agent generation | ✅ Done | Workflow detection + archetype-based agent markdown generation |
| 2.4 Reference doc generation | ⚠️ Partial | Memory→reference works; no verbose CLAUDE.md extraction |
| 2.5 Tier promotion/demotion | ✅ Done | Promotion (memory→artifacts) + demotion (CLAUDE.md→rules, rules→references) |
| 2.6 MCP Elicitation | ➡️ Replaced | AskUserQuestion used instead; no MCP server |
| 2.7 Repeated prompt detection | ✅ Done | TF-IDF + Jaccard similarity, 4+ session threshold |
| 2.8 Post-action detection | ✅ Done | Write/Edit→Bash pattern detection across sessions |

**Remaining Phase 2 work:**
- Reference doc extraction (2.4) — detect verbose CLAUDE.md/rules and extract to Tier 3
- ~~Tier demotion (2.5) — move domain-specific CLAUDE.md entries to scoped rules, oversized rules to references~~ ✅

### Phase 3: Proactive Intelligence (v0.3) — ~30% complete

| Task | Status | Notes |
|------|--------|-------|
| 3.1 Background analysis on SessionStart | ❌ Not started | |
| 3.2 Between-task ambient nudge | ➡️ Replaced | Session-start nudge system via settings levels |
| 3.3 Session-start passive briefing | ✅ Done | Nudge levels: quiet/balanced/eager |
| 3.4 Stale config detection | ✅ Done | Cross-references artifacts against session data; 4 matching strategies |
| 3.5 Artifact effectiveness tracking | ❌ Not started | Track if corrections stop after artifact deployed |

### Phase 4: Advanced (v1.0) — Not started

| Task | Status | Notes |
|------|--------|-------|
| 4.1 Cross-project aggregation | ❌ Deferred | Opt-in only, requires privacy design |
| 4.2 Explain mode | ❌ Not started | "Why does this rule exist?" with evidence |
| 4.3 Self-cost tracking | ❌ Not started | Token consumption reporting |
| 4.4 Export/share | ❌ Not started | Package config as shareable zip |

---

## Recently Completed

### Enterprise hardening + test suite
**Date:** 2026-03-28
Python 3.8 compat fixes, credential leak prevention, text sanitization, 68-test suite, defense-in-depth scope isolation. Version bumped to 0.2.3.

### Infrastructure migration to standardized template
**Date:** 2026-03-28
Migrated dev infrastructure to the project template. See `core-docs/history.md` for full details.

### Phase 1 + Phase 2 core features
**Date:** 2026-03-25 to 2026-03-27
Full analysis pipeline (config, transcripts, memory), unified `/forge` command, settings system, deep analysis mode, marketplace distribution, security hardening. See `core-docs/history.md` for detailed entries.

## Backlog

### Transcript discovery integration tests
**Priority:** High — `find_all_project_session_dirs` is the most fragile production code path (5 strategies, subprocess calls, path encoding/decoding, worktree resolution) with zero integration test coverage. A regression here means Forge silently analyzes nothing or leaks cross-project data.

See `tests/DISCOVERY_TEST_PLAN.md` for detailed scope and approach.

### Scoring system evaluation and tuning
**Priority:** Medium — the correction classifier and theme clustering work on synthetic data but haven't been validated against real-world transcripts, where corrections are ambiguous and conversations are messy. Need a way to capture ground truth from real `/forge` runs and measure precision/recall systematically.

See `tests/SCORING_EVAL_PLAN.md` for detailed scope and approach.

### Other backlog
- CI/CD setup (prerequisite: test suite exists)
- Cross-project aggregation (Phase 4, opt-in only)
- `forge:cleanup` command — detect and remove orphaned `~/.claude/forge/projects/<hash>/` directories for deleted projects
- Hash collision resilience — bump project hash from 12 to 16 hex chars if user base grows significantly
