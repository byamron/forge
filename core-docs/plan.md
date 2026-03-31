# Plan

## Current Focus

Parallel tracks: (1) real-world testing of Forge v0.2.3 via private marketplace install, and (2) continuing development on remaining Phase 2 + Phase 3 features.

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
**Status:** Not started
**Goal:** Complete the tier management system — Forge can promote content up but can't yet suggest moving bloated content down.

Scope:
- Detect domain-specific CLAUDE.md entries → suggest moving to scoped rules
- Detect oversized rules → suggest extracting detail to Tier 3 references
- Budget rebalancing — when CLAUDE.md exceeds threshold, prioritize which entries to demote
- Leave one-line pointers in the original location after extraction

### 3. Stale config detection (Task 3.4)
**Status:** Not started
**Goal:** Detect rules, skills, and CLAUDE.md entries that haven't been relevant in recent sessions.

Scope:
- Cross-reference existing artifacts against recent session transcripts
- Flag artifacts that were never triggered/referenced in the last N sessions
- Suggest archiving or removing stale content
- Report in `/forge` health summary

### 4. Reference doc extraction (Task 2.4)
**Status:** Partial (memory→reference works)
**Goal:** Auto-detect verbose CLAUDE.md entries and rules, extract to Tier 3 references.

Scope:
- Detect CLAUDE.md entries >3 lines that could be extracted
- Detect rule files exceeding budget (~50-100 lines)
- Generate reference doc with extracted content
- Replace original with a one-line pointer to the reference

### 5. Agent generation (Task 2.3)
**Status:** Done
**Goal:** Generate actual agent markdown from detected multi-phase workflow patterns.

Completed:
- Wired up `_build_from_workflows()` in `build_proposals()` (was defined but never called)
- Added descriptive workflow names via `_WORKFLOW_NAMES` lookup (plan-implement-verify, diagnose-and-fix, etc.)
- Replaced generic step descriptions with archetype-based templates (7 archetypes covering common patterns)
- Generated agents include proper frontmatter, tool constraints, evidence, and workflow steps
- 24 new tests covering the full pipeline

### 6. Background analysis on SessionStart (Task 3.1)
**Status:** Not started
**Goal:** Auto-trigger analysis when enough unanalyzed sessions accumulate.

Scope:
- SessionStart hook checks unanalyzed session count against threshold
- Spawns background script-only analysis (no LLM tokens)
- Must not block session start or noticeably impact quota

### 7. Artifact effectiveness tracking (Task 3.5)
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
| 2.5 Tier promotion/demotion | ⚠️ Partial | Promotion works (memory→artifacts); no demotion or budget rebalancing |
| 2.6 MCP Elicitation | ➡️ Replaced | AskUserQuestion used instead; no MCP server |
| 2.7 Repeated prompt detection | ✅ Done | TF-IDF + Jaccard similarity, 4+ session threshold |
| 2.8 Post-action detection | ✅ Done | Write/Edit→Bash pattern detection across sessions |

**Remaining Phase 2 work:**
- Reference doc extraction (2.4) — detect verbose CLAUDE.md/rules and extract to Tier 3
- Tier demotion (2.5) — move domain-specific CLAUDE.md entries to scoped rules, oversized rules to references

### Phase 3: Proactive Intelligence (v0.3) — ~30% complete

| Task | Status | Notes |
|------|--------|-------|
| 3.1 Background analysis on SessionStart | ❌ Not started | |
| 3.2 Between-task ambient nudge | ➡️ Replaced | Session-start nudge system via settings levels |
| 3.3 Session-start passive briefing | ✅ Done | Nudge levels: quiet/balanced/eager |
| 3.4 Stale config detection | ❌ Not started | Detect unused rules/skills/CLAUDE.md entries |
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

- CI/CD setup (prerequisite: test suite exists ✓)
- Cross-project aggregation (Phase 4, opt-in only)
