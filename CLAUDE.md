# Noticed — Claude Code Infrastructure Plugin

## Project

Noticed is a Claude Code plugin that analyzes sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs. It manages context architecture as a living system.

The plugin lives in `noticed/` and is tested with `claude --plugin-dir ./noticed`. After changes to skills, agents, or hooks, run `/reload-plugins` to pick up updates.

## Architecture

- **Skills** (`noticed/skills/*/SKILL.md`): User-facing commands — `/noticed` (unified analysis + review), `/noticed:settings` (nudge frequency config), `/noticed:version` (installed version and freshness check)
- **Agents** (`noticed/agents/*.md`): Subagents — `session-analyzer` (LLM quality gate + pattern detection)
- **Scripts** (`noticed/scripts/*.py`): Analysis and lifecycle — `analyze-config.py`, `analyze-transcripts.py`, `analyze-memory.py` (Phase A analyzers), `build-proposals.py` (proposal pipeline + effectiveness tracking), `cache-manager.py` (caching + orchestration), `project_identity.py` (project hash, user/project data dirs, find_project_root), `check-pending.py`, `background-analyze.py` (SessionStart hooks), `log-session.sh`, `finalize-proposals.py` (bookkeeping + tracking data), `format-proposals.py` (presentation formatting), `validate-paths.py` (path security validation), `merge-settings.py` (atomic settings.json hook merging), `read-settings.py`, `write-settings.py` (utilities)
- **Hooks** (`noticed/hooks/hooks.json`): SessionStart (pending check + background analysis), SessionEnd (session logging + cache update)
- **References** (`noticed/references/*.md`): Templates and best practices used during artifact generation

## Key Constraints

- **Security is non-negotiable.** Noticed must never delete user code, write outside `.claude/`/`CLAUDE.md`, or introduce vulnerabilities. All writes go through user approval. See `.claude/rules/security.md` for the full security policy.
- Python scripts use only the standard library (no pip dependencies). Must work on Python 3.8+.
- Subagents use `model: sonnet` and `effort: low` to minimize token cost. Every token Noticed consumes comes from the user's quota.
- The plugin never interrupts mid-task. All analysis is retroactive.
- Generated skills and agents are drafts. CLAUDE.md entries, rules, and hooks are typically production-ready.
- Session transcript JSONL format is not a stable API — parser must handle format variations gracefully.
- **Analysis scope is per-project.** All pattern detection is scoped to the current project and its worktrees. Noticed never reads transcripts from unrelated projects. Cross-project aggregation is a future opt-in feature only.
- **Artifacts default to project-level.** All generated artifacts go to `.claude/` (project-level), never `~/.claude/` (user-level). The user can override during review. Noticed never suggests user-level on its own.
- **Storage split.** Feedback data that shapes proposals (dismissed.json, history/applied.json, feedback_signals.json) lives in `.claude/noticed/` (project-level, git-tracked, shared across contributors). Personal settings, caches, pending proposals, and session logs live in `~/.claude/noticed/projects/<hash>/` (user-level, per-machine).

## Code Style

- Python: use type hints, `pathlib.Path` over `os.path`, `argparse` for CLI. Scripts output JSON to stdout, errors to stderr.
- Markdown: YAML frontmatter for skills and agents. Imperative voice for instructions.
- Hooks: valid JSON, case-sensitive matchers, no spaces around `|` in matcher patterns.

## Testing

See `.claude/rules/testing.md` for testing details. Run `python3 -m pytest tests/ -v` before committing.

## License

Proprietary. No license file — all rights reserved by default. The `plugin.json` `license` field is omitted intentionally.

## Core Documents

All project documentation lives in `core-docs/`. Review and update these as part of your workflow.

| Document | Path | Purpose |
|----------|------|---------|
| Plan | `core-docs/plan.md` | Living roadmap -- current focus, active work, completed features |
| History | `core-docs/history.md` | Decision log -- what was done, why, tradeoffs, branch+SHA |
| Feedback | `core-docs/feedback.md` | Synthesized user feedback distilled into rules |
| Workflow | `core-docs/workflow.md` | Agent workflow and session start checklist |
| Spec | `core-docs/spec.md` | Original product & technical specification (v0.1) |
| Roadmap | `core-docs/roadmap.md` | Original implementation roadmap with phase/task definitions |

## Development Infrastructure

**Important:** The plugin ships from `noticed/`. The dev infrastructure in `.claude/` is for *us* when working on Noticed. These are completely separate.

| What | Plugin (ships to users) | Dev (our tools) |
|------|------------------------|-----------------|
| Skills | `noticed/skills/` (`/noticed`, `/noticed:settings`, `/noticed:version`) | `.claude/skills/` (`/ship`, `/audit`) |
| Agents | `noticed/agents/` (`session-analyzer`) | `.claude/agents/` (`planner`, `domain`, `testing`, `docs`) |
| Rules | — | `.claude/rules/` (general, documentation, security, plugin-structure, python-scripts, skills-and-agents, testing) |

Dev agents are invoked with `claude --agent <name>`. See `core-docs/workflow.md` for the standard workflow.

## Communication style

Ask clarifying questions when genuinely unclear on a request, but don't over-ask — the user will request information when they need it. When using technical jargon or introducing terms, briefly explain what they mean inline. Keep all messages concise and direct.

## Post-audit workflow

After running /audit, if all checks pass and the branch would merge cleanly, open the PR automatically (run /ship) without asking — but do not merge. If the audit surfaces issues, fix what's straightforward and ask about anything ambiguous or risky. If there are merge conflicts or other blockers, surface them before proceeding.

## PR Readiness

Before creating any PR, verify the following:

- **Version bump.** If any file under `noticed/` changed, bump the version in all three locations: `noticed/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` `metadata.version`, and `.claude-plugin/marketplace.json` `plugins[0].version`.
- **Tests pass.** Run `python3 -m pytest tests/ -v` and confirm all tests pass. Do not create a PR with failing tests.
- **CLAUDE.md is current.** If the change adds, removes, or renames skills, agents, scripts, hooks, or references, update the Architecture section of this file to match.
- **Rules are current.** If the change introduces a new convention or constraint (e.g., a new required manifest field, a new security boundary), add or update the relevant rule in `.claude/rules/`.
- **History is updated.** If the change involves a significant design decision, architectural change, or non-obvious tradeoff, add an entry to `core-docs/history.md`.

## History

For the history of significant design and technical decisions, see `core-docs/history.md`. **Proactively update this file** whenever you make a significant design decision, change an architectural approach, resolve a non-obvious tradeoff, or deviate from the spec. Each entry should capture what was decided, why, and what alternatives were considered.
