# Noticed

Infrastructure architect for Claude Code. Noticed watches your sessions, detects patterns in how you work, and proposes infrastructure improvements — rules, hooks, skills, agents — that make Claude Code work better for your specific project. It learns from your feedback, so proposals get sharper over time.

## Installation

**Via marketplace (recommended):** In Claude Code, run `/plugins`, add `https://github.com/byamron/forge.git` as a marketplace, then install Noticed. (The repository is still named `forge` — only the plugin was renamed.)

**Local development:**
```bash
claude --plugin-dir ./noticed
```

**Requirements:** Claude Code v2.1.59+, Python 3.8+

### Upgrading from Forge

Noticed is the renamed successor to the Forge plugin (renamed in v0.5.0). If you previously had Forge installed:

1. Uninstall the old plugin first: `/plugin uninstall forge@forge` — leaving both installed registers duplicate SessionStart hooks and confuses the proposal pipeline.
2. Install Noticed via the marketplace as above.
3. Your data migrates automatically on first run. Personal settings, caches, pending proposals, and session logs at `~/.claude/forge/projects/<hash>/` are copied to `~/.claude/noticed/projects/<hash>/`. Project-level feedback data (`.claude/forge/dismissed.json`, `applied.json`, `feedback_signals.json`) is copied to `.claude/noticed/`. Legacy directories are left intact for rollback — delete them manually when you're confident the migration worked.
4. Skill invocations change: `/forge` → `/noticed`, `/forge:settings` → `/noticed:settings`, `/forge:version` → `/noticed:version`.

## Commands

| Command | What it does |
|---------|-------------|
| `/noticed` | Review and apply infrastructure proposals |
| `/noticed:settings` | Configure nudge frequency and proactive proposals |
| `/noticed:version` | Check installed version |

## What to expect

At **session start**, you'll see a one-line notification in the terminal:

- `Noticed has 3 proposals. Run /noticed to review.` — when proposals are ready
- `Noticed: tracking 23 sessions for this project.` — when Noticed is active but no proposals yet

At **session end**, Noticed logs the session and updates analysis caches. All of this is automatic — you never wait for it.

### When you run `/noticed`

Results are instant — pre-computed in the background. On a new project, Noticed analyzes synchronously (~30 seconds).

You see, in order:

1. **What changed** — new proposals, removed proposals, impact adjustments since your last review.
2. **Health table** — CLAUDE.md line count, rules, hooks, agents, stale artifacts, gaps.
3. **Calibration notes** — if past feedback has activated calibration ("Hook impact adjusted based on 5 previous low-impact dismissals").
4. **Proposals** — ranked by impact, filtered by the LLM quality gate.
5. **Review** — for each proposal:
   - **Approve** — generate the artifact, preview it, write it after your confirmation
   - **Modify** — tell Noticed what to change first
   - **Skip** — keep for next time (auto-dismissed after 3 skips)
   - **Never** — dismiss permanently with a reason (low impact, missing safety, already handled, not relevant)

### How Noticed learns

| What you do | What Noticed does next time |
|---|---|
| Dismiss for "low impact" | Deflates impact scores for that proposal type |
| Dismiss for "missing safety" or add approval gates | Activates the safety gate — automation proposals flagged for review |
| Skip 3 times | Auto-dismisses it |
| Approve | Tracks whether the pattern stops appearing (effectiveness monitoring) |

Feedback is stored in `.claude/noticed/` (git-tracked) — teammates benefit from your calibration.

## What Noticed generates

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

Configure via `/noticed:settings`:

| Setting | Options | Default | What it controls |
|---------|---------|---------|-----------------|
| Nudge level | `quiet` / `balanced` / `eager` | `balanced` | `quiet` suppresses the session-tracking notification |
| Proactive proposals | `on` / `off` | `on` | Show proposal count at session start |

## How it works

```
Sessions accumulate (automatic)
    |
Python scripts — config audit, transcript patterns, memory scan (zero tokens)
    |
Confidence gate — only high-confidence proposals survive (strong evidence required)
    |
LLM quality gate — filters generic patterns, finds contextual signals (~5K tokens)
    |
Cached proposals
    |
Session start — terminal notification with proposal count
    |
/noticed — full review: approve, modify, skip, or dismiss with reason
    |
Feedback loop — calibrates impact scores, activates safety gates, tracks effectiveness
```

**Session start hooks** (5s timeout each): `check-pending.py` decides what to show; `background-analyze.py` spawns analysis if needed. **Session end hooks**: `log-session.sh` logs the session; `cache-manager.py` updates caches (15s timeout).

## Data storage

| Location | What | Shared? |
|----------|------|---------|
| `.claude/noticed/` | Dismissed proposals, applied history, feedback signals | Yes (git-tracked, all contributors) |
| `~/.claude/noticed/projects/<hash>/` | Settings, analysis cache, pending proposals, session log | No (personal, per-machine) |
| `.claude/` | Generated artifacts (rules, skills, hooks, agents) | Yes (git-tracked) |

All analysis is scoped to the current project. No data leaves your machine. Noticed never reads source code, API keys, `.env` files, or credentials.
