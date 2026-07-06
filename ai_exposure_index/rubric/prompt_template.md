---
prompt_version: v1
updated: 2026-07-03
pairs_with_rubric: v1
---

# Prompt template for task AI-exposure scoring

The scorer builds each request from these pieces. The **rubric** (rubric.md) is sent
as the cached system prompt (stable across all tasks → prompt-cache friendly). The
**per-task block** below is the user turn. Placeholders in `{{...}}` are filled by
`score_tasks.py`.

## System prompt

```
{{RUBRIC_MARKDOWN}}
```

(The full contents of rubric.md, sent once and cached. Its version travels with the
output as RUBRIC_VERSION / RUBRIC_HASH.)

## User message (one per task)

```
Score this single task for AI exposure, using the rubric.

OCCUPATION
  O*NET-SOC code: {{ONET_SOC_CODE}}
  Title: {{OCCUPATION_TITLE}}
  Description: {{OCCUPATION_DESCRIPTION}}

TASK
  Task ID: {{TASK_ID}}
  Type: {{TASK_TYPE}}            (Core = central to the occupation; Supplemental = secondary)
  Importance to the occupation: {{IMPORTANCE_RAW}} on a 1-5 scale
  Statement: {{TASK_STATEMENT}}

Judge the task as it is actually performed in THIS occupation. Return the three
independent scores (ai_exposure_score, automation_score, augmentation_score), a
confidence, and a one-sentence rationale.
```

## Output contract

The model is constrained (structured outputs / `messages.parse`) to return exactly:

```json
{
  "ai_exposure_score": 0.0,
  "automation_score": 0.0,
  "augmentation_score": 0.0,
  "confidence": 0.0,
  "rationale": "one sentence, <= 240 chars"
}
```

All four numeric fields are floats in [0.0, 1.0]. The scorer attaches provenance
(TASK_ID, ONET_SOC_CODE, SCORING_RUN_ID, RUBRIC_VERSION, RUBRIC_HASH, PROMPT_VERSION,
MODEL_ID, SCORED_AT) around this object — the model only produces the JSON above.

## Notes for the scorer implementation

- Importance is passed as **raw 1-5** (matches the occupation-level weighting).
- Occupation description can be long; send it in full (do not truncate) — it is the
  context that disambiguates the task.
- A task whose SOC has no row in Occupation Data.txt still scores, with occupation
  title/description left blank and CONFIDENCE expected to be lower.
