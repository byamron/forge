#!/usr/bin/env python3
"""Sync version from plugin.json to marketplace.json.

Source of truth: forge/.claude-plugin/plugin.json
Targets: .claude-plugin/marketplace.json (metadata.version + plugins[0].version)

Used as a pre-commit hook to keep versions in sync.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


def read_staged(path: str) -> Optional[str]:
    """Read a file from the git index (staged content)."""
    try:
        return subprocess.check_output(
            ["git", "show", ":" + path],
            stderr=subprocess.DEVNULL,
        ).decode()
    except subprocess.CalledProcessError:
        return None


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    plugin_rel = "forge/.claude-plugin/plugin.json"
    marketplace_rel = ".claude-plugin/marketplace.json"
    marketplace_path = repo_root / marketplace_rel

    plugin_text = read_staged(plugin_rel)
    if plugin_text is None:
        print(f"ERROR: {plugin_rel} not found in git index", file=sys.stderr)
        sys.exit(1)

    marketplace_text = read_staged(marketplace_rel)
    if marketplace_text is None:
        print(f"ERROR: {marketplace_rel} not found in git index", file=sys.stderr)
        sys.exit(1)

    plugin = json.loads(plugin_text)
    marketplace = json.loads(marketplace_text)

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
