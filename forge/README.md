# Forge

Infrastructure architect for Claude Code. Analyzes your sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs.

## Installation

**Via marketplace (recommended):** In Claude Code, run `/plugins`, add `https://github.com/byamron/forge.git` as a marketplace, then install Forge.

**Local development:**
```bash
claude --plugin-dir ./forge
```

After cloning, enable the version-sync pre-commit hook:
```bash
git config core.hooksPath .githooks
```

**Requirements:** Claude Code v2.1.59+, Python 3.8+

## Commands

| Command | What it does |
|---------|-------------|
| `/forge` | Analyze your setup and walk through improvements |
| `/forge:settings` | Configure nudge frequency |
| `/forge:version` | Check installed version and freshness |

## What you'll see

Forge works quietly in the background and only surfaces information when it's useful.

### On session start

Forge checks for pending work and may show a one-line nudge:

| State | What you see |
|-------|-------------|
| Nothing pending | Nothing — Forge is silent |
| Pending proposals from a previous analysis | "Forge: 2 pending proposals to review. Run `/forge` to review." |
| Enough sessions since last analysis | "Forge: 5 sessions since last analysis. Run `/forge` to review." |
| Both | "Forge: 2 pending proposals to review, 5 sessions since last analysis. Run `/forge` to review." |
| Nudge level set to quiet | Nothing — nudges are disabled |

If enough unanalyzed sessions have accumulated, Forge also spawns a background analysis (zero tokens, no delay to your session). Results appear as proposals next time you run `/forge`.

### On session end

Forge silently logs the session for future analysis. No output, no delay.

### When you run `/forge`

1. **Context health** — a table showing your CLAUDE.md size, rule count, hooks, agents, and any gaps or issues detected
2. **Proposals** — a ranked list of suggested improvements with impact level, type, and evidence
3. **Review** — for each proposal, choose: **Approve** (generate it now), **Modify** (adjust first), **Skip** (keep for next time), or **Never** (dismiss permanently)
4. **Generate** — approved artifacts are drafted and shown for your final approval before any files are written

### Settings

Configure via `/forge:settings`:

**Nudge frequency** — controls the session-start nudge and background analysis trigger:

| Level | Behavior |
|-------|----------|
| `quiet` | Never nudge. Forge only runs when you invoke `/forge`. |
| `balanced` (default) | Nudge when proposals are pending or after 5+ sessions since last analysis. |
| `eager` | Nudge when proposals are pending or after 2+ sessions. |

Forge automatically runs an LLM quality gate in the background after each analysis cycle (~5K tokens). This filters out generic patterns and finds contextual signals the scripts cannot detect.

## What Forge generates

All artifacts are drafts you review before applying. Forge never writes files without your explicit approval.

| Artifact | Location | Example |
|----------|----------|---------|
| CLAUDE.md entry | `CLAUDE.md` (appended) | "Always run tests before committing" |
| Rule | `.claude/rules/<name>.md` | Path-scoped lint or style constraint |
| Hook | `.claude/settings.json` (merged) | Auto-format on save, lint on commit |
| Skill | `.claude/skills/<name>/SKILL.md` | Custom slash command for a repeated workflow |
| Agent | `.claude/agents/<name>.md` | Specialized subagent for a recurring task |
| Reference doc | `.claude/references/<name>.md` | Detailed template or best-practice guide |

## How it works

Forge operates in a **collect, analyze, review, generate** pipeline:

1. **Collect** — session transcripts, `.claude/` configuration, and auto-memory are read locally
2. **Analyze** (zero tokens) — Python scripts scan for repeated patterns, config gaps, and optimization opportunities
3. **Quality gate** (~5K tokens) — an LLM pass filters out generic patterns and finds contextual signals scripts can't detect, running in the background so you can keep working
4. **Review** — proposals are ranked by impact and presented for your decision
5. **Generate** — approved artifacts are drafted, shown for final approval, and placed in the correct locations

All analysis is scoped to the current project and its worktrees. No data leaves your machine.

## Where Forge stores data

| Location | Contents |
|----------|----------|
| `~/.claude/forge/projects/<hash>/` | Settings, proposals, applied history, analysis cache, session log. Shared across worktrees of the same project. |
| `.claude/` | Generated artifacts (rules, skills, agents, hooks). These are yours — Forge just creates them. |
| `CLAUDE.md` | Generated entries (appended). |

Forge never reads or writes source code, API keys, `.env` files, or credentials. The `<hash>` is derived from your git remote URL (credentials stripped).
