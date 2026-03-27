---
name: settings
description: >-
  Configure Forge nudge behavior. Use when the user wants to change how
  often Forge surfaces suggestions, or asks about Forge settings, or says
  things like "nudge me less" or "be more proactive."
---

## Step 0 — Resolve plugin root

Run this to determine the plugin's install directory:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; echo "$FORGE_ROOT"
```

Store the result — use it in place of `${CLAUDE_PLUGIN_ROOT}` for all script calls below. If it returns nothing, tell the user the Forge plugin scripts could not be located and stop.

## Step 1 — Read current settings

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/read-settings.py"
```

This outputs the current settings as JSON, including the active nudge level and what it means.

## Step 2 — Show the user their options

First, show the current level clearly on its own line:

> **Current level: balanced** (default)

Then present the three nudge levels in a table:

| Level | When Forge nudges | Best for |
|-------|-------------------|----------|
| **quiet** | Never — only runs when you invoke `/forge` | Full control, no interruptions |
| **balanced** (default) | When you have pending proposals, or after 5+ sessions since last analysis | Most users |
| **eager** | When you have any pending proposals, or after 2+ sessions since last analysis | Staying on top of config proactively |

## Step 3 — Apply the user's choice

If the user picks a level (or describes what they want in natural language — map it to the closest level), run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/write-settings.py" --nudge-level <level>
```

Where `<level>` is `quiet`, `balanced`, or `eager`.

Confirm the change with a one-line summary of what the new level means.

If the user's preference doesn't map cleanly to a level, explain the closest match and ask which they'd prefer.
