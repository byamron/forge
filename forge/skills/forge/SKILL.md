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
- `deep_analysis_cache`: Cached deep analysis results from background analysis (may be null)

## Step 1b: Deep analysis

Check for cached deep analysis results from background analysis:

1. **Cached results available** (`deep_analysis_cache` is not null): Merge its `proposals` into the script proposals using the merge rules below. **No LLM call needed — the work was already done in the background.**

2. **No cache, deep mode active** (`deep_analysis_cache` is null AND deep mode from flag or settings):
   - Prepare the agent's input by combining the `proposals`, `context_health`, and `conversation_pairs_sample` from Step 1
   - Use the Agent tool with `run_in_background: true` to spawn the `session-analyzer` agent (subagent_type: `session-analyzer`). In the prompt, include the combined input data and ask it to return a JSON array of additional proposals
   - **Continue to Step 2 immediately** — do not wait. The user will review script proposals while deep analysis runs.

3. **No cache, standard mode**: skip this step entirely.

**Deep proposal merge rules** (used whenever deep proposals are available):
- Deep proposals have `"source": "deep_analysis"` — append them after script proposals
- If a deep proposal describes the same pattern as a script proposal (same `id` or clearly overlapping evidence), keep the script proposal and enrich its `evidence_summary` with the deep insight instead of showing a duplicate
- Sort the merged list by impact (high first)

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
| Stale artifacts  | 0     | ✓      |
```

Use ⚠ for any metric with gaps or issues. If `context_health.over_budget` is true, mark CLAUDE.md with ⚠. If `context_health.stale_artifacts_count` > 0, mark Stale artifacts with ⚠. If `context_health.demotion_candidates` > 0, add a row showing the count with ⚠. If `context_health.effectiveness` exists and has `ineffective` > 0, add a row: "Ineffective artifacts | N | ⚠" and note which artifacts are still seeing their triggering patterns (from `effectiveness.ineffective_details`).

### Present script proposals first

**Do not mention filtering, noise removal, or data from other projects.** Only present proposals that are relevant to this project. If the analysis data contains irrelevant entries, silently skip them.

If there are no script proposals:
- If deep analysis is running (Step 1b case 2): show "Analyzing session patterns..." and wait for the deep agent to complete. When it returns, merge and present its proposals below. If the deep agent also returns no proposals, tell the user their setup looks good and stop.
- If no deep analysis is running: tell the user their setup looks good. Stop.

Present script proposals in a **single summary table** with evidence inline:

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

### Append deep proposals when ready (deep mode only)

After the user finishes reviewing script proposals, check if the background deep analysis agent has completed:

- **If completed**: merge its proposals using the merge rules from Step 1b. If there are new proposals (not duplicates of script proposals), present them in a second table and AskUserQuestion batch, prefixed with "Deep analysis found additional patterns:".
- **If still running**: wait for it. The user opted into deep mode — they expect deep results. Show "Finishing deep analysis..." while waiting.
- **If no deep analysis was running** (cached results were already merged in Step 1b, or standard mode): skip this.

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
- **Demotions** (type `demotion`): Two-step operation — create the new file and update the source:
  1. Read `demotion_detail` from the proposal.
  2. If `action` is `claude_md_to_rule`:
     - Write the new rule file to `suggested_path` with `suggested_content` (refine the draft into production-quality rule content with proper paths frontmatter).
     - Read CLAUDE.md and remove the lines listed in `demotion_detail.entries` (match by content, not line number — lines may have shifted).
     - Insert `demotion_detail.pointer` in CLAUDE.md where the first removed entry was.
  3. If `action` is `claude_md_verbose_to_reference`:
     - Write a new reference doc at `suggested_path` with the section content from `suggested_content` (refine into a well-structured reference doc with headings).
     - Read CLAUDE.md and find the `## <heading>` line matching `demotion_detail.heading` (exact match). Use `demotion_detail.line_start` as a hint if multiple headings match — pick the one nearest that line number. If the heading is not found (already moved or renamed), skip this proposal and tell the user.
     - Replace the section's body (keep the `## heading` line) with a one-line pointer: `demotion_detail.pointer`.
  4. If `action` is `rule_to_reference`:
     - Read the source rule file at `demotion_detail.source_file`.
     - Extract verbose sections (detailed examples, long explanations) to a new reference doc at `suggested_path`.
     - Replace the extracted sections in the rule with `demotion_detail.pointer`.
     - Keep the rule's frontmatter and core directives intact — only move the detail.
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
