/* ============================================================================
   12_occupation_exposure.sql
   ----------------------------------------------------------------------------
   Purpose : The corrected occupation-level AI exposure index. Replaces the
             placeholder as the source the axes read from.

   Formulas (see plan / rubric):
     Occupation metric = Σ(IMPORTANCE_RAW × task_score) / Σ(IMPORTANCE_RAW)
       - weighted by RAW importance (1-5), NOT normalized (norm zeroes IM=1 tasks)
       - over tasks that have BOTH an importance rating AND a real score
       - computed independently for exposure, automation, augmentation
     Employment weighting is NOT used here (only occupation -> axis, scripts 13-15).

   Coverage (both reported; importance-weight is primary):
     TASK_COUNT_COVERAGE        = scored+rated tasks / rated tasks
     IMPORTANCE_WEIGHT_COVERAGE = Σ importance(scored) / Σ importance(all rated)

   Run modes (dataset-global; no per-occupation mixing):
     EXPOSURE_MODE = 'REAL_TASK_SCORE' if any approved/loaded scores exist,
                     else 'PLACEHOLDER' (whole table uses the importance proxy).
     Per-occupation SCORE_STATUS in real mode:
       SCORED        - IMPORTANCE_WEIGHT_COVERAGE >= threshold (default 0.80)
       LOW_COVERAGE  - below threshold -> metrics NULL, excluded from axes
       NO_ONET       - occupation has no O*NET tasks at all

   Run after 11_stg_task_ai_scores.sql (and sql/03, sql/04 for staging + dims).
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    ANALYTICS;

/* ----------------------------------------------------------------------------
   Coverage threshold as a one-row config table (documented + easy to change).
   ---------------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS ANALYTICS.EXPOSURE_CONFIG (
    MIN_IMPORTANCE_WEIGHT_COVERAGE FLOAT
);
-- seed once (idempotent-ish: only insert if empty)
INSERT INTO ANALYTICS.EXPOSURE_CONFIG (MIN_IMPORTANCE_WEIGHT_COVERAGE)
SELECT 0.80
WHERE NOT EXISTS (SELECT 1 FROM ANALYTICS.EXPOSURE_CONFIG);

/* ----------------------------------------------------------------------------
   Occupation exposure fact.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE ANALYTICS.OCCUPATION_EXPOSURE_FACT AS
WITH cfg AS (
    SELECT MIN_IMPORTANCE_WEIGHT_COVERAGE AS min_cov FROM ANALYTICS.EXPOSURE_CONFIG
    QUALIFY ROW_NUMBER() OVER (ORDER BY MIN_IMPORTANCE_WEIGHT_COVERAGE) = 1
),
mode AS (
    -- dataset-global: are there ANY real scores loaded?
    SELECT IFF(EXISTS (SELECT 1 FROM STAGING.STG_TASK_AI_SCORES),
               'REAL_TASK_SCORE', 'PLACEHOLDER') AS exposure_mode
),
base AS (   -- national detailed occupations (the fact grain)
    SELECT OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, A_MEAN, A_MEDIAN
    FROM STAGING.STG_BLS_OEWS_NATIONAL
),
-- task-level: importance (raw) joined to the real score, per (occupation, task)
tasks AS (
    SELECT
        t.OCC_CODE,
        t.TASK_ID,
        i.IMPORTANCE_RAW,
        s.AI_EXPOSURE_SCORE,
        s.AUTOMATION_SCORE,
        s.AUGMENTATION_SCORE,
        s.CONFIDENCE
    FROM STAGING.STG_ONET_TASK_STATEMENTS t
    JOIN STAGING.STG_ONET_TASK_IMPORTANCE i
         ON t.TASK_ID = i.TASK_ID AND t.ONET_SOC_CODE = i.ONET_SOC_CODE
    LEFT JOIN STAGING.STG_TASK_AI_SCORES s
         ON t.TASK_ID = s.TASK_ID AND t.ONET_SOC_CODE = s.ONET_SOC_CODE
),
occ_real AS (   -- importance-RAW-weighted rollup over rated tasks
    SELECT
        OCC_CODE,
        COUNT(*)                                              AS rated_task_count,
        COUNT(AI_EXPOSURE_SCORE)                              AS scored_task_count,
        SUM(IMPORTANCE_RAW)                                   AS imp_total,
        SUM(IFF(AI_EXPOSURE_SCORE IS NOT NULL, IMPORTANCE_RAW, 0)) AS imp_scored,
        -- weighted means over scored tasks (numerator uses only scored tasks;
        -- denominator is the scored-task importance so the mean is well-formed)
        SUM(IMPORTANCE_RAW * AI_EXPOSURE_SCORE)
            / NULLIF(SUM(IFF(AI_EXPOSURE_SCORE IS NOT NULL, IMPORTANCE_RAW, 0)), 0) AS occ_exposure,
        SUM(IMPORTANCE_RAW * AUTOMATION_SCORE)
            / NULLIF(SUM(IFF(AUTOMATION_SCORE IS NOT NULL, IMPORTANCE_RAW, 0)), 0)  AS occ_automation,
        SUM(IMPORTANCE_RAW * AUGMENTATION_SCORE)
            / NULLIF(SUM(IFF(AUGMENTATION_SCORE IS NOT NULL, IMPORTANCE_RAW, 0)), 0) AS occ_augmentation,
        AVG(CONFIDENCE)                                       AS occ_confidence
    FROM tasks
    GROUP BY OCC_CODE
),
assembled AS (
    SELECT
        b.OCC_CODE, b.OCC_TITLE, b.O_GROUP,
        b.TOT_EMP, b.A_MEAN, b.A_MEDIAN,
        (SELECT exposure_mode FROM mode)                      AS EXPOSURE_MODE,
        r.rated_task_count, r.scored_task_count,
        -- coverage measures
        DIV0(r.scored_task_count, r.rated_task_count)         AS TASK_COUNT_COVERAGE,
        DIV0(r.imp_scored, r.imp_total)                       AS IMPORTANCE_WEIGHT_COVERAGE,
        -- placeholder proxy (avg normalized importance) for PLACEHOLDER mode / display
        p.AI_EXPOSURE                                         AS PLACEHOLDER_EXPOSURE,
        r.occ_exposure, r.occ_automation, r.occ_augmentation, r.occ_confidence
    FROM base b
    LEFT JOIN occ_real r ON b.OCC_CODE = r.OCC_CODE
    LEFT JOIN ANALYTICS.AI_EXPOSURE_PLACEHOLDER p ON b.OCC_CODE = p.OCC_CODE
),
scored AS (
    SELECT
        a.*,
        cfg.min_cov,
        -- status
        CASE
            WHEN a.rated_task_count IS NULL OR a.rated_task_count = 0 THEN 'NO_ONET'
            WHEN a.EXPOSURE_MODE = 'REAL_TASK_SCORE'
                 AND a.IMPORTANCE_WEIGHT_COVERAGE < cfg.min_cov      THEN 'LOW_COVERAGE'
            ELSE 'SCORED'
        END AS SCORE_STATUS
    FROM assembled a, cfg
),
final AS (
    SELECT
        OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, A_MEAN, A_MEDIAN,
        EXPOSURE_MODE, SCORE_STATUS,
        rated_task_count, scored_task_count,
        ROUND(TASK_COUNT_COVERAGE, 4)        AS TASK_COUNT_COVERAGE,
        ROUND(IMPORTANCE_WEIGHT_COVERAGE, 4) AS IMPORTANCE_WEIGHT_COVERAGE,
        -- the headline metrics: real weighted score when SCORED in real mode;
        -- placeholder proxy in PLACEHOLDER mode; NULL when LOW_COVERAGE/NO_ONET in real mode
        CASE
            WHEN EXPOSURE_MODE = 'PLACEHOLDER' THEN PLACEHOLDER_EXPOSURE
            WHEN SCORE_STATUS = 'SCORED'       THEN ROUND(occ_exposure, 4)
            ELSE NULL
        END AS AI_EXPOSURE,
        CASE WHEN EXPOSURE_MODE = 'REAL_TASK_SCORE' AND SCORE_STATUS = 'SCORED'
             THEN ROUND(occ_automation, 4) END   AS AUTOMATION,
        CASE WHEN EXPOSURE_MODE = 'REAL_TASK_SCORE' AND SCORE_STATUS = 'SCORED'
             THEN ROUND(occ_augmentation, 4) END AS AUGMENTATION,
        CASE WHEN EXPOSURE_MODE = 'REAL_TASK_SCORE' AND SCORE_STATUS = 'SCORED'
             THEN ROUND(occ_confidence, 4) END   AS EXPOSURE_CONFIDENCE,
        ROUND(PLACEHOLDER_EXPOSURE, 4)            AS PLACEHOLDER_EXPOSURE
    FROM scored
),
ranked AS (
    SELECT
        *,
        PERCENT_RANK() OVER (ORDER BY A_MEDIAN)                        AS WAGE_PERCENTILE,
        RANK() OVER (ORDER BY AI_EXPOSURE DESC NULLS LAST)             AS EXPOSURE_RANK,
        AI_EXPOSURE * TOT_EMP                                          AS WEIGHTED_EXPOSURE
    FROM final
    WHERE A_MEDIAN IS NOT NULL
)
SELECT
    r.OCC_CODE, r.OCC_TITLE, r.O_GROUP,
    r.TOT_EMP, r.A_MEAN, r.A_MEDIAN,
    r.WAGE_PERCENTILE, wb.WAGE_BAND,
    r.EXPOSURE_MODE, r.SCORE_STATUS,
    r.AI_EXPOSURE, r.AUTOMATION, r.AUGMENTATION, r.EXPOSURE_CONFIDENCE,
    r.WEIGHTED_EXPOSURE, r.EXPOSURE_RANK,
    r.rated_task_count, r.scored_task_count,
    r.TASK_COUNT_COVERAGE, r.IMPORTANCE_WEIGHT_COVERAGE,
    r.PLACEHOLDER_EXPOSURE
FROM ranked r
LEFT JOIN ANALYTICS.DIM_WAGE_BAND wb
       ON r.WAGE_PERCENTILE >= wb.WAGE_PERCENTILE_MIN
      AND r.WAGE_PERCENTILE <  wb.WAGE_PERCENTILE_MAX;

/* ---- quick look: mode + status breakdown, top real-scored occupations ---- */
SELECT EXPOSURE_MODE, SCORE_STATUS, COUNT(*) AS occupations
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
GROUP BY EXPOSURE_MODE, SCORE_STATUS
ORDER BY EXPOSURE_MODE, SCORE_STATUS;
