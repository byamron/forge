# Anthropic Best Practices for Claude Code Configuration

Condensed guidance from Anthropic's official documentation. Used by the artifact-generator agent to ensure generated artifacts follow official specifications.

## CLAUDE.md

- **Purpose:** Persistent instructions loaded at the start of every session
- **Keep concise:** Shorter files produce better adherence. Aim for ~100 lines project-level, ~50 lines user-level
- **Content:** Build commands, code style preferences, workflow rules, project conventions
- **Style:** Imperative voice, actionable instructions. No verbose explanations
- **Levels:** Project (`.claude/CLAUDE.md` or `CLAUDE.md`), user (`~/.claude/CLAUDE.md`), local (`.claude/CLAUDE.local.md`). All levels are additive
- **Budget:** Track line count. When approaching capacity, demote domain-specific entries to rules or extract verbose content to reference docs

## Rules (`.claude/rules/*.md`)

- **Purpose:** Context-specific instructions that load when matching files are opened
- **One topic per file** with descriptive filename in kebab-case
- **Path frontmatter** for scoping: `path: "**/*.tsx"` makes the rule load only when touching matching files
- **Discovery:** All `.md` files in `.claude/rules/` are discovered recursively
- **Without path frontmatter:** Rule loads globally (same as CLAUDE.md but in a separate file). Add path matchers when the rule is domain-specific
- **Content style:** Same concise, imperative style as CLAUDE.md

## Skills (`.claude/skills/<name>/SKILL.md`)

- **Purpose:** Reusable workflow packages loaded on invocation or when Claude determines relevance
- **Description is critical:** The description field determines when skills auto-trigger. Must be <1024 characters. Include trigger phrases and "Use when..." language
- **Progressive disclosure:** Frontmatter is always loaded (for routing). Body loads on invocation. `references/` directory loads on demand
- **Naming:** `name` field in kebab-case. Invoked as `/skill-name` or auto-triggered by description match
- **Budget:** Skill descriptions consume ~2% of context window collectively. Don't overload with too many skills

## Hooks

- **Purpose:** Deterministic actions that execute automatically at lifecycle points
- **Key principle:** "Use hooks for actions that must happen every time with zero exceptions"
- **Handler types:**
  - `command` — Shell command execution (most common)
  - `http` — HTTP endpoint call
  - `prompt` — LLM prompt evaluation
  - `agent` — Spawn a subagent
- **Key lifecycle events:**
  - `PostToolUse` — After Claude uses a tool (auto-format, auto-lint)
  - `Stop` — When Claude finishes responding (post-task validation)
  - `PreToolUse` — Before Claude uses a tool (safety gates)
  - `SessionStart` — When a session begins (context injection)
  - `SessionEnd` — When a session ends (cleanup, logging)
- **Matchers:** Case-sensitive, no spaces around `|`. Example: `Write|Edit`
- **Timeout:** In seconds. Default 10. Set higher for test runners (30s)

## Agents (`.claude/agents/*.md`)

- **Purpose:** Specialized subagents with custom system prompts and tool restrictions
- **Context isolation:** "Use a subagent when you need context isolation or when your context window is getting full"
- **Frontmatter fields:** `name`, `description`, `model`, `effort`, `maxTurns`, `tools`, `disallowedTools`, `skills`, `memory`, `background`, `isolation`
- **Cost control:** Use `model: sonnet` and `effort: low` for lightweight tasks. Keep `maxTurns` low (3-10)
- **Safety:** Use `disallowedTools` to restrict what the agent can do

## Context Budget

- Skill descriptions collectively use ~2% of context window (fallback: 16,000 characters)
- CLAUDE.md + CLAUDE.local.md + loaded rules = tier 1+2 context load at session start
- Avoid overloading tier 1 — move domain-specific content to rules, verbose content to reference docs
- Reference docs (tier 3) have no hard limit since they're loaded on demand
- Skill-scoped references (tier 4) load only during skill invocation
