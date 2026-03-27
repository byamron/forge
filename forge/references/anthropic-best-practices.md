# Anthropic Best Practices for Claude Code Configuration

Condensed from Anthropic's official documentation. Last updated 2026-03-27.

## CLAUDE.md
- Persistent instructions loaded at session start. Target under 200 lines per file, upper bound ~500
- Imperative voice, actionable instructions. No verbose explanations
- Levels: project (`.claude/CLAUDE.md` or root), user (`~/.claude/CLAUDE.md`), local (`.claude/CLAUDE.local.md`) — additive
- Supports `@path` imports for referencing external files

## Rules (`.claude/rules/*.md`)
- Context-specific instructions. One topic per file, kebab-case filename
- `paths` frontmatter (plural, YAML list) for scoping — rules with `paths` load only when matching files are read. Without `paths`, loads at session start
- Same concise imperative style as CLAUDE.md

## Skills (`.claude/skills/<name>/SKILL.md`)
- Reusable workflows invoked by name or auto-triggered by description match
- `name`: max 64 chars, lowercase+hyphens. `description`: <1024 chars, include "Use when..."
- Skill descriptions collectively consume ~2% of context (16K chars). Body loads on invocation only
- `.claude/commands/` is legacy — skills are preferred

## Hooks (`.claude/settings.json`)
- Deterministic actions at lifecycle points. Use for actions that must happen every time
- 4 handler types: `command`, `http`, `prompt`, `agent`
- Matchers: case-sensitive, no spaces around `|`
- Timeout defaults: command=600s, http=30s, prompt=30s, agent=60s
- 29 lifecycle events including: SessionStart/End, PreToolUse, PostToolUse, UserPromptSubmit, Stop, FileChanged, SubagentStart/Stop

## Agents (`.claude/agents/*.md`)
- Specialized subagents with custom system prompts and tool restrictions
- Use when you need context isolation. Use skills for reusable content in your conversation
- Required: `name` (lowercase+hyphens), `description`. Optional: `model`, `effort`, `maxTurns`, `disallowedTools`, `tools`, `permissionMode`

## Context Loading Order
At session start: system prompt → auto memory → environment → MCP tools → skill descriptions → user CLAUDE.md → user rules → project CLAUDE.md → project rules. Path-scoped rules and skill bodies load on demand.
