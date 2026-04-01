#!/usr/bin/env python3
"""Validate proposed artifact paths against Forge's security constraints.

Reads a JSON array of proposal objects from stdin, validates each path,
and outputs results as JSON to stdout.

Allowed write locations (all relative to project root):
- CLAUDE.md
- .claude/rules/**
- .claude/skills/**
- .claude/agents/**
- .claude/references/**
- .claude/settings.json
- .claude/forge/**

Usage:
    echo '[{"id": "p1", "suggested_path": ".claude/rules/lint.md"}]' | python3 validate-paths.py
"""

import json
import sys
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional


ALLOWED_PREFIXES = [
    ".claude/rules/",
    ".claude/skills/",
    ".claude/agents/",
    ".claude/references/",
    ".claude/forge/",
]

ALLOWED_EXACT = [
    "CLAUDE.md",
    ".claude/settings.json",
]


def validate_path(suggested_path: str) -> Dict[str, Any]:
    """Validate a single path against Forge's write boundary."""
    if not isinstance(suggested_path, str) or not suggested_path.strip():
        return {"valid": False, "reason": "Path is empty or not a string"}

    path = suggested_path.strip()

    if path.startswith("/") or path.startswith("~"):
        return {"valid": False, "reason": "Absolute path not allowed"}

    normalized = PurePosixPath(path)
    for part in normalized.parts:
        if part == "..":
            return {"valid": False, "reason": "Path traversal (..) not allowed"}

    normalized_str = str(normalized)

    for exact in ALLOWED_EXACT:
        if normalized_str == exact:
            return {"valid": True}

    for prefix in ALLOWED_PREFIXES:
        if normalized_str.startswith(prefix):
            remainder = normalized_str[len(prefix):]
            if remainder:
                return {"valid": True}

    return {
        "valid": False,
        "reason": "Path is outside allowed locations (.claude/rules/, .claude/skills/, "
                  ".claude/agents/, .claude/references/, .claude/forge/, "
                  ".claude/settings.json, CLAUDE.md)",
    }


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception as e:
        print("Error reading stdin: {}".format(e), file=sys.stderr)
        sys.exit(1)

    if not raw.strip():
        print("Error: no input provided on stdin", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print("Error: invalid JSON on stdin: {}".format(e), file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("Error: expected a JSON array on stdin", file=sys.stderr)
        sys.exit(1)

    results: List[Dict[str, Any]] = []

    for item in data:
        if not isinstance(item, dict):
            results.append({
                "id": None,
                "path": None,
                "valid": False,
                "reason": "Item is not a JSON object",
            })
            continue

        item_id: Optional[str] = item.get("id")
        suggested_path = item.get("suggested_path")

        if item_id is None:
            results.append({
                "id": None,
                "path": suggested_path,
                "valid": False,
                "reason": "Missing 'id' field",
            })
            continue

        if suggested_path is None:
            results.append({
                "id": item_id,
                "path": None,
                "valid": False,
                "reason": "Missing 'suggested_path' field",
            })
            continue

        validation = validate_path(suggested_path)
        entry: Dict[str, Any] = {
            "id": item_id,
            "path": suggested_path.strip() if isinstance(suggested_path, str) else suggested_path,
            "valid": validation["valid"],
        }
        if not validation["valid"]:
            entry["reason"] = validation["reason"]
        results.append(entry)

    all_valid = all(r["valid"] for r in results) if results else True

    output = {
        "results": results,
        "all_valid": all_valid,
    }

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
