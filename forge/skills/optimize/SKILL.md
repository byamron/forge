---
name: optimize
description: >
  Review and apply pending Forge proposals. Walks through each suggestion
  from a previous /forge:analyze run, showing what would be generated and
  where it would go. You approve, modify, or skip each one. Use after
  running /forge:analyze, or when Forge mentions pending suggestions.
---

You are running the Forge optimization flow. Follow these steps exactly:

## Step 1: Load proposals

Read `.claude/forge/proposals/pending.json`.

If the file doesn't exist or contains no proposals with `"status": "pending"`, tell the user:
> No pending proposals found. Run `/forge:analyze` first to scan your sessions and configuration.

Then stop.

Also read `.claude/forge/dismissed.json` if it exists — you'll need this to skip dismissed patterns.

## Step 2: Sort proposals

Sort pending proposals by:
1. Confidence: `high` before `medium`
2. Type priority: `claude_md_entry` and `rule` first (most impactful, simplest), then `hook`, then `skill` and `agent` (drafts that need iteration)

## Step 3: Present proposals one at a time

For each proposal with `"status": "pending"`:

### 3a. Show the evidence
State what was observed. Include specific evidence:
- For corrections: quote the user's actual messages and cite dates/sessions
- For config gaps: state what was detected (e.g., "Prettier is configured but no auto-format hook exists")
- For memory notes: quote the memory entry

### 3b. Show the preview
Display the exact artifact content that would be generated. Show it in a code block with the appropriate language. State:
- The artifact type (CLAUDE.md entry, rule, hook, skill, agent, reference doc)
- The file path where it would be placed
- Which context tier it belongs to (Tier 1: always loaded, Tier 2: contextual, Tier 3: on-demand)

### 3c. Add caveats for drafts
For skills and agents, note: "This is a draft — test it with a few prompts and refine as needed."

### 3d. Ask for a decision
Ask the user to choose one of:
- **approve** — Generate and place the artifact now
- **modify** — Tell me what to change, then generate
- **skip** — Keep for later (will appear next time)
- **never** — Dismiss permanently (won't be proposed again)

Wait for the user's response before proceeding.

## Step 4: Handle each decision

### If approved:
1. Spawn the `artifact-generator` agent. Pass it the proposal's `type`, `description`, `suggested_content`, and `suggested_path`. The agent will produce the final artifact content following Anthropic's specifications.
2. Write the generated artifact to the specified path:
   - For CLAUDE.md entries: append to `.claude/CLAUDE.md` (create if needed). Check total line count after — warn if over 100 lines
   - For rules: write to `.claude/rules/<name>.md` (create directory if needed)
   - For hooks: merge into `.claude/settings.json` (create if needed, preserve existing hooks)
   - For skills: create `.claude/skills/<name>/SKILL.md` (create directory structure)
   - For agents: write to `.claude/agents/<name>.md` (create directory if needed)
   - For reference docs: write to `.claude/references/<name>.md` (create directory if needed). Add a pointer line to CLAUDE.md
3. Update the proposal's status to `"applied"` in pending.json
4. Record in `.claude/forge/history/applied.json` (create if needed):
   ```json
   {
     "id": "proposal-id",
     "type": "artifact type",
     "path": "where it was placed",
     "applied_at": "ISO8601 timestamp",
     "content_preview": "first 100 chars of content",
     "evidence_summary": "brief summary of why"
   }
   ```

### If modified:
1. Ask what the user wants to change
2. Adjust the proposed content accordingly
3. Show the updated preview
4. Ask for approval of the modified version
5. If approved, follow the "approved" steps above

### If skipped:
Leave the proposal's status as `"pending"` — it will appear again next time.

### If never:
1. Update the proposal's status to `"dismissed"` in pending.json
2. Append the proposal to `.claude/forge/dismissed.json` (create if needed) with a timestamp
3. This pattern will not be proposed again unless the user resets via `/forge:status`

## Step 5: Summary

After processing all proposals, give a brief summary:
- How many were approved and applied
- How many were skipped
- How many were dismissed
- Remind the user they can run `/forge:status` to see the updated configuration health
