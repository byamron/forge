# Forge

Infrastructure architect for Claude Code. Analyzes your sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs.

## Commands

- `/forge:status` — Audit your Claude Code configuration health. Works immediately with no session history.
- `/forge:analyze` — Analyze recent sessions, config, and auto-memory to find improvement opportunities.
- `/forge:optimize` — Review and apply pending proposals from a previous analysis.

## Installation

```bash
claude --plugin-dir ./forge
```

## Requirements

- Claude Code v2.1.59+
- Python 3.8+

## How it works

Forge operates in a **collect -> analyze -> propose -> generate -> place** pipeline:

1. **Phase A** (zero tokens) — Python scripts scan your config, session transcripts, and auto-memory for patterns
2. **Phase B** (targeted LLM) — A subagent confirms candidates and selects the right artifact type
3. **Review** — You approve, modify, or skip each proposal
4. **Generate** — Artifacts are created and placed in the correct locations

All analysis happens locally. No data leaves your machine.
