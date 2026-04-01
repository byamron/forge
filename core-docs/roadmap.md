# Forge — Implementation Roadmap

## How to use this document

This is the implementation plan for Forge, a Claude Code plugin. It's designed to be read by an AI coding agent (Claude Code) alongside the product spec (`forge-spec.md`). Each phase is broken into discrete tasks with clear inputs, outputs, acceptance criteria, and test instructions. Work through tasks sequentially within each phase unless noted otherwise.

**Project setup:** This is a Claude Code plugin. The root directory is the plugin directory. It will be tested locally using `claude --plugin-dir ./forge` during development, then distributed via a marketplace.

**Testing approach:** Test continuously against your own Claude Code sessions. After each task, verify it works by running the plugin locally. The plugin reads real session data from `~/.claude/projects/` — use your actual project history as test data.

**Reference:** The full product spec is in `forge-spec.md`. Anthropic's plugin docs are at `code.claude.com/docs/en/plugins` and `code.claude.com/docs/en/plugins-reference`. Hooks docs at `code.claude.com/docs/en/hooks`. Skills docs at `code.claude.com/docs/en/skills`.

---

## Phase 1: Foundation (v0.1)

**Goal:** A working plugin with manual analysis that provides value from the first run via config audit and memory audit, plus basic pattern detection from session history. Generates CLAUDE.md entries, rules, and common hooks.

---

### Task 1.1: Plugin Skeleton

**What:** Create the plugin directory structure with manifest, empty component directories, and README.

**Output files:**
```
forge/
├── .claude-plugin/
│   └── plugin.json
├── skills/
│   ├── analyze/
│   │   └── SKILL.md
│   ├── optimize/
│   │   └── SKILL.md
│   └── status/
│       └── SKILL.md
├── agents/
│   ├── session-analyzer.md
│   └── artifact-generator.md
├── hooks/
│   └── hooks.json
├── scripts/
│   └── (added in later tasks)
├── references/
│   ├── artifact-templates.md
│   └── anthropic-best-practices.md
└── README.md
```

**plugin.json:**
```json
{
  "name": "forge",
  "version": "0.1.0",
  "description": "Infrastructure architect for Claude Code. Analyzes your sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs — and manages your context architecture over time.",
  "author": "",
  "license": "MIT"
}
```

**Acceptance criteria:**
- `claude --plugin-dir ./forge` launches without errors
- `/forge:analyze`, `/forge:optimize`, `/forge:status` appear in the slash command list (even if they're stubs)
- Plugin shows up in `/plugin` list

**Test:** Run `claude --plugin-dir ./forge` and type `/` to verify the three commands are visible. Type `/forge:status` — it should respond (even if just "Forge status: not yet implemented").

---

### Task 1.2: Status Skill (Config Health Audit)

**What:** Implement `/forge:status` as the first working feature. This is the cold-start entry point — it provides value with zero session history by auditing the user's current project configuration.

**The skill should instruct Claude to:**

1. Read the project's current configuration:
   - `.claude/CLAUDE.md` or `CLAUDE.md` (project-level)
   - `~/.claude/CLAUDE.md` (user-level)
   - `.claude/CLAUDE.local.md` (if exists, from `/remember`)
   - `.claude/rules/` directory (all .md files)
   - `.claude/skills/` directory (all SKILL.md files)
   - `.claude/settings.json` and `~/.claude/settings.json` (for hooks)
   - `.claude/agents/` directory (all .md files)

2. Read auto-memory (if exists):
   - `~/.claude/projects/` — find the directory matching the current project
   - Read `memory/MEMORY.md` and any topic files in `memory/`

3. Scan project tech stack:
   - `package.json` (Node/JS/TS projects — detect formatter, linter, test framework)
   - `Cargo.toml` (Rust), `pyproject.toml` / `setup.py` (Python), `go.mod` (Go)
   - `.prettierrc*`, `.eslintrc*`, `eslint.config.*`, `biome.json`
   - `tsconfig.json`, `jest.config.*`, `vitest.config.*`, `playwright.config.*`

4. Produce a health report covering:

   **Context budget:**
   - CLAUDE.md line count and estimated tier 1 token load
   - CLAUDE.local.md line count (if exists)
   - Number of rules, skills, agents, hooks
   - Warning if total tier 1 content is heavy (>150 lines combined)

   **Configuration gaps:**
   - Formatter detected in project but no PostToolUse auto-format hook
   - Linter detected but no auto-lint hook
   - Test framework detected but no pre-commit test hook
   - Detailed docs exist in project (README, docs/) but not referenced from CLAUDE.md

   **Placement issues:**
   - CLAUDE.md entries that appear domain-specific (e.g., mention specific file types, frameworks, or directories) and might be better as scoped rules
   - CLAUDE.local.md entries that duplicate CLAUDE.md content
   - Auto-memory notes that describe persistent preferences but haven't been promoted to CLAUDE.md or rules
   - Rules without path frontmatter that load globally when they could be scoped
   - Verbose CLAUDE.md entries (>3 lines each) that could be extracted to reference docs

   **Staleness:**
   - Skills that exist but whose descriptions are vague (likely to under-trigger)
   - Rules or CLAUDE.md entries that seem to contradict each other

5. Present the report conversationally, organized by priority (most impactful suggestions first). For each finding, explain what it is, why it matters, and what Forge would do about it. Ask if the user wants to act on any findings.

**SKILL.md for `/forge:status`:**

```yaml
---
name: status
description: >
  Audit your Claude Code configuration health. Shows context budget usage,
  identifies misplaced entries, detects capability gaps, and suggests
  improvements. Use when you want to check how healthy your Claude Code
  setup is, or on first install to see what Forge can do. Works immediately
  with no session history needed.
---
```

The body of the SKILL.md should contain the detailed instructions above for Claude to follow when the skill is invoked. Write it as clear, imperative instructions.

**Acceptance criteria:**
- `/forge:status` produces a readable health report for a real project
- Report correctly counts CLAUDE.md lines
- Report detects at least one missing hook opportunity (e.g., Prettier without auto-format hook)
- Report identifies at least one placement suggestion if CLAUDE.md has domain-specific entries
- Report reads auto-memory if it exists and flags notes that could be promoted

**Test:** Run against your own project(s). Compare the report's findings against what you know about your setup. Does it catch things you'd agree with? Does it make any suggestions that feel wrong or irrelevant?

---

### Task 1.3: Phase A Analysis Script — Config Audit (Mode 2)

**What:** Create `scripts/analyze-config.py` — a Python script that programmatically scans project configuration and produces structured JSON output. This is the deterministic, zero-token foundation that the status skill and future analysis builds on.

**Why separate from the skill?** The skill (Task 1.2) has Claude do the reading and reasoning. This script does the same scan programmatically so that future automated analysis (Phase 3 background analysis) doesn't require an LLM call for basic config health checks. Both exist: the skill is the user-facing interface, the script is the automation-ready backend.

**Input:** Project root path (defaults to current working directory)

**Output:** JSON to stdout:
```json
{
  "timestamp": "2026-03-25T10:30:00Z",
  "project_root": "/path/to/project",
  "context_budget": {
    "claude_md_lines": 87,
    "claude_local_md_lines": 23,
    "rules_count": 4,
    "rules_total_lines": 180,
    "skills_count": 3,
    "agents_count": 1,
    "hooks_count": 2,
    "estimated_tier1_lines": 110
  },
  "tech_stack": {
    "detected": ["typescript", "react", "vitest", "prettier", "eslint"],
    "package_manager": "pnpm",
    "formatter": "prettier",
    "linter": "eslint",
    "test_framework": "vitest"
  },
  "gaps": [
    {
      "type": "missing_hook",
      "severity": "high",
      "description": "Prettier detected (.prettierrc exists) but no PostToolUse auto-format hook configured",
      "suggested_artifact": "hook",
      "detail": {
        "hook_event": "PostToolUse",
        "matcher": "Write|Edit",
        "command": "npx prettier --write \"$CLAUDE_TOOL_INPUT_FILE_PATH\""
      }
    }
  ],
  "placement_issues": [
    {
      "type": "domain_specific_in_claude_md",
      "severity": "medium",
      "line_number": 45,
      "content": "When writing React components, always use functional components with hooks",
      "suggestion": "Move to .claude/rules/react.md with path: '**/*.tsx' frontmatter"
    }
  ],
  "auto_memory": {
    "exists": true,
    "memory_md_lines": 34,
    "topic_files": ["debugging.md", "patterns.md"],
    "promotable_notes": [
      {
        "source": "memory/MEMORY.md",
        "content": "Project uses pnpm, not npm",
        "suggestion": "Promote to CLAUDE.md — this is a persistent preference that should always be in context"
      }
    ]
  }
}
```

**Implementation notes:**
- Use only Python standard library (no pip dependencies) for portability
- Parse JSON files with `json` module, YAML frontmatter with simple string parsing (don't require pyyaml)
- For tech stack detection, check for file existence — don't try to parse every config format
- The "domain_specific_in_claude_md" detection is heuristic: look for lines mentioning specific file extensions (.tsx, .py, .rs), framework names (React, Vue, Django), or directory names (src/, tests/, api/)
- Accept `--project-root` flag, default to cwd
- Exit 0 on success with JSON to stdout, exit 1 on error with message to stderr

**Acceptance criteria:**
- Script runs in <2 seconds on a typical project
- Correctly detects tech stack from package.json / pyproject.toml / etc.
- Correctly identifies missing formatter hook when Prettier config exists but no PostToolUse hook in settings.json
- Produces valid JSON output
- Works when auto-memory directory doesn't exist (graceful handling)
- Works when CLAUDE.md doesn't exist (reports as empty, still checks other things)

**Test:** Run directly: `python scripts/analyze-config.py --project-root /path/to/your/project | python -m json.tool` — verify the output is valid JSON and the findings are accurate for a real project.

---

### Task 1.4: Phase A Analysis Script — Transcript Scan (Mode 1)

**What:** Create `scripts/analyze-transcripts.py` — a Python script that scans session transcript JSONL files for correction patterns, repeated prompts, and post-action patterns. Zero LLM calls.

**Input:** Path to project's session directory (`~/.claude/projects/<hash>/`)

**Challenges to address upfront:**
- The JSONL transcript format is not publicly documented as a stable API. Before writing the parser, examine several actual transcript files to understand the structure. Document the format you find in a comment at the top of the script. Note: the format may vary between Claude Code versions.
- The project hash in `~/.claude/projects/` needs to be mapped to the actual project path. Examine how Claude Code organizes this directory to find the mapping.

**Approach:**
1. First, write a discovery function that reads transcript files and prints their structure — field names, message types, how user vs. assistant messages are distinguished, where tool calls live, etc. Run this against real transcripts to understand the format before writing the actual analysis.
2. Then implement the analysis functions:

**Correction detection:**
- Scan user messages for correction-adjacent phrases: "no,", "not that", "I said", "always use", "never use", "don't use", "switch to", "I told you", "actually,", "that's not right", "we use X not Y", "let's do it this way instead"
- For each match, extract: session ID, timestamp, the full user message, and the preceding Claude response (for context)
- Group similar corrections using simple string similarity (difflib.SequenceMatcher, ratio > 0.6)
- Only flag as candidate if the same correction appears in 3+ messages across 2+ sessions

**Post-action detection:**
- Identify sequences where: Claude uses Write/Edit tool → user's next message is a Bash command
- Group by the Bash command — if the same command (or very similar) follows the same tool type across 5+ occurrences in 3+ sessions, flag as hook candidate
- Common patterns to detect: `npx prettier`, `npm run lint`, `npm test`, `cargo fmt`, `black`, `ruff`, `go fmt`

**Repeated prompt detection:**
- Extract first user message from each session
- Compare all opening messages using SequenceMatcher — if 4+ sessions start with messages that are >0.5 similar, flag as skill candidate
- Also: detect sequences of 3+ user messages that appear in the same order across 3+ sessions

**Output:** JSON to stdout, similar structure to config audit but focused on transcript findings:
```json
{
  "timestamp": "2026-03-25T10:30:00Z",
  "sessions_analyzed": 12,
  "session_date_range": "2026-03-13 to 2026-03-25",
  "candidates": {
    "corrections": [
      {
        "pattern": "User corrects Claude about test framework preference",
        "occurrences": 4,
        "sessions": ["abc123", "def456", "ghi789", "jkl012"],
        "evidence": [
          {"session": "abc123", "timestamp": "2026-03-20T14:22:00Z", "user_message": "no, we use vitest not jest — always vitest"},
          {"session": "def456", "timestamp": "2026-03-17T09:15:00Z", "user_message": "switch that to vitest"}
        ],
        "suggested_artifact": "claude_md_entry",
        "suggested_content": "Always use vitest for testing, never jest",
        "confidence": "high"
      }
    ],
    "post_actions": [],
    "repeated_prompts": [],
    "repeated_sequences": []
  }
}
```

**Acceptance criteria:**
- Script successfully discovers and reads at least one real session transcript
- Transcript format is documented in a comment at the top of the script
- Correction detection finds real corrections in test sessions (create a few test sessions with deliberate corrections if needed)
- Script runs in <5 seconds for 10 sessions
- Gracefully handles missing/empty/malformed transcript files
- Produces valid JSON output

**Test:** Run against your real session history. Verify it finds corrections you actually made. If you haven't made enough corrections to trigger the threshold, temporarily lower it for testing (add a `--min-occurrences` flag).

---

### Task 1.5: Phase A Analysis Script — Memory Audit (Mode 3)

**What:** Create `scripts/analyze-memory.py` — scans auto-memory files and CLAUDE.local.md for entries that could be upgraded to better artifact types.

**Input:** Project root + auto-memory directory path

**Analysis:**
- Read MEMORY.md and topic files from auto-memory directory
- Read CLAUDE.local.md if it exists
- For each entry/note, classify what type of information it is:
  - **Preference** ("uses pnpm", "prefers functional components") → candidate for CLAUDE.md entry
  - **Convention** ("tests go in `__tests__/`", "API routes follow REST conventions") → candidate for rule
  - **Workflow** ("deployment process: build → test → deploy to staging → deploy to prod") → candidate for skill
  - **Command** ("build with `pnpm build`", "run tests with `pnpm test`") → candidate for CLAUDE.md entry or hook
  - **Debugging knowledge** ("Redis connection issues usually mean the local server isn't running") → candidate for reference doc
- Cross-reference with existing config: if a memory note is already covered by a CLAUDE.md entry, rule, or hook, flag as redundant
- Check CLAUDE.local.md for entries that are domain-specific (mention specific file types/frameworks) — suggest moving to scoped rules

**Output:** JSON to stdout, same pattern as other scripts.

**Acceptance criteria:**
- Script reads auto-memory files from the correct location for the current project
- Correctly classifies at least some memory notes into appropriate artifact types
- Detects redundancy between memory notes and existing CLAUDE.md entries
- Gracefully handles projects with no auto-memory

**Test:** Run against a project where you've used Claude Code enough for auto-memory to have accumulated notes. Verify the classifications make sense.

---

### Task 1.6: Session-Analyzer Subagent (Phase B)

**What:** Create `agents/session-analyzer.md` — the subagent that confirms candidate patterns from Phase A and produces final proposals.

**Agent definition:**
```yaml
---
name: session-analyzer
description: >
  Confirms candidate patterns from Forge's Phase A analysis. Receives
  pre-filtered evidence (not full transcripts) and determines: is this
  a real pattern? What artifact type should it be? What should the content
  look like? Only invoked by the /forge:analyze skill.
model: sonnet
effort: low
maxTurns: 5
disallowedTools: Write, Edit, Bash
---
```

**System prompt should instruct the agent to:**
1. Receive Phase A output (JSON from the analysis scripts)
2. For each candidate with sufficient evidence:
   - Confirm the pattern is real and consistent (not coincidental or one-off)
   - Select the correct artifact type using these criteria:
     - **CLAUDE.md entry:** Universal preference, applies to all sessions regardless of file type. Short (1-2 lines).
     - **Rule:** Domain-specific preference, clusters around specific file types or areas. Medium length. Should include a `path` frontmatter suggestion.
     - **Skill:** Multi-step workflow repeated 4+ times. The steps should be specific enough to automate.
     - **Hook:** Deterministic action (same command every time) after a tool use. Must be non-destructive and safe to auto-run.
     - **Agent:** Multi-phase workflow requiring context isolation or parallel execution. Rare — most things are skills.
     - **Reference doc:** Detailed knowledge that's too long for CLAUDE.md or a rule but that Claude should be able to find when needed.
   - Draft the artifact content
   - Rate confidence: high (clear, consistent, 4+ occurrences) or medium (likely real, 3 occurrences, some ambiguity)
3. For each candidate from config audit or memory audit:
   - Evaluate whether the suggestion is genuinely beneficial
   - Draft the artifact if appropriate
   - Flag any that seem too opinionated or project-specific to suggest without more context
4. Output a structured summary of confirmed proposals

**Acceptance criteria:**
- Agent runs within 5 turns and produces structured proposals
- Agent correctly distinguishes between CLAUDE.md entries (universal) and rules (domain-specific)
- Agent includes specific evidence citations in its proposals
- Agent doesn't hallucinate patterns — if Phase A evidence is ambiguous, it says so

**Test:** Feed it real Phase A output and verify the proposals are sensible. Deliberately include one weak candidate (only 2 occurrences) and verify the agent rates it as low-confidence or skips it.

---

### Task 1.7: Artifact-Generator Subagent

**What:** Create `agents/artifact-generator.md` — generates the actual files from confirmed proposals.

**Agent definition:**
```yaml
---
name: artifact-generator
description: >
  Generates Claude Code infrastructure artifacts (CLAUDE.md entries, rules,
  skills, hooks, agents, reference docs) from confirmed Forge proposals.
  Follows Anthropic's official specifications for each artifact type.
  Only invoked by the /forge:optimize skill.
model: sonnet
effort: low
maxTurns: 10
---
```

**System prompt should include:**
- Templates and formatting rules for each artifact type (sourced from `references/artifact-templates.md`)
- Anthropic's official constraints: skill names in kebab-case, descriptions <1024 chars, no XML tags in frontmatter, etc.
- Context budget awareness: before adding to CLAUDE.md, check current line count and warn if approaching limit
- For hooks: generate valid JSON that can be merged into settings.json
- For skills: generate full directory structure with SKILL.md
- For rules: include path frontmatter when applicable
- Quality flagging: mark skills and agents as "draft — test and iterate" in a comment at the top

**Acceptance criteria:**
- Generated CLAUDE.md entries are concise (1-2 lines each)
- Generated rules include path frontmatter when the proposal specifies file types
- Generated hooks are valid JSON with correct structure
- Generated skills have valid frontmatter with name, description, and trigger phrases
- All generated artifacts pass basic validation (no XML in frontmatter, kebab-case names, etc.)

**Test:** Generate one artifact of each type. Manually review for correctness. Install a generated hook in settings.json and verify it works. Install a generated skill and verify it triggers correctly.

---

### Task 1.8: Analyze Skill

**What:** Implement `/forge:analyze` — the main analysis command that orchestrates Phase A + B.

**The skill should instruct Claude to:**
1. Run all three Phase A scripts and collect their JSON output
2. Merge the results into a unified candidate list
3. If there are candidates above the evidence threshold, spawn the session-analyzer subagent with the evidence
4. Present the analyzer's findings conversationally:
   - How many sessions were analyzed, over what date range
   - How many candidates Phase A found, how many Phase B confirmed
   - For each confirmed proposal: what, why, where it would go, and specific evidence
5. Tell the user to run `/forge:optimize` to review and apply proposals
6. Store proposals to `.claude/forge/proposals/pending.json`

**SKILL.md for `/forge:analyze`:**
```yaml
---
name: analyze
description: >
  Analyze your recent Claude Code sessions, configuration, and auto-memory
  to find opportunities for better infrastructure. Detects repeated corrections,
  workflow patterns, capability gaps, and misplaced configuration. Use when
  you want Forge to review your setup and suggest improvements. Run
  /forge:status first for a quick config health check without transcript analysis.
---
```

**Acceptance criteria:**
- Running `/forge:analyze` produces a summary of findings from all three Phase A modes
- Proposals are stored to disk in `.claude/forge/proposals/pending.json`
- If no candidates meet the threshold, the skill says so clearly (not a wall of empty results)
- Total execution time is reasonable (<30 seconds for 10 sessions)

**Test:** Run on a real project. Verify findings include both config audit suggestions (gaps, placement issues) and transcript-based patterns (if sufficient session history exists). Verify proposals file is written correctly.

---

### Task 1.9: Optimize Skill

**What:** Implement `/forge:optimize` — the proposal review and application command.

**The skill should instruct Claude to:**
1. Read `.claude/forge/proposals/pending.json`
2. If no pending proposals, say so and suggest running `/forge:analyze` first
3. Present proposals one at a time, highest confidence first:
   - State what was observed (with evidence)
   - Show exactly what would be generated (preview the content)
   - State where it would be placed (file path and tier)
   - For skills/agents: note that this is a draft that should be tested
   - Ask: **approve** / **modify** / **skip** / **never** (permanently dismiss this pattern)
4. For approved proposals:
   - Spawn the artifact-generator subagent to generate the artifact
   - Write the generated files to the correct locations
   - If adding to CLAUDE.md: append to the file, check line count, warn if over budget
   - If creating a new file: create it and confirm the path
   - Update `.claude/forge/history/applied.json` with a record of what was generated, when, and why
5. For modified proposals: ask what the user wants to change, adjust, and then generate
6. For skipped proposals: keep in pending for next time
7. For "never" proposals: move to `.claude/forge/dismissed.json` — won't be proposed again

**Acceptance criteria:**
- Proposals are presented one at a time with clear evidence
- Approved artifacts are written to the correct file paths
- CLAUDE.md budget is checked before appending
- History is recorded in `.claude/forge/history/`
- Dismissed proposals don't reappear in future runs

**Test:** Run through the full flow: `/forge:analyze` → `/forge:optimize` → approve a proposal → verify the artifact was created correctly. Then run `/forge:status` to see the updated health report.

---

### Task 1.10: SessionEnd Hook

**What:** Add a lightweight SessionEnd hook that logs which sessions have occurred since the last analysis.

**Hook in `hooks/hooks.json`:**
```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PLUGIN_ROOT/scripts/log-session.sh\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**`scripts/log-session.sh`:** A simple script that reads the session ID from stdin (the hook input JSON) and appends it with a timestamp to `.claude/forge/unanalyzed-sessions.log`. This is used by future phases to know how many sessions have passed since the last analysis.

**Acceptance criteria:**
- Hook fires on session end without errors
- Session ID and timestamp are logged
- Script completes in <1 second
- Does not interfere with session close

**Test:** Complete a Claude Code session and verify a line was appended to the log file.

---

### Task 1.11: References — Artifact Templates and Best Practices

**What:** Create the reference documents that the artifact-generator subagent uses.

**`references/artifact-templates.md`:**
Contains exact templates and formatting rules for each artifact type:
- CLAUDE.md entry template (imperative, 1-2 lines, no verbose explanation)
- Rule template (with path frontmatter example, kebab-case filename convention)
- Hook JSON template (PostToolUse auto-format, pre-commit test, etc.)
- Skill SKILL.md template (frontmatter with name/description, body with instructions)
- Agent template (frontmatter with name/description/model/effort/maxTurns/disallowedTools)
- Reference doc template (markdown with headings, linked from CLAUDE.md or rules)

**`references/anthropic-best-practices.md`:**
Condensed guidance from Anthropic's official docs, specifically:
- CLAUDE.md: keep concise, loaded every session, shorter files produce better adherence
- Rules: one topic per file, descriptive filename, path frontmatter for scoping
- Skills: description is critical for auto-triggering, progressive disclosure, <1024 chars
- Hooks: deterministic, handler types (command/prompt/agent), matcher patterns are case-sensitive
- Agents: model/effort/maxTurns, disallowedTools for safety, context isolation benefit
- Context budget: skill descriptions consume 2% of context window, avoid overloading tier 1

**Acceptance criteria:**
- Templates produce valid artifacts when followed
- Best practices are accurate to current Anthropic documentation
- Artifact-generator subagent can reference these files effectively

---

### Phase 1 Integration Test

After all tasks are complete, run the full flow end-to-end:

1. `claude --plugin-dir ./forge`
2. `/forge:status` — get a config health report
3. Use Claude Code normally for a few sessions (or use existing session history)
4. `/forge:analyze` — run full analysis
5. `/forge:optimize` — review and apply proposals
6. `/forge:status` — verify the health report reflects the changes
7. Verify generated artifacts work correctly in subsequent sessions

**Success criteria for Phase 1:**
- Plugin installs and runs without errors
- `/forge:status` provides useful config health information on first run (cold start works)
- `/forge:analyze` finds at least one actionable suggestion for a real project
- `/forge:optimize` successfully generates and places at least one artifact
- Generated artifacts are correct (valid structure, proper formatting, right location)
- Total token cost of analysis is <15,000 tokens (monitor with `/cost` or ccusage)

---

## Phase 2: Full Artifact Coverage (v0.2)

**Goal:** Generate all artifact types (skills, hooks, agents, reference docs). Add tier promotion/demotion. Add MCP Elicitation for batch review UI.

### Task 2.1: Skill Generation
Extend artifact-generator to produce full skill directories (SKILL.md + optional scripts/ and references/). Test trigger accuracy with a set of sample prompts. Mark generated skills as drafts.

### Task 2.2: Hook Generation
Extend artifact-generator to produce hook JSON for common patterns: PostToolUse auto-format, PostToolUse auto-lint, Stop test runner. Include hook template variants for detected tech stacks (Prettier, ESLint, Black, rustfmt, etc.).

### Task 2.3: Agent Generation
Extend artifact-generator to produce agent markdown definitions. Focus on the most common pattern: plan-implement-review workflows. Include sensible defaults for model, effort, maxTurns.

### Task 2.4: Reference Doc Generation
Extend artifact-generator to produce reference docs and update CLAUDE.md or rules with pointers. Implement the extraction logic: when a CLAUDE.md entry or rule is too verbose, extract detail to a reference doc and leave a one-line pointer.

### Task 2.5: Tier Promotion/Demotion
Implement the logic that moves content between tiers:
- CLAUDE.md → rules (when entry is domain-specific)
- CLAUDE.md → reference doc (when entry is verbose)
- Rules → reference doc (when rule grows beyond budget)
- Auto-memory → CLAUDE.md / rules / reference doc (when note should be infrastructure)
- Reference doc key points → CLAUDE.md / rules (when Claude repeatedly loads the same reference — detected via transcript analysis)

### Task 2.6: MCP Elicitation Server
Add an MCP server to the plugin (`.mcp.json`) that provides structured forms for batch proposal review. When `/forge:optimize` has 2+ proposals, present a form with checkboxes instead of walking through one-by-one conversationally.

### Task 2.7: Pattern Detection — Repeated Prompts and Sequences
Extend Phase A transcript scan to detect multi-step workflow patterns and repeated opening prompts. These feed skill and agent generation.

### Task 2.8: Pattern Detection — Post-Action Patterns
Extend Phase A transcript scan to reliably detect the "user always runs X after Claude edits" pattern. This feeds hook generation.

---

## Phase 3: Proactive Intelligence (v0.3)

**Goal:** Background analysis, ambient nudges, and stale config detection.

### Task 3.1: Background Analysis on SessionStart
Implement the SessionStart hook that checks unanalyzed session count and spawns background analysis when threshold is met. Verify this doesn't block session start or noticeably impact quota.

### Task 3.2: Between-Task Ambient Nudge
Implement the Stop hook that checks for pending proposals and returns a systemMessage for Claude to append as a natural-language nudge. Once per session, high-confidence only, dismissible.

### Task 3.3: Session-Start Passive Briefing
Implement configurable session-start mention of pending proposals. Default: passive (only on open-ended first prompts).

### Task 3.4: Stale Config Detection
Add to `/forge:status`: detect rules, skills, and CLAUDE.md entries that haven't been relevant in recent sessions. Suggest archiving or removing them.

### Task 3.5: Artifact Effectiveness Tracking
After deploying an artifact, track whether the pattern that triggered it (e.g., a correction) stops appearing in subsequent sessions. Report in `/forge:status`.

### Task 3.6: Scoring Evaluation Infrastructure (NEW — added from staff review)

**What:** Build tooling to measure the accuracy of the correction classifier and theme clustering against real-world data. The NLP thresholds (keyword weights, corrective classification threshold, theme confidence levels) were set by intuition and have never been validated.

**Why:** This is the core product risk. Forge's value depends on proposal quality. Without measured precision/recall, every threshold is a guess. False positives erode user trust; false negatives make Forge appear useless.

**Deliverables:**

1. **Pair extraction script** (`tests/scoring_eval/extract_pairs.py`): Reads real JSONL transcripts, outputs assistant→user conversation pairs in a human-reviewable JSON format. Same sanitization as the pipeline (500 char truncation, control char removal).

2. **Labeling guidelines** (`tests/scoring_eval/labeled/README.md`): Defines ground-truth labels (`corrective`, `confirmatory`, `new_instruction`, `followup`) and severity levels (`strong`, `moderate`, `mild`). Establishes labeling conventions for ambiguous cases.

3. **Evaluation script** (`tests/scoring_eval/eval_classifier.py`): Runs `classify_response()` against labeled data. Reports precision, recall, F1 per classification. Flags specific false positives and false negatives. The labeled dataset becomes a regression test — any weight change must not degrade measured accuracy.

4. **Diagnostic review script** (`tests/scoring_eval/review_diagnostics.py`): Reads cached transcript analysis from `~/.claude/forge/projects/<hash>/cache/transcripts.cache.json`. Shows all detected themes with scores, near-misses, and threshold sensitivity analysis ("at threshold 2.0, these 2 additional themes would surface").

**Acceptance criteria:**
- Extraction script produces reviewable pairs from real transcripts
- After labeling 50-100 pairs, evaluation script reports precision >80% and recall >70% for correction detection
- If targets not met, thresholds are tuned using the evaluation data as regression test
- Diagnostic script shows why proposals were or weren't generated after any `/forge` run

**Privacy:** Labeled data files are gitignored (contain real user messages). Evaluation runs locally only.

### Task 3.7: Reduce SKILL.md Fragility (NEW — added from staff review)

**What:** The `/forge` SKILL.md is a 209-line program written in natural language. Push deterministic logic into testable scripts. Keep SKILL.md as an orchestrator (~100 lines) that calls scripts and handles user interaction.

**Why:** Ambiguity in prose instructions becomes runtime bugs that can't be reproduced or tested. Moving deterministic steps (formatting, validation, merging) into scripts makes them testable and removes LLM interpretation variance.

**Deliverables:**
1. **Format script** — takes proposals + context_health JSON, outputs formatted health table and proposal table as text
2. **Path validator script** — takes proposed paths, validates against allowed locations, returns pass/fail per path
3. **Settings merger script** — reads existing settings.json, merges new hook, writes back atomically
4. Reduced SKILL.md (~100 lines): run scripts → show output → ask questions → write files → finalize

**Acceptance criteria:**
- Extracted scripts have full test coverage
- SKILL.md is <120 lines
- End-to-end `/forge` flow works identically to before

---

## Phase 4: Advanced (v1.0)

### Task 4.1: Cross-Project Pattern Aggregation
Detect patterns that appear across multiple projects. Generate user-level artifacts in `~/.claude/CLAUDE.md` or `~/.claude/rules/`.

### Task 4.2: Explain Mode
User can ask "why does this rule exist?" and Forge shows the original evidence and proposal that generated it, pulled from `.claude/forge/history/`.

### Task 4.3: Self-Cost Tracking
Report token consumption of Forge's own analysis in `/forge:status`, alongside estimated savings from generated artifacts.

### Task 4.4: Export/Share
Export a project's Forge-generated configuration as a shareable package (zip of .claude/ contents with README explaining each artifact).

---

## Development Notes

### Testing with Claude Code
During development, always test with `claude --plugin-dir ./forge`. After making changes to skills, agents, or hooks, run `/reload-plugins` inside the session to pick up updates without restarting.

### Debugging
Run `claude --debug` to see plugin loading, hook execution, and skill discovery logs. Toggle verbose mode with `Ctrl+O` to see hook progress in the transcript.

### Key file locations to know
- Session transcripts: `~/.claude/projects/<hash>/<session-id>.jsonl`
- Auto-memory: `~/.claude/projects/<project>/memory/`
- Session memory: `~/.claude/projects/<hash>/<session-id>/session-memory/summary.md`
- Plugin cache (installed plugins): `~/.claude/plugins/cache/`
- Plugin state (Forge writes here): `.claude/forge/`

### Dependencies
- Python 3.8+ (standard library only — no pip packages)
- Claude Code v2.1.59+ (for auto-memory support)
- Claude Code v2.1.76+ (for MCP Elicitation in Phase 2)