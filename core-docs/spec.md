# Forge — Claude Code Infrastructure Plugin

## Product & Technical Specification — v0.1

---

## 1. Vision

AI coding agents like Claude Code have a rich and growing infrastructure for customization — CLAUDE.md files, rules, skills, hooks, subagents, and plugins — but the learning curve to discover, understand, and correctly implement these is steep. Most users either never set them up, set them up poorly, or invest hours reading documentation and iterating through trial and error.

**Forge** is a Claude Code plugin that does three things existing tools cannot:

1. **Detects which artifact type fits a pattern** — not just "you keep correcting Claude" (auto-memory already handles that), but "this correction should be a rule scoped to `*.test.ts` files, not a CLAUDE.md entry, because it only matters when you're writing tests." The intelligence is in *artifact-type selection and placement*, not just pattern detection.

2. **Manages your context architecture as a living system** — tracks budget across tiers, promotes and demotes content based on actual usage, prevents context rot, and generates reference documents when CLAUDE.md or rules would overflow. No existing tool does this.

3. **Surfaces capabilities you don't know about** — detects when your workflow would benefit from a hook, skill, or agent you've never used, and offers to set it up. This bridges the gap between "how you currently work" and "what Claude Code can actually do for you."

**What Forge is NOT:** It is not another memory system. Claude Code already has auto-memory, session memory, and `/remember` for capturing preferences and corrections. Forge *reads those systems as inputs* and operates at a higher layer — it generates *infrastructure* (skills, hooks, agents, rules, reference docs), manages *where things live* in the context hierarchy, and surfaces *capabilities the user hasn't discovered*. As Anthropic improves its built-in primitives, Forge gets better inputs and becomes more valuable, not less. Memory remembers. Forge builds.

---

## 2. Goals

### Primary Goals

1. **Generate the right artifact for each pattern.** When a user repeats a correction, Forge doesn't just note it — it determines whether it should be a CLAUDE.md entry (universal, always loaded), a rule (domain-specific, loaded contextually), or a reference doc pointed to from CLAUDE.md (too detailed for always-loaded context). This artifact-type intelligence is the core differentiator.

2. **Manage context health over time.** Forge tracks how much context is loaded at session start, detects when CLAUDE.md is bloated or rules are stale, and actively manages the tier hierarchy — promoting high-frequency references to CLAUDE.md, demoting domain-specific entries to rules, extracting verbose content to reference docs. Configuration should get better over time, not just bigger.

3. **Surface infrastructure opportunities the user hasn't considered.** When Forge detects that a user manually runs prettier after every edit, it doesn't just propose a CLAUDE.md note — it proposes a PostToolUse hook, which is a fundamentally different and more powerful solution. When it detects multi-step workflows, it proposes skills or agents. The plugin knows the full Claude Code capability surface and matches patterns to the best available tool.

4. **Generate correct, high-quality drafts.** Every generated artifact must conform to Anthropic's official specifications. But Forge is honest that generated skills and agents are *drafts* — good starting points that the user should review and may iterate on. CLAUDE.md entries and rules are typically complete as-generated. Skills and agents may need refinement.

### What Forge Does vs. What Already Exists

Forge is designed to build **on top of** Anthropic's primitives, not compete with them. As Anthropic improves auto-memory, `/remember`, `/init`, and other built-in features, Forge gets better inputs — it doesn't get made obsolete. The durable value is at the meta layer: knowing which artifact type fits a pattern, managing context architecture holistically, and bridging users to capabilities they haven't discovered.

| Layer | Anthropic Primitives | Forge (Meta Layer) |
|---|---|---|
| **Detection** | Auto-memory detects preferences and patterns | Forge reads auto-memory as input signal |
| **Simple codification** | `/remember` proposes CLAUDE.local.md entries | Forge evaluates whether those entries are optimally placed |
| **Initial setup** | `/init` generates starter CLAUDE.md from codebase | Forge audits and evolves that config over time |
| **Artifact-type selection** | — (not addressed) | Forge decides: rule, skill, hook, agent, or reference doc |
| **Context architecture** | — (not addressed) | Forge manages tiers, budgets, promotion/demotion |
| **Capability discovery** | — (not addressed) | Forge suggests infrastructure the user hasn't tried |
| **Config health** | — (not addressed) | Forge detects staleness, conflicts, bloat, and gaps |

**Integration with Anthropic primitives (not competition):**

- **Auto-memory as input.** Forge reads `~/.claude/projects/<project>/memory/MEMORY.md` and topic files as a primary signal source. Auto-memory captures build commands, code style preferences, debugging insights, and architectural notes. Forge's job is to evaluate whether each memory note is optimally stored — or whether it should be upgraded to a rule, skill, hook, or reference doc. Example: auto-memory notes "user prefers vitest over jest" — Forge recognizes this should be a CLAUDE.md entry (always loaded, not just a memory note that may not surface).

- **`/remember` output as input.** When a user runs `/remember` and accepts proposed CLAUDE.local.md entries, Forge can audit those entries: are they scoped correctly? Should some be domain-specific rules instead of always-loaded? Are any redundant with existing CLAUDE.md content? Forge treats `/remember` as a feeder system, not a competitor.

- **`/init` as foundation.** Forge treats `/init`-generated CLAUDE.md as a starting point that should evolve. On first run, `/forge:status` audits the existing CLAUDE.md (whether from `/init` or hand-written) and suggests improvements — entries to scope as rules, verbose content to extract to references, missing common infrastructure for the detected tech stack.

- **Future-proofing.** If Anthropic adds "auto-generate rules from corrections" natively, Forge's Phase A transcript scanning for corrections becomes less important — but the tier management, context budgeting, capability gap detection, and config health monitoring remain valuable. Forge is positioned to always operate one layer above whatever primitives Anthropic provides. The plugin should be designed so that any individual feature can be deprecated without undermining the whole — the value is in the *system*, not any single detection capability.

### Non-Goals (v1)

- Replacing auto-memory, `/remember`, or `/init` — Forge layers on top of them
- Real-time, mid-session intervention
- Cross-project pattern detection (v1 is per-project)
- Team-wide pattern aggregation
- Integration with non-Claude Code tools (Cursor, Copilot, etc.)

### Cold Start Strategy

Forge cannot detect patterns that haven't occurred yet. It gets more valuable over time as sessions accumulate. To provide value from the first use:

- **Config audit on first run.** When the user first runs `/forge:analyze`, if existing CLAUDE.md, rules, or settings exist, Forge audits them for common issues: bloated CLAUDE.md, missing path matchers on rules, known-good hooks not configured (e.g., auto-format). This provides immediate value from existing configuration, not just from pattern detection.
- **Capability gap detection.** Even without accumulated patterns, Forge can scan the project structure (package.json, tsconfig, etc.) and suggest common infrastructure for that stack — similar to what `/init` does, but more opinionated about artifact types. "You have a React/TypeScript project with Prettier configured. Most projects like this benefit from a PostToolUse auto-format hook. Want one?"
- **Progressive value.** Be transparent that Forge improves with use. After 3-5 sessions, correction patterns emerge. After 10+ sessions, workflow patterns (skills, agents) become detectable. Set expectations accordingly — don't promise "80% of a power user's config in a week."

---

## 3. What's In Scope

The plugin generates and manages six artifact types, plus a reference document layer. Each maps to a distinct signal type in chat history.

### 3.1 Artifact Types

#### CLAUDE.md Entries
**What they are:** Persistent instructions loaded at the start of every session. The foundational layer.
**Anthropic guidance:** "Include Bash commands, code style, and workflow rules. This gives Claude persistent context it can't infer from code alone." CLAUDE.md files are additive — all levels contribute content simultaneously.
**Signal:** Repeated corrections. User tells Claude the same thing across multiple sessions ("use pnpm not npm", "we use Tailwind not CSS modules", "always use server actions").
**Budget constraint:** The plugin tracks CLAUDE.md line count and keeps it under a configurable threshold (default: ~100 lines for the project-level file). When approaching capacity, it promotes entries to Tier 2 (rules) or Tier 3 (reference docs).

#### Rules (`.claude/rules/*.md`)
**What they are:** Context-specific instructions that load when matching files are opened or relevant tasks begin.
**Anthropic guidance:** "Place markdown files in your project's `.claude/rules/` directory. Each file should cover one topic, with a descriptive filename like `testing.md` or `api-design.md`. All `.md` files are discovered recursively."
**Signal:** Domain-specific corrections or preferences that cluster around file types or areas of the codebase. User always gives the same guidance when working on API routes vs. frontend components vs. tests.
**Key design consideration:** Rules support `path` frontmatter for file-pattern matching. The plugin should use this to scope rules tightly — a rule about React components should only load when Claude is touching `.tsx` files.

#### Skills (`.claude/skills/<name>/SKILL.md`)
**What they are:** Reusable workflow packages that Claude loads when relevant or when invoked via `/command`.
**Anthropic guidance:** "For task-specific instructions that don't need to be in context all the time, use skills instead, which only load when you invoke them or when Claude determines they're relevant to your prompt." Skills use progressive disclosure — frontmatter is always loaded for routing, the body loads on invocation, and bundled references load on demand.
**Signal:** Repeated multi-step prompt sequences. User does the same 3-5 step workflow regularly (scaffolding a component, running a specific test/deploy sequence, reviewing a PR with a consistent checklist).
**Structure:** The plugin generates full skill directories including SKILL.md with proper frontmatter, optional `scripts/` for deterministic steps, and optional `references/` for detailed documentation.

#### Hooks (`hooks` in settings or plugin `hooks/hooks.json`)
**What they are:** Shell commands, HTTP endpoints, or LLM prompts that execute automatically at lifecycle points.
**Anthropic guidance:** "Use hooks for actions that must happen every time with zero exceptions." Hooks are deterministic — they always run when configured, regardless of model behavior. 21 lifecycle events are available, with 4 handler types (command, http, prompt, agent).
**Signal:** Repeated manual post-actions. User always runs a formatter after Claude edits, always runs tests before committing, always checks types after modifying an interface. Also detectable: repeated permission approvals for the same safe operations.
**Key events for v1:** `PostToolUse` (auto-format, auto-lint after edits), `Stop` (post-task validation), `PreToolUse` (safety gates), `SessionStart` (context injection).

#### Agents (`.claude/agents/*.md`)
**What they are:** Specialized subagents with custom system prompts, tool restrictions, and model selection. Run in isolated context and return summaries.
**Anthropic guidance:** "Use a subagent when you need context isolation or when your context window is getting full. The subagent might read dozens of files or run extensive searches, but your main conversation only receives a summary." Agents support `name`, `description`, `model`, `effort`, `maxTurns`, `tools`, `disallowedTools`, `skills`, `memory`, `background`, and `isolation` frontmatter fields.
**Signal:** Complex multi-phase workflows with distinct roles. User repeatedly does plan→implement→review sequences, or research→synthesize→write sequences. Also: tasks that routinely consume excessive context and would benefit from isolation.
**When to generate vs. skill:** If the workflow benefits from context isolation, parallel execution, or restricted tool access, it's an agent. If it's a linear set of instructions, it's a skill.

#### Reference Documents (`.claude/references/`, `docs/`, or skill `references/`)
**What they are:** Detailed documentation that Claude reads on demand. Not loaded into context automatically.
**Anthropic guidance:** Progressive disclosure — "the third level is additional files bundled within the skill directory that Claude can choose to navigate and discover only as needed." CLAUDE.md or rules can point to references with natural language ("for detailed API conventions, see `.claude/references/api-guide.md`").
**Signal:** Any generated content that exceeds what belongs in CLAUDE.md or a rule. Detailed style guides, API documentation, architectural decision records, workflow playbooks. Also: when the plugin detects that a skill needs extensive documentation.
**Key role:** Reference docs are the overflow valve. They allow the plugin to capture comprehensive knowledge without polluting always-loaded context.

### 3.2 Context Architecture (The Tier System)

The plugin manages a four-tier context hierarchy, inspired directly by Anthropic's progressive disclosure model. This is not just about *what* to generate — it's about *where to place it* for optimal context efficiency.

```
┌─────────────────────────────────────────────────────┐
│  TIER 1: Always Loaded                              │
│  CLAUDE.md (project + user-level)                   │
│  Budget: ~100 lines project, ~50 lines user         │
│  Content: High-frequency, universal preferences     │
│  Examples: "Use pnpm", "Prefer functional React",   │
│  "Run tests with vitest", one-line pointers to T3   │
├─────────────────────────────────────────────────────┤
│  TIER 2: Contextually Loaded                        │
│  .claude/rules/*.md                                 │
│  Budget: ~50-100 lines per rule file                │
│  Content: Domain-specific conventions               │
│  Loaded when: matching files opened or task matches │
│  Examples: api-design.md, testing.md, react.md      │
├─────────────────────────────────────────────────────┤
│  TIER 3: On-Demand Reference                        │
│  .claude/references/*.md, docs/                     │
│  Budget: No hard limit (not auto-loaded)            │
│  Content: Detailed guides, ADRs, examples           │
│  Loaded when: Claude decides it needs them          │
│  Examples: api-style-guide.md, deployment-guide.md  │
├─────────────────────────────────────────────────────┤
│  TIER 4: Skill/Agent-Scoped                         │
│  .claude/skills/*/references/                       │
│  Budget: Loaded only during skill invocation        │
│  Content: Workflow-specific deep documentation      │
│  Loaded when: skill or agent is active              │
│  Examples: pr-review-checklist.md, deploy-runbook   │
└─────────────────────────────────────────────────────┘
```

**Promotion and demotion logic:**
- When a Tier 3 reference is repeatedly loaded by Claude (detected via session analysis), the plugin suggests promoting key points to Tier 1 or 2.
- When Tier 1 (CLAUDE.md) approaches its budget, the plugin identifies entries that are domain-specific and offers to demote them to Tier 2 rules with appropriate path matchers.
- When a rule file grows beyond its budget, detailed content is extracted to a Tier 3 reference with a pointer left in the rule.

---

## 4. Technical Architecture

### 4.1 Plugin Structure

```
forge/
├── .claude-plugin/
│   └── plugin.json                  # Plugin manifest
├── skills/
│   ├── analyze/
│   │   └── SKILL.md                 # /forge:analyze
│   ├── optimize/
│   │   └── SKILL.md                 # /forge:optimize
│   └── status/
│       └── SKILL.md                 # /forge:status
├── agents/
│   ├── session-analyzer.md          # Analyzes session transcripts (Phase B)
│   ├── artifact-generator.md        # Generates config artifacts
│   └── context-auditor.md           # Audits current context health
├── hooks/
│   └── hooks.json                   # SessionEnd + Stop hooks
├── scripts/
│   ├── collect-sessions.sh          # Gathers session transcripts
│   ├── analyze-patterns.py          # Phase A pattern extraction (zero tokens)
│   └── context-budget.py            # Context budget tracking
├── references/
│   ├── signal-catalog.md            # Catalog of detectable patterns
│   ├── artifact-templates.md        # Templates for each artifact type
│   └── anthropic-best-practices.md  # Condensed official guidance
└── README.md
```

### 4.2 Data Flow

The plugin operates in a **collect → analyze → propose → generate → place** pipeline.

#### Stage 1: Collect
**Trigger:** `SessionEnd` hook fires after each Claude Code session.
**Input:** Session transcript JSONL files. Claude Code stores these at `~/.claude/projects/<project-hash>/<session-id>.jsonl`. The transcript contains the full conversation including user prompts, Claude responses, tool calls, tool results, and permission decisions.
**Action:** The `collect-sessions.sh` script copies/indexes the most recent N session transcripts (configurable, default: last 10) into a working directory for analysis. It also captures the current state of all existing configuration (CLAUDE.md, rules, skills, hooks, agents).
**Privacy consideration:** All analysis happens locally. No data leaves the user's machine.

#### Stage 2: Analyze
**Trigger:** Background on SessionStart (when unanalyzed sessions ≥ threshold) or manual via `/forge:analyze`.

##### Cost Model

All analysis runs within the user's existing Claude Code subscription — no additional billing. However, every token the plugin consumes is a token the user can't use for their actual work within their 5-hour quota window. This means the analysis must be efficient enough that the artifacts it produces save more tokens (and time) than the analysis consumed. A CLAUDE.md entry that prevents a recurring correction saves ~50-100 tokens per session indefinitely; the one-time analysis cost to detect it should be well under 10,000 tokens. The plugin must justify its token spend.

##### Two-Phase Analysis Architecture

The analysis is split into a cheap local pass and a targeted LLM pass to minimize token consumption.

**Phase A — Pattern Scan (zero tokens, pure scripting)**

A Python script (`scripts/analyze-patterns.py`) operates in two modes:

**Mode 1: Transcript scan** (runs against accumulated session transcripts)
Reads the last N session transcripts from disk and extracts structured data without any LLM calls:

- **User prompts:** Raw text of every user message
- **Correction signals:** Messages containing correction-adjacent phrases ("no,", "not that", "I said", "always use", "never use", "don't use", "switch to", "I told you", "we use X not Y", "actually,", "let's do it this way", "that's not right"). Also: user messages that immediately follow Claude's output AND repeat/rephrase information from a previous session (detected via cross-session prompt similarity, not just keyword matching)
- **Tool call patterns:** Tool name + key input parameters (e.g., Bash commands, file paths written/edited)
- **Post-edit user actions:** When a user's prompt immediately follows a Claude tool use and contains a Bash command or tool invocation — particularly when the same command follows the same tool type across sessions
- **Permission decisions:** Which tools/commands were approved and how often
- **Compaction events:** Whether `/compact` was triggered (indicating context pressure)
- **File access frequency:** Which files Claude read across sessions

**Limitations acknowledged:** Keyword-based correction detection has both false positives ("no, that looks good" isn't a correction) and false negatives (user silently redoes something without explicit correction language). This is why Phase A only flags *candidates* — Phase B (LLM) is responsible for confirming whether a candidate is a real pattern. Phase A optimizes for recall (don't miss real patterns), Phase B optimizes for precision (don't surface false ones).

The script also runs textual similarity checks (substring matching, keyword detection, simple fuzzy matching via difflib) across user prompts to detect repeated workflows. Each candidate includes the raw evidence: specific session IDs, timestamps, and exact quotes. This phase runs in <1 second and costs zero tokens.

**Mode 2: Config audit** (runs against existing project configuration)
Scans the project's current Claude Code configuration and flags issues:

- **CLAUDE.md health:** Line count vs. budget. Entries that look domain-specific but aren't in rules. Entries that are verbose and could be extracted to reference docs. Missing common entries for the detected tech stack (scans package.json, Cargo.toml, etc.).
- **Rule health:** Rule files without path frontmatter (loading globally when they should be scoped). Overly broad path matchers. Duplicate content between rules and CLAUDE.md.
- **Skill health:** Skill descriptions that are vague (likely to under-trigger) or overly broad (likely to over-trigger). Skills with no `references/` that are very long (candidates for progressive disclosure).
- **Hook gaps:** Common high-value hooks not configured for the detected tech stack: auto-format (Prettier/Black/rustfmt), auto-lint, auto-test. Detected by checking project config files (`.prettierrc`, `eslint.config`, etc.) against current hooks in settings.json.
- **Missing infrastructure:** Project patterns that suggest unused Claude Code capabilities — e.g., if the project has a complex deployment process documented in README but no `/deploy` skill, or a detailed style guide in docs/ that CLAUDE.md doesn't reference.

**Mode 3: Memory audit** (runs against auto-memory and /remember output)
Scans auto-memory files and CLAUDE.local.md for entries that could be upgraded or better placed:

- **Auto-memory notes at `~/.claude/projects/<project>/memory/`**: Reads MEMORY.md and topic files. Identifies notes that describe persistent preferences (candidates for CLAUDE.md or rules), workflow patterns (candidates for skills), repeated commands (candidates for hooks), or detailed knowledge (candidates for reference docs). Auto-memory captures useful signal but stores everything as flat markdown notes — Forge evaluates whether each note deserves to be promoted to proper infrastructure.
- **CLAUDE.local.md entries** (from `/remember`): Identifies entries that are domain-specific and would be better as scoped rules. Identifies entries that duplicate existing CLAUDE.md content. Identifies entries that are verbose and should be extracted to references. Flags when CLAUDE.local.md is growing large (it loads alongside CLAUDE.md, adding to Tier 1 budget).
- **Cross-reference with existing config**: Detects when a memory note or `/remember` entry is already covered by an existing rule, skill, or hook — indicating the memory is redundant and could be cleaned up.

**Phase B — Pattern Confirmation (targeted LLM, only for candidates)**

For each candidate pattern from Phase A that meets the minimum evidence threshold, the plugin sends a focused prompt to a subagent with *only the relevant excerpts* — not full transcripts. The subagent:

1. Confirms the pattern is real and consistent (not coincidental)
2. Determines the correct artifact type and tier placement
3. Drafts the artifact content
4. Assigns a confidence score

Subagent configuration for efficiency:
```yaml
name: session-analyzer
description: Analyzes pre-filtered session excerpts to confirm workflow patterns
model: sonnet
effort: low
maxTurns: 3
disallowedTools: Write, Edit, Bash
```

Using `effort: low` and `model: sonnet` (not opus) keeps token consumption minimal. Disallowing write/edit/bash tools prevents the analyzer from doing anything other than reading and reasoning. A typical Phase B call processes ~2,000-3,000 tokens of evidence excerpts per candidate pattern.

**Estimated total cost per analysis cycle:**
- Phase A: 0 tokens (local script)
- Phase B: ~2,000-5,000 tokens per confirmed pattern × typically 1-3 patterns = **~5,000-15,000 tokens per analysis**
- For context: this is roughly equivalent to 1-3 normal user prompts

##### Pattern Categories

| Pattern Category | What Phase A Scans For | Phase B Confirms | Output Artifact |
|---|---|---|---|
| **Repeated corrections** | Correction keywords + similar phrasing across sessions | Consistent preference, not one-off | → CLAUDE.md entry or Rule |
| **Repeated prompts** | High textual similarity between opening prompts | Genuine workflow vs. coincidence | → Skill |
| **Multi-step sequences** | Same tool call sequences in same order | Intentional workflow with ≥3 steps | → Skill or Agent |
| **Post-action patterns** | User Bash commands immediately following Claude edits | Same command each time, deterministic | → Hook |
| **Permission fatigue** | Same permission approved 5+ times, never denied | Truly safe, no edge cases | → Hook (auto-approve) |
| **Context overload** | Compaction frequency, CLAUDE.md line count | Specific entries to demote/restructure | → Context restructuring |
| **Domain clustering** | Corrections cluster around same file extensions/paths | Consistent domain-specific preference | → Rule with path matcher |
| **Reference loading** | Same file read by Claude in 5+ sessions | Key content worth promoting | → Promote points to T1/T2 |

##### Confidence & Evidence Framework

**The plugin never surfaces a proposal without meeting minimum evidence thresholds AND providing specific, verifiable evidence to the user.**

Minimum evidence thresholds (configurable):

| Artifact Type | Min. Occurrences | Min. Separate Sessions | Additional Requirement |
|---|---|---|---|
| CLAUDE.md entry | 3 corrections | 2 sessions | Same or very similar phrasing |
| Rule | 3 corrections | 2 sessions | Clustered around same file types/paths |
| Skill | 4 similar sequences | 3 sessions | ≥3 distinct steps in sequence |
| Hook | 5 manual repetitions | 3 sessions | Same command/action each time |
| Agent | 3 multi-phase workflows | 2 sessions | Distinct phases with role separation |
| Context restructuring | N/A | 3 sessions | CLAUDE.md >80% of budget OR 3+ compactions |

Evidence presentation is mandatory. Every proposal includes:
- **Specific quotes** from session transcripts (e.g., "In your March 20 session, you said: *'no, we use vitest not jest — always vitest.'*")
- **Session references** with timestamps so the user can verify
- **Frequency data** (e.g., "This correction appeared in 4 out of your last 7 sessions")
- **What would be generated** (exact content preview)
- **Where it would be placed** (file path and tier)
- **Expected benefit** (e.g., "This should eliminate ~50 tokens of correction per session")

Proposals that don't meet thresholds remain in a `candidate` state in `.claude/forge/candidates/`. They accumulate evidence over future analysis cycles and are only promoted to `pending` (user-visible) when they cross the threshold. The user never sees speculative or low-confidence suggestions.

**Output:** Confirmed proposals written to `.claude/forge/proposals/pending.json`. Unconfirmed candidates written to `.claude/forge/candidates/`. Analysis metadata (timestamp, sessions analyzed, token cost estimate) written to `.claude/forge/analysis/`.

#### Stage 3: Propose
**Trigger:** Analysis complete.
**Action:** The analyzer writes proposals to `.claude/forge/proposals/pending.json`. Each proposal includes: pattern type, confidence score (based on frequency and recency), proposed artifact type and placement tier, draft content, supporting evidence (session IDs and specific quotes), and a unique proposal ID.

Proposals are surfaced to the user via the timing windows described in Section 5 (Interaction Model). The plugin never forces proposals on the user — it stores them on disk and waits for the right moment (between-task nudge, session-start mention, or on-demand command).

**Proposal lifecycle:**
- `pending` → user hasn't seen it yet
- `presented` → surfaced to user, awaiting response
- `approved` → user accepted, ready for generation
- `modified` → user approved with changes, ready for generation
- `dismissed` → user explicitly skipped (won't re-propose unless pattern continues with 3+ new occurrences)
- `applied` → artifact generated and placed
- `archived` → artifact was applied but later removed by context auditor (stale)

#### Stage 4: Generate
**Trigger:** User approves one or more proposals.
**Engine:** The `artifact-generator` subagent. It receives the approved proposal and generates the correct artifact according to Anthropic's specifications.

**Generation rules (grounded in official docs):**

**Quality expectations vary by artifact type.** Not all artifacts are equal in complexity or how much user iteration they typically need:

- **CLAUDE.md entries** (high confidence, typically complete as-generated): Concise, imperative instructions. No verbose explanations. Follow the pattern: command/convention + brief rationale if non-obvious. Check current line count before inserting; if over budget, suggest demotion of existing entries first. *These are simple enough that the generated version is usually final.*

- **Rules** (high confidence, typically complete as-generated): One topic per file. Descriptive filename in kebab-case. Path frontmatter when scoped to specific files. Content follows the same concise style as CLAUDE.md. *Similar to CLAUDE.md entries — simple, declarative, usually ready to use.*

- **Hooks** (high confidence for common patterns): Valid JSON for the appropriate settings scope. Correct handler type selection (command for deterministic checks, prompt for semantic evaluation). Proper matcher patterns (case-sensitive, no spaces around `|`). Appropriate timeouts. *For well-known patterns (auto-format, auto-lint), the generated hook is usually production-ready. Custom hooks may need adjustment.*

- **Skills** (medium confidence, expect user iteration): Full SKILL.md with YAML frontmatter (`name` in kebab-case, `description` including trigger phrases and "Use when..." language). Progressive disclosure — frontmatter is routing, body is instructions, references/ for deep docs. *Forge generates a solid draft, but skill descriptions require testing to trigger correctly. The user should test with a few prompts and may need to refine the description or instructions. Forge flags this explicitly: "This is a draft skill. Test it with a few prompts and refine as needed."*

- **Agents** (medium confidence, expect user iteration): Markdown with frontmatter including `name`, `description`, `model` (default: sonnet), `effort`, `maxTurns`, and appropriate `tools`/`disallowedTools` restrictions. System prompt that clearly defines the agent's role and boundaries. *Agent definitions are more complex and subjective. Forge generates a reasonable starting point, but the user should review tool restrictions, model selection, and the system prompt. Forge flags this explicitly.*

- **Reference docs** (high confidence, complete as-generated): Markdown with clear headings and practical examples. Linked from the appropriate CLAUDE.md entry or rule via natural language ("for detailed conventions, see `.claude/references/X.md`"). *These are documentation, not configuration — the quality bar is "useful and accurate," not "triggers perfectly."*

#### Stage 5: Place
**Trigger:** Artifact generated and validated.
**Action:** The plugin writes files to the correct locations in the project's `.claude/` directory (or user-level `~/.claude/` for cross-project artifacts). It updates CLAUDE.md with any necessary pointers. It validates the result:
- Skills: checks frontmatter format, description length (<1024 chars), no XML tags
- Hooks: validates JSON structure, checks handler types against event support
- Rules: confirms path matchers are valid glob patterns
- CLAUDE.md: checks total line count stays within budget

**Post-placement:** The plugin stores a record of what was generated, when, and why, in `.claude/forge/history/`. This enables the context-auditor agent to track what's working and what isn't over time.

### 4.3 Context Auditor

A periodic health check that runs via `/forge:status` or automatically every N sessions. The `context-auditor` subagent:

1. **Measures context budget usage.** Scans CLAUDE.md (all levels), rules, active skills, and estimates total token consumption at session start. Flags when approaching skill description budget limits (2% of context window).

2. **Detects stale configuration.** If a rule, skill, or CLAUDE.md entry hasn't been relevant in the last N sessions, it flags it for potential removal or demotion.

3. **Detects conflicts.** If a rule contradicts a CLAUDE.md entry, or two skills have overlapping triggers, it flags the conflict.

4. **Suggests promotions/demotions.** Based on actual usage patterns (which rules loaded, which skills triggered, which references Claude read), suggests moving items between tiers.

5. **Produces a health report:**
    ```
    Context Health Report
    ─────────────────────
    CLAUDE.md (project):  87/100 lines (87% capacity)
    CLAUDE.md (user):     23/50 lines (46% capacity)
    Rules:                4 files, ~180 lines total
    Skills:               3 active, all triggered in last 7 days
    Hooks:                2 active (PostToolUse formatter, Stop linter)
    Agents:               1 active (code-reviewer)

    ⚠️  CLAUDE.md approaching capacity. 2 entries are domain-specific
        and could move to rules/frontend.md.
    ⚠️  Rule api-design.md hasn't loaded in 14 days. Consider archiving.
    ✓  All skills triggered correctly in recent sessions.
    ```

### 4.4 Key Technical Constraints

**Session transcript access:** Transcripts are stored as JSONL at `~/.claude/projects/<project-hash>/<session-id>.jsonl`. The plugin reads these via filesystem access. The transcript includes tool names, inputs, and outputs, which is essential for detecting post-action patterns and permission fatigue.

**Plugin caching:** Marketplace plugins are cached to `~/.claude/plugins/cache/` and cannot reference files outside their directory. The plugin must be self-contained. Generated artifacts are written to the *project's* `.claude/` directory, not the plugin's cache.

**Hook limitations:** Hooks are loaded at session start. Changes require `/reload-plugins` or a session restart. The plugin's SessionStart hook reads from a proposals file on disk rather than trying to modify hooks dynamically mid-session.

**Skill description budget:** Skill descriptions are loaded into context for routing. The total budget scales at 2% of the context window with a fallback of 16,000 characters. The plugin must account for its own skills' descriptions when assessing total budget.

**No direct terminal UI rendering:** Plugins cannot render custom terminal widgets. Interactive flows use Claude's conversational UI (via skill instructions that tell Claude how to present choices) or MCP Elicitation for structured forms. The plugin's UX is conversational, not widget-based.

---

## 5. Interaction Model

### 5.1 Core Principle: The Plugin Never Interrupts

The foundational design decision: **the plugin never interrupts the user mid-task.** Claude Code sessions are deep-focus work. Any interruption — even a helpful one — breaks flow and damages trust. The plugin can always analyze retroactively because session transcripts persist on disk as JSONL files at `~/.claude/projects/<project-hash>/<session-id>.jsonl`. There is no urgency. Nothing is lost if a session closes before the plugin surfaces a recommendation. The plugin has full read access to all past session transcripts for the current project, plus auto-memory and session memory files. This means every analysis can be thorough and retroactive rather than rushed and real-time.

### 5.2 Timing Windows

There are three moments where the plugin can surface information. Each has different constraints and different appropriate behaviors.

#### Window 1: Mid-Task (NEVER)
While Claude is actively working on a user's request — reading files, writing code, running commands — the plugin does nothing. No PostToolUse injections, no system messages, no nudges. The user is focused on their problem. The plugin is invisible.

#### Window 2: Between Tasks (Ambient Nudge — Opt-In)
Claude has finished a response. The user is reading, thinking, deciding what to do next. This is the one window where a gentle, optional nudge *may* appear — but only under strict conditions:

**Mechanism:** The `Stop` hook fires when Claude finishes responding. A lightweight script (no LLM call — pure filesystem check) looks for a pending proposals file on disk (`.claude/forge/proposals/pending.json`). If proposals exist AND the user hasn't been nudged this session (tracked via a session-scoped flag file), the hook returns a `systemMessage` that Claude appends to its response.

**What Claude says:**
Claude appends a brief, natural-language note at the end of its actual response. Not a formatted block. Not a separate section. Just a sentence:

> *I've noticed you've corrected me about testing conventions a few times recently. Want me to set up a rule for that so I remember automatically? (If not, just keep going — I won't ask again this session.)*

**Critical constraints:**
- **Once per session maximum.** After one nudge (whether engaged or ignored), the flag is set and no more nudges appear for the rest of the session.
- **High confidence only.** The nudge only fires if the proposal has a confidence score above the threshold (default: pattern observed 3+ times across separate sessions). No speculative suggestions.
- **Most impactful proposal only.** If there are 5 pending proposals, the nudge mentions only the single highest-impact one. The rest wait for the full review.
- **Ignorable by default.** If the user types their next prompt without responding to the nudge, the plugin treats this as "not now" and moves on. No follow-up, no reminder.
- **"Don't ask again" is permanent per pattern.** If the user dismisses a specific proposal, that exact pattern is marked as dismissed and never re-proposed unless the user resets via `/forge:status`.
- **Configurable off entirely.** The user can disable between-task nudges in plugin settings. The on-demand commands still work.

**What happens when the user says "yes":**
Claude, guided by the `/forge:optimize` skill, presents the specific proposal: what would be generated, the exact content, where it would be placed, and why. The user can approve as-is, modify, or skip. Claude generates and writes the artifact. One proposal, one interaction, back to work.

#### Window 3: Session Start (Briefing — Opt-In)
When the user begins a new session, the `SessionStart` hook checks for pending proposals that haven't been surfaced yet. If proposals exist, the hook returns a `systemMessage` that Claude weaves into its initial greeting — not as a blocking notification, but as ambient context.

**What Claude says:**
Nothing unless the user's first prompt triggers it naturally, OR as a one-line mention if the user says something open-ended like "hey" or "what should I work on":

> *By the way, Forge has 3 suggestions from your recent sessions. Run `/forge:optimize` whenever you want to review them.*

If the user's first message is task-focused ("fix the login bug"), Claude does NOT mention the plugin. The user is already working. The proposals will be there later.

**Configurable:** The user can set session-start briefings to `off` (never mention), `passive` (mention only on open-ended prompts), or `active` (always mention if proposals exist). Default: `passive`.

### 5.3 On-Demand Commands (Always Available)

These are the primary way power users interact with the plugin. Available at any time, never automatic.

- **`/forge:analyze`** — Run a full analysis of recent sessions now. Spawns the session-analyzer subagent, processes the last N transcripts, generates proposals. Shows a summary of what was found. Does NOT auto-apply anything.

- **`/forge:optimize`** — Review and apply pending proposals. Walks through each proposal conversationally (v0.1) or via MCP Elicitation form (v0.2+). User approves, modifies, or skips each one. Approved proposals are generated and placed immediately.

- **`/forge:status`** — Context health audit. Shows current configuration state, budget usage, stale artifacts, conflicts, and any pending proposals. Pure read-only, no changes.

### 5.4 Interaction Progression (v0.1 → v0.2)

#### v0.1: Conversational (AskUserQuestion Pattern)
All interaction happens through Claude's natural conversational UI. Skills instruct Claude on how to present proposals and ask for approval. When Claude needs a simple yes/no/choose, it uses its built-in AskUserQuestion tool (which renders interactive selection in the terminal). The skill instructions look like:

```markdown
Present each proposal one at a time. For each:
1. State what you observed (with a specific example from sessions)
2. State what you'd generate (artifact type, filename, approximate size)
3. Show a preview of the key content
4. Ask: approve / modify / skip

If the user says "approve", generate and place the artifact immediately.
If the user says "modify", ask what they'd like to change.
If the user says "skip", move to the next proposal.
```

This is low-cost to implement and works within existing Claude Code capabilities. The downside is that reviewing 5+ proposals conversationally is tedious.

#### v0.2: MCP Elicitation
The plugin adds an MCP server that uses MCP Elicitation to present structured forms for batch review. When the user runs `/forge:optimize` with multiple proposals, the MCP server sends an `elicitation/create` request with a JSON Schema form:

```json
{
  "message": "Forge — Review Proposals",
  "requestedSchema": {
    "type": "object",
    "properties": {
      "proposals": {
        "type": "object",
        "properties": {
          "claude_md_testing": {
            "type": "boolean",
            "description": "CLAUDE.md: 'Always use vitest, not jest' (adds 1 line)"
          },
          "rule_testing": {
            "type": "boolean",
            "description": "Rule: .claude/rules/testing.md — testing conventions (14 lines, loads for *.test.ts)"
          },
          "skill_scaffold": {
            "type": "boolean",
            "description": "Skill: /scaffold-component — React component scaffolding workflow"
          }
        }
      }
    }
  }
}
```

Claude Code renders this as an interactive form with checkboxes. The user selects what they want, submits, and the plugin generates the selected artifacts. Much faster for batch operations.

For single-proposal nudges (the between-task ambient nudge), the conversational pattern remains — a form for one yes/no question is overkill.

### 5.5 Interaction Principles

- **Never interrupt mid-task.** The user's current work always takes absolute priority.
- **Always ask before writing.** No artifact is created without explicit user approval. The plugin proposes; the user decides.
- **Show what AND why.** Every proposal includes the exact content that would be generated, where it would go, and what pattern triggered it — with specific examples pulled from session history ("In your March 20 session, you said 'no, we use vitest not jest'. This also happened on March 17 and March 14.").
- **Respect existing configuration.** The plugin never overwrites or modifies existing files. It appends to CLAUDE.md (with budget awareness), creates new rules/skills/hooks/agents, or creates new reference docs. If a proposed artifact would conflict with something that already exists, the plugin flags the conflict and asks the user to resolve it.
- **Every nudge is dismissible.** The user can always say "not now," ignore the nudge entirely, or disable nudges. Dismissed proposals don't come back unless the pattern continues and the user explicitly re-enables them.
- **Err on the side of silence.** When in doubt about whether to surface something, don't. A plugin that's quiet and helpful when asked is far better than one that's chatty and occasionally useful.
- **Frame as craft, not surveillance.** The plugin should never say "I've been monitoring your sessions" or "I noticed you always do X." Instead, frame suggestions around the *project* and *configuration*, not the person: "Your project could benefit from an auto-format hook — Prettier is configured but Claude doesn't auto-run it after edits." Or frame around the artifact: "Based on recent sessions, there's a testing conventions rule that would help Claude stay consistent." The emphasis is on what could be *built*, not what was *observed*.

### 5.6 Data the Plugin Can Access

For clarity on what powers the analysis. **Primary inputs** (★) are the most valuable signal sources — Forge reads Anthropic's own primitives first, then supplements with raw transcripts.

| Data Source | Location | Contents | Access Method |
|---|---|---|---|
| ★ Auto-memory | `~/.claude/projects/<project>/memory/` | Claude's self-written notes: build commands, patterns, preferences, debugging insights. **Pre-digested signal — the richest input.** | Read markdown files |
| ★ CLAUDE.local.md | Project root or `.claude/` | Entries from `/remember` — recurring patterns Claude already identified. **Forge audits placement, not detection.** | Read markdown file |
| ★ Current config | `.claude/CLAUDE.md`, `.claude/rules/`, `.claude/skills/`, `.claude/settings.json` | All existing configuration artifacts. **Forge audits health and completeness.** | Read project files |
| Session transcripts | `~/.claude/projects/<hash>/<id>.jsonl` | Full conversation: user prompts, Claude responses, tool calls, tool inputs/outputs, permission decisions | Read JSONL files |
| Session memory | `~/.claude/projects/<hash>/<id>/session-memory/summary.md` | Structured summaries of each session | Read markdown files |
| User-level config | `~/.claude/CLAUDE.md`, `~/.claude/settings.json` | User-wide configuration | Read user files |
| Project files | `package.json`, `.prettierrc`, `tsconfig.json`, etc. | Tech stack detection for capability gap analysis | Read project files |
| Plugin history | `.claude/forge/` | Past analyses, proposal history, dismissals, placement records | Read/write plugin state |

All data stays local. No network calls for analysis. The only token cost is the subagent LLM calls during Phase B confirmation and artifact generation.

---

## 6. Success Metrics

### Quantitative
- **Configuration coverage:** % of detectable pattern categories that have corresponding configuration artifacts after 2 weeks of use.
- **Proposal acceptance rate:** % of proposals the user approves. Target: >60%. Below 40% indicates the analyzer is generating low-quality suggestions.
- **Context budget efficiency:** Ratio of always-loaded tokens to total available context. Target: <15% at session start (including CLAUDE.md, rules, skill descriptions).
- **Correction frequency reduction:** After deploying a generated artifact, does the user stop making that correction? Measurable by comparing pre/post session transcripts.

### Qualitative
- User doesn't need to read Anthropic docs to get an effective configuration.
- Generated artifacts are indistinguishable from hand-written ones by a power user.
- The plugin feels like a knowledgeable colleague who watches how you work and quietly makes things better.

---

## 7. Resolved Decisions

1. **The plugin never interrupts mid-task.** All analysis is retroactive. Session transcripts persist on disk and can be analyzed at any time. There is no urgency to catch something before a session closes.

2. **Analysis is two-phase: cheap local scan + targeted LLM confirmation.** Phase A (Python script, zero tokens) flags candidates. Phase B (subagent, ~2-5k tokens per pattern) confirms them. This keeps total analysis cost to ~5,000-15,000 tokens per cycle — roughly 1-3 normal user prompts.

3. **Token cost is covered by subscription but is not free.** Every token the plugin uses comes from the user's 5-hour quota. The plugin must earn its token spend by saving more than it costs. All subagents use `model: sonnet` and `effort: low`.

4. **High confidence is mandatory.** Every artifact type has minimum evidence thresholds (3-5 occurrences across 2-3 sessions). Proposals always include specific, verifiable evidence from session transcripts. Low-confidence candidates accumulate silently until they cross thresholds.

5. **Interaction model: pull-first with optional ambient nudge.** On-demand commands (`/forge:analyze`, `optimize`, `status`) are the primary interface. Between-task ambient nudge (once per session max, high-confidence only) is opt-in. Session-start briefing is passive by default.

6. **MCP Elicitation is planned for v0.2.** v0.1 uses conversational UI (AskUserQuestion pattern). MCP Elicitation adds structured forms for batch proposal review in the next iteration.

7. **Reference documents are a first-class output.** The plugin manages a four-tier context hierarchy and actively promotes/demotes content between tiers based on usage patterns and budget constraints.

8. **Forge is not a memory system.** It explicitly complements auto-memory and `/remember` rather than competing with them. The differentiator is artifact-type intelligence (selecting the right kind of configuration), context architecture management (tier placement and budget), and capability discovery (suggesting infrastructure the user hasn't tried).

9. **Config audit provides cold-start value.** Phase A Mode 2 scans existing project configuration and tech stack on first run, providing actionable suggestions before any session patterns have accumulated. This addresses the cold start problem.

10. **Skills and agents are generated as drafts, not finished products.** Forge is transparent that CLAUDE.md entries and rules are typically complete as-generated, while skills and agents are starting points that benefit from user testing and iteration.

11. **Integration-first, not competition.** Forge reads auto-memory, `/remember` output, and `/init`-generated configuration as primary inputs. It builds on top of Anthropic's primitives rather than reimplementing them. If Anthropic improves detection or codification natively, Forge benefits from better inputs. The durable value — artifact-type intelligence, context architecture, capability discovery — sits above any individual primitive.

12. **Plugin name is Forge.** Slash commands: `/forge:analyze`, `/forge:optimize`, `/forge:status`. Concise, evocative of building/shaping, works well as a namespace prefix.

## 8. Open Questions

1. **Background analysis execution.** The SessionStart hook needs to spawn the analysis without blocking the session. Options: detached shell process, `background: true` agent, or deferred to idle_prompt (60s delay). Need to prototype and test which approach works reliably within Claude Code's plugin execution model.

2. **Cross-project patterns (future).** Many patterns (personal preferences, universal tool choices) are project-agnostic. User-level `~/.claude/CLAUDE.md` exists for this. How does the plugin detect that a pattern in Project A is the same as one in Project B? Deferred to Phase 4 but worth designing for.

3. **Transcript parsing robustness.** Session JSONL format is not publicly documented as a stable API. The plugin depends on its structure. Need to verify: is the format consistent across Claude Code versions? What happens when the format changes? Should the plugin include a schema validator?

4. **Plugin self-cost tracking.** Should the plugin report how many tokens it consumed during analysis? This would help the user evaluate whether the plugin is worth its token spend. Could show in `/forge:status`: "Last analysis used ~8,000 tokens. Estimated savings from generated artifacts: ~500 tokens/session × 10 sessions = ~5,000 tokens."

5. **Artifact effectiveness measurement.** After deploying a generated artifact, does the pattern actually stop? The plugin could compare correction frequency pre/post deployment. But this requires continued analysis — which has its own cost. Worth the investment?

6. **Config audit depth vs. opinionatedness.** The config audit (Phase A Mode 2) can detect missing infrastructure by scanning project files (e.g., "you have Prettier but no auto-format hook"). How opinionated should these suggestions be? Should Forge only suggest things that are near-universally beneficial (auto-format, auto-lint), or should it suggest more subjective infrastructure (code review agents, deployment skills)?

7. **Anthropic platform evolution.** As Anthropic adds features (e.g., better `/init`, auto-generated rules, smarter `/remember`), Forge's individual capabilities may overlap. The plugin should be modular enough that any single feature (correction detection, hook suggestion, etc.) can be deprecated without undermining the system. Need a periodic review process: every quarter, audit which Forge features are still differentiated vs. which have been absorbed by the platform.

---

## 9. Phased Delivery

### Phase 1: Foundation (v0.1)
- Plugin skeleton with manifest, directory structure, README
- SessionEnd hook for transcript indexing (lightweight, zero-token)
- `scripts/analyze-patterns.py` — Phase A with all three modes:
  - Mode 1: Transcript scan (correction patterns, post-action patterns)
  - Mode 2: Config audit (CLAUDE.md health, hook gaps, tech stack analysis)
  - Mode 3: Memory audit (auto-memory notes, CLAUDE.local.md placement)
- `/forge:analyze` skill (manual trigger, spawns Phase A + B)
- `/forge:status` skill (config health audit — works from first use, no sessions needed)
- Session-analyzer subagent (Phase B confirmation, sonnet, effort: low)
- Pattern detection: repeated corrections, config gaps, misplaced memory entries
- Artifact generation: CLAUDE.md entries, rule files, common hooks (auto-format, auto-lint)
- Basic context budget tracking (CLAUDE.md + CLAUDE.local.md line count)
- Conversational proposal review (AskUserQuestion pattern)
- Cold start: config audit + memory audit provide value on first run before patterns accumulate

### Phase 2: Full Artifact Coverage (v0.2)
- Skill generation with proper frontmatter and trigger phrase testing
- Hook generation (PostToolUse auto-format, Stop validation)
- Agent generation for multi-phase workflows
- Reference document generation with tier placement logic
- Tier promotion/demotion (CLAUDE.md → rules, rules → references)
- `/forge:status` context health audit
- MCP server with Elicitation for structured batch review UI
- Pattern detection: repeated prompts, multi-step sequences, post-action patterns

### Phase 3: Proactive Intelligence (v0.3)
- Background analysis on SessionStart (when unanalyzed sessions ≥ threshold)
- Between-task ambient nudge (Stop hook, once per session, high-confidence only)
- Session-start passive briefing (configurable)
- Permission fatigue detection
- Context overload detection (compaction frequency monitoring)
- Stale configuration detection and archival suggestions
- Artifact effectiveness tracking (did the correction frequency decrease?)

### Phase 4: Advanced (v1.0)
- Cross-project pattern aggregation (user-level artifacts)
- "Explain" mode — user can ask why any existing artifact was generated
- Self-cost tracking and ROI reporting in `/forge:status`
- Export/share configurations with team members
- Configurable confidence thresholds per artifact type
- Pattern candidate persistence across analysis cycles

---

*This spec is grounded in Anthropic's official documentation including: Building Effective Agents (Dec 2024), The Complete Guide to Building Skills for Claude (2026), Claude Code Docs on Memory, Skills, Hooks, Plugins, Settings, Best Practices, and Features Overview.*