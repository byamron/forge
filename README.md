# Forge

Infrastructure architect for Claude Code. Analyzes your sessions and configuration to generate optimized rules, skills, hooks, agents, and reference docs — then learns from your feedback to improve over time.

## Installation

**Via marketplace (recommended):** In Claude Code, run `/plugins`, add `https://github.com/byamron/forge.git` as a marketplace, then install Forge.

**Local development:**
```bash
claude --plugin-dir ./forge
```

**Requirements:** Claude Code v2.1.59+, Python 3.8+

## Commands

| Command | What it does |
|---------|-------------|
| `/forge` | Analyze your setup and walk through improvements |
| `/forge:settings` | Configure nudge frequency |
| `/forge:version` | Check installed version |

## How it works

Once installed, Forge runs automatically in the background. You don't need to do anything — it watches every session and builds up an understanding of your workflows.

### Background (every session, invisible)

**Session start:** Forge checks for pending proposals and may show a one-line nudge. If enough sessions have accumulated, it spawns background analysis — Python scripts detect patterns (zero tokens), then an LLM quality gate filters and enriches the results (~5K tokens). You don't wait for any of this.

**Session end:** Forge logs the session for future analysis. No output, no delay.

### When you run `/forge`

Results are instant — everything was pre-computed in the background. On first run for a new project, Forge analyzes synchronously with a progress message (~30 seconds).

1. **Health table** — CLAUDE.md size, rule count, hooks, agents, gaps, stale artifacts
2. **Proposals** — ranked by impact, filtered by the LLM quality gate. Each shows type, evidence, and what it would generate.
3. **Review** — for each proposal:
   - **Approve** — generate and place the artifact
   - **Modify** — tell Forge what to change first
   - **Skip** — keep for next time
   - **Never** — dismiss permanently (Forge asks why: low impact, missing safety, already handled, not relevant)
4. **Generate** — approved artifacts are drafted, previewed, and placed after your explicit approval

### How Forge learns

Forge gets better the more you use it. Your decisions shape future proposals:

| You do | Forge learns |
|---|---|
| Dismiss proposals for "low impact" | Future proposals of that type get deflated impact scores |
| Dismiss for "missing safety" or add approval gates | Safety gate activates — future automation proposals flagged for human-in-the-loop review |
| Skip a proposal 3 times | Auto-dismissed |
| Approve a proposal | Tracks whether the pattern it addressed stops appearing (effectiveness) |

Feedback is stored in `.claude/forge/` (git-tracked) — your teammates benefit from your calibration.

### The pipeline

```
Session data (every session, automatic)
    ↓
Python scripts — detect patterns, config gaps, staleness (zero tokens)
    ↓
LLM quality gate — filter generic patterns, find contextual signals (~5K tokens, background)
    ↓
Cached proposals (instant on next /forge)
    ↓
User review — approve, modify, skip, or dismiss with reason
    ↓
Feedback loop — calibrates future proposals
```

## What Forge generates

All artifacts are drafts you review before applying. Forge never writes files without your explicit approval.

| Artifact | Location | Example |
|----------|----------|---------|
| CLAUDE.md entry | `CLAUDE.md` (appended) | "Always use vitest, not jest" |
| Rule | `.claude/rules/<name>.md` | Path-scoped convention for test files |
| Hook | `.claude/settings.json` (merged) | Auto-format on save, lint after edit |
| Skill | `.claude/skills/<name>/SKILL.md` | Slash command for a repeated workflow |
| Agent | `.claude/agents/<name>.md` | Subagent for a recurring multi-step task |
| Reference doc | `.claude/references/<name>.md` | Verbose detail extracted from CLAUDE.md |

## Settings

Configure via `/forge:settings`:

| Level | Background analysis | Session-start message |
|-------|--------------------|-----------------------|
| `quiet` | Off — only analyzes when you run `/forge` | None |
| `balanced` (default) | After 5+ sessions accumulate | Tells Claude about pending proposals (Claude may mention it) |
| `eager` | After 2+ sessions accumulate | Same, but triggers sooner |

In balanced/eager mode, Forge automatically analyzes in the background and injects a system message that Claude can reference. In quiet mode, nothing happens until you manually run `/forge`.

## Data storage

| Location | What | Shared? |
|----------|------|---------|
| `.claude/forge/` | Dismissed proposals, applied history, feedback signals | Yes (git-tracked, all contributors) |
| `~/.claude/forge/projects/<hash>/` | Settings, cache, pending proposals, session log | No (personal, per-machine) |
| `.claude/` | Generated artifacts (rules, skills, hooks, agents) | Yes (git-tracked) |

All analysis is scoped to the current project. No data leaves your machine. Forge never reads source code, API keys, `.env` files, or credentials.
