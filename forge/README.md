# Forge

Infrastructure architect for Claude Code. Analyzes your sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs.

## Commands

- `/forge` — Analyze your setup and apply improvements. Audits config health, detects workflow patterns from session history, and walks you through reviewing and applying suggestions.
- `/forge:settings` — Configure nudge frequency and analysis depth.

## Installation

```bash
claude --plugin-dir ./forge
```

## Requirements

- Claude Code v2.1.59+
- Python 3.8+

## How it works

Forge operates in a **collect -> analyze -> review -> generate** pipeline:

1. **Phase A** (zero tokens) — Python scripts scan your config, session transcripts, and auto-memory for patterns
2. **Review** — You see findings and approve, modify, or skip each proposal
3. **Generate** — Artifacts are created and placed in the correct locations

All analysis is scoped to the current project (and its worktrees). No data leaves your machine. Forge never writes files without your explicit approval.
