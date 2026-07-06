/* ============================================================================
   11_stg_task_ai_scores.sql
   ----------------------------------------------------------------------------
   Purpose : STAGING view over the append-only RAW score table. Selects the
             single "current approved" scoring run, casts to numbers, range-
             checks, standardizes the OCC_CODE, and drops error rows.

   Run after 10_task_ai_scores_raw.sql (and after a run has been loaded +
   promoted in RAW.TASK_AI_SCORES_APPROVED_RUN).
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    STAGING;

/* ----------------------------------------------------------------------------
   Current approved run's clean, typed scores. One row per (TASK_ID, SOC).
   * Filters to the approved SCORING_RUN_ID (falls back to the newest run by
     LOADED_AT if the approved table is empty, so the pipeline still runs in
     dev before a run is formally promoted).
   * TRY_TO_DOUBLE + range guard: any score outside [0,1] becomes NULL and is
     excluded (defence in depth; the scorer already constrains 0..1).
   * Drops rows with a non-empty ERROR_MESSAGE.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE VIEW STAGING.STG_TASK_AI_SCORES AS
WITH approved AS (
    SELECT SCORING_RUN_ID
    FROM RAW.TASK_AI_SCORES_APPROVED_RUN
    QUALIFY ROW_NUMBER() OVER (ORDER BY APPROVED_AT DESC) = 1
),
chosen_run AS (
    -- approved run if present, else the most recently loaded run
    SELECT COALESCE(
        (SELECT SCORING_RUN_ID FROM approved),
        (SELECT SCORING_RUN_ID FROM RAW.TASK_AI_SCORES_RAW
         QUALIFY ROW_NUMBER() OVER (ORDER BY LOADED_AT DESC) = 1)
    ) AS SCORING_RUN_ID
),
typed AS (
    SELECT
        TRIM(r.TASK_ID)                              AS TASK_ID,
        TRIM(r.ONET_SOC_CODE)                        AS ONET_SOC_CODE,
        LEFT(TRIM(r.ONET_SOC_CODE), 7)               AS OCC_CODE,   -- 11-1011.00 -> 11-1011
        TRY_TO_DOUBLE(r.AI_EXPOSURE_SCORE)           AS AI_EXPOSURE_SCORE,
        TRY_TO_DOUBLE(r.AUTOMATION_SCORE)            AS AUTOMATION_SCORE,
        TRY_TO_DOUBLE(r.AUGMENTATION_SCORE)          AS AUGMENTATION_SCORE,
        TRY_TO_DOUBLE(r.CONFIDENCE)                  AS CONFIDENCE,
        r.RATIONALE,
        COALESCE(NULLIF(TRIM(r.REVIEW_STATUS), ''), 'unreviewed') AS REVIEW_STATUS,
        r.SCORING_RUN_ID, r.RUBRIC_VERSION, r.RUBRIC_HASH,
        r.PROMPT_VERSION, r.MODEL_ID
    FROM RAW.TASK_AI_SCORES_RAW r
    JOIN chosen_run c ON r.SCORING_RUN_ID = c.SCORING_RUN_ID
    WHERE (r.ERROR_MESSAGE IS NULL OR TRIM(r.ERROR_MESSAGE) = '')
      AND TRY_TO_NUMBER(TRIM(r.TASK_ID)) IS NOT NULL
)
SELECT *
FROM typed
WHERE AI_EXPOSURE_SCORE  BETWEEN 0 AND 1
  AND AUTOMATION_SCORE   BETWEEN 0 AND 1
  AND AUGMENTATION_SCORE BETWEEN 0 AND 1
-- one score per (task, soc): keep the row (defensive against accidental dup loads)
QUALIFY ROW_NUMBER() OVER (PARTITION BY TASK_ID, ONET_SOC_CODE ORDER BY OCC_CODE) = 1;

/* ---- preview ---- */
SELECT COUNT(*) AS scored_tasks,
       COUNT(DISTINCT OCC_CODE) AS occupations,
       ROUND(AVG(AI_EXPOSURE_SCORE), 3) AS avg_exposure,
       ROUND(AVG(CONFIDENCE), 3)        AS avg_confidence
FROM STAGING.STG_TASK_AI_SCORES;
