---
path: "forge/scripts/**/*.py"
---

These are Phase A analysis scripts that run locally with zero LLM token cost. They must be fast (<2 seconds for config audit, <5 seconds for transcript scan).

- Standard library only — no pip dependencies, no `pyyaml`. Parse YAML frontmatter with string splitting.
- Compatible with Python 3.8+ — use `Optional[X]` from `typing`, not `X | None`.
- Output valid JSON to stdout. Errors to stderr with exit code 1.
- Handle missing files, empty directories, and malformed input gracefully — never crash on bad data.
- Use `pathlib.Path` for all filesystem operations.
- The `~/.claude/projects/` directory structure maps project paths to hashes. The mapping strategy must try multiple approaches (exact match, partial match, fallback).
