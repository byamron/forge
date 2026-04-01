#!/usr/bin/env python3
"""Compare classifier approaches against labeled data.

Runs three classifiers against labeled pairs:
  - Baseline: current classify_response() as-is
  - Approach A: expanded keyword patterns (more coverage, same architecture)
  - Approach B: lower threshold + structural signals + false positive filter

Usage:
    python3 tests/scoring_eval/compare_approaches.py tests/scoring_eval/labeled/
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Load labeled data
# ---------------------------------------------------------------------------

def load_labeled_pairs(label_dir: Path) -> List[Dict[str, Any]]:
    pairs = []
    for f in sorted(label_dir.glob("*_pairs.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for p in data.get("pairs", []):
            if p.get("label"):
                p["_source"] = f.stem
                pairs.append(p)
    return pairs


# ---------------------------------------------------------------------------
# Baseline classifier (imported from production)
# ---------------------------------------------------------------------------

def _get_baseline_classifier():
    """Import the production classify_response."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "forge" / "scripts"))
    import importlib
    mod = importlib.import_module("analyze-transcripts")
    sys.path.pop(0)
    return mod.classify_response


# ---------------------------------------------------------------------------
# Approach A: Expanded keywords, same architecture
# ---------------------------------------------------------------------------

# New patterns observed from misclassification analysis
_A_STRONG_CORRECTION = [
    (re.compile(r"\bI told you\b", re.I), 0.4),
    (re.compile(r"\bthat'?s (?:not right|wrong|incorrect)\b", re.I), 0.4),
    (re.compile(r"\bI said\b", re.I), 0.35),
    (re.compile(r"\bwe use .+ not\b", re.I), 0.35),
    (re.compile(r"\buse .+ instead\b", re.I), 0.3),
    (re.compile(r"\bdon'?t (?:use|do|add|change|modify|remove)\b", re.I), 0.3),
    (re.compile(r"\bnever (?:use|do|add)\b", re.I), 0.3),
    (re.compile(r"\bshould(?:n'?t| not) (?:be|have|use)\b", re.I), 0.3),
    # NEW: approach/direction rejection
    (re.compile(r"\bwrong approach\b", re.I), 0.4),
    (re.compile(r"\bnot the (?:right|correct) (?:way|approach)\b", re.I), 0.35),
    (re.compile(r"\bthis is the wrong\b", re.I), 0.4),
]
_A_MILD_CORRECTION = [
    (re.compile(r"^no[,.\s]", re.I), 0.2),
    (re.compile(r"\bactually[,.]", re.I), 0.15),
    (re.compile(r"\binstead[,.]?\s", re.I), 0.15),
    (re.compile(r"\bswitch to\b", re.I), 0.15),
    (re.compile(r"\bwrong\b", re.I), 0.15),
    (re.compile(r"\bthat should be\b", re.I), 0.15),
    (re.compile(r"\bthis should be\b", re.I), 0.15),
    (re.compile(r"\bnot that\b", re.I), 0.15),
    # Reversal patterns
    (re.compile(r"\bscratch that\b", re.I), 0.3),
    (re.compile(r"\bnot quite\b", re.I), 0.2),
    (re.compile(r"\bdo what you had before\b", re.I), 0.3),
    (re.compile(r"\brevert\b", re.I), 0.2),
    (re.compile(r"\bundo\b", re.I), 0.2),
    (re.compile(r"\badd .+ back\b", re.I), 0.2),
    # Frustration / dealbreaker
    (re.compile(r"\bdealbreaker\b", re.I), 0.3),
    (re.compile(r"\bnot sure why you\b", re.I), 0.1),
    (re.compile(r"\bwhy did you\b", re.I), 0.2),
    (re.compile(r"\bwhy would you\b", re.I), 0.2),
    # Factual pushback
    (re.compile(r"\bthere (?:absolutely|definitely|clearly) is\b", re.I), 0.25),
    (re.compile(r"\bwhat do you mean\b", re.I), 0.2),
    (re.compile(r"\btoo subtle\b", re.I), 0.15),
    (re.compile(r"\btoo much\b", re.I), 0.1),
    (re.compile(r"\bi (?:also )?requested?\b", re.I), 0.15),
    (re.compile(r"\breframe\b", re.I), 0.15),
    # NEW: dissatisfaction signals (from labeled data)
    (re.compile(r"\bnot (?:quite )?doing it\b", re.I), 0.25),
    (re.compile(r"\bstill (?:drawing|showing|doing)\b", re.I), 0.15),
    (re.compile(r"\bsnapping\b", re.I), 0.15),
    (re.compile(r"\bgo back to\b", re.I), 0.2),
    (re.compile(r"\bwe can'?t\b", re.I), 0.15),
    # NEW: "i want to remove/change" (correcting existing state)
    (re.compile(r"\bi want to (?:remove|change|fix|redo)\b", re.I), 0.15),
    # NEW: questioning the assistant's understanding
    (re.compile(r"\bwhat do you mean .+\?\b", re.I), 0.2),
    (re.compile(r"\bthere (?:is no|are no)\b", re.I), 0.15),
    # NEW: "X is out" / "your context is from before"
    (re.compile(r"\byour (?:context|knowledge|info)\b", re.I), 0.15),
    (re.compile(r"\bis out\b.*\blook at\b", re.I), 0.15),
]
_A_CONFIRMATORY = [
    re.compile(r"^(?:yes|yeah|yep|ok|okay|sure|perfect|great|thanks|thank you|looks? good|lgtm|nice|awesome|exactly)[.!,\s]*$", re.I),
    re.compile(r"\bthat(?:'?s| is) (?:right|correct|perfect|great|good)\b", re.I),
    re.compile(r"\bno(?:,| ).*(?:looks? good|that'?s (?:right|correct|perfect|great))", re.I),
]

_A_CONTINUE_SIGNALS = {"resume", "retry", "continue", "go ahead", "proceed"}
_A_IMPERATIVE_STARTS = {
    "fix", "add", "remove", "delete", "update", "change", "create",
    "run", "build", "merge", "push", "ship", "deploy", "scan",
    "make", "check", "review", "open", "close", "get", "set",
}


def _tokenize(text: str) -> set:
    return set(re.findall(r"\b\w+\b", text.lower()))


def classify_approach_a(
    user_text: str,
    assistant_text: str,
    assistant_tools: list,
    assistant_files: list,
) -> Tuple[str, float]:
    """Approach A: expanded keywords, same architecture."""
    text = user_text.strip()
    if not text or len(text) < 5:
        return ("followup", 0.0)

    if text.startswith("/"):
        return ("new_instruction", 0.0)

    text_lower = text.lower()

    # Skill invocations (multi-line, starts with #) → new_instruction
    # Fix: these were getting classified as followup due to word overlap
    if "\n" in text and (text.startswith("#") or text.startswith("##")):
        return ("new_instruction", 0.0)

    # Confirmatory
    for pat in _A_CONFIRMATORY:
        if pat.search(text_lower):
            return ("confirmatory", 0.0)

    # Score correction signals
    score = 0.0
    for pat, weight in _A_STRONG_CORRECTION:
        if pat.search(text_lower):
            score += weight
    for pat, weight in _A_MILD_CORRECTION:
        if pat.search(text_lower):
            score += weight

    keyword_score = min(score, 0.5)

    # Context scoring (same as baseline)
    action_ref_score = 0.0
    if assistant_tools:
        tool_names = [t.get("name", "").lower() for t in assistant_tools]
        for tn in tool_names:
            if tn and tn in text_lower:
                action_ref_score += 0.1
        for fp in assistant_files:
            fname = fp.rsplit("/", 1)[-1].lower() if "/" in fp else fp.lower()
            if fname and fname in text_lower:
                action_ref_score += 0.15

    if assistant_text:
        user_tokens = _tokenize(text)
        asst_tokens = _tokenize(assistant_text[:500])
        if user_tokens and asst_tokens:
            overlap = len(user_tokens & asst_tokens) / max(len(user_tokens), 1)
            if overlap > 0.2:
                action_ref_score += 0.1

    action_ref_score = min(action_ref_score, 0.3)

    imperative_score = 0.0
    if len(text.split()) < 20 and assistant_tools:
        imperative_score += 0.1
    if len(text.split()) < 10 and keyword_score > 0:
        imperative_score += 0.1
    imperative_score = min(imperative_score, 0.2)

    total = keyword_score + action_ref_score + imperative_score

    if total >= 0.15:
        return ("corrective", min(total, 1.0))

    # Not corrective
    words = text.split()
    word_count = len(words)

    # Continue signals
    if text_lower.strip().rstrip(".!") in _A_CONTINUE_SIGNALS:
        return ("followup", 0.0)

    if word_count <= 4:
        first_lower = words[0].lower().rstrip(",.")
        if first_lower in _A_IMPERATIVE_STARTS:
            return ("new_instruction", 0.0)
        return ("followup", 0.0)

    if text.rstrip().endswith("?") and keyword_score == 0:
        return ("followup", 0.0)

    return ("new_instruction", 0.0)


# ---------------------------------------------------------------------------
# Approach B: Lower threshold + structural signals + false positive filter
# ---------------------------------------------------------------------------

# Negative signals — these patterns strongly indicate NOT a correction
_B_NOT_CORRECTION = [
    # Skill invocations (system-injected)
    re.compile(r"^#\s", re.M),
    re.compile(r"^Base directory for this skill:", re.I),
    re.compile(r"^You are running", re.I),
    # Ship/push workflow templates
    re.compile(r"^Ship the current branch:", re.I),
    re.compile(r"update docs.*commit.*push", re.I),
    # Pure imperatives without correction context
    re.compile(r"^(?:fix|add|remove|run|build|merge|push|ship|deploy)\s+(?:all|this|these|it)\s*$", re.I),
]

# Structural signals that boost correction probability
_B_CORRECTION_STRUCTURE = [
    # Starts with negation/pushback (exclude positive openers like "this is better/great")
    (re.compile(r"^(?:no|nah|nope|that'?s not|this isn'?t|we (?:can'?t|don'?t|shouldn'?t))\b", re.I), 0.15),
    # Contains contrast markers (but, however, although, though)
    (re.compile(r"\bbut\b.*(?:should|need|want|instead|rather)", re.I), 0.1),
    # Emotional intensifiers near content words
    (re.compile(r"\b(?:absolutely|definitely|clearly|obviously)\b", re.I), 0.1),
    # "this is better, but/although" — iteration WITH continued issue (mild correction)
    # Plain "this is better" without qualifier is positive followup, not correction
    (re.compile(r"\b(?:this|that) is (?:better|closer|improved)\b.*\b(?:but|although|however|still|can we|could we)\b", re.I), 0.1),
    # "too X" pattern — dissatisfaction with degree
    (re.compile(r"\btoo (?:subtle|much|aggressive|slow|fast|big|small|long|short)\b", re.I), 0.15),
    # "not quite" / "not exactly" / "not doing it"
    (re.compile(r"\bnot (?:quite|exactly|doing|working|right)\b", re.I), 0.15),
    # "i want to remove/change this" — correcting current output
    (re.compile(r"\bi want to (?:remove|change|redo|revert|fix)\b", re.I), 0.15),
    # "go back" / "restore" / "bring back"
    (re.compile(r"\b(?:go back|restore|bring back|put .+ back)\b", re.I), 0.15),
    # Questioning the assistant's assertion
    (re.compile(r"\bwhat do you mean\b", re.I), 0.15),
    (re.compile(r"\bwhy (?:did|would|are) you\b", re.I), 0.1),
    # "there absolutely is" — factual correction (only with intensifier)
    (re.compile(r"\bthere (?:absolutely|definitely|clearly) (?:is|are|isn'?t|aren'?t)\b", re.I), 0.15),
]


def classify_approach_b(
    user_text: str,
    assistant_text: str,
    assistant_tools: list,
    assistant_files: list,
) -> Tuple[str, float]:
    """Approach B: structural signals + false positive filter."""
    text = user_text.strip()
    if not text or len(text) < 5:
        return ("followup", 0.0)

    if text.startswith("/"):
        return ("new_instruction", 0.0)

    text_lower = text.lower()

    # --- Early exits for clear non-corrections ---
    # Skill invocations
    if "\n" in text and (text.startswith("#") or text.startswith("##")):
        return ("new_instruction", 0.0)

    # False positive filter: if any NOT_CORRECTION pattern matches, skip correction check
    is_template = any(pat.search(text) for pat in _B_NOT_CORRECTION)

    # Confirmatory
    for pat in _A_CONFIRMATORY:
        if pat.search(text_lower):
            return ("confirmatory", 0.0)

    # Continue signals
    _continue = {"resume", "retry", "continue", "go ahead", "proceed"}
    if text_lower.strip().rstrip(".!") in _continue:
        return ("followup", 0.0)

    # --- Correction scoring ---
    score = 0.0

    if not is_template:
        # Keyword scoring (reuse Approach A's expanded patterns)
        for pat, weight in _A_STRONG_CORRECTION:
            if pat.search(text_lower):
                score += weight
        for pat, weight in _A_MILD_CORRECTION:
            if pat.search(text_lower):
                score += weight
        keyword_score = min(score, 0.5)

        # Structural signals (Approach B's addition)
        structural_score = 0.0
        for pat, weight in _B_CORRECTION_STRUCTURE:
            if pat.search(text):
                structural_score += weight
        structural_score = min(structural_score, 0.3)

        # Context scoring
        action_ref_score = 0.0
        if assistant_tools:
            tool_names = [t.get("name", "").lower() for t in assistant_tools]
            for tn in tool_names:
                if tn and tn in text_lower:
                    action_ref_score += 0.1
            for fp in assistant_files:
                fname = fp.rsplit("/", 1)[-1].lower() if "/" in fp else fp.lower()
                if fname and fname in text_lower:
                    action_ref_score += 0.15

        if assistant_text:
            user_tokens = _tokenize(text)
            asst_tokens = _tokenize(assistant_text[:500])
            if user_tokens and asst_tokens:
                overlap = len(user_tokens & asst_tokens) / max(len(user_tokens), 1)
                if overlap > 0.2:
                    action_ref_score += 0.1

        action_ref_score = min(action_ref_score, 0.3)

        imperative_score = 0.0
        if len(text.split()) < 20 and assistant_tools:
            imperative_score += 0.1
        if len(text.split()) < 10 and keyword_score > 0:
            imperative_score += 0.1
        imperative_score = min(imperative_score, 0.2)

        total = keyword_score + structural_score + action_ref_score + imperative_score

        # Lower threshold (0.10 vs 0.15) — structural signals help compensate
        if total >= 0.10:
            return ("corrective", min(total, 1.0))

    # --- Not corrective ---
    words = text.split()
    word_count = len(words)

    if word_count <= 4:
        first_lower = words[0].lower().rstrip(",.")
        if first_lower in _A_IMPERATIVE_STARTS:
            return ("new_instruction", 0.0)
        return ("followup", 0.0)

    if text.rstrip().endswith("?") and score == 0:
        return ("followup", 0.0)

    return ("new_instruction", 0.0)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(
    pairs: List[Dict[str, Any]],
    classifier_fn,
    name: str,
) -> Dict[str, Any]:
    """Run classifier against labeled pairs and compute metrics."""
    classes = ["corrective", "confirmatory", "new_instruction", "followup"]
    tp = {c: 0 for c in classes}
    fp = {c: 0 for c in classes}
    fn = {c: 0 for c in classes}
    correct = 0
    total = len(pairs)
    misclass = []

    for p in pairs:
        true_label = p["label"]
        # Normalize tools: labeled data stores tool names as strings,
        # but the classifier expects dicts with {"name": ...}
        raw_tools = p.get("assistant_tools", [])
        tools = [{"name": t} if isinstance(t, str) else t for t in raw_tools]
        pred_label, pred_strength = classifier_fn(
            p["user_text"],
            p.get("assistant_text", ""),
            tools,
            p.get("assistant_files", []),
        )

        if pred_label == true_label:
            correct += 1
            tp[true_label] += 1
        else:
            fp[pred_label] += 1
            fn[true_label] += 1
            misclass.append({
                "id": f"{p.get('_source', '?')}:{p['id']}",
                "true": true_label,
                "pred": pred_label,
                "severity": p.get("severity", ""),
                "text": p["user_text"][:80],
            })

    metrics = {}
    for c in classes:
        prec = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) > 0 else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        support = tp[c] + fn[c]
        metrics[c] = {
            "precision": prec, "recall": rec, "f1": f1, "support": support,
            "tp": tp[c], "fp": fp[c], "fn": fn[c],
        }

    return {
        "name": name,
        "accuracy": correct / total if total > 0 else 0.0,
        "total": total,
        "correct": correct,
        "metrics": metrics,
        "misclassifications": misclass,
    }


def print_comparison(results: List[Dict[str, Any]]) -> None:
    """Print side-by-side comparison of approaches."""
    print("=" * 80)
    print("CLASSIFIER COMPARISON")
    print("=" * 80)
    print()

    # Summary table
    print(f"{'Metric':<30}", end="")
    for r in results:
        print(f"  {r['name']:>15}", end="")
    print()
    print("-" * (30 + 17 * len(results)))

    print(f"{'Overall accuracy':<30}", end="")
    for r in results:
        print(f"  {r['accuracy']:>14.1%}", end="")
    print()

    for cls in ["corrective", "confirmatory", "new_instruction", "followup"]:
        print()
        print(f"  {cls}")
        for metric_name in ["precision", "recall", "f1"]:
            print(f"    {metric_name:<26}", end="")
            for r in results:
                val = r["metrics"][cls][metric_name]
                print(f"  {val:>14.1%}", end="")
            print()
        print(f"    {'support':<26}", end="")
        for r in results:
            print(f"  {r['metrics'][cls]['support']:>15}", end="")
        print()

    # Correction-specific summary
    print()
    print("=" * 80)
    print("CORRECTION DETECTION (the metric that matters)")
    print("=" * 80)
    print()
    print(f"{'Metric':<30}", end="")
    for r in results:
        print(f"  {r['name']:>15}", end="")
    print()
    print("-" * (30 + 17 * len(results)))
    print(f"{'Precision (target >80%)':<30}", end="")
    for r in results:
        v = r["metrics"]["corrective"]["precision"]
        marker = " ✓" if v >= 0.8 else " ✗"
        print(f"  {v:>12.1%}{marker}", end="")
    print()
    print(f"{'Recall (target >70%)':<30}", end="")
    for r in results:
        v = r["metrics"]["corrective"]["recall"]
        marker = " ✓" if v >= 0.7 else " ✗"
        print(f"  {v:>12.1%}{marker}", end="")
    print()
    print(f"{'F1':<30}", end="")
    for r in results:
        print(f"  {r['metrics']['corrective']['f1']:>14.3f}", end="")
    print()

    # Show what each approach fixes/breaks vs baseline
    if len(results) >= 2:
        baseline_miss = {m["id"] for m in results[0]["misclassifications"]}
        for r in results[1:]:
            current_miss = {m["id"] for m in r["misclassifications"]}
            fixed = baseline_miss - current_miss
            broken = current_miss - baseline_miss
            print(f"\n--- {r['name']} vs Baseline ---")
            if fixed:
                print(f"  Fixed ({len(fixed)}):")
                for m in r["misclassifications"] + results[0]["misclassifications"]:
                    if m["id"] in fixed:
                        sev = f" [{m['severity']}]" if m.get("severity") else ""
                        print(f"    ✓ {m['id']}{sev} ({m['true']}→was {m['pred']}): {m['text']}")
                        fixed.discard(m["id"])
            if broken:
                print(f"  Regressed ({len(broken)}):")
                for m in r["misclassifications"]:
                    if m["id"] in broken:
                        sev = f" [{m['severity']}]" if m.get("severity") else ""
                        print(f"    ✗ {m['id']}{sev} ({m['true']}→now {m['pred']}): {m['text']}")


# ---------------------------------------------------------------------------
# Approach C: Hybrid — A's keywords + B's structural boost + FP filter
# ---------------------------------------------------------------------------

def classify_approach_c(
    user_text: str,
    assistant_text: str,
    assistant_tools: list,
    assistant_files: list,
) -> Tuple[str, float]:
    """Approach C: A's expanded keywords + B's structural signals + FP filter.

    Key differences from A:
    - Adds structural correction signals (negation starts, contrast, iteration)
    - Uses B's false positive filter for templates/skills
    - Threshold stays at 0.15 (not lowered to 0.10)
    """
    text = user_text.strip()
    if not text or len(text) < 5:
        return ("followup", 0.0)

    if text.startswith("/"):
        return ("new_instruction", 0.0)

    text_lower = text.lower()

    # Skill invocations
    if "\n" in text and (text.startswith("#") or text.startswith("##")):
        return ("new_instruction", 0.0)

    # False positive filter from B
    is_template = any(pat.search(text) for pat in _B_NOT_CORRECTION)

    # Confirmatory
    for pat in _A_CONFIRMATORY:
        if pat.search(text_lower):
            return ("confirmatory", 0.0)

    # Continue signals
    _continue = {"resume", "retry", "continue", "go ahead", "proceed"}
    if text_lower.strip().rstrip(".!") in _continue:
        return ("followup", 0.0)

    # --- FP filter: "yes/great/good - but <instruction>" is not a correction ---
    # It's a confirmatory opener followed by a new instruction or followup
    _CONFIRM_THEN_PIVOT = re.compile(
        r"^(?:yes|yeah|yep|great|good|nice|perfect|ok|okay)\s*[-—–,]\s*(?:but|and|now|let'?s|we)\b",
        re.I,
    )
    confirm_pivot = bool(_CONFIRM_THEN_PIVOT.match(text))

    # --- Correction scoring ---
    score = 0.0
    if not is_template:
        # A's expanded keywords
        for pat, weight in _A_STRONG_CORRECTION:
            if pat.search(text_lower):
                score += weight
        for pat, weight in _A_MILD_CORRECTION:
            if pat.search(text_lower):
                score += weight
        keyword_score = min(score, 0.5)

        # B's structural signals (capped lower — supplementary, not primary)
        structural_score = 0.0
        for pat, weight in _B_CORRECTION_STRUCTURE:
            if pat.search(text):
                structural_score += weight
        structural_score = min(structural_score, 0.2)

        # Context scoring
        action_ref_score = 0.0
        if assistant_tools:
            tool_names = [t.get("name", "").lower() for t in assistant_tools]
            for tn in tool_names:
                if tn and tn in text_lower:
                    action_ref_score += 0.1
            for fp in assistant_files:
                fname = fp.rsplit("/", 1)[-1].lower() if "/" in fp else fp.lower()
                if fname and fname in text_lower:
                    action_ref_score += 0.15

        if assistant_text:
            user_tokens = _tokenize(text)
            asst_tokens = _tokenize(assistant_text[:500])
            if user_tokens and asst_tokens:
                overlap = len(user_tokens & asst_tokens) / max(len(user_tokens), 1)
                if overlap > 0.2:
                    action_ref_score += 0.1

        action_ref_score = min(action_ref_score, 0.3)

        imperative_score = 0.0
        if len(text.split()) < 20 and assistant_tools:
            imperative_score += 0.1
        if len(text.split()) < 10 and keyword_score > 0:
            imperative_score += 0.1
        imperative_score = min(imperative_score, 0.2)

        total = keyword_score + structural_score + action_ref_score + imperative_score

        # If message opens with confirmatory language then pivots,
        # require stronger signal to classify as corrective
        threshold = 0.15
        if confirm_pivot:
            threshold = 0.40

        # Questions with only structural signals (no keywords) are likely
        # followups, not corrections — require at least some keyword signal
        if text.rstrip().endswith("?") and keyword_score == 0:
            threshold = 0.30

        if total >= threshold:
            return ("corrective", min(total, 1.0))

    # --- Not corrective ---
    words = text.split()
    word_count = len(words)

    if word_count <= 4:
        first_lower = words[0].lower().rstrip(",.")
        if first_lower in _A_IMPERATIVE_STARTS:
            return ("new_instruction", 0.0)
        return ("followup", 0.0)

    if text.rstrip().endswith("?") and score == 0:
        return ("followup", 0.0)

    return ("new_instruction", 0.0)


def main():
    parser = argparse.ArgumentParser(description="Compare classifier approaches")
    parser.add_argument("label_dir", type=str, help="Directory with labeled JSON files")
    args = parser.parse_args()

    label_dir = Path(args.label_dir)
    pairs = load_labeled_pairs(label_dir)
    if not pairs:
        print("No labeled pairs found", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(pairs)} labeled pairs\n")

    baseline_fn = _get_baseline_classifier()

    results = [
        evaluate(pairs, baseline_fn, "Baseline"),
        evaluate(pairs, classify_approach_a, "A: Keywords+"),
        evaluate(pairs, classify_approach_b, "B: Structural"),
        evaluate(pairs, classify_approach_c, "C: Hybrid"),
    ]

    print_comparison(results)


if __name__ == "__main__":
    main()
