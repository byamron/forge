# Scoring System Evaluation and Tuning Plan

## Problem

The correction classifier (`classify_response`) and theme clustering (`group_into_themes`)
are the core intelligence of Forge's transcript analysis. They determine whether a user
message is a correction, how strong it is, and whether corrections cluster into actionable
themes. Currently:

- The synthetic integration tests validate that the logic works on clear-cut inputs
  (explicit "don't use X, use Y" corrections with strong keyword matches).
- There is no validation against real-world transcripts, where corrections are ambiguous
  ("hmm that's not quite right", "can you try a different approach", "actually let me
  rethink this"), confirmatory messages look corrective ("no, that's perfect"), and
  conversations are much longer and noisier.
- The keyword weights (0.4 for "I told you", 0.15 for "actually") and thresholds
  (0.25 for corrective classification, 3.0/6.0 for theme confidence) were set by
  intuition, not measured against labeled data.

The risk: false positives (normal conversation classified as correction → noisy proposals)
and false negatives (real corrections missed → Forge appears to do nothing useful).

## Two-part approach

### Part 1: Labeled evaluation dataset from real transcripts

**Goal:** Build a small labeled dataset of real conversation pairs with ground-truth
classifications, then measure precision/recall of the classifier against it.

**How it works:**

1. **Extract conversation pairs from real sessions.** Write a script that reads JSONL
   transcripts and outputs conversation pairs (assistant action → user response) in a
   reviewable format. This is similar to what `build_conversation_pairs()` already does
   but outputs to a human-readable file instead of feeding into the pipeline.

2. **Manual labeling.** Review each pair and assign a ground-truth label:
   `corrective`, `confirmatory`, `new_instruction`, or `followup`. For corrective pairs,
   also assign a severity: `strong` (user is clearly frustrated or repeating themselves),
   `moderate` (clear correction but neutral tone), `mild` (subtle redirection).
   Store labels in a JSON file alongside the extracted pairs.

3. **Evaluation script.** Compare `classify_response()` output against ground truth.
   Report precision, recall, F1 for each classification. Flag specific false
   positives and false negatives for analysis.

4. **Iteration.** Adjust keyword patterns, weights, and thresholds based on the
   evaluation results. Re-run evaluation to measure improvement. The labeled dataset
   becomes a regression test — any weight change must not degrade measured accuracy.

**File structure:**
```
tests/scoring_eval/
  extract_pairs.py      — extracts pairs from real JSONL transcripts
  eval_classifier.py    — runs classifier against labeled data, reports metrics
  labeled/
    README.md           — labeling guidelines and severity definitions
    <project>_pairs.json — extracted pairs with ground-truth labels
```

**Privacy considerations:**
- Labeled data files should be gitignored (they contain real user messages).
- The evaluation script works on whatever labeled data exists locally — it doesn't
  need to be committed.
- Add `tests/scoring_eval/labeled/*.json` to `.gitignore`.
- The extraction script should sanitize/truncate messages the same way the pipeline
  does (500 char limit, control char removal).

**What to measure:**
- **Correction precision:** Of pairs classified as corrective, what % are actually
  corrections? Target: >80%. Below 60% means noisy proposals.
- **Correction recall:** Of actual corrections, what % are detected? Target: >70%.
  Below 50% means Forge misses too many patterns.
- **Strength calibration:** For detected corrections, does `correction_strength`
  correlate with labeled severity? Plot strength vs. severity bucket.
- **Confirmatory precision:** Are "looks good" / "thanks" messages correctly
  classified? False negatives here (confirmatory classified as corrective) are
  particularly bad — they generate proposals from positive feedback.

### Part 2: Capture scoring diagnostics during real /forge runs

**Goal:** When running `/forge` on real projects, capture enough diagnostic data
to understand why specific proposals were (or weren't) generated, without requiring
manual labeling.

**How it works:**

The transcript analyzer already outputs structured data (correction themes with
evidence, weighted scores, confidence levels). The gap is that this output is
consumed by the skill and discarded. We need a way to persist it for review.

1. **Scoring diagnostics file.** After each `/forge` run, the cache manager already
   saves analysis results to `~/.claude/forge/projects/<hash>/cache/transcripts.cache.json`.
   This already contains the full correction themes with evidence, scores, and confidence.
   No new persistence needed — just need a way to review it.

2. **Diagnostic review script.** A script that reads the cached transcript analysis
   and presents it in a reviewable format:
   - All detected correction themes with their weighted scores and confidence
   - The top conversation pairs that contributed to each theme (already in `evidence`)
   - Pairs that scored just below the threshold (near-misses)
   - Classification distribution across all pairs (what % corrective, confirmatory, etc.)

   This gives a quick "why did Forge propose / not propose this?" view after any run.

3. **Threshold sensitivity analysis.** The diagnostic script can also show what would
   change if thresholds were adjusted:
   - "At threshold 2.0 instead of 3.0, these 2 additional themes would surface"
   - "At threshold 4.0 instead of 3.0, this theme would be filtered out"
   This helps calibrate thresholds without blind trial-and-error.

**File structure:**
```
tests/scoring_eval/
  review_diagnostics.py  — reads cache, presents scoring diagnostics
  sensitivity.py         — threshold sensitivity analysis
```

**Integration with real-world testing workflow:**
After running `/forge` on a real project, the workflow becomes:
1. Note which proposals appeared and whether they were useful
2. Run `python3 tests/scoring_eval/review_diagnostics.py --project-root .` to see
   the full scoring picture
3. If a proposal was a false positive, find the contributing pairs and consider
   adding them to the labeled dataset as "not corrective"
4. If an expected proposal didn't appear, check near-misses to understand whether
   it's a classification gap or a threshold issue

## What NOT to build

- **Automated labeling via LLM.** Tempting but circular — we'd be using Claude to
  evaluate Claude's correction detection. The value of the labeled dataset is that
  it represents human judgment.
- **A/B testing framework.** Overkill for a single-user plugin. The labeled dataset
  + diagnostic review gives enough signal.
- **Continuous evaluation in CI.** The labeled data contains real transcripts and
  can't be committed. Evaluation runs locally as part of the tuning workflow.

## Estimated scope

**Part 1 (labeled dataset):** ~2-3 hours to build the extraction and evaluation
scripts. Labeling depends on how many pairs you review — 50-100 pairs across 2-3
projects would give meaningful signal. This is a one-time investment that compounds
as the labeled set grows.

**Part 2 (diagnostic review):** ~1-2 hours. Mostly reading from existing cache
files and formatting output. The cache structure is already well-defined.

**When to do this:** After running `/forge` on 2-3 real projects (Active Work Item 1).
You need real session data to extract pairs from. The evaluation infrastructure should
exist before making any weight or threshold changes — otherwise you're tuning blind.
