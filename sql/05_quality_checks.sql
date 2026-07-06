/* ============================================================================
   05_quality_checks.sql
   ----------------------------------------------------------------------------
   Purpose : Data-quality checks in the QUALITY schema.

   Pattern : Every check INSERTs one summary row into QUALITY.DQ_RESULTS with a
             PASS / WARN / FAIL status, so you get a single results dashboard.
             Individual diagnostic SELECTs follow each check (commented as
             "-- inspect:") for drilling into offending rows.

   Run after 04_create_analytics_tables.sql. Safe to re-run (results table is
   truncated at the top of each run).

   Checks implemented (matches the project spec):
     1  Missing OCC_CODE in BLS staging table
     2  Missing OCC_CODE after O*NET standardization
     3  Join completeness between BLS and O*NET
     4  Duplicate records in dimension tables
     5  Missing / invalid TOT_EMP
     6  Missing / invalid A_MEDIAN
     7  Exposure scores outside the expected 0..1 range
     8  Record counts before and after joins
     9  Occupations in BLS that do not match O*NET
     10 O*NET occupations that do not match BLS
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    QUALITY;

/* ---- Results table -------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS QUALITY.DQ_RESULTS (
    CHECK_ID     INTEGER,
    CHECK_NAME   VARCHAR,
    METRIC       VARCHAR,     -- what we counted
    METRIC_VALUE NUMBER,      -- the number
    STATUS       VARCHAR,     -- PASS / WARN / FAIL
    CHECKED_AT   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- fresh run each time
TRUNCATE TABLE QUALITY.DQ_RESULTS;

/* ============================================================================
   CHECK 1 - Missing OCC_CODE in BLS staging table
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 1, 'Missing OCC_CODE in BLS staging', 'null_or_blank_occ_code',
       COUNT(*),
       IFF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM STAGING.STG_BLS_OEWS
WHERE OCC_CODE IS NULL OR TRIM(OCC_CODE) = '';
-- inspect: SELECT * FROM STAGING.STG_BLS_OEWS WHERE OCC_CODE IS NULL OR TRIM(OCC_CODE)='';

/* ============================================================================
   CHECK 2 - Missing OCC_CODE after O*NET standardization
   (LEFT(...,7) should never be null/short for a valid SOC code)
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 2, 'Missing/short OCC_CODE after O*NET standardization',
       'bad_standardized_occ_code',
       COUNT(*),
       IFF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM STAGING.STG_ONET_TASK_STATEMENTS
WHERE OCC_CODE IS NULL OR LENGTH(OCC_CODE) <> 7;
-- inspect: SELECT ONET_SOC_CODE, OCC_CODE FROM STAGING.STG_ONET_TASK_STATEMENTS WHERE LENGTH(OCC_CODE)<>7;

/* ============================================================================
   CHECK 3 - Join completeness between BLS and O*NET
   What share of BLS national occupations have at least one O*NET task?
   WARN if < 80% match (expected: not every BLS SOC exists in O*NET).
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
WITH bls AS (SELECT DISTINCT OCC_CODE FROM STAGING.STG_BLS_OEWS_NATIONAL),
     matched AS (
        SELECT COUNT(*) AS n
        FROM bls b
        WHERE EXISTS (SELECT 1 FROM STAGING.STG_ONET_TASKS o WHERE o.OCC_CODE = b.OCC_CODE)
     ),
     total AS (SELECT COUNT(*) AS n FROM bls)
SELECT 3, 'BLS->O*NET join completeness (% matched)',
       'pct_bls_occ_with_onet_tasks',
       ROUND(100.0 * matched.n / NULLIF(total.n, 0), 1),
       IFF(100.0 * matched.n / NULLIF(total.n,0) >= 80, 'PASS', 'WARN')
FROM matched, total;

/* ============================================================================
   CHECK 4 - Duplicate records in dimension tables
   DIM_OCCUPATION (OCC_CODE), DIM_INDUSTRY (NAICS), DIM_REGION (AREA) should be
   unique on their key. DIM_TASK key is (TASK_ID, ONET_SOC_CODE).
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 4, 'Duplicate keys in DIM_OCCUPATION', 'dup_occ_code',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM (SELECT OCC_CODE FROM ANALYTICS.DIM_OCCUPATION GROUP BY OCC_CODE HAVING COUNT(*)>1);

INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 4, 'Duplicate keys in DIM_INDUSTRY', 'dup_naics',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM (SELECT NAICS FROM ANALYTICS.DIM_INDUSTRY GROUP BY NAICS HAVING COUNT(*)>1);

INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 4, 'Duplicate keys in DIM_REGION', 'dup_area',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM (SELECT AREA FROM ANALYTICS.DIM_REGION GROUP BY AREA HAVING COUNT(*)>1);

INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 4, 'Duplicate keys in DIM_TASK', 'dup_task_key',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM (SELECT TASK_ID, ONET_SOC_CODE FROM ANALYTICS.DIM_TASK
      GROUP BY TASK_ID, ONET_SOC_CODE HAVING COUNT(*)>1);

/* ============================================================================
   CHECK 5 - Missing / invalid TOT_EMP in the fact table
   (null or <= 0 employment is invalid for a detailed occupation)
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 5, 'Missing/invalid TOT_EMP in fact', 'bad_tot_emp',
       COUNT(*), IFF(COUNT(*)=0,'PASS','WARN')
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
WHERE TOT_EMP IS NULL OR TOT_EMP <= 0;

/* ============================================================================
   CHECK 6 - Missing / invalid A_MEDIAN in the fact table
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 6, 'Missing/invalid A_MEDIAN in fact', 'bad_a_median',
       COUNT(*), IFF(COUNT(*)=0,'PASS','WARN')
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
WHERE A_MEDIAN IS NULL OR A_MEDIAN <= 0;

/* ============================================================================
   CHECK 7 - Exposure scores outside the expected 0..1 range
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 7, 'AI_EXPOSURE outside [0,1]', 'out_of_range_exposure',
       COUNT(*), IFF(COUNT(*)=0,'PASS','FAIL')
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
WHERE AI_EXPOSURE IS NOT NULL AND (AI_EXPOSURE < 0 OR AI_EXPOSURE > 1);

/* ============================================================================
   CHECK 8 - Record counts before and after joins
   Rows in the BLS national slice vs rows that survived into the fact table
   (fact drops rows with NULL A_MEDIAN). Report the retention rate.
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
WITH before_cnt AS (SELECT COUNT(*) n FROM STAGING.STG_BLS_OEWS_NATIONAL),
     after_cnt  AS (SELECT COUNT(*) n FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT)
SELECT 8, 'Row retention BLS national -> fact', 'pct_rows_retained',
       ROUND(100.0 * after_cnt.n / NULLIF(before_cnt.n,0), 1),
       IFF(100.0 * after_cnt.n / NULLIF(before_cnt.n,0) >= 90, 'PASS', 'WARN')
FROM before_cnt, after_cnt;

-- Also log the raw before/after counts as their own rows for transparency.
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 8, 'Row count BEFORE join (BLS national)', 'rows', COUNT(*), 'INFO'
FROM STAGING.STG_BLS_OEWS_NATIONAL;
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 8, 'Row count AFTER join (fact)', 'rows', COUNT(*), 'INFO'
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT;

/* ============================================================================
   CHECK 9 - Occupations in BLS that do NOT match O*NET
   (Expected to be > 0: some BLS occupations have no O*NET task profile.)
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 9, 'BLS occupations with no O*NET match', 'bls_only_occ',
       COUNT(*), 'INFO'
FROM (
    SELECT DISTINCT b.OCC_CODE
    FROM STAGING.STG_BLS_OEWS_NATIONAL b
    WHERE NOT EXISTS (SELECT 1 FROM STAGING.STG_ONET_TASKS o WHERE o.OCC_CODE = b.OCC_CODE)
);
-- inspect (list them):
-- SELECT DISTINCT b.OCC_CODE, b.OCC_TITLE FROM STAGING.STG_BLS_OEWS_NATIONAL b
-- WHERE NOT EXISTS (SELECT 1 FROM STAGING.STG_ONET_TASKS o WHERE o.OCC_CODE=b.OCC_CODE);

/* ============================================================================
   CHECK 10 - O*NET occupations that do NOT match BLS
   (Expected to be > 0: O*NET has some codes not in the BLS national detailed slice.)
   ============================================================================ */
INSERT INTO QUALITY.DQ_RESULTS (CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS)
SELECT 10, 'O*NET occupations with no BLS match', 'onet_only_occ',
       COUNT(*), 'INFO'
FROM (
    SELECT DISTINCT o.OCC_CODE
    FROM STAGING.STG_ONET_TASKS o
    WHERE NOT EXISTS (SELECT 1 FROM STAGING.STG_BLS_OEWS_NATIONAL b WHERE b.OCC_CODE = o.OCC_CODE)
);

/* ============================================================================
   RESULTS DASHBOARD
   ----------------------------------------------------------------------------
   One glance tells you the health of the build. Any FAIL needs attention;
   WARN and INFO are expected/contextual.
   ============================================================================ */
SELECT CHECK_ID, CHECK_NAME, METRIC, METRIC_VALUE, STATUS, CHECKED_AT
FROM QUALITY.DQ_RESULTS
ORDER BY CHECK_ID,
         CASE STATUS WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 WHEN 'INFO' THEN 2 ELSE 3 END,
         CHECK_NAME;

-- Overall gate: fails 0?
SELECT COUNT_IF(STATUS='FAIL') AS fail_count,
       COUNT_IF(STATUS='WARN') AS warn_count,
       IFF(COUNT_IF(STATUS='FAIL')=0, 'BUILD OK', 'BUILD HAS FAILURES') AS verdict
FROM QUALITY.DQ_RESULTS;
