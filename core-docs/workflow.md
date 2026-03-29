# Workflow

How to work with Claude and agents on Forge development.

---

## Session Start Checklist

Before starting any work (~1 minute):

1. **Read `plan.md`** -- check "Current focus" and "Handoff Notes."
2. **Spot-check relevant docs** -- if relying on a design or architecture doc, verify key claims against the actual code.
3. **Pick your agent** -- see agent table in CLAUDE.md or use `claude --agent <name>`.

## Agent Workflow

For each piece of work, pick one primary agent. Full specs live in `.claude/agents/`.

### Standard feature workflow

```
1. Planner Agent   --> scope feature, write UX goals, update plan.md
2. Domain Agent    --> Python scripts, analyzers, plugin infrastructure
3. Testing Agent   --> tests for new behavior
4. Docs Agent      --> history.md, plan.md, commit
```

Use `/clear` between agent phases to keep context small.

### Quick recipes

**Bugfix:**
1. Testing Agent: write regression test reproducing the bug
2. Domain Agent: fix until test passes
3. Docs Agent: update plan.md and commit

**Script improvement:**
1. Domain Agent with plan.md + the script file
2. Testing Agent: add/update tests
3. Docs Agent if the change is significant

**Feedback iteration (user corrects implementation):**
1. Domain Agent: apply the corrected approach
2. Docs Agent: document feedback in feedback.md, update history.md

## Important: Plugin vs Dev Infrastructure

- **Plugin files** (`forge/skills/`, `forge/agents/`, `forge/scripts/`, `forge/hooks/`): These ship to users. Changes here require a version bump.
- **Dev files** (`.claude/skills/`, `.claude/agents/`, `.claude/rules/`, `core-docs/`): These are for *us* when developing Forge. They are not part of the plugin.

Never confuse the two. A `/ship` skill in `.claude/skills/ship/` is our dev workflow tool. A `/forge` skill in `forge/skills/forge/` is the product.
