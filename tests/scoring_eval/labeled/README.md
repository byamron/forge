# Labeling Guidelines

Ground-truth labels for evaluating the correction classifier.

## Labels

Each conversation pair gets one classification label:

| Label | Definition | Examples |
|-------|-----------|----------|
| `corrective` | User is correcting, redirecting, or overriding the assistant's action | "no, use vitest not jest", "that's wrong, we use tabs", "switch to pnpm" |
| `confirmatory` | User approves or acknowledges the assistant's action | "looks good", "thanks", "perfect", "yes, that's right" |
| `new_instruction` | User gives a new task unrelated to the assistant's last action | "now add a login page", "can you refactor the API?", "/test" |
| `followup` | User continues the conversation without correcting or starting fresh | "what about the edge case?", "can you also handle nulls?", "explain that" |

## Severity (corrective only)

| Severity | Definition |
|----------|-----------|
| `strong` | User is frustrated, repeating themselves, or explicitly says "I told you" / "I said" | "I TOLD you to use vitest", "again, don't use npm" |
| `moderate` | Clear correction, neutral tone | "actually use vitest instead", "switch that to tabs" |
| `mild` | Subtle redirection, could be interpreted as preference | "hmm, let's try a different approach", "can you use the other one?" |

## Ambiguous cases

- "no, that's perfect" → `confirmatory` (the "no" negates an implied question, not the action)
- "can you try a different approach" → `corrective:mild` (redirecting, even if polite)
- "hmm that's not quite right" → `corrective:moderate`
- "ok but change X" → `corrective:mild` (partial approval with correction)
- "let's do it differently" after seeing output → `corrective:mild`
- "use X" with no prior context → `new_instruction` (no action to correct)

## File format

```json
{
  "project": "project-name",
  "extraction_date": "2026-03-31",
  "pairs": [
    {
      "id": "pair_001",
      "session_id": "abc123",
      "turn_index": 3,
      "user_text": "no, use vitest not jest",
      "assistant_text": "I'll set up jest for testing...",
      "assistant_tools": ["Write"],
      "assistant_files": ["jest.config.ts"],
      "label": "corrective",
      "severity": "moderate",
      "notes": ""
    }
  ]
}
```

## Privacy

These files contain real user messages and are gitignored. Do not commit them.
