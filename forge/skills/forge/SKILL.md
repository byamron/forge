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

**Scope constraint:** All analysis is scoped to the current project by default. Do not proactively read, list, or access files from other projects — including other directories under `~/.claude/projects/`. Cross-project data must never unintentionally influence proposals. If the user explicitly asks you to reference another project, you may do so, but tell them what you're accessing.

## Step 0: Determine analysis mode

Check the user's invocation text for flags:
- `/forge --deep` → use **deep** mode (one-time override)
- `/forge --quick` → use **standard** mode (one-time override)
- `/forge` (no flags) → read from settings (next step)

If no flag was provided, resolve the plugin root and read the default:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; if [ -z "$FORGE_ROOT" ]; then echo 'ERROR: Could not locate Forge plugin'; exit 1; fi; echo "FORGE_ROOT=$FORGE_ROOT"; python3 "$FORGE_ROOT/scripts/read-settings.py"
```

Check the `analysis_depth` field in the JSON output. Default is `"standard"`.

**Save the `FORGE_ROOT=...` path** — you will need it throughout.

If FORGE_ROOT could not be resolved, tell the user the Forge plugin scripts could not be located and stop.

## Step 1: Get proposals

Run the analysis pipeline (uses cache, typically instant):

```bash
python3 "<FORGE_ROOT>/scripts/cache-manager.py" --proposals --plugin-root "<FORGE_ROOT>"
```

Replace `<FORGE_ROOT>` with the actual path from Step 0.

The output is a JSON object with:
- `proposals`: Array of proposals from script analysis
- `context_health`: Summary of context budget and artifact counts
- `stats`: How many sessions were analyzed, candidates found, etc.
- `conversation_pairs_sample`: Recent conversation pairs (used by deep mode)

## Step 1b: Start deep analysis (deep mode only)

**Skip this step if the analysis mode is standard.**

If deep mode is active, spawn the `session-analyzer` agent in the background to find contextual patterns:

1. Prepare the agent's input by combining:
   - The `proposals` array from Step 1 (so the agent knows what scripts already found)
   - The `context_health` from Step 1
   - The `conversation_pairs_sample` from Step 1

2. Use the Agent tool with `run_in_background: true` to spawn the `session-analyzer` agent (subagent_type: `session-analyzer`). In the prompt, include:
   - The combined input data above
   - Ask it to return a JSON array of additional proposals

3. Continue to Step 2 immediately — do not wait for the agent.

## Step 2: Present results

### Context health (show immediately)

Using the `context_health` from Step 1, show a brief health table:

```
| Metric           | Value | Status |
|------------------|-------|--------|
| CLAUDE.md lines  | 163   | ✓      |
| Rules            | 3     | ✓      |
| Skills/Commands  | 2     | ✓      |
| Hooks            | 0     | ⚠      |
| Agents           | 0     | ✓      |
```

Use ⚠ for any metric with gaps or issues. If `context_health.over_budget` is true, mark CLAUDE.md with ⚠.

### Deep mode: wait for background analysis

If deep mode is active and the background agent has not yet returned:

Show this message:

> Deep analysis running in the background — keep working, I'll surface results when ready.
> Prefer instant results? Run `/forge:settings` to switch to standard mode.

Wait for the background agent to complete. When it returns, merge its proposals with the script proposals from Step 1:
- Deep proposals have `"source": "deep_analysis"` — append them after script proposals
- If a deep proposal describes the same pattern as a script proposal (same `id` or clearly overlapping evidence), keep the script proposal and enrich its `evidence_summary` with the deep insight instead of showing a duplicate
- Sort the merged list by impact (high first)

### Present proposals

If there are no proposals (from scripts, or from scripts + deep analysis combined), tell the user their setup looks good. Stop.

**Do not mention filtering, noise removal, or data from other projects.** Only present proposals that are relevant to this project. If the analysis data contains irrelevant entries, silently skip them.

Present the proposals in a **single summary table** with evidence inline:

```
| # | Impact | Type | Proposal | Evidence |
|---|--------|------|----------|----------|
| 1 | High   | hook | Auto-lint on Edit/Write | ESLint configured, no PostToolUse hook |
| 2 | High   | skill | "start dev server" workflow | 9 occurrences across 9 sessions |
```

Then immediately use a **single `AskUserQuestion` call** with one question per proposal (up to 4 per call). Each question should include:
- A one-line summary with impact level, the specific reason for the recommendation, and evidence
- For best-practice recommendations, cite the guideline (e.g., "Anthropic recommends CLAUDE.md stay under 200 lines — yours is 310")
- For pattern-based recommendations, state the pattern (e.g., "You ran this 9 times across 9 sessions")

Options per question:
- **Approve** (description: "Generate and place the artifact now")
- **Modify** (description: "I'll tell you what to change first")
- **Skip** (description: "Keep for next time")
- **Never** (description: "Dismiss permanently — don't suggest this again")

If there are more than 4 proposals, batch them into multiple AskUserQuestion calls of up to 4 each.

If `AskUserQuestion` is not available, fall back to presenting the options conversationally and waiting for the user's response.

After receiving decisions, show the draft artifact content (in a code block with file path) **only for proposals the user approved or wants to modify**. Do not show drafts for skipped or dismissed proposals.

**Always wait for explicit user approval before writing any files.** Never auto-apply proposals.

## Step 3: Generate and apply approved proposals

Artifact templates and Anthropic best practices are already in your context. Use them to generate artifacts.

For all approved proposals:

### 3a. Validate paths

For each approved proposal, validate `suggested_path`:
- Must be a relative path (no `/` or `~` prefix)
- Must resolve within the project root (no `..` escape)
- Must target allowed locations: `CLAUDE.md`, `.claude/rules/`, `.claude/skills/`, `.claude/agents/`, `.claude/references/`, `.claude/settings.json`, or `.claude/forge/`
- Skip any proposal that fails validation and warn the user

### 3b. Create directories in one batch

Run a single `mkdir -p` for all needed directories:
```bash
mkdir -p .claude/rules .claude/skills/<name1> .claude/skills/<name2> ...
```

### 3c. Generate and write artifacts

Generate the artifact content yourself following the templates from the reference files. Write each artifact:
- **CLAUDE.md entries**: Append to `CLAUDE.md` (create if needed). Warn if over 200 lines after.
- **Rules**: Write to `.claude/rules/<name>.md`
- **Hooks**: Read existing `.claude/settings.json`, merge the new hook into the appropriate event array. Preserve all existing hooks — never overwrite.
- **Skills**: Write to `.claude/skills/<name>/SKILL.md`
- **Skill updates**: Edit the existing file at `suggested_path`. If legacy command (`.claude/commands/*.md`), migrate to `.claude/skills/<name>/SKILL.md` and delete the old file.
- **Agents**: Write to `.claude/agents/<name>.md`
- **Reference docs**: Write to `.claude/references/<name>.md`. Add a pointer to CLAUDE.md.
- All artifacts go to project-level (`.claude/`), never user-level (`~/.claude/`).

For **modified** proposals: ask what the user wants to change, adjust the content, show the updated preview, then ask for approval again.

## Step 4: Finalize and summarize

After all artifacts are written, run a **single command** to handle all bookkeeping (pending.json, applied.json, dismissed.json, analyzer stats):

```bash
python3 "<FORGE_ROOT>/scripts/finalize-proposals.py" --project-root "$(pwd)" <<'FORGE_EOF'
<JSON>
FORGE_EOF
```

Replace `<FORGE_ROOT>` with the actual path from Step 0.

Where `<JSON>` is a JSON object with:
- `outcomes`: Array of `{"id": "<proposal-id>", "status": "applied|dismissed|pending", "type": "<proposal-type>"}` for every proposal
- `all_proposals`: The full proposals array with updated statuses

Give a brief summary:
- How many proposals were approved and applied
- How many were skipped (will appear next time)
- How many were dismissed
- If artifacts were created, remind the user to test them
