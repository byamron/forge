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
| `/forge:settings` | Configure nudge frequency and proactive proposals |
| `/forge:version` | Check installed version |

## What to expect

Forge communicates through **system messages** — context injected at session start that Claude can reference in conversation. Claude may mention them naturally or not, depending on context. Running `/forge` is always the guaranteed way to see everything.

### Between `/forge` runs

Forge runs four hooks every session automatically. You never wait for them.

At **session start**, Forge decides what to tell you based on what it knows. In priority order:

1. **Proactive proposals** — when a pattern is strong enough (high confidence, high impact or 5+ occurrences), Forge surfaces it directly: "Add rule: always use vitest, not jest — corrected 8 times across 6 sessions." This gives you enough context to decide without running `/forge`.

2. **Nudge** — when proposals are pending or enough sessions have accumulated since last analysis: "Forge: 3 pending proposals to review. Run `/forge` to review."

3. **Effectiveness alert** — if an applied artifact isn't working (the pattern it addressed keeps appearing): "'Use vitest' may not be working — the triggering pattern is still present." Always shown regardless of settings.

4. **Health signal** — when nothing else to report: "Forge: tracking 23 sessions for this project. All 5 applied artifacts effective."

At **session end**, Forge logs the session and updates analysis caches.

### When you run `/forge`

Results are instant — pre-computed in the background. On a new project, Forge analyzes synchronously (~30 seconds).

You see, in order:

1. **What changed** — new proposals, removed proposals, impact adjustments since your last review.
2. **Health table** — CLAUDE.md line count, rules, hooks, agents, stale artifacts, gaps.
3. **Calibration notes** — if past feedback has activated calibration ("Hook impact adjusted based on 5 previous low-impact dismissals").
4. **Proposals** — ranked by impact, filtered by the LLM quality gate.
5. **Review** — for each proposal:
   - **Approve** — generate the artifact, preview it, write it after your confirmation
   - **Modify** — tell Forge what to change first
   - **Skip** — keep for next time (auto-dismissed after 3 skips)
   - **Never** — dismiss permanently with a reason (low impact, missing safety, already handled, not relevant)

### How Forge learns

| What you do | What Forge does next time |
|---|---|
| Dismiss for "low impact" | Deflates impact scores for that proposal type |
| Dismiss for "missing safety" or add approval gates | Activates the safety gate — automation proposals flagged for review |
| Skip 3 times | Auto-dismisses it |
| Approve | Tracks whether the pattern stops appearing (effectiveness monitoring) |

Feedback is stored in `.claude/forge/` (git-tracked) — teammates benefit from your calibration.

## What Forge generates

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

| Setting | Options | Default | What it controls |
|---------|---------|---------|-----------------|
| Nudge level | `quiet` / `balanced` / `eager` | `balanced` | How aggressively Forge nudges about unanalyzed sessions |
| Proactive proposals | `on` / `off` | `on` | Surface high-confidence proposals at session start |

Proactive proposals and effectiveness alerts are independent of nudge level — they fire whenever Forge has something worth showing. Setting nudge to `quiet` suppresses session-count nudges and the health signal, but not actionable information.

## How it works

```
Sessions accumulate (automatic)
    |
Python scripts — config audit, transcript patterns, memory scan (zero tokens)
    |
LLM quality gate — filters generic patterns, finds contextual signals (~5K tokens)
    |
Cached proposals
    |
Session start — proactive surfacing of high-confidence proposals
    |
/forge — full review: approve, modify, skip, or dismiss with reason
    |
Feedback loop — calibrates impact scores, activates safety gates, tracks effectiveness
```

**Session start hooks** (5s timeout each): `check-pending.py` decides what to show; `background-analyze.py` spawns analysis if needed. **Session end hooks**: `log-session.sh` logs the session; `cache-manager.py` updates caches (15s timeout).

## Data storage

| Location | What | Shared? |
|----------|------|---------|
| `.claude/forge/` | Dismissed proposals, applied history, feedback signals | Yes (git-tracked, all contributors) |
| `~/.claude/forge/projects/<hash>/` | Settings, analysis cache, pending proposals, session log | No (personal, per-machine) |
| `.claude/` | Generated artifacts (rules, skills, hooks, agents) | Yes (git-tracked) |

All analysis is scoped to the current project. No data leaves your machine. Forge never reads source code, API keys, `.env` files, or credentials.
