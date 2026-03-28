---
path: "forge/**"
---

Forge is a Claude Code plugin. The `forge/` directory is the plugin root.

- The plugin is self-contained. Generated artifacts are written to the *user's project* `.claude/` directory, not the plugin's own directory.
- `hooks/hooks.json` defines lifecycle hooks. Changes require `/reload-plugins` or a session restart.
- `references/` contains docs used by the artifact-generator agent at generation time. Keep these accurate to current Anthropic documentation.
- Don't add runtime dependencies. The plugin must work on any machine with Python 3.8+ and Claude Code.

## Manifest rules (plugin.json + marketplace.json)

These rules exist because the marketplace caches plugins by version. If you change anything without bumping the version, users get stale installs.

- `forge/.claude-plugin/plugin.json` MUST contain `skills`, `agents`, and `hooks` path fields. Without them, Claude Code loads the plugin but registers zero skills — the plugin silently does nothing. Never remove these fields.
- **Bump the version on every change to any file under `forge/`.** Not just "shipping releases" — any change that touches plugin behavior, scripts, skills, agents, hooks, or the manifest itself. The marketplace resolves updates by version; same version = no update.
- The version in `forge/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (both the `metadata.version` and the plugin entry `version`) MUST always match. Update all three in the same commit.
- Run `python3 -m pytest tests/ -v` after any manifest change to catch sync issues.
