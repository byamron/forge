# Forge

Infrastructure architect for Claude Code. Forge watches your sessions, detects patterns in how you work, and proposes infrastructure improvements — rules, hooks, skills, agents — that make Claude Code work better for your specific project. It learns from your feedback, so proposals get sharper over time.

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
| `/forge` | Review and apply infrastructure proposals |
| `/forge:settings` | Configure nudge frequency |
| `/forge:version` | Check installed version |

## What happens when you use Forge

### Every session (automatic, invisible)

Forge runs four hooks — two at session start, two at session end. You never see them.

**Session start:**
- Checks for pending proposals. If any exist and your nudge level allows it, injects a system message into Claude's context mentioning them.
- Spawns background analysis if enough sessions have accumulated since the last run. Python scripts detect patterns at zero token cost, then an LLM quality gate filters and enriches the results (~5K tokens).

**Session end:**
- Logs the session for future analysis.
- Updates analysis caches so the next `/forge` is instant.

### When you run `/forge`

Results are instant — everything was pre-computed in the background. On a new project where no background analysis has run yet, Forge analyzes synchronously (~30 seconds) with a progress message.

You see, in order:

1. **What changed** — if you've run `/forge` before, a summary of what's different: new proposals, removed proposals, impact adjustments. This tells you whether it's worth reviewing again or if nothing moved.

2. **Health table** — CLAUDE.md line count, rules, hooks, agents, stale artifacts, demotion candidates, ineffective artifacts. Warnings flag gaps and budget pressure.

3. **Calibration notes** — if your past feedback has activated any calibration mechanisms, Forge tells you. Examples:
   - "Hook impact adjusted based on 5 previous low-impact dismissals."
   - "Automation proposals flagged for safety review based on your feedback."
   - "2 proposals auto-dismissed after being skipped 3 times."

   These explain *why* the proposal set looks the way it does — not just what's in it.

4. **Proposals** — ranked by impact (high first), filtered by the LLM quality gate. Each row shows impact level, type, a description, and evidence from your sessions.

5. **Review** — for each proposal, you choose:
   - **Approve** — Forge generates the artifact, previews it, and writes it after your explicit confirmation
   - **Modify** — tell Forge what to change, then approve the revised version
   - **Skip** — keep it for next time (auto-dismissed after 3 skips)
   - **Never** — dismiss permanently. Forge asks why: low impact, missing safety steps, already handled, or not relevant. The reason feeds the calibration loop.

   For structural proposals (demotions, reference doc extractions), the review includes a content preview — the first few lines of what would be generated — so you can judge the change before approving.

6. **Generate** — approved artifacts are written to `.claude/`. Hooks are merged into `settings.json` non-destructively.

### How Forge learns from you

Every decision you make during review shapes future proposals:

| What you do | What Forge does next time |
|---|---|
| Dismiss proposals for "low impact" | Deflates impact scores for that proposal type — fewer low-value proposals surface |
| Dismiss for "missing safety" or add approval gates when modifying | Activates the safety gate — future automation proposals (hooks, agents) are flagged for human-in-the-loop review |
| Skip a proposal 3 times | Auto-dismisses it — you shouldn't have to keep saying "not now" |
| Approve a proposal | Tracks whether the pattern it addressed stops appearing in subsequent sessions (effectiveness tracking) |

This feedback is stored in `.claude/forge/` and git-tracked, so your teammates benefit from your calibration without running `/forge` themselves.

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
| Demotion | Rule or reference doc + CLAUDE.md update | Move a 20-line section to a rule, leave a one-line pointer |

## Settings

Configure via `/forge:settings`:

| Level | Background analysis | Session-start nudge |
|-------|--------------------|-----------------------|
| `quiet` | Off — only analyzes when you run `/forge` | Silent |
| `balanced` (default) | After 5+ sessions accumulate | System message about pending proposals |
| `eager` | After 2+ sessions accumulate | Same, triggers sooner |

The session-start nudge is a system message injected into Claude's context. Claude may or may not surface it depending on conversational context. To review proposals directly, run `/forge`.

## The pipeline

```
Sessions accumulate (automatic)
    |
Python scripts - config audit, transcript patterns, memory scan (zero tokens)
    |
LLM quality gate - filters generic patterns, finds contextual signals (~5K tokens)
    |
Cached proposals (instant on next /forge)
    |
User review - approve, modify, skip, or dismiss with reason
    |
Feedback loop - calibrates impact scores, activates safety gates, decays stale skips
    |
Next /forge run - sharper proposals, "what changed" summary, calibration notes
```

## Data storage

| Location | What | Shared? |
|----------|------|---------|
| `.claude/forge/` | Dismissed proposals, applied history, feedback signals | Yes (git-tracked, all contributors) |
| `~/.claude/forge/projects/<hash>/` | Settings, analysis cache, pending proposals, session log | No (personal, per-machine) |
| `.claude/` | Generated artifacts (rules, skills, hooks, agents) | Yes (git-tracked) |

All analysis is scoped to the current project. No data leaves your machine. Forge never reads source code, API keys, `.env` files, or credentials.
