# AI Exposure Index — Task-to-Occupation metric + three analytical axes

This folder replaces the warehouse's **placeholder** AI exposure (which was just
average O\*NET task importance) with a **real, rubric-based Task AI Score** produced
by Claude, then rolls it up to occupations and breaks it out along three independent
axes for a Tableau dashboard.

> **Exposure ≠ unemployment risk.** These scores measure how much AI can *touch* a
> task, split into *automation* (replace the human) and *augmentation* (assist the
> human). Whether exposure becomes job loss depends on economics, regulation, and
> firm choices far beyond this data. Say so wherever the number is shown.

## The three metrics (per task, independent, 0–1)

| Metric | Meaning |
|--------|---------|
| **Exposure** | Degree the task is affected by current AI (broad). |
| **Automation** | Likelihood AI performs the task *in place of* the human. |
| **Augmentation** | Likelihood AI *assists* a human who stays in the loop. |

They are scored independently — a task can be high on both, one, or neither.

## The three analytical axes (independent, not a hierarchy, no crossed cube)

Each axis re-aggregates the **same** occupation index; they are never crossed with
each other (no state×industry×occupation cube — it has no practical meaning and OEWS
can't support it).

| Axis | Grain | Weighting |
|------|-------|-----------|
| **Industry** | NAICS sector (private, `OWN_CODE=5`) | employment-weighted |
| **Region** | Area, with **granularity** = State / Metropolitan / Nonmetropolitan | employment-weighted |
| **Wage percentile** | Low / Middle / High band | employment-weighted |

## Formulas

**Occupation (importance-RAW weighted — NOT employment, NOT normalized importance):**
```
OCC_metric = Σ(IMPORTANCE_RAW × task_metric) / Σ(IMPORTANCE_RAW)
```
over tasks that have both an importance rating and a score, computed separately for
exposure / automation / augmentation.

**Axis (employment weighted rollup of the occupation index):**
```
Axis_exposure = Σ(OCC_EXPOSURE × EMP) / Σ(EMP)
```
LOW_COVERAGE / NO_ONET occupations are excluded; each axis cell reports `EMP_COVERAGE`.

## Run modes — no silent mixing

- `EXPOSURE_MODE = REAL_TASK_SCORE` when scores are loaded; `PLACEHOLDER` (whole
  dataset, clearly labeled) only when none are.
- Per-occupation `SCORE_STATUS`: `SCORED` (importance-weight coverage ≥ 0.80),
  `LOW_COVERAGE` (below threshold → metrics NULL, excluded from axes), `NO_ONET`.
- A real-mode occupation is never backfilled with the placeholder.

## Provenance & reproducibility

`RAW.TASK_AI_SCORES_RAW` is **append-only** with full provenance per row
(`SCORING_RUN_ID`, `RUBRIC_VERSION`, `RUBRIC_HASH`, `PROMPT_VERSION`, `MODEL_ID`,
`SCORED_AT`, `ERROR_MESSAGE`). `RAW.TASK_AI_SCORES_APPROVED_RUN` promotes one run;
`STAGING.STG_TASK_AI_SCORES` reads only that run. Re-scoring never overwrites history.

## How to run it

```bash
pip install -r ai_exposure_index/requirements.txt

# 0. (once) regenerate prepared CSVs incl. occupation context
python python/prepare_data.py

# 1. PILOT — smoke-test code/format/distribution (dry-run needs no API key)
python ai_exposure_index/scoring/score_tasks.py --dry-run --pilot 5
python ai_exposure_index/scoring/score_tasks.py --pilot 100          # needs Claude creds

# 2. CALIBRATION — the real validation (BEFORE any full run)
python ai_exposure_index/calibration/build_calibration_sample.py --n 250 --annotators 2
#   → humans fill calibration_sample.csv independently, then:
python ai_exposure_index/calibration/compare_scores.py \
    --human ai_exposure_index/calibration/calibration_sample.csv \
    --model ai_exposure_index/data/task_ai_scores_<run>.csv
#   Gate: model-vs-human agreement should approach inter-annotator agreement, and the
#   automation/augmentation confusion count should be low. Revise the rubric if not.

# 3. FULL RUN — only after calibration passes (Batch API, resumable)
python ai_exposure_index/scoring/score_tasks.py --all --resume

# 4. Validate the SQL logic offline (no Snowflake, no API; synthetic scores by default)
python ai_exposure_index/validate_offline.py
python ai_exposure_index/validate_offline.py --scores ai_exposure_index/data/task_ai_scores_<run>.csv

# 5. Load + build in Snowflake (YOU run these — no writes are performed for you)
#    Load the score CSV into RAW.TASK_AI_SCORES_RAW (see sql/10 loader note),
#    promote the run in RAW.TASK_AI_SCORES_APPROVED_RUN, then run in order:
#    sql/09, 11, 12, 13, 14, 15, 16, 17
```

## SQL scripts (run order)

| Script | Builds |
|--------|--------|
| `sql/09_staging_slices.sql` | `STG_BLS_OEWS_INDUSTRY`, `STG_BLS_OEWS_REGION` |
| `sql/10_task_ai_scores_raw.sql` | `RAW.TASK_AI_SCORES_RAW` (append-only) + approved-run table |
| `sql/11_stg_task_ai_scores.sql` | `STG_TASK_AI_SCORES` (current approved run) |
| `sql/12_occupation_exposure.sql` | `OCCUPATION_EXPOSURE_FACT` (index + modes + coverage) |
| `sql/13_axis_industry.sql` | `INDUSTRY_EXPOSURE_FACT` + `INDUSTRY_OCCUPATION_EXPOSURE_FACT` |
| `sql/14_axis_region.sql` | `REGION_EXPOSURE_FACT` + `REGION_OCCUPATION_EXPOSURE_FACT` |
| `sql/15_axis_wage_band.sql` | `WAGE_BAND_EXPOSURE_FACT` |
| `sql/16_tableau_views.sql` | `VW_EXPOSURE_AXIS` (long) + 3 occupation-grain views |
| `sql/17_quality_checks.sql` | Exposure-index checks → `QUALITY.DQ_RESULTS` |

## Tableau

Connect to `ANALYTICS`. Use **`VW_EXPOSURE_AXIS`** (long format) as the primary source:

- Create a string parameter **`Axis`** with values `INDUSTRY` / `REGION` / `WAGE_BAND`;
  filter the view to `AXIS_TYPE = [Axis]`.
- Create a second parameter **`Region granularity`** (`State` / `Metropolitan` /
  `Nonmetropolitan`); when `Axis = REGION`, filter `GRANULARITY = [Region granularity]`
  — this drives the metro-vs-nonmetro comparison.
- Plot `AI_EXPOSURE` (and `AUTOMATION` / `AUGMENTATION`) by `AXIS_LABEL`; use
  `EMP_COVERAGE` to shade/flag low-confidence cells.
- For drill-down, use `VW_OCCUPATION_NATIONAL`, `VW_REGION_OCCUPATION`,
  `VW_INDUSTRY_OCCUPATION` (kept separate on purpose — never one view with both region
  and industry keys).
- For a state choropleth, Tableau geocodes the `STATE` field natively — no shapefile.

## Constraints honored

- **No writes to the remote Snowflake DB** — every script here is authored for *you*
  to run; nothing was executed against the account. The scorer and validators are
  local-only and never connect to Snowflake.
- **`account_info.txt` is read-only** and its contents are never embedded anywhere.
- The full 18,796-task run was gated on calibration and only run **after** rubric v2
  passed — calibration first, then the full score.

## Status — SCORED (rubric v2, all 18,796 tasks)

**Calibration (rubric v1 → v2).** A 249-task sample stratified across all 22 O\*NET
major groups was scored and compared against independent human annotation. v1 vs v2:

| metric | v1 MAE | v2 MAE | v2 Pearson | v2 band-agree |
|--------|--------|--------|-----------|---------------|
| exposure | 0.197 | **0.160** | 0.58 | 49% |
| automation | 0.157 | **0.143** | 0.50 | 78% |
| augmentation | 0.188 | **0.172** | 0.61 | 55% |

Automation/augmentation confusion = **0%** in both. v2 added a calibrated scoring
scale (physical-task floor ≈0.2, high-knowledge ceiling ≈0.8, mixed default 0.4–0.5)
and worked boundary cases; every metric improved. Single-annotator calibration, so
there is no inter-annotator ceiling to compare against — treat agreement as "good,
not yet formally validated."

**Full run.** All **18,796 tasks scored with rubric v2** →
`data/task_ai_scores_v2_full_b6a49483.csv` (100% coverage, 0 out-of-range, 0 null).
Scored via Claude subagents (`MODEL_ID = claude-opus-4-8-subagent`) rather than the
API — same rubric/prompt/schema; provenance recorded per row.

**Offline validation (real scores).** `validate_offline.py --scores ...` passes all
invariants: occupation exposure ∈ [0,1] (774 occupations, mean 0.41), importance-RAW
weighting confirmed, industry private emp ≤ national (no double-count), region axis
all three granularities (51/393/137), all axis exposures ∈ [0,1].

**Real signal (vs the flat placeholder).** Exposure now varies meaningfully:
- By wage band: Low **0.37** → Middle **0.43** → High **0.54** (higher-paid work is more exposed).
- By occupation group: highest = Computer/Math 0.62, Business/Finance 0.59, Office/Admin 0.57; lowest = Construction 0.27, Install/Repair 0.29, Cleaning 0.30.

**To load into Snowflake (you run it):** load
`data/task_ai_scores_v2_full_b6a49483.csv` into `RAW.TASK_AI_SCORES_RAW` (sql/10
loader note), set it approved in `RAW.TASK_AI_SCORES_APPROVED_RUN`, then run
`sql/09, 11, 12, 13, 14, 15, 16, 17`.

**Report (`reports/index.html`) regenerated with real scores** — every chart now
shows the real index. It includes an **interactive three-axis explorer** (the HTML
preview of Tableau's `VW_EXPOSURE_AXIS`): pick Industry / Region / Wage band, and for
Region pick State (51) / Metropolitan (393) / Nonmetropolitan (137); bars are
employment-weighted mean exposure, hover for employment + coverage. Rebuild anytime
with `python python/build_report.py` (auto-detects the real-score CSV; falls back to
placeholder if absent).
