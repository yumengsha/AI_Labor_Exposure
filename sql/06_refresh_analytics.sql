/* ============================================================================
   06_refresh_analytics.sql
   ----------------------------------------------------------------------------
   Purpose : Rebuild the derived layers (STAGING views, ANALYTICS star schema,
             QUALITY checks) after new RAW data has been loaded.

   This script is meant to be run by the automated refresh job (python/
   refresh_pipeline.py) AFTER python/load_local_files.py has refreshed RAW.

   It does NOT re-run the raw load. It just rebuilds everything downstream of
   RAW, which is safe and idempotent because scripts 03/04/05 all use
   CREATE OR REPLACE.

   Execution model:
     The Snowflake Python connector runs one statement per execute() call, so
     python/refresh_pipeline.py executes the individual files 03, 04, 05 in
     order. This file (06) is the single place that also records a refresh-log
     row so you can see when the warehouse was last rebuilt and whether quality
     passed. Run it LAST, after 03/04/05.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    QUALITY;

/* ----------------------------------------------------------------------------
   Refresh log: one row per rebuild, capturing counts + quality verdict.
   ---------------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS QUALITY.REFRESH_LOG (
    REFRESHED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    BLS_LATEST_YEAR   INTEGER,
    BLS_RAW_ROWS      NUMBER,
    ONET_TASK_ROWS    NUMBER,
    FACT_ROWS         NUMBER,
    OCCUPATIONS       NUMBER,
    QUALITY_FAILS     NUMBER,
    QUALITY_WARNS     NUMBER,
    VERDICT           VARCHAR
);

/* ----------------------------------------------------------------------------
   Insert a log row summarizing the current state of the warehouse.
   (Assumes 03/04/05 have already run in this session / just before this.)
   ---------------------------------------------------------------------------- */
INSERT INTO QUALITY.REFRESH_LOG
    (BLS_LATEST_YEAR, BLS_RAW_ROWS, ONET_TASK_ROWS, FACT_ROWS,
     OCCUPATIONS, QUALITY_FAILS, QUALITY_WARNS, VERDICT)
SELECT
    (SELECT MAX(DATA_YEAR)  FROM RAW.BLS_OEWS_RAW),
    (SELECT COUNT(*)        FROM RAW.BLS_OEWS_RAW),
    (SELECT COUNT(*)        FROM RAW.ONET_TASK_STATEMENTS_RAW),
    (SELECT COUNT(*)        FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT),
    (SELECT COUNT(*)        FROM ANALYTICS.DIM_OCCUPATION),
    (SELECT COUNT_IF(STATUS='FAIL') FROM QUALITY.DQ_RESULTS),
    (SELECT COUNT_IF(STATUS='WARN') FROM QUALITY.DQ_RESULTS),
    (SELECT IFF(COUNT_IF(STATUS='FAIL')=0, 'BUILD OK', 'BUILD HAS FAILURES')
     FROM QUALITY.DQ_RESULTS);

/* ----------------------------------------------------------------------------
   Show the most recent refreshes.
   ---------------------------------------------------------------------------- */
SELECT *
FROM QUALITY.REFRESH_LOG
ORDER BY REFRESHED_AT DESC
LIMIT 10;
