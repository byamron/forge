"""Plugin manifest validation tests.

Catches the class of bugs where plugin.json is missing required fields
or version numbers drift between plugin.json and marketplace.json.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_JSON = REPO_ROOT / "forge" / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


class TestPluginJsonRequired:
    """plugin.json must have the fields Claude Code needs to load skills."""

    def test_has_skills_field(self):
        data = _load_json(PLUGIN_JSON)
        assert "skills" in data, "plugin.json missing 'skills' — marketplace installs will load zero skills"

    def test_has_agents_field(self):
        data = _load_json(PLUGIN_JSON)
        assert "agents" in data, "plugin.json missing 'agents' — marketplace installs won't register agents"

    def test_has_hooks_field(self):
        data = _load_json(PLUGIN_JSON)
        assert "hooks" in data, "plugin.json missing 'hooks' — marketplace installs won't register hooks"

    def test_skills_path_resolves(self):
        data = _load_json(PLUGIN_JSON)
        skills_dir = PLUGIN_JSON.parent.parent / data["skills"].lstrip("./")
        assert skills_dir.is_dir(), f"skills path '{data['skills']}' does not resolve to a directory"

    def test_agents_path_resolves(self):
        data = _load_json(PLUGIN_JSON)
        agents_dir = PLUGIN_JSON.parent.parent / data["agents"].lstrip("./")
        assert agents_dir.is_dir(), f"agents path '{data['agents']}' does not resolve to a directory"

    def test_hooks_path_resolves(self):
        data = _load_json(PLUGIN_JSON)
        hooks_file = PLUGIN_JSON.parent.parent / data["hooks"].lstrip("./")
        assert hooks_file.is_file(), f"hooks path '{data['hooks']}' does not resolve to a file"


class TestVersionSync:
    """Version numbers must match across plugin.json and marketplace.json."""

    def test_marketplace_metadata_version_matches(self):
        plugin = _load_json(PLUGIN_JSON)
        marketplace = _load_json(MARKETPLACE_JSON)
        assert plugin["version"] == marketplace["metadata"]["version"], (
            f"plugin.json version ({plugin['version']}) != "
            f"marketplace.json metadata.version ({marketplace['metadata']['version']})"
        )

    def test_marketplace_plugin_entry_version_matches(self):
        plugin = _load_json(PLUGIN_JSON)
        marketplace = _load_json(MARKETPLACE_JSON)
        entry = marketplace["plugins"][0]
        assert plugin["version"] == entry["version"], (
            f"plugin.json version ({plugin['version']}) != "
            f"marketplace.json plugins[0].version ({entry['version']})"
        )
