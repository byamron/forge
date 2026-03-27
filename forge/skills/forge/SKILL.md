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

## Step 0: Resolve plugin root

Run this to determine the plugin's install directory:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; echo "$FORGE_ROOT"
```

If this returns a path, store it — use it in place of `${CLAUDE_PLUGIN_ROOT}` for all script calls in subsequent steps. If it returns nothing, tell the user the Forge plugin scripts could not be located and stop.

## Step 1: Check for pending proposals

Read `.claude/forge/proposals/pending.json` if it exists. Count proposals with `"status": "pending"`. Also read `.claude/forge/dismissed.json` if it exists — you'll need this to filter out dismissed patterns later.

If there are pending proposals, tell the user:
> Found N pending proposal(s) from a previous analysis. I'll present those after running a fresh check.

## Step 2: Run Phase A analysis scripts

First, check if cached results are available:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cache-manager.py" --check --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

Parse the output. Each script (`config`, `transcripts`, `memory`) will be either `"fresh"` (with cached `result`) or `"stale"`.

- For **fresh** scripts: use the cached `result` directly — no need to re-run.
- For **stale** scripts: run only those in a single bash command:

```bash
echo '===CONFIG===' && python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyze-config.py" 2>&1; echo '===TRANSCRIPTS===' && python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyze-transcripts.py" 2>&1; echo '===MEMORY===' && python3 "${CLAUDE_PLUGIN_ROOT}/scripts/analyze-memory.py" 2>&1
```

Only include scripts that are stale in the command above — skip fresh ones. If all three are fresh, skip this bash command entirely.

If any script fails, use the others. The config audit provides value even without transcripts.

## Step 3: Present status summary

Using the config audit results, present a **formatted health overview** as a table:

```
| Metric           | Value | Status |
|------------------|-------|--------|
| CLAUDE.md lines  | 43    | ✓      |
| Rules            | 3     | ✓      |
| Skills/Commands  | 2     | ✓      |
| Hooks            | 0     | ⚠ gaps |
| Agents           | 0     | ✓      |
```

Below the table, list only actionable items:
- **Gaps**: Missing formatter/linter hooks, unreferenced docs.
- **Placement issues**: Domain-specific entries in CLAUDE.md, rules without path scoping, verbose entries that should be reference docs.

Keep this concise. If everything is healthy, say so in one sentence.

## Step 4: Present pattern findings

Using the transcript and memory analysis results, show findings in a compact format:

- **Repeated prompts**: Show the top patterns with occurrence counts and example messages. These are skill candidates.
- **Corrections**: If any were detected, show the pattern and evidence.
- **Post-action patterns**: If any were detected, show the command and context.
- **Memory promotions**: Notes that should be upgraded to proper artifacts.

If no transcript patterns were found, say so briefly. Do not present empty categories.

## Step 5: Build the proposal list

Merge findings into proposals. Each proposal needs:
- `id`: Descriptive slug (e.g., `start-dev-server-skill`, `auto-format-hook`)
- `type`: One of `claude_md_entry`, `rule`, `skill`, `skill_update`, `hook`, `agent`, `reference_doc`
- `confidence`: `high` or `medium`
- `impact`: Rate as `high`, `medium`, or `low` based on how much this would improve the user's workflow:
  - **high**: Saves significant manual effort (e.g., automating a multi-step workflow repeated 10+ times) or fixes a real config problem
  - **medium**: Meaningful improvement (e.g., auto-linting, promoting repeated corrections to rules)
  - **low**: Minor cleanup or cosmetic (e.g., removing stale entries, reordering config)
- `description`: What this proposal does
- `suggested_content`: Draft content for the artifact
- `suggested_path`: Where the artifact would be placed
- `evidence`: Array of evidence items
- `status`: `"pending"`

**Drop low-impact proposals.** Only present high and medium impact proposals. If a proposal is purely cosmetic or nitpicky, skip it.

Apply minimum evidence thresholds:

| Artifact Type | Min Occurrences | Min Sessions |
|---|---|---|
| CLAUDE.md entry | 3 corrections | 2 sessions |
| Rule | 3 corrections | 2 sessions |
| Skill | 4 similar prompts | 3 sessions |
| Hook | 5 manual repetitions | 3 sessions |

**Exceptions:** Config gap suggestions (missing hooks for detected linter/formatter) are included regardless of session evidence, but only at medium or high impact.

**Cross-reference with existing artifacts:** The config audit returns three inventory lists:
- `existing_skills`: Skills (`.claude/skills/*/SKILL.md`) and legacy commands (`.claude/commands/*.md`), each with name, description, full content, path, and format (`"skill"` or `"legacy_command"`).
- `existing_agents`: Agents (`.claude/agents/*.md`), each with name, description, full content, and path.
- `existing_hooks`: Hooks from `.claude/settings.json`, each with event, matcher, type, command, and source path.

Before proposing any new artifact, check the relevant inventory:
- **Skills**: Read the full content of existing skills/commands. If one already handles the pattern, do not propose a duplicate. If it could be improved, propose a `skill_update` instead. If a legacy command covers the pattern, consider proposing migration to the modern skills format.
- **Agents**: If a proposed agent overlaps with an existing agent's responsibilities, suppress or propose a modification.
- **Hooks**: If a proposed hook duplicates an existing hook (same event + similar matcher/command), suppress it. If the existing hook could be extended (e.g., adding a file type to the matcher), propose a modification.

Combine these new proposals with any pending proposals from Step 1. Deduplicate by comparing descriptions and evidence — don't propose the same thing twice.

Filter out any proposals whose pattern matches a dismissed entry in `dismissed.json`.

## Step 6: Review proposals with the user

If there are no proposals, tell the user their setup looks good and stop.

Present all proposals together using a **single `AskUserQuestion` call** with one question per proposal (up to 4 proposals per call). For each proposal, the question should include:

- A one-line summary with impact level (e.g., "**[High]** Add auto-lint hook — ESLint configured but no PostToolUse hook exists")
- The artifact type and target path

Each question should have these options:
- **Approve** (description: "Generate and place the artifact now")
- **Modify** (description: "I'll tell you what to change first")
- **Skip** (description: "Keep for next time")
- **Never** (description: "Dismiss permanently — don't suggest this again")

If there are more than 4 proposals, batch them into multiple AskUserQuestion calls of up to 4 each.

Before asking, show a summary table of all proposals:

```
| # | Impact | Type | Proposal |
|---|--------|------|----------|
| 1 | High   | hook | Add auto-lint hook for ESLint |
| 2 | Medium | rule | Extract framework details from CLAUDE.md |
```

Then show the preview (artifact content in a code block) for each proposal, so the user can see what they're approving.

If `AskUserQuestion` is not available, fall back to presenting the options conversationally and waiting for the user's response.

**Always wait for explicit user approval before writing any files.** Never auto-apply proposals.

## Step 7: Apply approved proposals

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

## Step 8: Save and summarize

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
