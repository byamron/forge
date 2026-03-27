---
name: settings
description: >-
  Configure Forge nudge behavior. Use when the user wants to change how
  often Forge surfaces suggestions, or asks about Forge settings, or says
  things like "nudge me less" or "be more proactive."
---

## Step 1 — Read current settings

Run:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/read-settings.py"
```

This outputs the current settings as JSON, including the active nudge level and what it means.

## Step 2 — Show the user their options

Present the three nudge levels:

- **quiet** — No automatic nudges. Forge only runs when you invoke `/forge`. Best if you prefer full control and find nudges distracting.
- **balanced** (default) — Nudge on session start, but only after 5+ new sessions since the last analysis. One line, no token cost. Best for most users.
- **eager** — Nudge on session start after 2+ new sessions. Best if you want Forge to stay on top of your configuration proactively.

Show which level is currently active.

## Step 3 — Apply the user's choice

If the user picks a level (or describes what they want in natural language — map it to the closest level), run:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/write-settings.py" --nudge-level <level>
```

Where `<level>` is `quiet`, `balanced`, or `eager`.

Confirm the change with a one-line summary of what the new level means.

If the user's preference doesn't map cleanly to a level, explain the closest match and ask which they'd prefer.
