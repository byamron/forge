# Forge — Decision History

Significant design and technical decisions, captured as the project evolves. Each entry records what was decided, why, and what alternatives were considered.

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
