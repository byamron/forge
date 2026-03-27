---
name: version
description: >-
  Check which version of Forge is installed and whether it matches the latest
  build. Use when testing Forge, after updating, or to verify the plugin loaded
  correctly.
---

## Step 1 — Resolve plugin root and read version

Run this command to get the installed plugin location and version info:

```bash
FORGE_ROOT="${CLAUDE_PLUGIN_ROOT}"; if [ -z "$FORGE_ROOT" ]; then FORGE_ROOT=$(python3 -c "import json,pathlib; data=json.loads(pathlib.Path.home().joinpath('.claude/plugins/installed_plugins.json').read_text()); print(next((v[0]['installPath'] for k,v in data.get('plugins',{}).items() if k.startswith('forge@')), ''))" 2>/dev/null); fi; if [ -z "$FORGE_ROOT" ]; then echo 'ERROR: Could not locate Forge plugin'; exit 1; fi; echo "FORGE_ROOT=$FORGE_ROOT"; echo "---"; cat "$FORGE_ROOT/.claude-plugin/plugin.json" 2>/dev/null; echo "---"; python3 -c "
import json, pathlib, sys
path = pathlib.Path.home() / '.claude/plugins/installed_plugins.json'
if not path.exists():
    print(json.dumps({'error': 'installed_plugins.json not found'}))
    sys.exit(0)
data = json.loads(path.read_text())
plugins = data.get('plugins', {})
for key, entries in plugins.items():
    if key.startswith('forge@'):
        entry = entries[0] if entries else {}
        print(json.dumps({
            'registry_key': key,
            'scope': entry.get('scope', 'unknown'),
            'install_path': entry.get('installPath', ''),
            'version': entry.get('version', ''),
            'git_commit_sha': entry.get('gitCommitSha', ''),
            'installed_at': entry.get('installedAt', ''),
            'last_updated': entry.get('lastUpdated', '')
        }, indent=2))
        sys.exit(0)
print(json.dumps({'error': 'forge not found in installed_plugins.json'}))
"
```

## Step 2 — Present version info

Parse the output from Step 1 and present a clear version report:

**Plugin loaded from:** `<FORGE_ROOT path>`
**Plugin version:** `<version from plugin.json>`
**Marketplace key:** `<registry_key>` (e.g., `forge@forge`)
**Scope:** `<scope>` (user = global, project = per-project)
**Git SHA:** `<git_commit_sha>`
**Last updated:** `<last_updated>`

If `CLAUDE_PLUGIN_ROOT` was set (not empty before fallback), note that the plugin was loaded directly by Claude Code. If the fallback was used, note that.

## Step 3 — Freshness check

If the git SHA is available, tell the user:
- "This is the version Claude Code has cached. If you've pushed updates to the marketplace repo, run `/plugins` to check for updates."

If the install path points to a symlink or local path (not inside `~/.claude/plugins/cache/`), note that the plugin is running from a local development copy and always reflects the latest files on disk.

If any field is missing or the plugin wasn't found in the registry, warn that version tracking may not be working correctly.
