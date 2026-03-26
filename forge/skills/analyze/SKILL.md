---
name: analyze
description: >
  Analyze your recent Claude Code sessions, configuration, and auto-memory
  to find opportunities for better infrastructure. Detects repeated corrections,
  workflow patterns, capability gaps, and misplaced configuration. Use when
  you want Forge to review your setup and suggest improvements. Run
  /forge:status first for a quick config health check without transcript analysis.
---

You are running the Forge analysis pipeline. Follow these steps exactly:

## Step 1: Run Phase A analysis scripts

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

## Step 2: Merge and filter candidates

Combine results into a unified candidate list. Apply these minimum evidence thresholds:

| Artifact Type | Min Occurrences | Min Sessions | Notes |
|---|---|---|---|
| CLAUDE.md entry | 3 corrections | 2 sessions | Same or very similar phrasing |
| Rule | 3 corrections | 2 sessions | Clustered around same file types/paths |
| Skill | 4 similar sequences | 3 sessions | 3+ distinct steps |
| Hook | 5 manual repetitions | 3 sessions | Same command each time |

**Exceptions:** Config gap suggestions (missing hooks, placement issues) are included regardless of session evidence. Memory audit promotable notes are also included.

## Step 3: Confirm with Phase B (if candidates exist)

If there are transcript-based candidates that meet the thresholds above, spawn the `session-analyzer` agent with the evidence. Pass only the relevant evidence excerpts, not full transcripts.

The agent will:
- Confirm whether each pattern is real and consistent
- Select the correct artifact type
- Draft artifact content
- Rate confidence (high or medium)

## Step 4: Present findings

Present results conversationally:

1. **Summary**: How many sessions were analyzed, date range, how many candidates Phase A found, how many Phase B confirmed
2. **Config audit findings**: Gaps, placement issues, budget warnings — present these even without session evidence
3. **Transcript-based findings**: For each confirmed proposal, explain:
   - What the pattern is
   - Why it matters
   - Where the artifact would go (file path and tier)
   - Specific evidence from sessions (quote user messages, cite session dates)
4. **Memory audit findings**: Promotable notes, redundant entries

If no candidates meet thresholds and no config gaps were found, say so clearly. Do not present empty sections or walls of "nothing found."

## Step 5: Store proposals

Create the proposals directory and file:

```bash
mkdir -p .claude/forge/proposals
```

Write all proposals to `.claude/forge/proposals/pending.json`. Each proposal must have:
- `id`: A unique identifier (use a UUID or descriptive slug)
- `type`: One of `claude_md_entry`, `rule`, `skill`, `hook`, `agent`, `reference_doc`
- `confidence`: `high` or `medium`
- `description`: What this proposal does
- `suggested_content`: The actual content to generate
- `suggested_path`: Where the artifact would be placed
- `evidence`: Array of evidence items (quotes, session refs, config findings)
- `status`: `"pending"`

## Step 6: Next steps

Tell the user to run `/forge:optimize` to review and apply the proposals one by one.
