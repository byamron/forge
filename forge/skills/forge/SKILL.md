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

## Step 1: Check for pending proposals

Read `.claude/forge/proposals/pending.json` if it exists. Count proposals with `"status": "pending"`. Also read `.claude/forge/dismissed.json` if it exists — you'll need this to filter out dismissed patterns later.

If there are pending proposals, tell the user:
> Found N pending proposal(s) from a previous analysis. I'll present those after running a fresh check.

## Step 2: Run Phase A analysis scripts

Run all three scripts and capture their JSON output:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/analyze-config.py"
```

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/analyze-transcripts.py"
```

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/analyze-memory.py"
```

If any script fails, report the error but continue with the others. The config audit provides value even without transcripts.

## Step 3: Present status summary

Using the config audit results, present a brief health overview:

- **Context budget**: CLAUDE.md line count, number of rules/skills/agents/hooks. Warn if tier 1 content exceeds 150 lines.
- **Gaps**: Missing formatter/linter hooks, unreferenced docs. Only mention gaps that exist — don't list things that are fine.
- **Placement issues**: Domain-specific entries in CLAUDE.md, rules without path scoping, verbose entries that should be reference docs. Only mention if found.

Keep this section concise — a few lines, not a wall of text. If everything looks healthy, say so in one sentence and move on.

## Step 4: Present pattern findings

Using the transcript and memory analysis results:

- **Repeated prompts**: Show the top patterns with occurrence counts and example messages. These are skill candidates.
- **Corrections**: If any were detected, show the pattern and evidence.
- **Post-action patterns**: If any were detected, show the command and context.
- **Memory promotions**: Notes that should be upgraded to proper artifacts.

If no transcript patterns were found (no session history, or patterns below threshold), say so briefly and move on. Do not present empty categories.

## Step 5: Build the proposal list

Merge findings into proposals. Each proposal needs:
- `id`: Descriptive slug (e.g., `start-dev-server-skill`, `auto-format-hook`)
- `type`: One of `claude_md_entry`, `rule`, `skill`, `hook`, `agent`, `reference_doc`
- `confidence`: `high` or `medium`
- `description`: What this proposal does
- `suggested_content`: Draft content for the artifact
- `suggested_path`: Where the artifact would be placed
- `evidence`: Array of evidence items
- `status`: `"pending"`

Apply minimum evidence thresholds:

| Artifact Type | Min Occurrences | Min Sessions |
|---|---|---|
| CLAUDE.md entry | 3 corrections | 2 sessions |
| Rule | 3 corrections | 2 sessions |
| Skill | 4 similar prompts | 3 sessions |
| Hook | 5 manual repetitions | 3 sessions |

**Exceptions:** Config gap suggestions and memory promotions are included regardless of session evidence.

**Cross-reference with existing artifacts:** The config audit returns an `existing_skills` list with each skill's name, description, full content, and path. Before proposing a new skill, read the full content of existing skills and check whether one already handles the detected pattern. If it does:
- Do **not** propose a new skill for the same pattern.
- If the existing skill could be improved based on the evidence (e.g., the user's actual phrasing reveals steps the skill misses, or the skill could handle additional variants), propose a **modification** to the existing skill instead, with `type: "skill_update"` and `suggested_path` pointing to the existing skill's path.

Combine these new proposals with any pending proposals from Step 1. Deduplicate by comparing descriptions and evidence — don't propose the same thing twice.

Filter out any proposals whose pattern matches a dismissed entry in `dismissed.json`.

## Step 6: Review proposals with the user

If there are no proposals, tell the user their setup looks good and stop.

If there are proposals, present them **one at a time**, highest confidence first. For each proposal:

### 6a. Show the evidence
State what was observed. Include specifics:
- For repeated prompts: quote the user's actual messages and how many sessions
- For config gaps: state what was detected (e.g., "Prettier is configured but no auto-format hook exists")
- For memory notes: quote the entry
- For corrections: quote the user's messages with dates

### 6b. Show the preview
Display the exact artifact content that would be generated in a code block. State:
- The artifact type
- The file path where it would be placed
- For skills/agents: note "This is a draft — test and refine"

### 6c. Ask for a decision

Use the `AskUserQuestion` tool to present a structured choice. The question should summarize the proposal (e.g., "Create a '/dev-server' skill from 11 repeated prompts?") with these options:

- **Approve** (description: "Generate and place the artifact now")
- **Modify** (description: "I'll tell you what to change first")
- **Skip** (description: "Keep for next time")
- **Never** (description: "Dismiss permanently — don't suggest this again")

If `AskUserQuestion` is not available, fall back to presenting the options conversationally and waiting for the user's response.

**Always wait for explicit user approval before writing any files.** Never auto-apply proposals.

## Step 7: Apply approved proposals

For each approved proposal:

1. Spawn the `artifact-generator` agent with the proposal details (type, description, suggested_content, suggested_path). The agent produces the final artifact content.
2. Write the artifact to the specified path:
   - **CLAUDE.md entries**: Append to `CLAUDE.md` (create if needed). Warn if over 100 lines after.
   - **Rules**: Write to `.claude/rules/<name>.md` (create directory if needed)
   - **Hooks**: Read existing `.claude/settings.json`, merge the new hook into the appropriate event array (e.g., add a new PostToolUse entry alongside existing ones). Create the file if it doesn't exist. Preserve all existing hooks — never overwrite.
   - **Skills**: Create `.claude/skills/<name>/SKILL.md` (create directory structure)
   - **Agents**: Write to `.claude/agents/<name>.md`
   - **Reference docs**: Write to `.claude/references/<name>.md`. Add a pointer line to CLAUDE.md: `For detailed X conventions, see .claude/references/Y.md`
   - All artifacts go to project-level (`.claude/`), never user-level (`~/.claude/`).
3. Update the proposal's status to `"applied"` in pending.json
4. Record in `.claude/forge/history/applied.json`
5. Update feedback stats:
   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/update-analyzer-stats.py" --category <category> --outcome approved --theme-hash <proposal-id>
   ```

For **modified** proposals: ask what the user wants to change, adjust the content, show the updated preview, then ask for approval again.

For **skipped** proposals: leave status as `"pending"`.

For **never** proposals:
1. Update status to `"dismissed"` in pending.json
2. Append to `.claude/forge/dismissed.json` with a timestamp
3. Update feedback stats:
   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/update-analyzer-stats.py" --category <category> --outcome suppressed --theme-hash <proposal-id>
   ```

## Step 8: Save and summarize

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
