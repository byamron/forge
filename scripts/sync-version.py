#!/usr/bin/env python3
"""Sync version from plugin.json to marketplace.json.

Source of truth: forge/.claude-plugin/plugin.json
Targets: .claude-plugin/marketplace.json (metadata.version + plugins[0].version)

Used as a pre-commit hook to keep versions in sync.
"""

import json
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    plugin_path = repo_root / "forge" / ".claude-plugin" / "plugin.json"
    marketplace_path = repo_root / ".claude-plugin" / "marketplace.json"

    if not plugin_path.exists():
        print(f"ERROR: {plugin_path} not found", file=sys.stderr)
        sys.exit(1)
    if not marketplace_path.exists():
        print(f"ERROR: {marketplace_path} not found", file=sys.stderr)
        sys.exit(1)

    plugin = json.loads(plugin_path.read_text())
    marketplace = json.loads(marketplace_path.read_text())

    version = plugin.get("version")
    if not version:
        print("ERROR: No version field in plugin.json", file=sys.stderr)
        sys.exit(1)

    changed = False

    if marketplace.get("metadata", {}).get("version") != version:
        marketplace.setdefault("metadata", {})["version"] = version
        changed = True

    for p in marketplace.get("plugins", []):
        if p.get("name") == "forge" and p.get("version") != version:
            p["version"] = version
            changed = True

    if changed:
        marketplace_path.write_text(json.dumps(marketplace, indent=2) + "\n")
        print(f"Synced version {version} to marketplace.json")
    else:
        print(f"Versions already in sync ({version})")


if __name__ == "__main__":
    main()
