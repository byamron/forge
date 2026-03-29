---
name: audit
description: >
  Review recent changes against project docs and standards. Use after completing
  a feature or before shipping to catch gaps. Checks code against documented
  rules, security policy, and feedback.
context: fork
agent: Explore
allowed-tools: Read, Grep, Glob, Bash
---

You are auditing recent changes against project standards. This runs in an isolated context.

## 1. Gather context

- Run `git diff main..HEAD --name-only` to list changed files
- Run `git log --oneline main..HEAD` for commit history
- Read `CLAUDE.md` for project standards
- Read `core-docs/feedback.md` for documented rules and past corrections

## 2. Check documentation completeness

- Does `core-docs/history.md` have entries for the changes? Are they complete (what, why, tradeoffs)?
- Does `core-docs/plan.md` reflect the current state?
- Were any user corrections made that aren't captured in `core-docs/feedback.md`?

## 3. Check against feedback rules

For each entry in `core-docs/feedback.md`, check if the recent changes violate any synthesized rules. Flag violations.

## 4. Check version and manifest (if forge/ changed)

If any file under `forge/` changed:
- Are all three version locations in sync? (`forge/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` metadata, `.claude-plugin/marketplace.json` plugin entry)
- Does the manifest list all skills and agents?

## 5. Check security compliance

- Read `.claude/rules/security.md`
- Scan changed Python scripts for: `shell=True`, raw `.removesuffix()`, `eval()`, `exec()`, credential handling without stripping
- Check hook commands for chained commands or redirects

## 6. Run tests

```bash
python3 -m pytest tests/ -v
```

## 7. Report

Produce a concise report:

```
## Audit Results

### Documentation
- [pass/fail] history.md updated
- [pass/fail] plan.md reflects current state
- [pass/fail] feedback.md captures corrections

### Version & Manifest (if applicable)
- [pass/fail] versions in sync
- [pass/fail] manifest complete

### Security
- [list any violations]

### Tests
- [pass/fail] test results

### Recommendations
- [actionable items to fix before shipping]
```
