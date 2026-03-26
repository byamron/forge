---
path: "forge/**"
---

Forge is a Claude Code plugin. The `forge/` directory is the plugin root.

- `.claude-plugin/plugin.json` is the manifest — update the version when shipping releases.
- The plugin is self-contained. Generated artifacts are written to the *user's project* `.claude/` directory, not the plugin's own directory.
- `hooks/hooks.json` defines lifecycle hooks. Changes require `/reload-plugins` or a session restart.
- `references/` contains docs used by the artifact-generator agent at generation time. Keep these accurate to current Anthropic documentation.
- Don't add runtime dependencies. The plugin must work on any machine with Python 3.8+ and Claude Code.
