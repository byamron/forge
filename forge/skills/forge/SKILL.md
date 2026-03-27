---
name: forge
description: >
  Analyze your Claude Code setup and apply improvements. Audits configuration
  health, detects workflow patterns from session history, and walks you through
  applying suggestions. Use when you want to optimize your Claude Code
  infrastructure, check your setup health, or review pending suggestions.
  Works immediately on first run with no session history needed.
---

You are running Forge, the Claude Code infrastructure optimizer. Follow these steps in order.

## Step 1: Get proposals

Run a single command that resolves the plugin, runs any stale analysis, and returns ready-to-present proposals:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; if [ -z "$FORGE_ROOT" ]; then echo 'ERROR: Could not locate Forge plugin'; exit 1; fi; python3 "$FORGE_ROOT/scripts/cache-manager.py" --proposals --plugin-root "$FORGE_ROOT"
```

If the output starts with `ERROR`, tell the user the Forge plugin scripts could not be located and stop.

The output is a JSON object with:
- `proposals`: Array of proposals, each with `id`, `type`, `impact`, `description`, `evidence_summary`, `suggested_content`, `suggested_path`, `status`
- `context_health`: Summary of context budget and artifact counts
- `stats`: How many sessions were analyzed, candidates found, etc.

## Step 2: Present proposals

If there are no proposals, show the context health one-liner and tell the user their setup looks good. Stop.

Present the proposals in a **single summary table** with evidence inline:

```
| # | Impact | Type | Proposal | Evidence |
|---|--------|------|----------|----------|
| 1 | High   | hook | Auto-lint on Edit/Write | ESLint configured, no PostToolUse hook |
| 2 | High   | skill | "start dev server" workflow | 9 occurrences across 9 sessions |
```

Then immediately use a **single `AskUserQuestion` call** with one question per proposal (up to 4 per call). Each question should include:
- A one-line summary with impact level and evidence

Options per question:
- **Approve** (description: "Generate and place the artifact now")
- **Modify** (description: "I'll tell you what to change first")
- **Skip** (description: "Keep for next time")
- **Never** (description: "Dismiss permanently — don't suggest this again")

If there are more than 4 proposals, batch them into multiple AskUserQuestion calls of up to 4 each.

If `AskUserQuestion` is not available, fall back to presenting the options conversationally and waiting for the user's response.

After receiving decisions, show the draft artifact content (in a code block with file path) **only for proposals the user approved or wants to modify**. Do not show drafts for skipped or dismissed proposals.

**Always wait for explicit user approval before writing any files.** Never auto-apply proposals.

## Step 3: Apply approved proposals

For each approved proposal:

0. **Validate the artifact path before writing.** The `suggested_path` must satisfy ALL of these:
   - It is a relative path (does not start with `/` or `~`)
   - It resolves to a location within the project root (no `..` traversal that escapes)
   - It targets only allowed locations: `CLAUDE.md`, `.claude/rules/`, `.claude/skills/`, `.claude/agents/`, `.claude/references/`, `.claude/commands/` (for legacy migration reads), `.claude/settings.json`, or `.claude/forge/`
   - If any path fails validation, **skip the proposal**, warn the user, and mark it as skipped

1. Spawn the `artifact-generator` agent with the proposal details (type, description, suggested_content, suggested_path). The agent produces the final artifact content.
2. Write the artifact to the specified path:
   - **CLAUDE.md entries**: Append to `CLAUDE.md` (create if needed). Warn if over 100 lines after.
   - **Rules**: Write to `.claude/rules/<name>.md` (create directory if needed)
   - **Hooks**: Read existing `.claude/settings.json`, merge the new hook into the appropriate event array (e.g., add a new PostToolUse entry alongside existing ones). Create the file if it doesn't exist. Preserve all existing hooks — never overwrite.
   - **Skills**: Create `.claude/skills/<name>/SKILL.md` (create directory structure)
   - **Skill updates**: Edit the existing file at `suggested_path`. Show a diff of what changed. If the existing artifact is a legacy command (`.claude/commands/*.md`), migrate it to `.claude/skills/<name>/SKILL.md` and delete the old file.
   - **Agents**: Write to `.claude/agents/<name>.md`
   - **Reference docs**: Write to `.claude/references/<name>.md`. Add a pointer line to CLAUDE.md: `For detailed X conventions, see .claude/references/Y.md`
   - All artifacts go to project-level (`.claude/`), never user-level (`~/.claude/`).
3. Update the proposal's status to `"applied"` in pending.json
4. Record in `.claude/forge/history/applied.json`
5. Update feedback stats:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update-analyzer-stats.py" --category <category> --outcome approved --theme-hash <proposal-id>
   ```

For **modified** proposals: ask what the user wants to change, adjust the content, show the updated preview, then ask for approval again.

For **skipped** proposals: leave status as `"pending"`.

For **never** proposals:
1. Update status to `"dismissed"` in pending.json
2. Append to `.claude/forge/dismissed.json` with a timestamp
3. Update feedback stats:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update-analyzer-stats.py" --category <category> --outcome suppressed --theme-hash <proposal-id>
   ```

## Step 4: Save and summarize

Only save proposals if there were any (skip the file write if there were no proposals to record).

Before writing, tell the user: "Saving proposal records — this lets Forge remember what you've reviewed so it won't re-suggest dismissed items or lose skipped proposals between sessions."

Write the full proposal list (with updated statuses) to `.claude/forge/proposals/pending.json`:
```bash
mkdir -p .claude/forge/proposals
```

Write the JSON array of all proposals. Applied proposals have `"status": "applied"`, dismissed have `"status": "dismissed"`, skipped keep `"status": "pending"`. This way, the next `/forge` run knows what's been handled.

Give a brief summary:
- How many proposals were approved and applied
- How many were skipped (will appear next time)
- How many were dismissed
- If artifacts were created, remind the user to test them

### Context health

After the summary, show the `context_health.summary` from the Step 1 output. Only show if it contains useful information (budget warnings, placement notes). If everything is clean, skip this.
