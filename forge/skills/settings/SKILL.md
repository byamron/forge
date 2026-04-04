---
name: settings
description: >-
  Configure Forge nudge behavior. Use when the user wants to change how often
  Forge surfaces suggestions -- things like "nudge me less", "be more
  proactive", or asks about Forge settings.
---

## Step 0 -- Resolve plugin root

Run this to determine the plugin's install directory:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; echo "$FORGE_ROOT"
```

Store the result -- use it in place of `${CLAUDE_PLUGIN_ROOT}` for all script calls below. If it returns nothing, tell the user the Forge plugin scripts could not be located and stop.

## Step 1 -- Read current settings

Run:

```bash
python3 "<FORGE_ROOT>/scripts/read-settings.py"
```

This outputs the current settings as JSON, including the active nudge level and what it means.

## Step 2 -- Show the user their options

### Nudge frequency

Show the current level clearly:

> **Current nudge level: balanced** (default)

| Level | When Forge nudges | Best for |
|-------|-------------------|----------|
| **quiet** | Never -- only runs when you invoke `/forge` | Full control, no interruptions |
| **balanced** (default) | When you have pending proposals, or after 5+ sessions since last analysis | Most users |
| **eager** | When you have any pending proposals, or after 2+ sessions since last analysis | Staying on top of config proactively |

### Proactive proposals

Show the current setting:

> **Proactive proposals: on** (default)

When **on**, Forge surfaces high-confidence suggestions at session start with enough detail to approve them inline -- no need to run `/forge`. When **off**, Forge still analyzes in the background but only shows a count ("3 pending proposals").

## Step 3 -- Apply the user's choice

Map natural language to the closest option:
- "quiet" / "don't nudge" -> `--nudge-level quiet`
- "balanced" / "default" -> `--nudge-level balanced`
- "eager" / "proactive" -> `--nudge-level eager`
- "show proposals at start" / "proactive on" -> `--proactive-proposals on`
- "don't show proposals at start" / "proactive off" -> `--proactive-proposals off`

Both flags can be combined in one call. Run:

```bash
python3 "<FORGE_ROOT>/scripts/write-settings.py" --nudge-level <level> --proactive-proposals <on|off>
```

Confirm the change with a one-line summary of what the new setting means.

If the user's preference doesn't map cleanly, explain the closest match and ask which they'd prefer.
