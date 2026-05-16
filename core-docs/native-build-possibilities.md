# Native Build Possibilities

This document captures architectural patterns that become available when a Forge-like system is built natively into an AI coding app instead of shipped as a Claude Code plugin. It exists because a prototype called Designer-Noticed (inside the Designer app at `/Users/benyamron/dev/designer`, Phase 21.A2) explored most of these patterns before that project changed direction. The work is not lost — these are the ideas worth carrying forward whenever native integration becomes possible, either inside Claude Code itself or in another AI coding surface.

Forge today is a plugin. Plugins read what Claude Code chooses to expose (session transcripts, hook events, settings) and write through user-approved diffs. That boundary is the source of Forge's safety guarantees and the source of its limitations. The transferable Designer ideas — synthesis boundaries, content-addressed dedup, richer proposal kinds, signal events — are already covered in plan items P10-P14. This document covers what remains: the ideas that *require* owning the runtime.

Audience: future Forge contributors evaluating a native re-platform, or anyone deciding whether to build a new learning-layer feature inside an AI coding app from scratch.

---

## Why this exists

A plugin lives outside the host's event loop. It can observe what the host serializes to disk (transcripts) and what the host invokes it for (hooks), but it cannot subscribe to fine-grained events, mutate the host's UI, or run analyses inside the same process that's about to make a decision. Designer-Noticed was a clean-slate rebuild of Forge's value proposition inside a process that owns its own event store, UI, and runtime. The constraints that shaped Forge (no shared state with Claude Code, only retrospective analysis, markdown-only outputs) dissolve at that boundary.

This doc is not a recommendation to re-platform. Plugin distribution is what makes Forge usable today. It's a catalog of capability ceilings the plugin model imposes, so a future port has a reference for what to reclaim first.

---

## Event-store foundation

Designer's runtime is built on an append-only event log. Every state-changing action — a tool call accepted, a scope override granted, a cost threshold crossed, a memory note saved — is an event with a monotonic ID, timestamp, and typed payload. Findings and proposals are *also* events (`FindingRecorded`, `ProposalEmitted`, `ProposalResolved`). State at any point in time is a projection over the log.

What this unlocks:

- **Replay.** Re-run a detector across historical events to validate threshold changes against real data, no synthetic fixtures needed. Forge today validates threshold changes against `tests/fixtures/` — Designer can validate against actual user history.
- **Causal trails.** Every proposal carries `source_findings: Vec<FindingId>`; every finding carries `evidence: Vec<Anchor>` pointing to specific messages, tool calls, or file spans in the log. Explaining "why did this proposal exist" is a graph traversal, not a heuristic.
- **Time-windowed queries.** "How did approval-grant rate change in the 24h after we shipped scope rule X" is a single query. Forge has to reconstruct this from transcript JSONL re-parsing.
- **Schema evolution.** Events are versioned per type. A detector v2 can choose to ignore v1 events or re-interpret them, without losing the v1 history. Forge's `dismissed.json` is a flat structure with no versioning — schema changes require migration scripts.

What it costs: storage discipline (every event must be self-describing, no implicit context), schema governance (event types are forever once written), and the operational weight of an append-only store with rotation, compaction, and replay tooling.

A native Forge would store events in SQLite-WAL or LMDB. JSONL works but loses query speed. Designer used a custom flat-file format with B-tree indices.

---

## Native detectors that need owned-runtime signals

Six of Designer's nine detectors overlap with Forge (repeated_correction, repeated_prompt_opening, multi_step_tool_sequence, config_gap, domain_specific_in_claude_md, memory_promotion). Forge already implements equivalents. The remaining three are inaccessible to a plugin because the underlying events are never exposed:

### `approval_always_granted`

Detects when a user has approved every instance of a scope override (e.g., always allows the assistant to read `/etc/`). Suggests adjusting the approval policy so the user isn't asked.

Required signal: the host has to log every approval prompt + the user's choice. Claude Code shows approval prompts but does not persist a structured `ApprovalGranted` event a plugin can read. The closest plugin-side approximation is parsing transcript "tool_result" entries for approval markers — fragile and incomplete (denials aren't logged at all).

What a native build would do: subscribe to a `Permission::Decided { resource, decision, ts }` event stream and aggregate by `(resource_pattern, decision)` over a rolling window.

### `scope_false_positive`

Detects when a user denies a scope override and then later approves the same operation on the same path. Suggests relaxing the scope rule that produced the denial — it was a false positive.

Required signal: paired `ScopeDenied` and `ApprovalGranted` events with shared resource identifiers. Plugin-side, denials are not exposed at all. Without them, this detector cannot exist.

What a native build would do: store both events; periodic scan for denial → grant pairs within N days on the same resource; emit a `ScopeRuleRelaxation` proposal with the specific rule path and the resource that should be carved out.

### `cost_hot_streak`

Detects token-spend spikes that warrant a model-tier change or a cost cap. Native Designer emits `CostRecorded { tokens_in, tokens_out, model, ts }` per LLM invocation.

Required signal: per-invocation token counts attributed to the user (not the plugin's own consumption). Forge can approximate this from transcript token estimates but with substantial error and a one-cycle lag (estimates come from the previous session).

What a native build would do: streaming windowed sum over `CostRecorded`; threshold on tokens-per-hour or cost-per-task; propose model downgrade or cost cap, gated by safety review.

### `compaction_pressure`

Designer-specific. Detects when a workspace's event log is approaching its compaction threshold and surfaces a hint to clean up. Has no plugin analog because compaction is an internal runtime concern.

---

## Boundary-driven synthesis

Designer's most important architectural choice: detection and synthesis are decoupled in time, not in code.

Detectors run on every relevant event. They are cheap, deterministic, and produce findings into the event log immediately. Synthesis — turning findings into user-facing proposals — runs only on `AppCore::synthesize_pending(project_id)`, which is called at exactly two triggers:

1. **Track completion** — when a bounded shipping unit (a task, a build, a PR) finishes. Debounced 30 seconds to absorb the detector burst that typically follows a state transition.
2. **First workspace-home view of the day** — per project, per UTC date. The user opens the dashboard for the first time today; Designer batches everything that's accumulated and shows it once.

This is the pattern P10 imports into Forge. But the native version can do more than the plugin port:

- **Debouncing.** A plugin's only natural trigger is SessionStart (one-shot). A native runtime can debounce: "schedule synthesis 30s after the last finding arrived, cancel if another arrives in the meantime."
- **Synthesis as a real boundary.** Designer's synthesis call is *the* gate. Findings exist before synthesis runs but they don't trigger any UI. A plugin port has to fake this through "compute proposals always, suppress notification sometimes" because there's no separate place to put the unsurfaced findings.
- **Cancellation.** A native synthesize call can be interrupted if the user starts a new task; the plugin has no notion of "user is now busy with something else."

The conceptual win is the same in both worlds: detection is cheap and frequent; surfacing is rare and intentional. The plumbing differs.

---

## Native UI affordances

Forge's UI is the Claude Code terminal: a startup notification line, markdown proposal cards rendered through a skill, and a chat-based approval flow. Designer's UI is React (`packages/app/src/components/DesignerNoticed/`) with:

- **Workspace-home live feed** — top 8 proposals by severity, opened state per proposal, in-line thumbs-up/down with no chat turn consumed.
- **Settings → Activity → "Designer noticed" archive** — read-only history of every finding ever recorded, filterable, with full evidence trails. Forge has nothing equivalent; `applied.json` and `dismissed.json` are not surfaced anywhere.
- **Snooze with explicit duration picker** — Forge proposals can be skipped, but "remind me in a week" requires another UI affordance the terminal can't provide.
- **Dismiss-reason capture as structured choices** — Designer presents the reason picker as a native dropdown, not a freeform text prompt. The structured data flows back into Phase B retuning without LLM parsing.
- **Per-proposal acceptance/dismiss telemetry visible at a glance** — "this category has 70% acceptance" shown next to category headers, calibrating the user's trust before they even open the proposal.

A native port can also support things like:

- **Diff previews rendered inline**, with the same editor component the user uses elsewhere — no markdown approximation.
- **Hover-to-explain** on evidence anchors, jumping into the source event without leaving the proposal view.
- **Multi-proposal selection and batch actions** ("approve all in this category", with per-item confirmation).
- **Notification fan-out** to the system tray when a high-severity proposal appears outside session boundaries, not just at session start.

These are not nice-to-haves; they fundamentally change what the user does. A terminal notification trains the user to glance and continue. A persistent feed trains the user to come back when they want context. The two designs select for different rates of engagement.

---

## Safety-gated proposal kinds

Some Designer proposal kinds are too risky to apply with a single keystroke and require interaction patterns the terminal can't safely support:

- **`ScopeRuleRelaxation`** — must re-type the resource path to confirm. Prevents accidental approval from a typo'd keypress.
- **`AutoApproveHook`** — must dry-run on a representative event before the rule is committed. Designer renders a "would have decided X on Y" preview.
- **`RemovalCandidate`** (also in P12) — must type the filename to confirm. Forge's P12 port implements this in markdown by asking the user to type the filename in chat; the native version is a confirmation modal with the actual file contents visible.

The terminal can ask for type-to-confirm input but cannot enforce "you must read this preview first" or "this action is rate-limited to one per minute". A native runtime can. Designer's gating is enforced in the React component, not in the proposal data model — the proposal carries a `safety_class` and the renderer chooses the interaction.

---

## Local models

Designer's detector trait accepts `local_ops: Option<&dyn LocalOps>` from day one. In Phase A this is always `None`; in Phase B a small local model (4-8B parameters, on-device) becomes available for:

- **Synthesis humanization** — turn "detector emitted 5 findings with shared digest X" into a one-sentence title that reads like a human wrote it. Today Forge uses the Claude API for this, charged against the user's quota.
- **Drafted diffs** — for `Hook`, `Rule`, `ClaudeMdEntry` kinds, the local model writes the proposed content. The user reviews; if they accept, no Claude API call was made. If they want changes, the larger model is invoked.
- **Cheap re-classification** — when the user dismisses a proposal with reason "not relevant", the local model can re-classify similar findings as low-confidence without a network call.
- **Privacy** — local synthesis means proposal content (which can include evidence quoted from the user's session) never leaves the device. Designer uses this to gate certain proposal kinds behind a "local synthesis only" flag.

What it costs natively: bundling a local model (~4-8GB), the inference runtime (llama.cpp or similar), GPU/Metal acceleration coordination, model lifecycle management (updates, fallback when GPU unavailable). Significant operational weight; only worth it if the per-user LLM cost reduction is meaningful at the runtime's scale.

The plugin version is constrained to the Claude API. The user's quota is the only model budget Forge has access to, which is why the LLM quality gate (P0b) is the only LLM step in Forge today and why P13 signals are recorded for *future* local retuning that has no host to run in.

---

## Context optimizer integration

Designer's Phase 5 (separate from the learning layer) is a context optimizer: a system that observes which files Claude actually needed during a task and adjusts the prompt structure for future tasks accordingly. Designer-Noticed feeds it: when a `RuleExtraction` proposal is accepted, the context optimizer is informed that a new scoped rule exists and updates its loading strategy automatically.

In a plugin world this round-trip doesn't exist. Forge writes a scoped rule with `paths` frontmatter; Claude Code's rule loader picks it up next session. There's no feedback to Forge about whether the rule actually changed Claude's loading behavior. P9 (session health analysis) is Forge's attempt to approximate this by detecting frequently-read files, but it operates blind to whether scoped rules it already produced are reducing re-reads.

A native build closes the loop: detector → proposal → applied artifact → observed prompt-structure change → measured reduction in re-reads → confidence update for the detector. Every step except the last exists in Forge today; the last requires runtime instrumentation only the host can provide.

---

## Persistence and replay

Designer's findings and proposals are immutable. Status (`Open`, `Accepted`, `Dismissed`, `Snoozed`) is *derived* from the latest `ProposalResolved` event per `proposal_id` (last-write-wins). The proposal record itself never changes after `ProposalEmitted`.

Forge does the opposite: `dismissed.json` and `applied.json` are mutable JSON dicts updated in place. This works at Forge's scale but loses three things:

- **Reversibility.** A bug that incorrectly marked proposals as dismissed corrupts the file. Designer's version: emit a corrective `ProposalResolved` event with the right status; the projection re-derives correctly. The bad data is in the log but doesn't affect current state.
- **Audit.** "When was this dismissed and why" requires Forge to add fields to the dismissed entry. In Designer it's just `SELECT * FROM events WHERE proposal_id = X ORDER BY ts`.
- **Concurrent writes.** Two Forge processes finalizing simultaneously can race on `dismissed.json`. The current `_write_json_atomic` helper handles the file write but not the read-modify-write sequence. An append-only log doesn't have this problem (each writer appends independently; the projection sorts by timestamp).

A native build standardizes on event sourcing for all interaction state. Forge's `signals.jsonl` (P13) is a small step in this direction — append-only, replayable — but only for one slice of the data.

---

## Migration thought experiment

If Forge moved native — either inside Claude Code's runtime or as a standalone AI coding surface — what stays and what changes:

**Stays (>80% reusable):**
- All Phase A analyzers (`analyze-config.py`, `analyze-transcripts.py`, `analyze-memory.py`). Pure functions over data; the data source changes, the analysis doesn't.
- Builder logic (`_build_from_*` functions in `build-proposals.py`). The proposal schema, thresholds, and dedup rules carry over.
- Validation helpers (`validate-paths.py`). Path security is the same problem in any runtime.
- Test fixtures and the synthetic profile generator. Replay-against-fixtures is even more useful in a native runtime.
- The LLM quality gate prompt (`forge/agents/session-analyzer.md`). The synthesis step's prompt doesn't change with the runtime.

**Changes (rewrite required):**
- Hooks (`hooks.json` SessionStart, SessionEnd) → event subscriptions. The trigger model is fundamentally different.
- Settings persistence (`settings.json` + `read-settings.py` / `write-settings.py`) → native config UI + typed config struct. Free-form JSON becomes structured.
- Storage layout (`.claude/forge/` + `~/.claude/forge/projects/<hash>/`) → event log + projection cache. Split between project-shared and user-personal becomes "events have project_id + workspace_id".
- Notification surface (`systemMessage`) → native UI components.
- Approval flow (markdown + AskUserQuestion) → typed proposal renderer with safety-class-aware interaction.
- Dismissal/applied tracking (`dismissed.json`, `applied.json`) → `ProposalResolved` events; status derived.

**New (no equivalent in Forge today):**
- Event log infrastructure (storage, rotation, projections, replay tooling).
- Native UI surfaces (workspace feed, settings archive, snooze modal, dry-run preview).
- Local-model integration (`LocalOps` trait, bundled model, fallback paths).
- The native detectors that need owned-runtime signals (approval_always_granted, scope_false_positive, cost_hot_streak).

**Removed:**
- Plugin manifest and version-bump rules (`forge/.claude-plugin/plugin.json` + `marketplace.json`). Native distribution uses the host's release pipeline.
- Path encoding for `~/.claude/projects/<hash>/` resolution. The runtime knows what project it's in.
- The Forge-co-installation probe (P14). Subsumed by the host's single learning layer.

The order to migrate, if it ever becomes the goal: event log first (storage + projections), then the detector trait (port builders to read from event projections instead of analyzer outputs), then the synthesis boundary and UI (the user-visible win), then the native-only detectors (the differentiator), then local models (the cost story). Each step is independently shippable inside the host; nothing has to land atomically.

---

## What's worth taking now, even without a native runtime

Even staying as a plugin, three things from the native architecture are worth importing — and are already scoped as P10-P13:

- **Synthesis boundaries** (P10): the single biggest UX improvement. Native or not, Forge benefits from separating detection from surfacing.
- **`window_digest` dedup** (P11): content-addressed identity for proposals. Trivial to add; eliminates a class of duplicate-proposal bugs.
- **First-class signal events** (P13): an append-only log of every interaction. Doesn't change behavior immediately but unlocks future threshold tuning (P8) and provides audit data.

Everything else in this document is genuinely native-only or requires infrastructure (local models, event store, native UI) that exceeds the plugin's scope. Worth knowing about, worth designing toward when adjacent work touches the relevant interfaces, but not worth building speculatively.
