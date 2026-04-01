---
name: forge
description: >
  Analyze your Claude Code setup and apply improvements. Audits configuration
  health, detects workflow patterns from session history, and walks you through
  applying suggestions. Use when you want to optimize your Claude Code
  infrastructure, check your setup health, or review pending suggestions.
  Works immediately on first run with no session history needed.
  Supports --deep for LLM-enhanced analysis and --quick for script-only mode.
context:
  - references/artifact-templates.md
  - references/anthropic-best-practices.md
---

You are running Forge, the Claude Code infrastructure optimizer. Follow these steps in order.

**Scope constraint:** All analysis is scoped to the current project. Do not read files from other projects under `~/.claude/projects/`. If the user asks you to, tell them what you're accessing.

## Step 0: Determine analysis mode

Check the user's invocation text for flags:
- `/forge --deep` → **deep** mode
- `/forge --quick` → **standard** mode
- `/forge` (no flags) → read from settings

Resolve the plugin root and read settings:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; if [ -z "$FORGE_ROOT" ]; then echo 'ERROR: Could not locate Forge plugin'; exit 1; fi; echo "FORGE_ROOT=$FORGE_ROOT"; python3 "$FORGE_ROOT/scripts/read-settings.py"
```

Save the `FORGE_ROOT=...` path. If unresolved, tell the user and stop. Check `analysis_depth` in output (default: `"standard"`).

## Step 1: Get proposals

```bash
python3 "<FORGE_ROOT>/scripts/cache-manager.py" --proposals --plugin-root "<FORGE_ROOT>"
```

Returns JSON with `proposals`, `context_health`, `conversation_pairs_sample`, and `deep_analysis_cache`.

## Step 1b: Deep analysis

1. If `deep_analysis_cache` is not null: merge its `proposals` into script proposals (see merge rules below). No LLM call needed.
2. If null AND deep mode active: spawn the `session-analyzer` agent in background (`run_in_background: true`, subagent_type: `session-analyzer`) with the proposals + context_health + conversation_pairs_sample. Continue immediately.
3. If null AND standard mode: skip.

**Merge rules:** Deep proposals (`"source": "deep_analysis"`) append after script proposals. Deduplicate by `id` or overlapping evidence — enrich the script proposal instead. Sort by impact (high first).

## Step 2: Format and present results

Pipe the proposals JSON through the formatter:

```bash
python3 "<FORGE_ROOT>/scripts/format-proposals.py" <<'FORGE_EOF'
<PROPOSALS_JSON>
FORGE_EOF
```

The output is JSON with `health_table`, `proposal_table`, `proposal_count`, `has_deep_cache`, and `proposals`. Show the `health_table` first, then the `proposal_table`.

If `proposal_count` is 0:
- If deep analysis is running: show "Analyzing session patterns..." and wait. Present deep proposals when ready. If none, say setup looks good and stop.
- Otherwise: say setup looks good and stop.

Use a **single `AskUserQuestion` call** (up to 4 proposals per call) with options:
- **Approve** — "Generate and place the artifact now"
- **Modify** — "I'll tell you what to change first"
- **Skip** — "Keep for next time"
- **Never** — "Dismiss permanently"

If more than 4 proposals, batch into multiple calls. If `AskUserQuestion` unavailable, ask conversationally.

### Deep proposals (deep mode only)

After script proposal review, check if the background agent completed:
- **Done**: merge and present new proposals in a second batch.
- **Still running**: wait ("Finishing deep analysis..."). The user opted into deep mode.
- **Not running**: skip.

Show draft artifact content only for approved/modified proposals. **Wait for explicit approval before writing files.**

## Step 3: Generate and apply approved proposals

Artifact templates and best practices are in your context.

### 3a. Validate paths

```bash
python3 "<FORGE_ROOT>/scripts/validate-paths.py" <<'FORGE_EOF'
<ARRAY_OF_PROPOSALS_WITH_ID_AND_SUGGESTED_PATH>
FORGE_EOF
```

Skip any proposal where `valid` is false and warn the user.

### 3b. Create directories and write artifacts

Run `mkdir -p` for all needed directories in one batch.

Generate artifact content following templates. Write each type:
- **CLAUDE.md entries**: Append. Warn if over 200 lines after.
- **Rules**: Write to `.claude/rules/<name>.md`
- **Hooks**: Use the merge script:
  ```bash
  python3 "<FORGE_ROOT>/scripts/merge-settings.py" --settings-path .claude/settings.json <<'FORGE_EOF'
  {"event": "PostToolUse", "matcher": "Write|Edit", "command": "...", "timeout": 10}
  FORGE_EOF
  ```
- **Skills**: Write to `.claude/skills/<name>/SKILL.md`
- **Skill updates**: Edit existing file. Migrate legacy `.claude/commands/*.md` to skills format.
- **Agents**: Write to `.claude/agents/<name>.md`
- **Reference docs**: Write to `.claude/references/<name>.md`, add pointer to CLAUDE.md.
- **Demotions**: Read `demotion_detail` from proposal. Create the target file, then update the source (CLAUDE.md or rule) by removing/replacing the demoted content with a one-line pointer.
- All artifacts go to `.claude/` (project-level), never `~/.claude/`.

For **modified** proposals: ask what to change, adjust, preview, then ask for approval again.

## Step 4: Finalize

```bash
python3 "<FORGE_ROOT>/scripts/finalize-proposals.py" --project-root "$(pwd)" <<'FORGE_EOF'
<JSON>
FORGE_EOF
```

Where `<JSON>` has `outcomes` (array of `{id, status, type}`) and `all_proposals`. Summarize: how many approved, skipped, dismissed. Remind user to test created artifacts.
