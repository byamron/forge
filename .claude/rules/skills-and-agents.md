---
path: "forge/{skills,agents}/**/*.md"
---

Skills and agents are markdown files with YAML frontmatter that instruct Claude on what to do.

- Skill `name` must be kebab-case. `description` must be <1024 characters and include "Use when..." trigger language.
- No XML tags in frontmatter values.
- Body instructions use imperative voice with clear step structure (## Step N headers).
- Agent frontmatter must include `model`, `effort`, and `maxTurns`. Default to `model: sonnet`, `effort: low`.
- Use `disallowedTools` on agents that should only read and reason, not write files.
- Skills reference analysis scripts via `$CLAUDE_PLUGIN_ROOT/scripts/` — this resolves to the plugin's install directory at runtime.
