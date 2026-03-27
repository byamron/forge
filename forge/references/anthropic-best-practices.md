# Anthropic Best Practices for Claude Code Configuration

Condensed guidance from Anthropic's official documentation. Used by the artifact-generator agent to ensure generated artifacts follow official specifications. Last updated 2026-03-27.

## CLAUDE.md

- **Purpose:** Persistent instructions loaded into the context window at the start of every session
- **Target under 200 lines per file.** Files over 200 lines consume more context and may reduce adherence. If growing, move reference content to skills or path-scoped rules
- **Upper bound ~500 lines** — beyond this, reference material should be in skills (loaded on-demand)
- **Content:** Build commands, code style preferences, workflow rules, project conventions
- **Style:** Imperative voice, actionable instructions. No verbose explanations
- **Levels:** Project (`.claude/CLAUDE.md` or root `CLAUDE.md`), user (`~/.claude/CLAUDE.md`), local (`.claude/CLAUDE.local.md`). All levels are additive
- **`@path` imports:** Reference external files inline with `@path` syntax
- **Delivered as a user message** after the system prompt, not as part of the system prompt itself

## Rules (`.claude/rules/*.md`)

- **Purpose:** Context-specific instructions, discovered recursively from `.claude/rules/`
- **One topic per file** with descriptive filename in kebab-case
- **`paths` frontmatter** (plural, YAML list) for scoping:
  ```yaml
  ---
  paths:
    - "**/*.tsx"
    - "**/*.ts"
  ---
  ```
  Rules with `paths` load only when Claude reads matching files. Rules without `paths` load at session start (same as CLAUDE.md)
- **User-level rules** in `~/.claude/rules/` apply to every project. Project rules have higher priority
- **Symlinks** supported for sharing rules across projects
- **Content style:** Same concise, imperative style as CLAUDE.md

## Skills (`.claude/skills/<name>/SKILL.md`)

- **Purpose:** Reusable workflow packages invoked by name or auto-triggered by description match
- **Description:** Recommended but optional. If omitted, uses the first paragraph of markdown content. Claude matches task context against descriptions to decide which skills are relevant
- **Name:** `name` field, max 64 characters, lowercase and hyphens
- **Budget:** Skill descriptions collectively consume ~2% of context window (fallback: 16,000 characters). Override with `SLASH_COMMAND_TOOL_CHAR_BUDGET` env var. Run `/context` to check for warnings about excluded skills
- **Progressive disclosure:** Frontmatter always loaded (for routing). Body loads on invocation. Supporting files in the skill directory load on demand when Claude reads them
- **Commands merged into skills:** `.claude/commands/` files still work and support the same frontmatter. Skills are recommended since they support additional features like supporting files. If a skill and command share the same name, the skill takes precedence

### Skill frontmatter fields

| Field | Notes |
|-------|-------|
| `name` | Max 64 characters, lowercase letters and hyphens |
| `description` | When this skill should trigger. Include "Use when..." language |
| `argument-hint` | Hint text shown in slash command autocomplete |
| `user-invocable` | Whether the skill appears in slash command menu |
| `disable-model-invocation` | If true, skill is invisible to auto-triggering |
| `allowed-tools` | Tools the skill can use |
| `model` | Model override for this skill |
| `effort` | Reasoning effort level |
| `context` | Additional context files to load |
| `agent` | Run as a subagent with these settings |
| `hooks` | Lifecycle hooks scoped to this skill |
| `paths` | File patterns that trigger this skill |
| `shell` | Shell environment for bash commands |

## Hooks

- **Purpose:** Deterministic actions that execute automatically at lifecycle points
- **Key principle:** "Use hooks for actions that must happen every time with zero exceptions"
- **4 handler types:** `command` (shell), `http` (endpoint), `prompt` (LLM eval), `agent` (subagent)
- **Matchers:** Case-sensitive, no spaces around `|`. Example: `Write|Edit`

### Timeout defaults by handler type

| Type | Default timeout |
|------|----------------|
| `command` | 600 seconds |
| `http` | 30 seconds |
| `prompt` | 30 seconds |
| `agent` | 60 seconds |

### Lifecycle events (29 total)

**Session:** SessionStart, SessionEnd
**Configuration:** InstructionsLoaded, ConfigChange
**User interaction:** UserPromptSubmit, Notification, Elicitation, ElicitationResult
**Tool use:** PreToolUse, PermissionRequest, PostToolUse, PostToolUseFailure
**Subagents:** SubagentStart, SubagentStop
**Completion:** Stop, StopFailure, TeammateIdle
**Tasks:** TaskCreated, TaskCompleted
**Filesystem:** CwdChanged, FileChanged
**Context:** PreCompact, PostCompact
**Worktrees:** WorktreeCreate, WorktreeRemove

## Agents (`.claude/agents/*.md`)

- **Purpose:** Specialized subagents with custom system prompts and tool restrictions
- **When to use:** "Use a subagent when you need context isolation or when your context window is getting full." Use skills for reusable content that runs in your conversation
- **Name:** Lowercase letters and hyphens

### Agent frontmatter fields

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Lowercase letters and hyphens |
| `description` | Yes | When Claude should delegate to this agent |
| `tools` | No | Inherits all if omitted |
| `disallowedTools` | No | Removed from inherited/specified tools |
| `model` | No | `sonnet`, `opus`, `haiku`, full model ID, or `inherit` (default: `inherit`) |
| `effort` | No | `low`, `medium`, `high`, `max` (max is Opus 4.6 only) |
| `maxTurns` | No | Max agentic turns |
| `permissionMode` | No | `default`, `acceptEdits`, `dontAsk`, `bypassPermissions`, `plan` |
| `skills` | No | Full content injected at startup |
| `mcpServers` | No | MCP servers available to subagent |
| `hooks` | No | Lifecycle hooks scoped to subagent |
| `memory` | No | `user`, `project`, or `local` |
| `background` | No | Run as background task |
| `isolation` | No | `worktree` for git worktree isolation |
| `initialPrompt` | No | Auto-submitted first user turn when agent runs as main |

## Context Loading Order

At session start (in order):
1. System prompt (~4,200 tokens)
2. Auto memory / MEMORY.md (first 200 lines or 25KB)
3. Environment info (~280 tokens)
4. MCP tools (deferred, names only, ~120 tokens)
5. Skill descriptions (~450 tokens, not re-injected after /compact)
6. User-level `~/.claude/CLAUDE.md`
7. User-level rules without `paths` frontmatter
8. Project CLAUDE.md
9. Project rules without `paths` frontmatter

On demand:
- Path-scoped rules: load when matching files are read
- Skill body content: loads on invocation
- Skill supporting files: load when Claude reads them
- Reference docs: load when Claude reads them

Note: `.claude/references/` is a project convention, not an official Anthropic standard. The official approach for reference material is to put supporting files inside skill directories.
