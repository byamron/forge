---
name: status
description: >
  Audit your Claude Code configuration health. Shows context budget usage,
  identifies misplaced entries, detects capability gaps, and suggests
  improvements. Use when you want to check how healthy your Claude Code
  setup is, or on first install to see what Forge can do. Works immediately
  with no session history needed.
---

You are running the Forge status audit. Follow these steps exactly:

## Step 1: Run the config audit script

Run:
```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/analyze-config.py"
```

Capture the JSON output. If the script fails, report the error and continue with what you can gather manually.

## Step 2: Run the memory audit script

Run:
```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/analyze-memory.py"
```

Capture the JSON output. If the script fails or finds nothing, that's fine — continue.

## Step 3: Present the health report

Using the combined results from both scripts, present a conversational health report. Organize by priority — most impactful suggestions first. Cover these sections:

### Context Budget
- CLAUDE.md line count and estimated tier 1 token load
- CLAUDE.local.md line count (if it exists)
- Number of rules, skills, agents, and hooks
- If total tier 1 content (CLAUDE.md + CLAUDE.local.md) exceeds 150 lines, warn that context is heavy and suggest demoting entries to rules or reference docs

### Configuration Gaps
- Formatter detected in project (Prettier, Black, Biome, rustfmt, gofmt) but no PostToolUse auto-format hook → suggest adding one
- Linter detected (ESLint, Ruff) but no auto-lint hook → suggest adding one
- Test framework detected but no pre-commit test hook → mention as optional
- Project has docs/ directory or detailed README but CLAUDE.md doesn't reference them → suggest adding a pointer

### Placement Issues
- CLAUDE.md entries that mention specific file extensions, frameworks, or directories → suggest moving to scoped rules with path frontmatter
- CLAUDE.local.md entries that duplicate CLAUDE.md content → suggest removing duplicates
- Auto-memory notes that describe persistent preferences → suggest promoting to CLAUDE.md or rules
- Rules without path frontmatter that load globally → suggest adding path scoping
- Verbose CLAUDE.md entries (>3 lines each) → suggest extracting to reference docs

### Staleness
- Skills with vague or overly short descriptions (likely to under-trigger)
- Rules or CLAUDE.md entries that appear to contradict each other

## Step 4: Explain and suggest

For each finding:
1. Explain what it is in plain language
2. Explain why it matters (impact on Claude's behavior or context budget)
3. State what Forge would do about it (the specific artifact it would generate)

## Step 5: Next steps

End by telling the user:
- Run `/forge:analyze` for a deeper analysis that includes session transcript patterns (repeated corrections, workflow patterns, post-action habits)
- Run `/forge:optimize` after analysis to review and apply specific proposals
