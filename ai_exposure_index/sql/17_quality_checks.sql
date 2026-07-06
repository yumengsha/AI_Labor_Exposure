/* ============================================================================
   17_quality_checks.sql  -  Data-quality checks for the exposure index
   ----------------------------------------------------------------------------
   Appends rows to QUALITY.DQ_RESULTS (created by sql/05) so these checks show
   up in the same dashboard. Each check is PASS / WARN / FAIL / INFO.

   Run last, after scripts 11-16.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    QUALITY;

CREATE TABLE IF NOT EXISTS QUALITY.DQ_RESULTS (
    CHECK_ID     INTEGER,
    CHECK_NAME   VARCHAR,
    METRIC       VARCHAR,
    METRIC_VALUE NUMBER,
    STATUS       VARCHAR,
    CHECKED_AT   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

/* 20 - task scores in range [0,1] (should be 0 out-of-range; scorer + STAGING guard) */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 20, 'Task scores outside [0,1]', 'bad_score_rows',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM STAGING.STG_TASK_AI_SCORES
WHERE AI_EXPOSURE_SCORE  NOT BETWEEN 0 AND 1
   OR AUTOMATION_SCORE   NOT BETWEEN 0 AND 1
   OR AUGMENTATION_SCORE NOT BETWEEN 0 AND 1;

/* 21 - sub-scores present whenever exposure present (real mode, SCORED rows) */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 21, 'SCORED rows missing a sub-score', 'incomplete_scored_rows',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
WHERE SCORE_STATUS = 'SCORED'
  AND (AI_EXPOSURE IS NULL OR AUTOMATION IS NULL OR AUGMENTATION IS NULL);

/* 22 - exposure mode (INFO) */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 22, 'Exposure mode: ' || ANY_VALUE(EXPOSURE_MODE),
       'occupations', COUNT(*),
       IFF(ANY_VALUE(EXPOSURE_MODE)='REAL_TASK_SCORE','INFO','WARN')
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT;

/* 23 - coverage: how many occupations fell below the coverage threshold */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 23, 'Occupations with LOW_COVERAGE (real mode)', 'low_coverage_occ',
       COUNT_IF(SCORE_STATUS='LOW_COVERAGE'),
       'INFO'
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT;

/* 24 - mean importance-weight coverage among SCORED occupations */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 24, 'Mean importance-weight coverage (SCORED)', 'pct',
       ROUND(100*AVG(IMPORTANCE_WEIGHT_COVERAGE),1),
       IFF(AVG(IMPORTANCE_WEIGHT_COVERAGE) >= 0.80 OR COUNT(*)=0,'PASS','WARN')
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
WHERE SCORE_STATUS='SCORED';

/* 25 - industry axis: summed sector employment must not exceed national total.
   (private sector <= national all-ownership total; strong no-double-count guard) */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
WITH ind AS (SELECT SUM(TOTAL_EMP) AS emp FROM ANALYTICS.INDUSTRY_EXPOSURE_FACT),
     nat AS (SELECT SUM(TOT_EMP) AS emp FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT)
SELECT 25, 'Industry emp <= national emp (no double-count)', 'ratio_pct',
       ROUND(100*DIV0(ind.emp, nat.emp),1),
       IFF(ind.emp <= nat.emp, 'PASS', 'FAIL')
FROM ind, nat;

/* 26 - region axis: all three granularities present */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 26, 'Region granularities present (expect 3)', 'granularities',
       COUNT(DISTINCT GRANULARITY),
       IFF(COUNT(DISTINCT GRANULARITY)=3,'PASS','WARN')
FROM ANALYTICS.REGION_EXPOSURE_FACT;

/* 27 - state count (expect 51: 50 states + DC) */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 27, 'State areas present', 'states',
       COUNT(*),
       IFF(COUNT(*) BETWEEN 50 AND 56,'PASS','WARN')
FROM ANALYTICS.REGION_EXPOSURE_FACT
WHERE GRANULARITY='State';

/* 28 - all axis exposures within [0,1] */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 28, 'Axis exposures outside [0,1]', 'bad_axis_rows',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM ANALYTICS.VW_EXPOSURE_AXIS
WHERE AI_EXPOSURE IS NOT NULL AND AI_EXPOSURE NOT BETWEEN 0 AND 1;

/* ---- results dashboard (exposure-index checks) ---- */
SELECT CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS, CHECKED_AT
FROM QUALITY.DQ_RESULTS
WHERE CHECK_ID >= 20
ORDER BY CHECK_ID, CHECKED_AT DESC;
