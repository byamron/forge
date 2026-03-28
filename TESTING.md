# Forge — Test Plan

Structured testing for the Forge plugin. Run these against real projects with session history.

## Prerequisites

- Claude Code v2.1.59+
- Python 3.8+
- At least one project with existing session history in `~/.claude/projects/`

---

## 1. Installation

### 1a. Marketplace install

1. In Claude Code, run `/plugins`
2. Add `https://github.com/byamron/forge.git` as a marketplace source
3. Install the Forge plugin
4. Restart the session or run `/reload-plugins`

**Verify:**
- [ ] Plugin loads without errors
- [ ] `/forge`, `/forge:settings`, `/forge:version` appear as available commands

### 1b. Local development install

```bash
claude --plugin-dir ./forge
```

**Verify:**
- [ ] Plugin loads without errors
- [ ] All three skills are available
- [ ] Changes to skill files are picked up after `/reload-plugins`

### 1c. Version verification

Run `/forge:version`.

**Verify:**
- [ ] Shows correct version (0.1.0)
- [ ] Shows FORGE_ROOT path
- [ ] For marketplace installs: shows git SHA and last updated timestamp
- [ ] For local dev: notes it's running from a local copy
- [ ] Freshness guidance is accurate

---

## 2. Core pipeline (`/forge`)

### 2a. First run — no prior Forge state

Run `/forge` on a project that has session history but has never used Forge before (no `.claude/forge/` directory).

**Verify:**
- [ ] FORGE_ROOT resolves correctly
- [ ] Scripts run without errors (check stderr for Python tracebacks)
- [ ] Context health table displays with correct values
- [ ] Proposals are presented (if patterns exist in session history)
- [ ] Each proposal has: impact level, type, description, evidence
- [ ] AskUserQuestion presents Approve/Modify/Skip/Never options
- [ ] No proposals reference other projects' data

### 2b. Approve a proposal

Select "Approve" on a proposal.

**Verify:**
- [ ] Artifact content preview shown before writing
- [ ] Path validation passes (relative path, within `.claude/`)
- [ ] File is written to the correct location
- [ ] For hooks: existing `.claude/settings.json` is read-merged-written (not overwritten)
- [ ] For CLAUDE.md entries: content is appended, not replaced
- [ ] Finalize script runs and updates `pending.json`, `history/applied.json`

### 2c. Skip and dismiss proposals

Skip one proposal, dismiss another with "Never".

**Verify:**
- [ ] Skipped proposal appears on next `/forge` run
- [ ] Dismissed proposal never appears again
- [ ] `dismissed.json` contains the dismissed proposal ID

### 2d. Modify a proposal

Select "Modify" on a proposal and request a change.

**Verify:**
- [ ] User is asked what to change
- [ ] Updated preview is shown
- [ ] Requires explicit approval before writing

### 2e. Cached re-run

Run `/forge` again immediately after a previous run.

**Verify:**
- [ ] Results appear instantly (cached, no re-analysis)
- [ ] Previously applied proposals are not re-proposed
- [ ] Previously skipped proposals reappear
- [ ] Previously dismissed proposals do not reappear

### 2f. No proposals scenario

Run `/forge` on a project with a well-configured `.claude/` and minimal session history.

**Verify:**
- [ ] Context health table still displays
- [ ] Message like "your setup looks good" appears
- [ ] No empty table or error

---

## 3. Deep analysis (`/forge --deep`)

### 3a. Deep mode invocation

Run `/forge --deep`.

**Verify:**
- [ ] Context health table appears immediately (not blocked on LLM)
- [ ] "Deep analysis running in the background" message shown
- [ ] Background agent completes and deep proposals are merged with script proposals
- [ ] Deep proposals have `source: deep_analysis`
- [ ] No duplicate proposals between script and deep results
- [ ] Merged list is sorted by impact

### 3b. Quick mode override

Run `/forge --quick`.

**Verify:**
- [ ] Only script proposals shown (no background agent spawned)
- [ ] Works even if default setting is `deep`

---

## 4. Settings (`/forge:settings`)

### 4a. Read current settings

Run `/forge:settings`.

**Verify:**
- [ ] FORGE_ROOT resolves (tests the fix from PR #10)
- [ ] Current nudge level and analysis depth are displayed
- [ ] Option tables render correctly

### 4b. Change nudge level

Say "set to quiet" or "eager".

**Verify:**
- [ ] `.claude/forge/settings.json` is created/updated
- [ ] Confirmation message shows what changed
- [ ] Next `/forge:settings` run reflects the new value

### 4c. Change analysis depth

Say "turn on deep analysis".

**Verify:**
- [ ] Setting written correctly
- [ ] Next `/forge` (no flags) uses deep mode

---

## 5. Hooks

### 5a. SessionEnd hook

End a session normally (type `/exit` or close the terminal).

**Verify:**
- [ ] `.claude/forge/unanalyzed-sessions.log` is created/updated with the session
- [ ] `~/.claude/forge/repo-index.json` contains the current project's remote URL
- [ ] No credential leakage in the repo-index (check for tokens in URLs)
- [ ] Cache is updated (`cache-manager.py --update` ran)

### 5b. Hook timeout behavior

Check `claude --debug` output for hook execution timing.

**Verify:**
- [ ] `log-session.sh` completes within 5s
- [ ] `cache-manager.py --update` completes within 15s

---

## 6. Script-level validation

Run these individually from the repo root to isolate failures.

### 6a. Config audit

```bash
python3 forge/scripts/analyze-config.py
```

**Verify:**
- [ ] Valid JSON output to stdout
- [ ] `tech_stack` detects the correct stack (check for `package.json`, `pyproject.toml`, etc.)
- [ ] `placement_issues` are reasonable (not flagging file trees or code blocks)
- [ ] Existing skills, rules, hooks inventoried with full content

### 6b. Transcript analysis

```bash
python3 forge/scripts/analyze-transcripts.py --project-root "$(pwd)"
```

**Verify:**
- [ ] Valid JSON output to stdout
- [ ] Cross-worktree discovery finds sessions from all worktrees of the same repo
- [ ] Correction detection doesn't produce false positives from design/iteration conversations
- [ ] Repeated prompts are genuine (high occurrence + multi-session)
- [ ] Completes in <5 seconds

### 6c. Memory audit

```bash
python3 forge/scripts/analyze-memory.py
```

**Verify:**
- [ ] Valid JSON output to stdout
- [ ] Memory entries are classified (convention/preference/workflow)
- [ ] Promotion suggestions make sense

### 6d. Cache manager

```bash
python3 forge/scripts/cache-manager.py --check --plugin-root ./forge
python3 forge/scripts/cache-manager.py --proposals --plugin-root ./forge
```

**Verify:**
- [ ] `--check` reports which analyses are stale
- [ ] `--proposals` returns merged proposals with context health
- [ ] Cache files written to `.claude/forge/cache/`

### 6e. Build proposals

```bash
python3 forge/scripts/build-proposals.py --plugin-root ./forge
```

**Verify:**
- [ ] Evidence thresholds applied (skill: 4 occurrences/3 sessions, rule: 3/2, etc.)
- [ ] Duplicate detection via Jaccard similarity works
- [ ] Previously dismissed proposals filtered out

---

## 7. Security checks

### 7a. Path validation

During `/forge`, if a proposal has a suspicious `suggested_path`:

**Verify:**
- [ ] Paths with `..` are rejected
- [ ] Absolute paths are rejected
- [ ] Paths outside `.claude/` and `CLAUDE.md` are rejected
- [ ] Warning shown to user for each rejected path

### 7b. Agent isolation

Run `/forge --deep` and check agent behavior:

**Verify:**
- [ ] `session-analyzer` cannot write files (disallowedTools: Write, Edit, Bash)
- [ ] Agent uses `model: sonnet` and `effort: low`

### 7c. Data isolation

Run `/forge` on project A, then on project B:

**Verify:**
- [ ] Project A's proposals contain no references to project B's files or patterns
- [ ] Cross-worktree aggregation only groups worktrees of the same repo (verified by git remote URL)

---

## 8. Edge cases

### 8a. No session history

Run `/forge` on a brand-new project with zero sessions.

**Verify:**
- [ ] Config audit still runs and produces useful output
- [ ] Transcript analysis returns empty results (not an error)
- [ ] Plugin doesn't crash or show confusing messages

### 8b. No `.claude/` directory

Run `/forge` on a project with no existing Claude Code config.

**Verify:**
- [ ] Config audit reports the gap
- [ ] Proposals to create initial config are reasonable
- [ ] Directories are created cleanly when artifacts are approved

### 8c. Large session history

Run on a project with 50+ sessions (e.g., this repo's own history via Conductor worktrees).

**Verify:**
- [ ] Analysis completes in <5 seconds
- [ ] No memory errors or truncation
- [ ] Cross-worktree discovery handles deleted worktrees gracefully
