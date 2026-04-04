---
name: forge
description: >
  Analyze your Claude Code setup and apply improvements. Audits configuration
  health, detects workflow patterns from session history, and walks you through
  applying suggestions. Use when you want to optimize your Claude Code
  infrastructure, check your setup health, or review pending suggestions.
  Works immediately on first run with no session history needed.
context:
  - references/artifact-templates.md
  - references/anthropic-best-practices.md
---

You are running Forge, the Claude Code infrastructure optimizer. Follow these steps in order.

**Scope constraint:** All analysis is scoped to the current project. Do not read files from other projects under `~/.claude/projects/`. If the user asks you to, tell them what you're accessing.

## Step 0: Resolve plugin root

Resolve the plugin root and read settings:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; if [ -z "$FORGE_ROOT" ]; then echo 'ERROR: Could not locate Forge plugin'; exit 1; fi; echo "FORGE_ROOT=$FORGE_ROOT"; python3 "$FORGE_ROOT/scripts/read-settings.py"
```

Save the `FORGE_ROOT=...` path. If unresolved, tell the user and stop.

## Step 1: Get proposals

```bash
python3 "<FORGE_ROOT>/scripts/cache-manager.py" --proposals --plugin-root "<FORGE_ROOT>"
```

Returns JSON with `proposals`, `context_health`, `conversation_pairs_sample`, and `deep_analysis_cache`.

## Step 1b: Apply quality filter from deep analysis

1. If `deep_analysis_cache` is not null: use its `filtered_proposals` as the proposal set (these are the script proposals that passed the LLM quality gate). Append `additional_proposals` after them. Sort by impact (high first). This replaces the raw script proposals entirely.
2. If `deep_analysis_cache` is null: the LLM quality filter has not run yet for this analysis cycle. Use the raw script `proposals` directly. Note to the user: "Forge's quality filter will run in the background for your next session."

## Step 2: Format and present results

Pipe the proposals JSON through the formatter:

```bash
python3 "<FORGE_ROOT>/scripts/format-proposals.py" <<'FORGE_EOF'
<PROPOSALS_JSON>
FORGE_EOF
```

The output is JSON with `health_table`, `proposal_table`, `proposal_count`, `has_deep_cache`, `proposals`, and `safety_flagged_ids`. Show the `health_table` first, then the `proposal_table`.

If `safety_flagged_ids` is non-empty, note to the user: "Proposals marked [Safety review] should include human approval steps -- previous similar proposals were modified or dismissed for missing safety gates."

If `proposal_count` is 0:
- Say setup looks good and stop.

Use a **single `AskUserQuestion` call** (up to 4 proposals per call) with options:
- **Approve** -- "Generate and place the artifact now"
- **Modify** -- "I'll tell you what to change first"
- **Skip** -- "Keep for next time"
- **Never** -- "Dismiss permanently"

If more than 4 proposals, batch into multiple calls. If `AskUserQuestion` unavailable, ask conversationally.

### Feedback capture

**On Never:** Follow up with a single AskUserQuestion: "What's the main reason?" with options: "Low impact", "Missing safety steps", "Already handled", "Not relevant". Map the choice to the outcome's `reason` field:

| User picks | `reason` value |
|------------|----------------|
| Low impact | `low_impact` |
| Missing safety steps | `missing_safety` |
| Already handled | `already_handled` |
| Not relevant | `not_relevant` |

If the user declines or AskUserQuestion is unavailable, use `"unspecified"`. Example outcome: `{"id": "auto-lint-hook", "status": "dismissed", "type": "hook", "reason": "low_impact"}`.

**On Modify:** After generating the revised artifact, classify the modification based on the user's requested changes (infer from context -- do not ask the user to pick a category):
- User asked for approval steps, confirmation, dry-run, or human-in-the-loop -> `"added_approval_gate"`
- User narrowed scope (fewer files, events, triggers) -> `"narrowed_scope"`
- >50% of content was rewritten -> `"rewrote_content"`
- Otherwise -> `"minor_tweaks"`

Record as `modification_type` in the outcome. Example: `{"id": "auto-lint-hook", "status": "applied", "type": "hook", "modification_type": "added_approval_gate"}`.

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

Generate artifact content following templates. **For safety-flagged proposals** (those in `safety_flagged_ids`): the generated hook or agent MUST include a human approval mechanism -- a confirmation prompt, dry-run flag, or explicit user gate. Do not generate automation that runs silently if the safety gate is active.

Write each type:
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

Where `<JSON>` has `outcomes` and `all_proposals`. Each outcome has `{id, status, type}` plus optional fields: `reason` (for dismissed), `modification_type` (for modified-then-applied). Summarize: how many approved, skipped, dismissed. Remind user to test created artifacts.
