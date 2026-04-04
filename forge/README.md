# Forge

Infrastructure architect for Claude Code. Watches your sessions, detects patterns in how you work, and proposes rules, hooks, skills, and agents to make your setup better — then learns from your feedback.

## Installation

**Via marketplace (recommended):** In Claude Code, run `/plugins`, add `https://github.com/byamron/forge.git` as a marketplace, then install Forge.

**Local development:**
```bash
claude --plugin-dir ./forge
```

**Requirements:** Claude Code v2.1.59+, Python 3.8+

## What you'll see

All Forge messages appear as **system messages** — context injected at session start that Claude can reference in conversation. They're not pop-ups or banners. Claude sees the message and may mention it naturally ("By the way, Forge has a suggestion...") or you might not hear about it until you ask. Running `/forge` is always the guaranteed way to see everything.

### Day 1: silence

Forge starts logging sessions immediately but stays quiet until it has enough data. You won't notice it.

### After a few sessions: a nudge

Once Forge has analyzed enough sessions, Claude's context includes a note like:

> Forge: 3 pending proposals to review. Run `/forge` to review.

Claude may mention this at the start of your conversation, or not — it depends on context. Either way, the proposals are ready when you run `/forge`.

### When Forge is confident: proactive proposals

When a pattern is strong enough — high confidence, high impact or 5+ occurrences — Forge includes more detail in the system message so Claude can present it directly:

> Forge has 1 high-confidence suggestion:
>
> - **Add rule: always use vitest, not jest** -- corrected 8 times across 6 sessions (8 occurrences across 6 sessions)
>
> Run `/forge` to review and apply.

This gives Claude enough context to tell you about it without you having to run `/forge` first.

### When everything is healthy: a status line

When there are no new proposals and all applied artifacts are working, Forge includes a brief health line:

> Forge: tracking 23 sessions for this project. All 5 applied artifacts effective.

### When something isn't working: an alert

If an applied artifact isn't having the intended effect — say you added a "use vitest" rule but the same correction keeps appearing — Forge flags it:

> Note: 'Use vitest' may not be working -- the same pattern appeared 3 times since it was applied.

This fires regardless of your settings. Effectiveness problems are always surfaced.

## Running `/forge`

Results are instant — everything was pre-computed in the background. On first run for a new project, Forge analyzes synchronously (~30 seconds).

1. **Health table** — CLAUDE.md size, rule count, hooks, agents, gaps, stale artifacts
2. **Proposals** — ranked by impact, filtered by an LLM quality gate. Each shows type, evidence, and what it would generate.
3. **Review** — for each proposal:
   - **Approve** — generate and place the artifact
   - **Modify** — tell Forge what to change first
   - **Skip** — keep for next time
   - **Never** — dismiss permanently (Forge asks why: low impact, missing safety, already handled, not relevant)
4. **Generate** — approved artifacts are drafted, previewed, and written after your explicit approval

Forge never writes files without your approval.

## What Forge generates

| Artifact | Location | Example |
|----------|----------|---------|
| CLAUDE.md entry | `CLAUDE.md` (appended) | "Always use vitest, not jest" |
| Rule | `.claude/rules/<name>.md` | Path-scoped convention for test files |
| Hook | `.claude/settings.json` (merged) | Auto-format on save, lint after edit |
| Skill | `.claude/skills/<name>/SKILL.md` | Slash command for a repeated workflow |
| Agent | `.claude/agents/<name>.md` | Subagent for a recurring multi-step task |
| Reference doc | `.claude/references/<name>.md` | Verbose detail extracted from CLAUDE.md |

## How Forge learns

Every decision you make calibrates future proposals:

| You do | Forge learns |
|---|---|
| Dismiss proposals for "low impact" | Future proposals of that type get deflated impact scores |
| Dismiss for "missing safety" or add approval gates | Safety gate activates — automation proposals flagged for human-in-the-loop review |
| Skip a proposal 3 times | Auto-dismissed (Forge takes the hint) |
| Approve a proposal | Tracks whether the pattern stops appearing (effectiveness monitoring) |

Feedback is stored in `.claude/forge/` (git-tracked) — your teammates benefit from your calibration.

## Commands

| Command | What it does |
|---------|-------------|
| `/forge` | Review all proposals and apply improvements |
| `/forge:settings` | Configure nudge behavior and proactive proposals |
| `/forge:version` | Check installed version |

## Settings

Configure via `/forge:settings`:

| Setting | Options | Default | What it controls |
|---------|---------|---------|-----------------|
| Nudge level | `quiet` / `balanced` / `eager` | `balanced` | How aggressively Forge nudges about unanalyzed sessions |
| Proactive proposals | `on` / `off` | `on` | Surface high-confidence proposals at session start |

**Nudge levels:**
- **quiet** — no session-count nudges. Forge only reports when you run `/forge`.
- **balanced** — nudge after 5+ sessions since last analysis.
- **eager** — nudge after 2+ sessions.

Proactive proposals and effectiveness alerts are independent of nudge level — they always fire when Forge has something worth showing.

## How it works under the hood

Every session, four hooks run automatically:

**Session start:**
1. `check-pending.py` — decides what to tell you (proactive proposal, nudge, health signal, or effectiveness alert)
2. `background-analyze.py` — spawns background analysis if needed (Python pattern detection + LLM quality gate, ~5K tokens)

**Session end:**
3. `log-session.sh` — logs the session for future analysis
4. `cache-manager.py` — updates analysis caches

You never wait for any of this. The analysis runs in the background, and results are cached for the next `/forge` run or session-start message.

## Data storage

| Location | What | Shared? |
|----------|------|---------|
| `.claude/forge/` | Dismissed proposals, applied history, feedback signals | Yes (git-tracked, all contributors) |
| `~/.claude/forge/projects/<hash>/` | Settings, cache, pending proposals, session log | No (personal, per-machine) |
| `.claude/` | Generated artifacts (rules, skills, hooks, agents) | Yes (git-tracked) |

All analysis is scoped to the current project. No data leaves your machine. Forge never reads source code, API keys, `.env` files, or credentials.
