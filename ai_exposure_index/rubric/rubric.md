---
rubric_version: v2
updated: 2026-07-05
scale: 0.0-1.0
model_intended: claude-opus-4-8
changelog: "v2 - calibrated against human annotation. Added a scoring-scale
  section (physical-task floor ~0.2, high-knowledge ceiling ~0.8, mixed default
  0.4-0.5) and worked boundary cases for the middle band."
---

# Task AI Exposure Scoring Rubric

## Scoring scale (READ FIRST — calibrated to human annotation)

Use the **full** definitions below, but keep these calibration anchors in mind so
scores land on a consistent scale:

- **Physical-task floor ≈ 0.2, not 0.** A task that is fundamentally physical,
  manual, or in-person is still rarely a true 0 — almost every real task has a
  thin digital edge AI can touch (looking up a spec, logging what was done,
  sequencing the work). Reserve 0.0–0.1 for the purest bodily acts with no
  information component at all. Most physical tasks land around **0.2**.
- **High-knowledge ceiling ≈ 0.8.** Predominantly cognitive/analytical/language
  tasks that still involve human judgment, accountability, or context land around
  **0.7–0.8** — not 0.9+. Reserve **0.9–1.0** for near-pure information
  transformation AI already does end to end (transcription, translation,
  straightforward data entry, boilerplate drafting).
- **Mixed default ≈ 0.4–0.5.** Most real tasks blend a physical/interpersonal
  core with a cognitive shell (a nurse who assesses AND charts; a mechanic who
  diagnoses AND turns wrenches). These land in the **0.4–0.5** middle band. When a
  task has both a hands-on part and a documentation/analysis part, this is home.

These anchors apply to AI_EXPOSURE. Automation and augmentation use their own
definitions but the same "physical floor / knowledge ceiling / mixed middle"
intuition keeps them on scale.

---
# Task AI Exposure Scoring Rubric (definitions)

You are scoring a **single work task** performed within a **specific occupation** for
its exposure to current-generation AI (large language models, vision models, code
generation, agentic tool use, and the software/robotics they can drive today and in
the near term — not speculative future AGI).

You output **three independent scores in [0.0, 1.0]** plus a **confidence** and a
one-sentence **rationale**. The three scores measure *different things* and must be
judged separately — do not derive one from another.

> **Critical framing:** High exposure does **not** mean the worker will lose their
> job. Exposure measures how much AI can *touch* the task. Whether that becomes
> automation (replacement) or augmentation (assistance) is captured separately, and
> employment outcomes depend on economics, regulation, and firm choices far beyond
> this task. Score the task, not the career.

---

## The task is scored *in the context of its occupation*

The same sentence ("schedule appointments", "prepare reports") can be routine in one
occupation and high-stakes in another. Use the provided occupation title and
description to judge what the task actually involves *here* — the physical setting,
the stakes, the judgment required, who the output goes to.

---

## Dimension 1 — AI_EXPOSURE_SCORE (overall)

**Definition:** the degree to which current AI can meaningfully perform, accelerate,
or transform this task — regardless of whether the end result is replacement or
assistance. This is the broad "how much does AI touch this task" measure.

A task is highly exposed when its core work is **digital, language-, data-, image-,
or code-based**, has **observable inputs and outputs**, and does **not** intrinsically
require physical presence, manual dexterity, in-person human trust, or real-time
bodily action.

| Score | Anchor | Example task / occupation |
|-------|--------|---------------------------|
| 0.0–0.1 | Essentially no information component — a pure bodily/manual act. Rare; use sparingly. | "Restrain and comfort a frightened animal during examination" (Veterinary Technician) |
| 0.2 | **Physical-task floor.** Core work is physical/manual/in-person; AI touches only a thin edge (log it, look up a spec, sequence it). | "Wash, peel, and cut foods" (Food Prep Worker); "Install drywall and tape seams" (Drywall Installer); "Hold rivets while riveters form heads" (Iron Worker) |
| 0.3–0.4 | Low-mixed. Mostly physical/interpersonal, but a real documentation/lookup sub-step AI can do. | "Take patient vital signs and record them" (Nursing Assistant) — recording is exposed, the taking is not |
| 0.4–0.5 | **Mixed default (most tasks).** A genuine blend: a hands-on or interpersonal core PLUS a cognitive/documentation shell AI can meaningfully help with. | "Diagnose equipment faults from readings and decide repairs" (Industrial Mechanic); "Inspect and document evidence with photo equipment" (Forensic Tech) |
| 0.6 | Moderately-high. Substantial analytical/language content; a modest physical or judgment part remains. | "Maintain student attendance, grade, and records" (Teacher) — data work, but embedded in a classroom role |
| 0.7–0.8 | **High-knowledge ceiling.** Predominantly digital/language/analytical with human judgment or accountability; AI does most of it under oversight. | "Draft routine correspondence and summarize documents" (Legal Secretary); "Write and debug standard application code" (Software Developer) |
| 0.9–1.0 | Near-pure information transformation AI already does end to end. Reserve for these. | "Transcribe audio recordings into text" (Medical Transcriptionist); "Translate written documents" (Translator) |

## Dimension 2 — AUTOMATION_SCORE

**Definition:** the likelihood that AI can perform this task **in place of the human**
— the human is removed from the loop for this task. Judge *replacement*, not
*assistance*.

Score high when the task has clear, checkable success criteria, tolerates occasional
error or has cheap error-correction, and does not require accountability, licensure,
physical action, or human relationship to be the point.

| Score | Anchor |
|-------|--------|
| 0.0–0.2 | AI cannot replace the human — physical, licensed-accountability, high-stakes-judgment, or relationship-defining work. |
| 0.3–0.4 | Small routine sub-parts could run unattended; the task as a whole still needs the human. |
| 0.5–0.6 | Roughly half could be handed off to AI with spot-checking; the rest needs a person. |
| 0.7–0.8 | Most of the task could run with light human review/approval. |
| 0.9–1.0 | The task can be fully executed by AI with negligible human involvement. |

## Dimension 3 — AUGMENTATION_SCORE

**Definition:** the likelihood that AI **assists a human** doing this task — making
them faster, more accurate, or more capable **while the human stays in the loop** and
remains responsible. Judge *assistance*, not *replacement*.

Score high when AI can draft, suggest, retrieve, check, or accelerate, but a human
must still decide, verify, act physically, or take accountability.

| Score | Anchor |
|-------|--------|
| 0.0–0.2 | AI offers little useful help; the task is physical/interpersonal with no digital leverage point. |
| 0.3–0.4 | AI provides minor support (reference lookup, reminders). |
| 0.5–0.6 | AI meaningfully speeds or improves part of the task; human clearly still leads. |
| 0.7–0.8 | AI is a strong copilot for most of the task; human directs and verifies. |
| 0.9–1.0 | AI can do nearly all the heavy lifting; the human's role is direction, judgment, and sign-off. |

### Automation vs. Augmentation — disambiguation

These are **not** opposites and **not** required to sum to anything. A task can be
high on both (AI could do it alone *and* is a great copilot), high on one and low on
the other, or low on both.

- **High automation, low augmentation:** "Sort incoming emails into folders by rule."
  AI just does it; there's little human-in-the-loop value to add.
- **Low automation, high augmentation:** "Develop a legal argument for a novel case."
  A lawyer must own it (accountability, licensure), but AI dramatically accelerates
  research and drafting.
- **High on both:** "Write a first-draft marketing blog post." AI can produce it
  alone, and also serves as a strong copilot for a human writer.
- **Low on both:** "Physically administer anesthesia and monitor the patient."
  Neither replacement nor digital assistance meaningfully applies to the core act.

If you find yourself scoring augmentation as `1 − automation`, stop and re-judge —
that is the most common error.

---

## Worked boundary cases (calibration — the 0.3–0.6 middle band)

These are the cases where scoring drifts most. Anchor to them.

| Task (occupation) | Exposure | Why |
|---|---|---|
| "Wash, peel, and cut foods" (Food Prep) | **0.2** | Pure manual act; the only AI edge is a recipe/quantity lookup. Physical floor, not 0. |
| "Remove damaged tile, brick, mortar; clean surfaces" (Brickmason Helper) | **0.2** | Manual demolition/cleaning; thin edge only. |
| "Portray and interpret roles using speech and gesture" (Actor) | **0.2** | Live embodied performance; AI cannot perform the act itself. Physical/creative floor. |
| "Inventory stock to determine type and condition" (Costume Attendant) | **0.3–0.4** | Physical handling, but the inventory *record* is a real digital sub-step. |
| "Maintain production or time records" (Printing Press Operator) | **0.4–0.5** | The record-keeping is automatable, but it is a small ancillary part of a hands-on press-operating job — judge the task *as embedded in that role*, not as standalone data entry. |
| "Maintain student attendance, grades, records" (Teacher) | **0.5–0.6** | Genuine data work AI helps with, but tied to classroom judgment and privacy. Mid, not high. |
| "Diagnose equipment faults from readings; decide repairs" (Mechanic) | **0.5** | Analytical diagnosis (AI helps) + physical repair (it can't). Textbook mixed middle. |
| "Use photo/video equipment to document evidence" (Forensic Tech) | **0.4–0.5** | Physical scene work + documentation; chain-of-custody accountability caps it. |

**Rule of thumb for "maintain/keep records" tasks:** if the record-keeping is a
*standalone clerical job* (e.g. a records clerk), score high (0.7+). If it is an
*ancillary duty embedded in a hands-on or front-line role* (press operator,
teacher, technician), score the mixed middle (0.4–0.6) — the task lives inside a
job the AI cannot otherwise do.

---

## CONFIDENCE (0.0–1.0)

Your confidence in these scores given the information provided.

| Score | Meaning |
|-------|---------|
| 0.8–1.0 | Task is clearly described and unambiguous; scores are well-grounded. |
| 0.5–0.7 | Task is somewhat vague or its occupational context leaves room for interpretation. |
| 0.0–0.4 | Task statement is ambiguous, could mean very different things, or you lack context to judge. |

Lower confidence does **not** change the scores — it flags them for human review.

---

## RATIONALE

One sentence (≤ 240 chars): the single most important reason for the scores, naming
the deciding factor (e.g. "Physical patient contact caps exposure despite the
digital charting component."). No restating the scores as numbers.

---

## Scoring discipline

- Judge the **task as actually performed in this occupation**, not the occupation
  overall and not the task in the abstract.
- Score what current/near-term AI can do, not speculative future capability.
- The three scores are independent — compute each on its own definition.
- Do not let job desirability, wages, or "should AI do this" ethics affect the score
  — this is a capability measurement, not a recommendation.
- When genuinely unsure, score your best estimate and lower CONFIDENCE rather than
  defaulting to 0.5.
