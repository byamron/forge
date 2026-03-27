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
