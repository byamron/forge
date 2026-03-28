# Forge

Infrastructure architect for Claude Code. Analyzes your sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs.

## Commands

- `/forge` — Analyze your setup and apply improvements. Use `--deep` for LLM-enhanced pattern detection, `--quick` for script-only mode.
- `/forge:settings` — Configure nudge frequency and analysis depth (standard/deep).
- `/forge:version` — Check installed version and verify the build is current.

## Installation

**Via marketplace (recommended):** In Claude Code, run `/plugins`, add `https://github.com/byamron/forge.git` as a marketplace, then install Forge.

**Local development:**
```bash
claude --plugin-dir ./forge
```

After cloning, enable the version-sync pre-commit hook:
```bash
git config core.hooksPath .githooks
```

## Requirements

- Claude Code v2.1.59+
- Python 3.8+

## How it works

Forge operates in a **collect -> analyze -> review -> generate** pipeline:

1. **Phase A** (zero tokens) — Python scripts scan your config, session transcripts, and auto-memory for patterns
2. **Deep analysis** (optional, ~5K tokens) — LLM pass finds contextual patterns scripts can't detect (position-aware signals, implicit preferences, approval gates). Runs in the background.
3. **Review** — You see findings and approve, modify, or skip each proposal
4. **Generate** — Artifacts are created and placed in the correct locations

All analysis is scoped to the current project (and its worktrees). No data leaves your machine. Forge never writes files without your explicit approval.
