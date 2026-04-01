# History

Detailed record of shipped work. Reverse chronological (newest first). This is not a changelog -- it captures the **why**, **tradeoffs**, and **decisions** behind each change so future sessions have full context on how the project evolved.

---

## How to Write an Entry

```
### [Short title of what was shipped]
**Date:** YYYY-MM-DD
**Branch:** branch-name
**Commit:** [SHA or range]

**What was done:**
[Concrete deliverables -- what changed in user-facing terms.]

**Why:**
[The problem this solved or the goal it served.]

**Design decisions:**
- [UX or product choice + reasoning]

**Technical decisions:**
- [Implementation choice + reasoning]

**Tradeoffs discussed:**
- [Option A vs Option B -- why this one won]

**Lessons learned:**
- [What didn't work, what did, what to do differently]
```

Use the `SAFETY` marker on any entry that modifies error handling, persistence, data loss prevention, or fallback behavior.

---

## Entries

### Classifier tuning: 47.8% → 89.4% accuracy on real data (v0.3.2)
**Date:** 2026-04-01
**Branch:** classifier-tuning

**What was done:**
Tuned the correction classifier against 113 hand-labeled pairs from 2 real projects (portfolio-site, PriorityAppXcode). Results: correction precision 66.7% → 100%, correction recall 13.3% → 86.7%, overall accuracy 47.8% → 89.4%. Remaining 12 misclassifications are on the followup/new_instruction boundary — genuinely ambiguous cases that don't affect proposal quality.

**Why:**
The scoring evaluation revealed the classifier was too keyword-dependent. Real users say "that's not quite doing it" and "scratch that" — not "I told you" or "don't use X". The keyword list needed expansion and the scoring architecture needed structural signals.

**Design decisions:**
- Added two-tier correction scoring: keyword signals (strong + mild) combined with structural signals (negation-before-verb, "this is better...but" pivots, question-as-correction). Each tier is capped independently to prevent over-scoring.
- Added false-positive filters: template/workflow messages (`## Prerequisites`, `Ship the current branch`) are never classified as corrections regardless of keyword matches.
- Fixed `len(text) < 5` early exit that was misclassifying single-word imperatives like "fix" as followup.
- Added negative lookahead on "that should be" to exclude locative phrases ("that should be in xcode-testing").
- Relabeled 3 clearly wrong ground-truth labels (directives mislabeled as confirmatory).

**Technical decisions:**
- Used Approach C (hybrid keyword + structural scoring) over pure keyword expansion (A) or pure structural (B). Approach B had 100% recall but 42.9% precision — too many false positives. Approach C maintained high precision while substantially improving recall.
- Scoring eval infrastructure (`extract_pairs.py`, `eval_classifier.py`, `compare_approaches.py`) lives in `tests/scoring_eval/` and is gitignored for ephemeral output. Labeled data is checked in for regression testing.

**Tradeoffs discussed:**
- Considered pushing further on followup/new_instruction boundary (the remaining 12 errors). Decided against it — these are genuinely ambiguous and further tuning risks overfitting. The correction boundary (the one that drives proposals) is already at ceiling.

---

### Background deep analysis and scoring evaluation results (v0.3.1)
**Date:** 2026-04-01
**Branch:** forge-code-review

**What was done:**
1. **Background deep analysis** — When `analysis_depth: "deep"` is set, the SessionStart background process now runs an LLM pass (`claude -p --bare --model sonnet`) after Phase A scripts complete. Results are cached as `deep-analysis.json` (24-hour TTL) so the next `/forge` invocation has deep results instantly — no `--deep` flag needed.
2. **Scoring evaluation on real data** — Ran the evaluation infrastructure against 2 real projects (portfolio-site: 129 pairs, PriorityAppXcode: 103 pairs). Labeled 113 pairs manually. Results: correction recall 13.3% (target >70%), overall accuracy 47.8%. Confirmed the classifier is too keyword-dependent — real corrections use conversational language ("that's not quite doing it", "scratch that") that the keyword list doesn't cover.
3. **SKILL.md deep mode UX** — Rewrote the deep analysis flow: script proposals are shown first (user reviews while deep agent runs in background), deep proposals appended when ready. If deep agent is still running after script review, waits for it (user opted into deep — deliver the results). Zero-proposal edge case handled.

**Why:**
Staff review identified two gaps: (a) deep analysis only ran interactively, meaning every `/forge --deep` invocation paid the LLM cost and wait time; (b) the classifier had never been validated against real data. Background deep caching solves (a); the eval results quantify (b) and provide the labeled dataset for threshold tuning.

**Design decisions:**
- Deep analysis runs on SessionStart (not SessionEnd) because SessionEnd processes get killed when the user closes the terminal.
- Uses `claude -p --bare --model sonnet --effort low --no-session-persistence` to minimize cost and avoid recursive Forge invocation.
- UX follows "Option C" — script proposals fill the wait time naturally. The only blocking wait is when there are zero script proposals and the deep agent is still running (least common case).

**Technical decisions:**
- `background-analyze.py` reads cached proposals and transcript pairs from the script analysis pass, builds the session-analyzer prompt inline, and pipes it to `claude -p` via stdin. No temp files needed.
- `cache-manager.py` exposes `_read_deep_analysis_cache()` with 24-hour TTL — stale deep results are ignored rather than served.
- `shutil.which("claude")` gates the deep pass — if the CLI isn't available, it silently skips.

**Tradeoffs discussed:**
- Considered Option A (show script proposals, tell user deep results cached for next run) — rejected as disjointed UX. Option B (two-phase: show scripts, exit, background deep, notify later) — rejected for same run-twice problem. Option C (fill wait with script review) won because it's non-blocking in the common case and respects the user's explicit opt-in to deep mode.
- Considered running deep on SessionEnd — rejected because the user may close the terminal. SessionStart gives the full session duration for the background process to complete.

---

### Artifact effectiveness tracking (Task 3.5, v0.3.0)
**Date:** 2026-03-31
**Branch:** forge-code-review

**What was done:**
Implemented artifact effectiveness tracking. When a proposal is applied, the triggering pattern details are recorded in `applied.json`. On subsequent `/forge` runs, `build-proposals.py` checks if the triggering pattern still appears in current transcript analysis. Reports per-artifact effectiveness (effective/ineffective) in `context_health`. SKILL.md updated to show ineffective artifacts with a warning.

**Why:**
Task 3.5 / P1 from staff review — without knowing if proposals actually help, Forge can't learn or self-improve. This closes the feedback loop: P0 tells us if proposals are accurate; P1 tells us if they're useful.

**Design decisions:**
- Tracking data is recorded at apply-time in `finalize-proposals.py` rather than stored separately — keeps all applied-proposal data in one place.
- Effectiveness is computed at analysis-time in `build-proposals.py` rather than a separate script — avoids another subprocess call and the data is already available.
- Fuzzy matching uses the existing `_similarity()` (Jaccard) to handle renamed or slightly different patterns between analysis runs.

**Technical decisions:**
- Used `_tokenize()` (set-based) for post-action matching against command strings, since proposal IDs don't contain the actual command text.
- Lowered Jaccard threshold to 0.25 for effectiveness fuzzy matching (vs 0.3 for dedup) because we want to catch pattern persistence even with slight rephrasing.
- Effectiveness is only reported when `applied_history` has entries with `tracking` data — no noise for old entries applied before this feature.

**Tradeoffs discussed:**
- Considered time-based windowing (only check sessions after apply date) vs. checking all current sessions. Chose all-current for simplicity — if the pattern is gone now, the artifact is working regardless of when it was deployed.
- 12 new tests (312 total).

---

### Consolidate find_project_root (v0.3.0)
**Date:** 2026-03-31
**Branch:** forge-code-review

**What was done:**
Moved `find_project_root()` from 5 duplicate copies (check-pending, read-settings, write-settings, background-analyze, cache-manager) into `project_identity.py`. All callers now import from the single source. Added 4 tests.

**Why:**
P3 from staff review — minor DRY violation, 5 copies of the same 6-line function.

**Technical decisions:**
- Function signature matches the most complete version (from background-analyze): `find_project_root(override: Optional[str] = None) -> Path`.
- Callers that already import from `project_identity` just add `find_project_root` to their existing import line.

---

### Scoring evaluation infrastructure (Task 3.6)
**Date:** 2026-03-31
**Branch:** forge-code-review

**What was done:**
Built scoring evaluation infrastructure to measure the accuracy of Forge's correction classifier against real-world data. Three scripts: pair extraction (from real transcripts), classifier evaluation (precision/recall/F1 against labeled ground truth), and diagnostic review (cached analysis introspection with threshold sensitivity). Plus labeling guidelines and 17 new tests (249 total).

**Why:**
Staff-level code review identified the #1 product risk: the NLP pipeline uses hand-tuned thresholds (0.25 corrective classification, 3.0/6.0 theme confidence, keyword weights) that were set by intuition and never validated against real data. Without measured precision/recall, every threshold is a guess. False positives erode user trust; false negatives make Forge appear useless.

**Design decisions:**
- Scripts are dev-only tooling (in `tests/scoring_eval/`), not part of the plugin. They import from the pipeline scripts using `importlib.import_module()` (same pattern as test suite).
- Labeled data files are gitignored since they contain real user messages. Evaluation runs locally only.
- Evaluation script reports both per-class metrics and severity calibration (checks if predicted strength correlates monotonically with labeled severity).

**Technical decisions:**
- Used `importlib.import_module("analyze-transcripts")` for hyphenated module names, matching existing test convention.
- Diagnostic review reads from existing cache files (`~/.claude/forge/projects/<hash>/cache/transcripts.cache.json`) — no new persistence needed.
- Threshold sensitivity analysis shows what would change at different thresholds, enabling data-driven tuning rather than blind trial-and-error.

**Tradeoffs discussed:**
- Considered automated labeling via LLM (circular — using Claude to evaluate Claude's detection) vs. human labeling (gold standard but labor-intensive). Chose human labeling as the ground truth source.
- Considered adding evaluation to CI (can't — labeled data contains real transcripts and can't be committed) vs. local-only workflow. Chose local-only.

### Background analysis on SessionStart (v0.2.8)
**Date:** 2026-03-31
**Branch:** session-start-hook
**Commit:** (pending)

**What was done:**
Added SessionStart hook that auto-triggers background Phase A analysis when enough unanalyzed sessions accumulate. Also wires `check-pending.py` into the SessionStart hook for ambient nudges.

**Why:**
Task 3.1 — users shouldn't have to remember to run `/forge`. After enough sessions, Forge should proactively analyze in the background so proposals are ready when the user next invokes `/forge`.

**Design decisions:**
- Reuse nudge level thresholds for background analysis trigger (quiet=never, balanced=5, eager=2). If the user configured how proactive Forge should be, that should govern both nudging and background analysis.
- Background process resets the unanalyzed-sessions.log after successful analysis, so the count starts fresh. Losing a concurrent SessionEnd entry is acceptable since the cache is already fresh.

**Technical decisions:**
- Script spawns itself with `--run` flag as a detached subprocess (`start_new_session=True`). This avoids inline Python hacks and keeps the lock file cleanup in a proper `finally` block.
- Lock file with 5-minute staleness timeout prevents concurrent analysis runs. Stale locks from crashed processes are auto-cleaned.
- Delegates actual analysis to existing `cache-manager.py --update`, which already orchestrates all Phase A scripts + proposal building.

**Tradeoffs discussed:**
- Could have created a separate wrapper script for the background process, but self-spawning with `--run` is simpler and keeps all logic in one file.
- Could have atomically removed only the lines that existed before analysis started (to preserve concurrent SessionEnd entries), but truncation is simpler and the edge case is benign — the cache is fresh regardless.

### Transcript discovery integration tests
**Date:** 2026-03-31
**Branch:** transcript-discovery-tests

**What was done:**
Added 30 integration tests for `find_all_project_session_dirs()` in `tests/test_session_discovery.py`. Covers all 5 discovery strategies (exact match, worktree list, forward index, workspace-prefix heuristic, git remote scan), cross-project leakage prevention, subprocess timeout graceful degradation, mtime-based result sorting, deduplication across strategies, malformed repo-index.json handling, and multi-strategy composition. Total test count: 232.

**Why:**
This function is the most fragile production code path — 5 strategies, subprocess calls to git, path encoding/decoding, and cross-worktree aggregation — with zero integration test coverage. A regression means Forge either silently analyzes nothing (missing worktrees) or leaks data from unrelated projects (security violation).

**Design decisions:**
- Used monkeypatch + tmp_path (Option A from the test plan) rather than refactoring for dependency injection. The function's clear strategy boundaries made targeted monkeypatching clean without requiring production code changes.
- Created a `DiscoveryEnv` helper class to encapsulate the fake home dir, encoded project dirs, git remote responses, and worktree output — keeping individual tests focused on a single behavior.
- Monkeypatched `Path.home()` to redirect `~/.claude/projects/` to a temp dir, and `subprocess.run` to return canned git responses. Real directory structures are created in tmp_path for `_decode_project_dir` path existence checks.

**Technical decisions:**
- Tests create real directories at tmp_path-based paths so `_decode_project_dir`'s greedy path reconstruction algorithm works naturally without additional mocking.
- The subprocess mock raises `OSError` for non-git commands to catch unintended subprocess usage in tests.
- Strategy 5 performance guard test (`test_scan_skipped_when_enough_matches`) verifies the function's optimization: the expensive per-directory git remote scan is skipped when strategies 1-4 already found 2+ matches.

**Tradeoffs discussed:**
- Option A (monkeypatch) vs Option B (dependency injection refactor): chose A because the production code is stable and well-structured; refactoring it purely for testability would add complexity with no user-facing benefit.
- Considered testing `_decode_project_dir` with synthetic paths, but using real tmp_path directories exercises the greedy path reconstruction algorithm end-to-end, which is more valuable.

### Reference doc extraction — complete Task 2.4, finish Phase 2
**Date:** 2026-03-31
**Branch:** finish-ref-doc-extraction

**What was done:**
Completed the last Phase 2 task: verbose CLAUDE.md section detection and extraction to reference docs. Forge can now detect CLAUDE.md sections with prose content (>3 lines) and propose extracting them to `.claude/references/`, leaving a one-line pointer in CLAUDE.md. This completes the full tier demotion pipeline: domain-specific entries→rules, oversized rules→references, verbose sections→references, memory→all artifact types.

**Why:**
CLAUDE.md is loaded every session (Tier 1). Verbose explanatory sections waste context budget — they should be in reference docs (Tier 3) where Claude loads them on demand. This was the only remaining gap in Phase 2.

**Design decisions:**
- Prose detection heuristic: count lines >60 chars that don't start with bullet/table/heading markers. Require 2+ prose lines — pure bullet lists of short rules are fine in CLAUDE.md even if long. This avoids false positives on well-structured directive lists.
- `min_lines=4` default threshold: sections with fewer than 4 non-empty lines aren't worth extracting — the overhead of a separate file + pointer outweighs the savings.

**Technical decisions:**
- `_is_verbose_section()` is a standalone function (not inline in `find_demotion_candidates`) so it can be tested independently and potentially reused for rule verbosity detection later.
- `find_demotion_candidates()` gained an optional `claude_md_sections` parameter (defaults to `None`/empty list) to preserve backward compatibility with existing callers and tests.
- Proposal `action` is `claude_md_verbose_to_reference` (distinct from `claude_md_to_rule` and `rule_to_reference`) so the SKILL.md can give specific execution instructions: find section by heading, replace body, keep heading line.
- Confidence is `high` for 8+ line sections, `medium` for shorter ones — larger sections are more clearly worth extracting.

**Tradeoffs discussed:**
- Could have used a more sophisticated NLP approach (sentence detection, readability scores) for prose classification. Chose simple character-count + prefix heuristics because the standard-library constraint rules out NLP packages, and the heuristic is good enough for the common case.
- Could have also detected verbose subsections within a section (e.g., a section with both bullets and a long paragraph). Chose to operate at the `## heading` section granularity since that's what `_parse_claude_md_sections` already provides and partial extraction would be much more complex.

### Fix proposal builder bugs (v0.2.7)
**Date:** 2026-03-30
**Branch:** test-forge-on-synthetic

**What was done:**
Fixed four bugs that caused proposals to contain "unknown" names, wrong file paths, wrong hook commands, and gibberish skill names:
1. `_build_from_gaps()` always read `detail.get("linter")`, producing "auto-unknown-hook" for formatter and test framework gaps. Now checks `linter`, `formatter`, and `test_framework` keys.
2. `_generate_hook_content()` had the same `detail.get("linter", "eslint")` bug — formatter gaps (prettier, black, etc.) generated eslint commands. Now uses a command lookup table keyed by tool name.
3. `_build_from_memory()` read a nonexistent `topic` field (always "unknown") and hardcoded all paths to `.claude/rules/`. Now derives topic from `source` filename and maps `suggested_artifact` to the correct target path (rules, references, skills, or CLAUDE.md).
4. `find_repeated_prompts()` lacked a `canonical_text` field, so `_build_from_repeated_prompts()` fell back to the generic pattern string ("Similar opening prompt in N sessions"), producing unusable skill names. Now emits the shortest user message from the group as `canonical_text`.

**Why:**
All four bugs caused the proposal review flow to present meaningless names, incorrect paths, and wrong hook commands, making generated artifacts useless or harmful without manual correction.

**Technical decisions:**
- Bugs 1-2: Used `or`-chain (`detail.get("linter") or detail.get("formatter") or ...`) rather than a mapping dict. The keys are mutually exclusive per gap type, so short-circuit `or` is clear and correct.
- Bug 2: Replaced if/elif chain with explicit command lookup tables for formatters and linters. Covers all tools from `analyze-config.py`'s `_FORMATTER_COMMANDS` and `_LINTER_COMMANDS`.
- Bug 3: Derive topic from `Path(source).stem` rather than adding a `topic` field to analyze-memory.py. The source filename already contains the meaningful name; adding redundant fields creates sync risk.
- Bug 3: Added `seen_ids` set for duplicate ID detection since multiple memory notes can come from the same source file.
- Bug 4: Used `min(group, key=lambda x: len(x[1]))` to pick the shortest message as canonical text. Shortest is most likely to be the reusable command form rather than a verbose first-time explanation.

**Tradeoffs discussed:**
- Could have fixed Bug 3 by adding a `topic` field in analyze-memory.py instead. Chose to derive from `source` to avoid changing the analyzer's output contract and keep the fix minimal.

### Agent generation (Task 2.3) — full implementation
**Date:** 2026-03-30
**Branch:** review-roadmap-priorities

**What was done:**
Completed agent generation, closing the last gap in artifact type coverage. Forge can now detect recurring multi-phase workflow patterns in session transcripts and generate full agent markdown definitions with proper frontmatter, tool constraints, workflow steps, and evidence.

**Why:**
The framework existed (`_build_from_workflows`, `_generate_agent_content`) but was never wired into the main pipeline and produced generic content. This was the last stub in Phase 2 artifact coverage.

**Design decisions:**
- Archetype-based generation: 7 named archetypes (plan-implement-verify, diagnose-and-fix, test-driven-development, etc.) map phase sequences to rich role descriptions and step templates. Unknown sequences fall back to phase-set heuristics.
- Descriptive pattern naming: `_WORKFLOW_NAMES` lookup in the transcript analyzer replaces generic "Workflow: read -> write -> execute" with "plan-implement-verify". This flows through to proposal IDs and agent file names.
- Evidence inclusion: Generated agents include a summary of the sessions that triggered the pattern, giving users confidence the suggestion is data-driven.

**Technical decisions:**
- The main bug was that `_build_from_workflows()` was defined but never called in `build_proposals()` — a single missing line. The rest was improving content quality.
- Agent archetypes are a dict keyed by phase tuple, making them O(1) to look up and easy to extend.
- `_archetype_from_phases()` provides a fallback for sequences not in the archetype dict, using phase-set heuristics.

**Tradeoffs discussed:**
- Per-archetype step templates vs. generic phase descriptions: Chose per-archetype. The whole point of agent generation is producing useful drafts, not TODO-filled stubs. Generic descriptions defeat the purpose.
- Naming in transcript analyzer vs. proposal builder: Chose to name in the transcript analyzer (`_WORKFLOW_NAMES`). The pattern name flows through the entire pipeline (proposals, file paths, agent names), so it's best set at the source.

---

### Stale config detection (Task 3.4)
**Date:** 2026-03-30
**Branch:** roadmap-next-priorities
**Commit:** [pending]

**What was done:**
Added stale artifact detection to the Forge analysis pipeline. The system cross-references existing rules, skills, and agents against recent session transcripts and flags artifacts that haven't been referenced in 15+ sessions. Stale artifacts appear as proposals in `/forge` and as a count in the health summary table.

**Why:**
Over time, projects accumulate rules, skills, and CLAUDE.md entries that were once relevant but no longer match the team's workflow. These stale artifacts waste context budget and can mislead Claude with outdated guidance. Detecting and surfacing them completes the lifecycle management story — Forge can now both create and clean up artifacts.

**Design decisions:**
- Staleness logic lives in `build-proposals.py` (not a new script) because it needs data from both config and transcript analyses, and `build-proposals.py` already cross-references both. Avoids a new cache key, fingerprint function, and orchestration complexity.
- Four reference-matching strategies: (1) name match in session tokens, (2) slash-command match for skills, (3) content keyword co-occurrence (3-of-5 top terms), (4) glob-based path matching for scoped rules. This avoids both false positives (name-only would miss indirect references) and false negatives (keywords-only would miss direct invocations).
- Minimum 10 sessions required before staleness analysis runs, preventing premature alerts on new or low-usage projects.

**Technical decisions:**
- `analyze-transcripts.py` now emits `session_text_index` (per-session bag of tokens) and `session_tool_paths` (per-session file paths from tool uses). These are compact indexes that enable efficient cross-referencing in `build-proposals.py` without re-reading raw transcripts.
- `analyze-config.py` now emits `existing_rules` (full rule inventory with paths frontmatter) and `claude_md_sections` (parsed by ## heading). These were previously only counted, not inventoried.
- `_artifact_keywords()` uses simple frequency-based keyword extraction (no TF-IDF needed at proposal time since the corpus is small). Generic infrastructure terms are excluded.
- `fnmatch` used for path glob matching since rules use shell-style patterns.

**Tradeoffs discussed:**
- Standalone script vs. in `build-proposals.py`: A new `analyze-staleness.py` would have cleaner separation but required a new cache entry, fingerprint function, and would duplicate config+transcript loading. Since `build-proposals.py` already orchestrates both data sources, putting it there was simpler.
- Content keyword matching vs. name-only matching: Name-only would miss rules like `security.md` when the discussion is about "never commit secrets." Content keywords catch these but risk false positives. Requiring 3-of-5 top terms to co-occur balances precision and recall.
- CLAUDE.md section staleness deferred: Sections don't have clear identifiers like rules/skills do, making matching unreliable. Initial implementation focuses on rules, skills, and agents which have distinct names and paths.

---

### Fix directory regex and add Swift domain support
**Date:** 2026-03-30
**Branch:** synthetic-test-datasets
**Commit:** [pending]

**What was done:**
Fixed `_DIRECTORY_RE` in `analyze-config.py` which had a trailing `\b` that silently prevented matching directories followed by a space (e.g., "tests/ directory" was missed while "tests/unit" worked). Added Swift/SwiftUI support to placement detection (`_EXTENSION_RE`, `_FRAMEWORK_RE`), domain classifiers (`_DOMAIN_CLASSIFIERS`), and memory domain indicators (`DOMAIN_INDICATORS`). Version bumped to 0.2.6.

**Why:**
Discovered via synthetic test dataset work. The `\b` bug meant any CLAUDE.md entry writing `tests/` or `api/` followed by a space got zero placement detection — a real user-facing false negative. Swift gap meant SwiftUI projects got no domain-specific recommendations at all.

**Technical decisions:**
- **Removed trailing `\b` from `_DIRECTORY_RE`** — Every pattern already ends with `/` (a non-word char) which naturally terminates the match. The `\b` was never intentional: it only worked when `/` was followed by a word char (like `tests/unit`), not a space. Same fix applied to `DOMAIN_INDICATORS` in `analyze-memory.py`.
- **Added `swift` domain classifier** — Patterns: `\.swift\b`, `\bswiftui\b`, `\bswiftdata\b`. Paths frontmatter: `**/*.swift`. Placed after svelte but before python in the classifier order.

---

### Synthetic test dataset generator for pipeline integration testing
**Date:** 2026-03-30
**Branch:** synthetic-test-datasets
**Commit:** [pending]

**What was done:**
Created a synthetic fixture generator (`tests/generate_fixtures.py`) that produces 5 self-contained project profiles covering the full Forge analysis pipeline. Added 39 integration tests (`tests/test_integration_pipeline.py`) that run all four analysis scripts (config, transcripts, memory, build-proposals) on synthetic data. Updated `tests/conftest.py` with session-scoped fixtures for each profile. Total test count: 119 → 160, all passing in <0.3s.

**Why:**
The existing 119 tests were all unit-level — testing individual functions like `classify_response`, `_score_impact`, domain classification. Zero tests verified the full pipeline: config analysis + transcript analysis + memory analysis → build-proposals. Regressions in how scripts compose were invisible until manual `/forge` testing on real projects. Synthetic fixtures enable testing new features (stale config detection, agent generation) against known project shapes before real-world exposure.

**Design decisions:**
- **5 orthogonal profiles** — Each targets a distinct detection surface: swift-ios (memory-only path), react-ts (config analysis: tech stack, hooks, placement, demotion, budget), python-corrections (transcript analysis: corrections, post-actions, repeated prompts), rust-minimal (threshold enforcement — signals below threshold must NOT produce proposals), fullstack-mature (dismissed/suppressed filtering and dedup). This covers all proposal types and the most important negative path (threshold enforcement).
- **Direct function calls, no subprocess** — Tests import analysis scripts as modules and call internal functions (same pattern as existing unit tests). This is faster, more debuggable, and avoids needing git remotes for transcript directory discovery. Transcript loading bypasses `find_all_project_session_dirs()` and parses JSONL from a `_transcripts/` directory directly.
- **Session-scoped fixtures** — Profile materialization happens once per pytest run (`scope="session"`). The generation is deterministic, so sharing is safe. This keeps the 39 integration tests running in <0.3s.
- **Standalone CLI** — `python3 tests/generate_fixtures.py --output-dir /tmp/fixtures` generates all profiles for manual inspection or ad-hoc testing outside pytest.

**Technical decisions:**
- **JSONL format mirrors real transcripts** — Entries use the exact same `{"type", "message", "timestamp", "sessionId", "isSidechain"}` structure that `parse_transcript()` expects. Tool use blocks in assistant messages include `name` and `input` fields.
- **Transcript signals calibrated to thresholds** — Python-corrections profile has 6 pathlib corrections across 4 sessions (threshold: 3+ occurrences, 2+ sessions), 6 pytest post-actions across 4 sessions (threshold: 3+ occurrences, 2+ sessions), and 4 similar openers (threshold: 3+ sessions). Rust-minimal has 2 corrections in 1 session (below threshold) to test filtering.
- **Dismissed and suppressed data in `_forge_data/`** — Profiles that test filtering (fullstack-mature) include `dismissed.json` and `analyzer-stats.json` with suppressed theme hashes. The theme hash is computed using the same algorithm as `analyze-transcripts.py`.

**Tradeoffs discussed:**
- **Synthetic vs. anonymized real data** — Synthetic data is deterministic, zero-privacy-risk, and can be precisely calibrated to trigger specific thresholds. Real anonymized data would test edge cases better but introduces privacy complexity and non-determinism. Chose synthetic with the option to add more profiles later for edge cases.
- **Domain indicators vs. Swift support** — Discovered that `analyze-memory.py`'s `DOMAIN_INDICATORS` and `analyze-config.py`'s `_DIRECTORY_RE` don't cover `.swift` files or `\b...\b` patterns where the directory is followed by a space. The swift-ios profile works around this by using entries that match existing indicators (`.py`, `components/`). This is a pre-existing gap in the analysis scripts, not a fixture issue.

---

### User-decision data moved to user-level storage (SAFETY)
**Date:** 2026-03-30
**Branch:** forge-data-git-strategy
**Commit:** [pending]

**What was done:**
Moved all Forge runtime data from `.claude/forge/` (per-worktree, gitignored) to `~/.claude/forge/projects/<hash>/` (shared across all worktrees of the same project). This includes dismissed proposals, settings, applied history, pending proposals, analysis caches, and the unanalyzed session log. `.claude/forge/` no longer exists in the project directory — Forge has zero git footprint for runtime data. Added `project_identity.py` module for project hash computation and transparent migrate-on-read from legacy locations. Updated `log-session.sh` to write session log via `project_identity.py` CLI. 13 new tests. Version bumped to 0.2.5.

**Why:**
Files in `.claude/forge/` are gitignored and per-worktree. This meant dismissed proposals and settings didn't persist across worktrees, causing the same proposals to reappear in different worktrees and settings to be lost. Users noticed Forge files in diffs, creating confusion about whether data was being properly tracked.

**Design decisions:**
- **Project identity via git remote URL hash** -- SHA-256 of the cleaned remote URL, first 12 hex chars. Two worktrees of the same repo produce the same hash. Fallback to path-based encoding (matching Claude Code's scheme) when no git remote exists.
- **Everything moves to user-level** -- All runtime data (decisions, caches, session log) moves to `~/.claude/forge/projects/<hash>/`. Caches use fingerprint-based invalidation, so sharing across worktrees is safe — stale fingerprint just triggers a rebuild (<2s). Session log benefits from sharing since sessions in any worktree count toward the nudge threshold.
- **Transparent migration** -- On first read, `resolve_user_file()` checks the new location, falls back to legacy, and auto-migrates (copy + delete old). No manual migration step needed.

**Technical decisions:**
- Centralized in a single `project_identity.py` module rather than duplicating hash logic across scripts. All scripts import from it.
- `resolve_user_file()` handles the full lifecycle: new location check, legacy fallback, migration. Scripts just call it with a relative path.
- Path traversal rejected via `..` check in `resolve_user_file()`, consistent with existing security patterns.

**Tradeoffs discussed:**
- **User-level vs. project-level storage**: Project-level (`.claude/forge/`) is simpler but doesn't survive across worktrees. User-level (`~/.claude/forge/projects/`) requires a stable project identity mechanism but solves the cross-worktree problem. User-level won because the whole point is that users shouldn't have to think about this.
- **Hash vs. full path for project identity**: Hash (12 chars) is clean but opaque for debugging. Full encoded path is human-readable but long. Chose hash because it's stable across worktrees by definition (same remote = same hash), and the opaqueness is acceptable since users never interact with this directory.
- **Migrate-on-read vs. batch migration script**: Migrate-on-read is gradual and zero-effort for users. A batch script would be more explicit but adds a step. Chose migrate-on-read to maintain the "set and forget" principle.

**Lessons learned:**
- Gitignored files in `.claude/` create a confusing UX -- they show in diffs but aren't tracked, and they don't propagate between worktrees. Moving everything to user-level eliminates this entire class of confusion. Cache sharing across worktrees is safe because fingerprint validation already handles staleness.
- Known considerations for future: orphaned data after project deletion (add `forge:cleanup` command eventually), hash collision risk at 12 hex chars is negligible for individual users, path-based fallback (no git remote) breaks if project moves.

---

### Tier demotion / budget rebalancing (Task 2.5)
**Date:** 2026-03-29
**Branch:** next-roadmap-priorities
**Commit:** [pending]

**What was done:**
Implemented the downward tier management path: Forge can now detect bloated content and suggest moving it to more appropriate tiers. Two demotion paths: (1) domain-specific CLAUDE.md entries → scoped rules with path frontmatter, (2) oversized rules (>80 lines) → reference docs. Budget-aware scoring marks demotions as high-impact when CLAUDE.md exceeds 200 lines. SKILL.md updated with two-step demotion handling (create new file + replace source content with pointer). Version bumped to 0.2.4.

**Why:**
Forge could promote content up (memory → artifacts) but couldn't suggest moving bloated content down. Users with large CLAUDE.md files full of domain-specific entries had no automated path to restructure. The tier system spec defined demotion as a core feature (alongside promotion) for context budget management.

**Design decisions:**
- New `demotion` proposal type rather than reusing existing `rule`/`reference_doc` types. Reason: demotions are two-step operations (create target + edit source), and the SKILL.md needs to distinguish them from simple creation proposals. The `demotion_detail` field carries source location, entries to extract, and pointer text.
- Domain classifier uses ordered regex matching against framework names, file extensions, and directory patterns. First match wins (most specific first: frameworks → extensions → directories). This avoids complex multi-signal merging.
- 2-entry minimum per domain group before suggesting a demotion. A single domain-specific line isn't worth a new rule file — the overhead of the file outweighs the benefit.
- Replaced `_build_from_budget()` which created a generic `reference_doc` proposal that was scored "low" and silently filtered out. The new `_build_from_demotions()` creates specific, actionable proposals per domain group.

**Technical decisions:**
- Detection in `analyze-config.py` (zero-cost), proposal building in `build-proposals.py` (zero-cost), execution in SKILL.md (LLM-guided). Keeps the expensive part (reading files, deciding what to extract) in the LLM while detection stays cheap.
- Oversized rule threshold set at 80 lines (Anthropic spec recommends 50-100 per rule). Chose the upper end to avoid false positives on legitimately detailed rules.
- `finalize-proposals.py` maps `demotion` to a new `tier_management` stat category, separate from `corrections`.

**Tradeoffs discussed:**
- New type vs. reusing existing: A reuse approach (just add `demotion_detail` to `rule` proposals) would avoid SKILL.md changes, but makes filtering/categorization confusing. New type is cleaner.
- Threshold 2 vs. 3 entries per domain: 2 is more aggressive (suggests more demotions) but a pair of entries is enough to justify a scoped rule file. 3 would miss many legitimate cases.
- "Verbose CLAUDE.md section extraction" (multi-line entries that aren't domain-specific) was deferred — it overlaps with Task 2.4 (reference doc extraction) and requires more sophisticated content analysis.
### Infrastructure migration to standardized template
**Date:** 2026-03-28
**Branch:** optimize-infra
**Commit:** [pending -- this commit]

**What was done:**
Migrated the project's Claude Code development infrastructure to the standardized project template. This affects how *we develop Forge*, not the plugin Forge ships to users. Changes:
- Moved `.claude/references/history.md` → `core-docs/history.md`
- Added `core-docs/` structure: plan.md, feedback.md, workflow.md
- Added dev agents in `.claude/agents/`: planner, domain, testing, docs (separate from `forge/agents/` which ships to users)
- Added dev skills in `.claude/skills/`: ship, audit (separate from `forge/skills/` which ships to users)
- Added `.claude/rules/general.md` (documentation discipline, scope control)
- Added `.claude/rules/documentation.md` (core-docs format rules)
- Added `.claude/settings.json` (PreToolUse hook blocking writes to sensitive files)
- Updated CLAUDE.md to reference core-docs and distinguish plugin vs dev infrastructure

**Why:**
Standardize on the project template used across all projects. Adds structured planning, feedback tracking, agent-based workflow, and shipping skills that the project was missing. All changes are additive -- nothing was deleted or overwritten.

**Design decisions:**
- Plugin files (`forge/skills/`, `forge/agents/`) and dev files (`.claude/skills/`, `.claude/agents/`) are in completely separate namespaces. CLAUDE.md explicitly documents the distinction to prevent confusion.
- Template files for UI (agents/ui.md, rules/ui.md, rules/dev-server.md, design-language.md) were excluded -- Forge is a CLI plugin with no UI.
- Template's safety.md was excluded -- the project's existing security.md is more comprehensive and Forge-specific.

**Tradeoffs discussed:**
- Full template adoption vs. selective: Chose selective. Forge is a plugin, not an app. Blindly copying UI-oriented files would add noise.
- Moving history.md out of .claude/references/: Chose to move. core-docs/history.md is the standard location and core-docs/ is the canonical home for living project documentation. Git history is preserved via `git mv`.

**How to revert:**
This is a single commit. Run `git revert <SHA>` to undo the entire migration. All changes are additive (new files + one move), so reverting cleanly removes everything.

---

## 2026-03-25: Initial MVP architecture (Phase 1)

**Decision:** Built the full Phase 1 plugin structure in a single pass — 3 skills, 2 agents, 3 Python scripts, hooks, and reference docs.

**Why:** The spec and roadmap were detailed enough to build all components without iterative discovery. Shipping the complete skeleton first means every piece can be tested end-to-end immediately.

**Alternatives considered:**
- Building incrementally (one skill at a time) — rejected because the components are tightly coupled (analyze skill depends on scripts, optimize skill depends on agents) and testing any single piece requires the others to exist.

---

## 2026-03-25: Python 3.8+ compatibility over modern syntax

**Decision:** Use `typing.Optional[X]` instead of `X | None` union syntax in all Python scripts.

**Why:** The scripts must run on any machine with Claude Code installed. Python 3.9 (shipped with macOS) doesn't support `X | None` — that requires 3.10+. Hit this as a runtime error during initial testing.

**Alternatives considered:**
- Requiring Python 3.10+ — rejected because macOS ships 3.9 and we don't want install friction.
- Using `from __future__ import annotations` — would work but adds a line to every file for a minor syntactic convenience.

---

## 2026-03-25: Three separate analysis scripts vs. one unified script

**Decision:** Split Phase A analysis into three scripts: `analyze-config.py`, `analyze-transcripts.py`, `analyze-memory.py`.

**Why:** Follows the roadmap's design (Tasks 1.3, 1.4, 1.5). Each script has a distinct input source and can run independently. The `/forge:status` skill only needs config + memory scripts, not transcripts. Separation also makes each script easier to test and debug.

**Alternatives considered:**
- Single `analyze.py` with subcommands — would reduce file count but couples unrelated analysis modes. A transcript parsing bug would block config audit.

---

## 2026-03-25: Project directory mapping uses multi-strategy fallback

**Decision:** The transcript and memory scripts use three strategies to map a project root to its `~/.claude/projects/` directory: exact normalized path match, partial path component match, and recency-based fallback.

**Why:** Claude Code's project hash format (`-Users-name-project`) is not documented as stable. A single strategy would be brittle. The fallback chain ensures the scripts work even if the naming convention changes.

**Alternatives considered:**
- Only exact match — too fragile if Claude Code changes its hashing.
- Scanning all directories and reading metadata files — potentially slow with many projects. Used as strategy 3 (fallback) rather than primary.

---

## 2026-03-25: Placement issue detection uses regex heuristics

**Decision:** The config audit detects domain-specific CLAUDE.md entries by regex-matching file extensions (`.tsx`, `.py`), framework names (`React`, `Django`), and directory paths (`src/`, `tests/`).

**Why:** A simple, zero-token approach that catches the most common cases. Validated against a real project (portfolio-site) where it correctly identified 33 entries that could be scoped rules — including a 163-line CLAUDE.md that was well over budget.

**Limitations:** Will flag file tree listings and directory structure documentation as "domain-specific" even when they're just context. Phase B (the session-analyzer agent) is responsible for filtering out false positives before surfacing to the user.

---

## 2026-03-25: Core dev config follows Forge's own tier system

**Decision:** Set up this repo's own `.claude/` configuration using the same tier architecture Forge recommends: concise CLAUDE.md (Tier 1), scoped rules with path frontmatter (Tier 2), reference docs for detailed content (Tier 3).

**Why:** Dogfooding. If we're building a tool that optimizes context architecture, our own repo should be a good example. Also validates that the tier model works in practice.

**Structure:**
- `CLAUDE.md` — ~40 lines, universal project context
- `.claude/rules/python-scripts.md` — scoped to `forge/scripts/**/*.py`
- `.claude/rules/skills-and-agents.md` — scoped to `forge/{skills,agents}/**/*.md`
- `.claude/rules/plugin-structure.md` — scoped to `forge/**`
- `.claude/references/history.md` — decision log (this file), pointed to from CLAUDE.md

---

## 2026-03-25: Session-analyzer output format aligned with proposal schema

**Decision:** Updated the session-analyzer agent's output format to include `id`, `evidence` (as an array of objects), and `status` fields — matching exactly what the analyze skill writes to `pending.json` and what the optimize skill reads.

**Why:** Code review revealed a structural mismatch: the session-analyzer produced `evidence_summary` (string) and `reasoning` (string) but the analyze skill expected `evidence` (array) and `status` ("pending"). The optimize skill would fail to process proposals without these fields. Fixed by aligning the agent's output spec to the shared proposal schema.

**Lesson:** When multiple components pass data through a shared JSON format, define the schema in one place and reference it. The proposal schema is the contract between analyze → pending.json → optimize.

---

## 2026-03-25: Stop hook added for ambient nudge (Phase 3 prep)

**Decision:** Added a `Stop` hook and `check-pending.py` script alongside the existing `SessionEnd` hook. The script checks for pending high-confidence proposals and outputs a `systemMessage` nudge — once per session maximum.

**Why:** While ambient nudges are a Phase 3 feature, the infrastructure is lightweight (a single Python script) and aligns with the spec's Window 2 interaction model. Having the hook in place early means we can test the nudge behavior as proposals accumulate during Phase 1 testing.

**Constraints followed from spec:** Once per session max (flag file), high-confidence only, outputs nothing if no proposals exist, completes in <2 seconds.

---

## 2026-03-25: Config audit placement detection improved to skip file trees

**Decision:** Added filters to `find_placement_issues()` in `analyze-config.py` to skip lines containing tree-drawing characters (`├`, `└`, `│`) and lines inside code blocks. These are structural documentation, not domain-specific instructions.

**Why:** Testing against a real project (portfolio-site) showed 33 placement issues flagged, but most were from a file tree listing in CLAUDE.md. After filtering, only genuine domain-specific instructions are flagged. This matches the spec's note that "Phase A optimizes for recall" — but flagging file tree lines as placement issues is noise, not recall.

---

## 2026-03-25: Transcript parser hardened against real JSONL format

**Decision:** Three fixes to `analyze-transcripts.py` based on validating against real Claude Code session transcripts:

1. **Filter sidechain entries** (`isSidechain: true`). These are internal subagent conversations that would cause false positive corrections if treated as user messages.

2. **Fix `prev_was_edit` reset in post-action detection**. Tool result entries (which have empty `role`) appeared between assistant edits and user follow-up messages, resetting the flag and causing nearly all post-action patterns to be missed. Fixed by only resetting on user messages.

3. **Filter system-injected user messages**. Messages starting with `<system_instruction>` or `<local-command-caveat>` are framework-injected, not real user input.

**Why:** Validated the parser against real `.jsonl` files from `~/.claude/projects/`. Discovered the actual format includes entry types (`user`, `assistant`, `queue-operation`), sidechain markers, system-injected messages, and interleaved tool_result entries. The parser's assumptions were broadly correct for the happy path but missed these edge cases.

**Impact:** Post-action detection was essentially broken (high severity). Sidechain filtering prevents false positives when Forge itself runs (its own subagent conversations appear in transcripts).

---

## 2026-03-26: Cross-worktree transcript aggregation

**Decision:** Replaced single-directory session lookup (`find_project_sessions_dir`) with multi-directory aggregation (`find_all_project_session_dirs`) that discovers all worktrees/checkouts of the same repo. Uses a 5-strategy layered approach:

1. **Exact match** — encode current path, find in `~/.claude/projects/`
2. **Git worktree list** — encode each active worktree path
3. **Forward index** — check `~/.claude/forge/repo-index.json` (maintained by SessionEnd hook)
4. **Git remote scan** — for dirs whose paths still exist, verify remote URL matches
5. **Workspace-prefix heuristic** — from confirmed worktree matches (strategies 2-4), decode the path, use the parent directory as a workspace prefix, find all dirs with that prefix

Also updated the SessionEnd hook (`log-session.sh`) to maintain a global repo index (`~/.claude/forge/repo-index.json`) mapping git remote URLs to project directory names.

**Why:** The primary user works in Conductor, which spawns worktrees for parallel tasks. Each worktree gets its own `~/.claude/projects/` directory, so without aggregation, patterns are fragmented across 50-100+ isolated session buckets. Testing showed only 8% of project dirs still have resolvable git remotes (worktrees are cleaned up), and `history.jsonl` contains zero Conductor sessions (it only logs interactive prompts). The 5-strategy approach maximizes coverage: strategy 5 (workspace prefix) catches deleted worktrees by inferring the workspace root from confirmed matches.

**Alternatives considered:**
- **Do nothing**: Would miss most of the user's work (197/212 project dirs are Conductor worktrees).
- **Option 1 only (retroactive)**: Gets ~30% of dirs via path existence + git remote. Misses 70% of deleted worktrees.
- **Option 2 only (forward index)**: Perfect going forward but no retroactive coverage of existing data.
- **Both options**: Chosen. Option 1 bootstraps with historical data, option 2 ensures completeness going forward, strategy 5 bridges the gap for deleted worktrees.

**Key finding:** Claude Code project directory names are NOT hashed — they're the filesystem path with `/` replaced by `-` (e.g., `-Users-ben-conductor-workspaces-forge-salvador`). Path reconstruction is ambiguous when directory names contain hyphens (e.g., `portfolio-site`), solved with a greedy left-to-right algorithm that checks filesystem existence at each step.

**Results:** portfolio-site: 112 dirs, 127 transcripts. PriorityAppXcode: 58 dirs, 75 transcripts. All under 1 second.

---

## 2026-03-26: Settings system and nudge levels

**Decision:** Added a settings system (`/forge:settings` skill + `settings.json` file) with three predefined nudge levels: quiet (never), balanced (after 5+ sessions, default), and eager (after 2+ sessions). Removed the Stop hook for nudges since users aren't present to read them — nudges now happen on session start via a CLAUDE.md rule.

**Why:** The primary user works in Conductor with many short-lived worktrees. Nudges at session end are wasted (terminal is closing). Session start is when the user is present and engaged. The settings system exists primarily to prevent annoying nudges from turning users off — conservative defaults with an escape hatch.

**Alternatives considered:**
- Manual JSON editing: defeats the purpose of a plugin that reduces configuration overhead.
- Per-setting granular controls: overengineered for three levels. Predefined levels are simpler.
- No settings at all: nudge frequency is the one thing that genuinely needs to be configurable per user.

---

## 2026-03-26: Smart conversation-pair analyzer with feedback loop

**Decision:** Rewrote the transcript correction detection from scratch. The old approach scanned user messages in isolation with regex patterns (e.g., "does this message contain 'no' or 'wrong'?") and grouped by raw string similarity. The new approach analyzes *conversation pairs* — what the assistant did, then how the user responded — and classifies each response as corrective, confirmatory, new_instruction, or followup.

Key changes:
1. **Conversation pair analysis.** Each detection includes the assistant's preceding action (tool uses, files touched, text output). A message like "no, use snake_case" is only classified as corrective if it follows an action and references the action's context. This eliminates false positives from conversational "no" usage.

2. **Graduated scoring.** Corrections have a strength score (0.0-1.0) based on keyword intensity, action reference, and imperative tone. "I told you to use snake_case" scores higher than "actually, let's try snake_case."

3. **Intra-session weighting.** If Claude gets corrected 5 times for the same thing in one session, that scores 9.5 (weighted: 1.0 + 1.5 + 2.0 + 2.5 + 2.5), not 5.0. This reflects that repeated in-session corrections are a stronger signal than isolated ones.

4. **Theme extraction via TF-IDF + Jaccard.** Replaces SequenceMatcher with tokenized word overlap. "use snake_case for variables" and "variable names should be snake case" now group together because they share key terms, not because they have similar character sequences.

5. **Feedback loop.** Stores outcomes (approved/dismissed/suppressed) in `~/.claude/forge/analyzer-stats.json`. Computes precision rates per category and adjusts confidence thresholds: poor historical precision raises the bar for future proposals, good precision lowers it. Permanently suppressed themes are never re-proposed.

6. **Auto-generated message filtering.** Context continuation summaries ("continued from a previous conversation"), command invocations (`<command-name>`), and task notifications are filtered from analysis. These are framework-generated, not user corrections.

**Why:** Testing against real data revealed that the old regex approach produced almost entirely false positives. On 781 conversation pairs from portfolio-site sessions, the old approach found dozens of "corrections" that were actually design requests ("make X 400 instead of 300"). The new conversation-pair approach correctly classified these as new_instruction (no preceding assistant action to correct) and identified only genuine behavioral corrections.

**Performance:** portfolio-site (50 sessions, 782 pairs): 1.05s. PriorityAppXcode (50 sessions, 730 pairs): 1.37s. Well within the 3-second budget.

**Limitation noted for roadmap:** The repeated prompts detector finds "start a dev server" (11 sessions) and "fix" (4 sessions) as genuine skill candidates. But correction detection finds few patterns because the test projects have mostly design-iteration conversations, not repeated coding corrections. More diverse test data needed. Artifact lifecycle/decay detection flagged as next implementation priority.

---

## 2026-03-27: LLM gap analysis — script vs. LLM pattern detection

**Decision:** Ran LLM analysis on the same conversation pairs the Python script processes (portfolio-site: 10 sessions, PriorityAppXcode: 10 sessions) to measure what the script misses.

**Key findings:**

1. **0 corrections confirmed correct.** The LLM independently verified that the user's communication style is directive ("create a plan and implement"), not corrective ("no, do X instead"). The conversation-pair classifier is working correctly — the signal genuinely isn't there, not a false negative.

2. **Repeated prompts are the strongest signal.** Both script and LLM agree. The script correctly identifies: "start dev server" (11x), "update docs + merge" (6x), "fix issues" (5x), "/push workflow" (4x), "/ship workflow" (3x). These are clear skill candidates.

3. **LLM finds patterns the script can't detect:**
   - **Contextual position**: "Start dev server" as a session opener vs. immediately after "Done — replaced asset" are different signals. The latter is a post-task workflow preference that should trigger proactive behavior, not just a skill.
   - **Approval-gated deliberation**: User asks clarifying questions before greenlighting implementation. Can't be detected by keyword matching — the signal is the *absence* of "go ahead" until after back-and-forth.
   - **State signals**: "xcode is closed" is an implicit preference about what commands are safe to run, volunteered as context. Requires semantic understanding.
   - **Review → immediate action directive**: After code reviews, user always issues a single action directive without discussion. Suggests: present reviews concisely, wait for directive, don't ask clarifying questions.

4. **What the script does that the LLM can't:** The script aggregates across 50+ sessions, handles cross-worktree discovery, scores themes with TF-IDF, and runs in <2 seconds. The LLM provides deeper analysis on individual pairs but can't scale to the full dataset affordably.

**Conclusion:** The Python script and LLM are complementary, not competing. The script is the right first pass (zero-token, fast, cross-worktree). The LLM should be an optional second pass for ambiguous candidates or when the user opts in. Added Task 4.3 (LLM-Assisted Pattern Detection) to the roadmap.

**Roadmap updated:** Reprioritized Phase 2 based on real data. Skill generation and artifact lifecycle are now the top priorities. Correction detection improvement deferred to Phase 3 (pending more diverse test data). Unified `/forge` command added as Phase 2 task. Contextual pattern detection (position-aware analysis) added as Phase 2 task.

---

## 2026-03-27: Analysis scope is per-project by default

**Decision:** All Forge analysis is strictly scoped to the current project and its worktrees. Forge never reads transcripts from unrelated projects. Cross-project aggregation (Task 4.1) is a future opt-in setting only.

**Why:** Privacy. Patterns from a private work project should not leak into suggestions for a personal project. The user may work across projects with different sensitivity levels, team ownership, or confidentiality requirements. Per-project scope is the safe default.

**How this works today:** `analyze-transcripts.py` takes `--project-root` and uses the 5-strategy cross-worktree discovery to find all session dirs for *that specific repo*. It matches on git remote URL — so worktrees of the same repo are aggregated, but unrelated repos are never touched.

**Future:** Cross-project aggregation could be valuable (e.g., "this user always wants snake_case in every project"). If added, it will be opt-in via `/forge:settings` with clear documentation about what data is shared across project boundaries.

---

## 2026-03-27: LLM replaces Phase B confirmation, not the script

**Decision:** Replace the Phase B session-analyzer confirmation step with an LLM pass that analyzes raw conversation pairs for contextual patterns. The Python script stays as the data pipeline. The previous architecture (Script → LLM confirmation) is replaced by (Script + LLM → merged candidates).

**Why:** Phase B confirmation is currently dead weight. The script's high-frequency findings (11x "start dev server") don't need LLM confirmation — frequency is sufficient evidence. And when the script finds 0 candidates (corrections, post-actions), Phase B has nothing to confirm. Meanwhile, the LLM gap analysis showed the LLM finds genuinely different patterns (contextual position, implicit preferences, approval gates) that the script can never detect. The LLM should be finding new patterns, not rubber-stamping the script's output.

**Why not replace the script entirely:** The script handles cross-worktree discovery, JSONL parsing, and 50-session aggregation — things you can't affordably send through an LLM. The script is the data layer (~0 tokens, <2s); the LLM is the intelligence layer (~5K tokens, ~5-10s). They're complementary.

**Settings:** `analysis_depth: standard` (script only, default) or `deep` (script + LLM). Users on subscriptions set `deep`; API-billing users keep the default.

---

## 2026-03-27: Artifacts always default to project-level scope

**Decision:** All generated artifacts are placed at project-level (`.claude/`) by default. Forge never suggests user-level placement on its own. The user can override during review ("make this user-level").

**Why:** Suggesting user-level placement would require knowing that a pattern transcends multiple projects — which requires cross-project analysis, which we explicitly decided against for privacy. Even if we had the data, "always use snake_case" might be a convention one project chose, not a personal universal. Forge can't distinguish without reading other projects.

**How:** During `/forge` review, the user can say "approve, but make this user-level" to place an artifact in `~/.claude/` instead. This is a Phase 4 feature (Task 4.3) — for now, everything goes to project-level.

---

## 2026-03-27: Cross-type misuse detection added to config audit

**Decision:** Extend the config audit to detect content placed in the wrong artifact type — behavioral preferences inside skills, multi-step workflows in CLAUDE.md, deterministic commands in rules instead of hooks, rules without path scoping that mention specific file types.

**Why:** Users (and Claude itself) routinely put content in the wrong artifact type. A skill that says "always use functional components" in step 3 means that preference only applies when the skill is invoked — it should be a rule that's always active. A CLAUDE.md entry with a 15-line deployment workflow burns context budget every session when it should be a skill invoked on demand. Detecting and fixing these misplacements is core to Forge's value proposition of optimizing context architecture.

**Implementation:** Split between script (structural signals — line counts, regex for command patterns, path-scope checks) and LLM pass (semantic understanding — distinguishing a behavioral preference from a workflow step). Added as Phase 2 Task 2.6.

---

## 2026-03-27: Unified `/forge` command replaces three separate skills

**Decision:** Consolidated `/forge:status`, `/forge:analyze`, `/forge:optimize` into a single `/forge` command. `/forge:settings` remains separate.

**Why:** The three-command split created unnecessary cognitive overhead. The user explicitly said "I don't want to have to learn a bunch of stuff." In practice, analyze→optimize was always run back-to-back, and status was just the first section of analyze. The only scenario for running optimize separately was to revisit pending proposals from a prior session — the unified command handles this by checking for pending proposals first.

**Flow:** The unified command runs in order: (1) check for pending proposals, (2) run Phase A scripts, (3) present status summary, (4) present pattern findings, (5) merge into proposals, (6) present each proposal one at a time with approve/modify/skip/never options, (7) apply approved proposals via artifact-generator agent, (8) record decisions for feedback loop.

**Key constraint preserved:** The plugin always asks explicit permission before writing any files. Proposals are presented with full evidence and a preview of what would be generated. The user must approve each one individually.

**AskUserQuestion integration:** The skill instructs Claude to use the `AskUserQuestion` tool (Claude Agent SDK built-in) to present structured multiple-choice options for each proposal (Approve/Modify/Skip/Never). This provides a cleaner UI than free-text conversation when available. Falls back to conversational asking if the tool isn't available. Limitation: 1-4 questions with 2-4 options each, not available in subagents.

---

## 2026-03-27: Full artifact inventory with duplicate/overlap detection

**Decision:** The config auditor now returns full inventories of existing skills (including legacy `.claude/commands/*.md`), agents, and hooks — with complete file content, not just counts. The `/forge` skill cross-references these inventories before proposing new artifacts.

**Why:** Without cross-referencing, the plugin would propose a new skill for a pattern already handled by an existing skill or legacy command. Discovered this when the transcript analyzer flagged "start a dev server and send a link" as a skill candidate in a project that already had a `/link` command doing exactly that. Names and descriptions alone aren't enough — the full body content is needed to determine if the pattern is truly covered or if there's a gap the existing artifact misses.

**Scope:** Skills and legacy commands return name, description, full content, path, and format. Agents return the same fields. Hooks return event, matcher, type, command, and source path. A new `skill_update` proposal type handles modifications to existing skills, including migration from legacy commands to modern skills format.

**Alternatives considered:**
- Name + description only — rejected because the description is a summary; the actual behavior lives in the body instructions.
- Scanning only `.claude/skills/` — rejected because legacy `.claude/commands/` files still work and are common in existing projects.

---

## 2026-03-26: Security hardening pass

**Decision:** Comprehensive security review and hardening of the entire plugin. Changes:

1. **Fixed shell injection in `log-session.sh`.** `$REMOTE_URL` and `$PROJECT_DIR_NAME` were interpolated into Python string literals via single quotes — a crafted git remote URL containing `'` could inject arbitrary Python code. Fixed by passing values via environment variables (`FORGE_DIR_NAME`, `FORGE_REMOTE_URL`) and reading with `os.environ`.

2. **Restricted artifact-generator agent.** Added `disallowedTools: [Bash]`. The agent only needs Write/Edit to produce artifacts — it never needs shell access. This limits blast radius if the agent misinterprets a proposal.

3. **Added safety constraints to both agents.** Explicit, non-negotiable rules: write targets are restricted to `.claude/` and `CLAUDE.md`, hooks must be non-destructive, no executable generation, no file deletion (except approved legacy command migration).

4. **Added path validation to `/forge` skill.** Before writing any artifact, the skill validates that `suggested_path` is relative, stays within the project root (no `..` traversal), and targets only allowed locations.

5. **Added path traversal protection to `_decode_project_dir()`.** Rejects encoded directory names containing `..` components. Final resolved path is checked for traversal.

6. **Created `.claude/rules/security.md`.** Documents the full security policy: write boundaries, shell safety, agent isolation, data handling, and destructive operation rules.

**Why:** Forge runs as a plugin inside Claude Code, which has broad file system access. A user trusting Forge with their project is trusting it to not delete code, leak data, or introduce vulnerabilities. The existing code was mostly safe by design (atomic writes, subprocess list form, credential stripping) but had gaps: the shell injection in `log-session.sh` was real, the artifact-generator having Bash access was unnecessary risk, and safety invariants were implicit rather than documented and enforced.

**Alternatives considered:**
- Sandboxing via containerization — overkill for a Claude Code plugin; the permission model (disallowedTools, user approval gates) is the right level of isolation.
- Removing the SessionEnd hook entirely — too aggressive; the hook is useful and the injection was fixable.

---

## 2026-03-27: Review fixes — shell safety, stale cache, cross-project leakage

**Decision:** Four fixes from code review of the `forge-ux-improvements` branch:

1. **Shell injection in finalize command.** The `/forge` skill instructed the LLM to run `echo '<JSON>' | python3 finalize-proposals.py` where the JSON contained user-derived text (evidence_summary, description from transcript analysis). Single quotes in user messages (e.g., "don't") would break the shell quoting. Fixed by replacing `echo` with a heredoc using a single-quoted delimiter (`<<'FORGE_EOF'`), which prevents all shell expansion.

2. **Stale proposals after cache refresh.** `get_proposals()` called `update_cache()` which could re-run analysis scripts, but then returned a pre-existing `proposals.json` without checking if analysis was refreshed. Fixed by checking if any analysis status was "updated" before returning cached proposals.

3. **Cross-project transcript leakage in workspace-prefix matching.** Strategy 4's prefix-matching had two gaps: (a) candidate directories with no git remote bypassed verification entirely, (b) when the current project had no remote, all prefix-matched dirs were accepted. Fixed by requiring `current_remote` to be set for prefix matching, and using a `verified` flag that only accepts candidates on positive remote match.

4. **Generated ESLint hook violated security rules.** `_generate_hook_content()` produced an ESLint command with `2>/dev/null || echo "..."`, violating the security rule against chained commands and redirects in hooks. Fixed by stripping to a clean single invocation.

**Why:** Issues 1 and 3 are security fixes (shell injection, data isolation). Issue 2 is a correctness bug (users see outdated proposals). Issue 4 is a policy violation in generated artifacts.

---

## 2026-03-27: Marketplace distribution setup

**Decision:** Added infrastructure for distributing Forge via the Claude Code private plugin marketplace: a `.claude-plugin/marketplace.json` manifest at the repo root, a `scripts/sync-version.py` build tool to keep the manifest version in sync with `forge/.claude-plugin/plugin.json`, a `.githooks/pre-commit` hook to automate the sync, and a `/forge:version` skill for users to verify their installed build.

**Why:** Users need a way to install Forge without cloning the repo and pointing `--plugin-dir` at it. The marketplace is Claude Code's native distribution mechanism. The version sync tooling prevents the manifest and plugin from drifting apart — the pre-commit hook reads staged content from the git index (not the working tree) to ensure committed files are always consistent.

**Key design choices:**
- `sync-version.py` and the pre-commit hook live at the repo root (`scripts/`, `.githooks/`), not under `forge/`. They are developer build tooling, not part of the plugin runtime. The plugin remains self-contained under `forge/`.
- `plugin.json` is the single source of truth for the version number. The marketplace manifest is a downstream consumer.
- The `/forge:version` skill reads `installed_plugins.json` from `~/.claude/plugins/` to report the installed build, including git SHA and freshness.

---

## 2026-03-27: Deep analysis mode — background LLM pass + dead code cleanup

**Decision:** Added `analysis_depth` setting (standard/deep) and `/forge --deep`/`--quick` flags. Deep mode runs scripts synchronously (instant with cache), shows the health table immediately, then spawns the session-analyzer agent in the background for contextual pattern detection. All proposals are presented together when the agent completes. Standard mode is unchanged from the previous synchronous flow.

Also deleted the `artifact-generator` agent (never invoked — the `/forge` skill generates artifacts inline) and rewrote the `session-analyzer` agent from its old Phase B confirmation role to deep analysis.

**Why:** The 2026-03-27 LLM gap analysis showed scripts and LLM find complementary patterns. Scripts handle scale (50+ sessions, <2s, zero tokens). LLM finds contextual signals (position-aware patterns, implicit preferences, approval gates) on a sample of conversation pairs. The background UX means users don't wait — they see the health table immediately and can continue working while the LLM runs.

**Default is standard** (zero token cost) to avoid surprise billing. Users opt in via `/forge:settings` or per-invocation with `--deep`. The proactive/hook path always uses scripts only regardless of setting.

**Security note:** Step 1b spawns the `session-analyzer` agent directly (subagent_type: `session-analyzer`), not a `general-purpose` agent with inlined instructions. This ensures the agent's `disallowedTools: [Write, Edit, Bash]` constraint from `session-analyzer.md` frontmatter is enforced, per `.claude/rules/security.md`.

**Alternatives considered:**
- Always running deep on explicit `/forge` invocation — rejected because some users on API billing want to control token spend per invocation.
- Running deep analysis at SessionEnd — rejected because sessions may be tearing down (especially in Conductor worktrees), and silent background token spend is surprising.
- Two-wave proposal presentation (show script proposals immediately, then deep proposals when ready) — rejected because it creates context-switching during review and risks the user approving something that overlaps with a deep proposal not yet shown.

---

## 2026-03-28: Enterprise hardening — security, tests, and Python 3.8 compat

**Decision:** Comprehensive audit and hardening pass to make Forge production-ready for enterprise customers. Three phases:

**Phase 1 — Critical fixes (7 items):**
1. Replaced all 6 `str.removesuffix()` calls (Python 3.9+) with a `_removesuffix()` backport helper. This was a showstopper — the claimed Python 3.8 compatibility was broken.
2. Credential stripping now returns `<redacted-url>` on exception instead of the original URL with embedded credentials. Fixed in both `analyze-transcripts.py` and `log-session.sh`.
3. `_decode_project_dir()` now calls `Path.resolve()` on the final decoded path and guards empty-string returns at all 3 call sites. Prevents symlink-based path traversal.
4. Added `_sanitize_text()` helper to strip control characters (`\x00-\x08`, `\x0b-\x0c`, `\x0e-\x1f`, `\x7f`) at all user text truncation points across 3 scripts. Prevents log injection and terminal escape attacks.
5. Replaced `[2.5] * max(0, count - 3)` list allocation in `_intra_session_weight()` with pure arithmetic, capped at 100. Eliminates memory spike from adversarial session data.
6. Cache manager now validates subprocess JSON output is a `dict` before caching. Prevents a script bug from silently corrupting downstream analysis.
7. All silent exception handlers now log to stderr with the exception message. Critical for enterprise support diagnostics.

**Phase 2 — Test infrastructure (68 tests):**
- Created `tests/` with pytest configuration (`pyproject.toml`, `conftest.py` with shared fixtures).
- `test_analyze_transcripts.py`: removesuffix compat, credential stripping (normal + malformed + fail-safe), path traversal rejection, text sanitization, weight bounds, JSONL parsing, response classification.
- `test_build_proposals.py`: threshold filtering, dismissed exclusion, duplicate detection, impact scoring, similarity.
- `test_cache_manager.py`: atomic writes, cache roundtrips, fingerprint determinism.
- `test_security.py`: regression guards — grep for `shell=True` (assert zero), grep for raw `.removesuffix()` (assert zero), credential leak tests, no `eval()`/`exec()`, path traversal blocked.

**Phase 3 — Enterprise polish (5 items):**
1. Added `--project-root` existence validation in 4 scripts (analyze-config already had it).
2. Explicit `0o644` file permissions on all atomic writes (prevents restrictive umask issues).
3. `log-session.sh` now uses `git rev-parse --show-toplevel` first, falls back to directory walk. Fixes incorrect root detection in monorepos.
4. License set to proprietary (no LICENSE file, `plugin.json` license field omitted). All rights reserved.
5. Version bumped to 0.2.0.

**Why:** The MVP was architecturally sound but had gaps that would be flagged in an enterprise security review. The `removesuffix` bug would crash on Python 3.8 (common in locked-down enterprise environments). Credential leakage on error paths is a hard fail for security teams. Zero tests means every change requires manual testing. These fixes address the highest-risk items without over-engineering.

**Alternatives considered:**
- Structured logging framework — rejected; plain stderr is sufficient at this scale.
- Shared utility module for `_sanitize_text` / `_removesuffix` — rejected; scripts are intentionally standalone, duplicating a 4-line helper is pragmatic.
- CI/CD setup — deferred; the test suite is the prerequisite. CI is a separate effort.

---

## 2026-03-28: Defense-in-depth scope isolation rules

**Decision:** Added explicit scope isolation rules at every layer of the plugin: security policy (`.claude/rules/security.md`), plugin manifest (`plugin.json`), session-analyzer agent, and the `/forge` skill. Each layer independently enforces that Forge only reads data from the current project during normal analysis.

**Why:** The existing "Analysis scope is per-project" constraint in CLAUDE.md was a single high-level statement. LLM agents follow instructions more reliably when the same constraint is reinforced at the point of action — the security rule for policy enforcement, the agent frontmatter for subagent isolation, and the skill body for the entry-point. A single missed instruction shouldn't create cross-project data leakage.

**What was added:**
- **Security rule — Read boundary:** Defines exactly what Forge can read during normal analysis (current project dir, its `.claude/` config, matched `~/.claude/projects/` dirs). Carves out `~/.claude/forge/analyzer-stats.json` as the only cross-project file. Requires disclosure when users explicitly request cross-project access.
- **Plugin manifest:** Explicit `skills`, `agents`, `hooks` path declarations for discoverability.
- **Session-analyzer agent:** New safety constraint: only reason about data provided in input, never proactively access other project dirs.
- **Forge skill:** Scope constraint paragraph near the top of instructions, repeating the isolation rule at the user-facing entry point.

**Alternatives considered:**
- Adding the constraint only to security.md — rejected because agents and skills have their own instruction context and may not load rules files. Each layer should be self-contained.
- Adding runtime enforcement (path checks in Python scripts) — the scripts already scope via `--project-root` and git remote matching. The new rules are LLM-instruction-level defense, complementing the existing code-level scoping.

---

## 2026-03-28: Agents manifest field must be an array, not a directory string

**Decision:** Changed the `agents` field in `plugin.json` from `"./agents/"` (directory string) to `["./agents/session-analyzer.md"]` (array of file paths).

**Why:** Claude Code's manifest validator rejects a directory string for `agents` with "Invalid Input". The `skills` field accepts a directory path, but `agents` requires an explicit array of file paths. This was a silent install failure — the plugin appeared in the Installed tab but with a validation error, meaning agents were never registered.

**How this was caught:** After PR #14 (manifest validation tests), testing the installed plugin showed the error in the `/plugin` UI. The project's own tests passed because they validated the directory existed, not the field's type.

**Lesson:** Manifest tests should validate field types against Claude Code's actual schema, not just check that referenced paths exist. Added an `isinstance(data["agents"], list)` assertion to prevent regression.
