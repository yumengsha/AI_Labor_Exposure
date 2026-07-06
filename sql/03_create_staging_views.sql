/* ============================================================================
   03_create_staging_views.sql
   ----------------------------------------------------------------------------
   Purpose : Build the STAGING layer - clean, typed, standardized views on top
             of the RAW tables. Views (not tables) so they always reflect the
             latest RAW load and cost nothing to store.

   What this layer does:
     * Renames / clarifies columns.
     * Casts text -> numbers, stripping commas and treating BLS suppression
       symbols (* # blank) as NULL.
     * Standardizes the occupation code:
           BLS   OCC_CODE          = 11-1021       (already 7 chars)
           O*NET "O*NET-SOC Code"  = 11-1021.00    -> LEFT(...,7) = 11-1021
       so BLS and O*NET can join on a common OCC_CODE.
     * Filters to the rows this project actually needs.

   Run after 02_load_raw_data.sql.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    STAGING;

/* ============================================================================
   1. BLS OEWS - cleaned & typed
   ----------------------------------------------------------------------------
   TRY_TO_DECIMAL / TRY_TO_DOUBLE return NULL instead of erroring on bad input,
   so suppressed or malformed wages become NULL rather than blowing up the view.
   We strip commas first in case any survived the export.
   ============================================================================ */
CREATE OR REPLACE VIEW STAGING.STG_BLS_OEWS AS
SELECT
    -- keep the most recent year available per (area, industry, occupation)
    DATA_YEAR,
    -- occupation
    TRIM(OCC_CODE)                                          AS OCC_CODE,
    TRIM(OCC_TITLE)                                         AS OCC_TITLE,
    LOWER(TRIM(O_GROUP))                                    AS O_GROUP,
    -- geography
    TRIM(AREA)                                              AS AREA,
    TRIM(AREA_TITLE)                                        AS AREA_TITLE,
    TRIM(AREA_TYPE)                                         AS AREA_TYPE,
    TRIM(PRIM_STATE)                                        AS STATE,
    -- industry
    TRIM(NAICS)                                             AS NAICS,
    TRIM(NAICS_TITLE)                                       AS INDUSTRY_TITLE,
    LOWER(TRIM(I_GROUP))                                    AS I_GROUP,
    TRIM(OWN_CODE)                                          AS OWN_CODE,
    -- employment (integer-ish, keep as decimal to be safe)
    TRY_TO_DECIMAL(REPLACE(TOT_EMP, ',', ''), 38, 0)        AS TOT_EMP,
    -- wages
    TRY_TO_DOUBLE(REPLACE(H_MEAN,   ',', ''))               AS H_MEAN,
    TRY_TO_DOUBLE(REPLACE(A_MEAN,   ',', ''))               AS A_MEAN,
    TRY_TO_DOUBLE(REPLACE(H_MEDIAN, ',', ''))               AS H_MEDIAN,
    TRY_TO_DOUBLE(REPLACE(A_MEDIAN, ',', ''))               AS A_MEDIAN,
    TRY_TO_DOUBLE(REPLACE(A_PCT10,  ',', ''))               AS A_PCT10,
    TRY_TO_DOUBLE(REPLACE(A_PCT25,  ',', ''))               AS A_PCT25,
    TRY_TO_DOUBLE(REPLACE(A_PCT75,  ',', ''))               AS A_PCT75,
    TRY_TO_DOUBLE(REPLACE(A_PCT90,  ',', ''))               AS A_PCT90
FROM RAW.BLS_OEWS_RAW
WHERE OCC_CODE IS NOT NULL
  AND OCC_CODE <> '00-0000';   -- drop the "All Occupations" rollup row

/* ---- Convenience view: latest year, national, cross-industry, DETAILED -----
   This is the slice used to build the occupation fact table:
     * AREA_TYPE = '1'      -> national totals (one row per occupation)
     * I_GROUP   = cross-industry + OWN_CODE 1235 -> all ownerships combined
     * O_GROUP   = detailed  -> the granular occupations we care about
   Picking a single, unambiguous slice avoids double-counting employment.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE VIEW STAGING.STG_BLS_OEWS_NATIONAL AS
WITH latest AS (
    SELECT MAX(DATA_YEAR) AS max_year FROM STAGING.STG_BLS_OEWS
)
SELECT b.*
FROM STAGING.STG_BLS_OEWS b, latest
WHERE b.DATA_YEAR = latest.max_year
  AND b.AREA_TYPE = '1'            -- national
  AND b.I_GROUP   = 'cross-industry'
  AND b.OWN_CODE  = '1235'         -- total, all ownerships
  AND b.O_GROUP   = 'detailed';    -- detailed occupations only

/* ============================================================================
   2. O*NET Task Statements - cleaned + standardized OCC_CODE
   ============================================================================ */
CREATE OR REPLACE VIEW STAGING.STG_ONET_TASK_STATEMENTS AS
SELECT
    TRIM("ONET_SOC_CODE")                       AS ONET_SOC_CODE,
    LEFT(TRIM("ONET_SOC_CODE"), 7)              AS OCC_CODE,   -- 11-1011.00 -> 11-1011
    TRY_TO_NUMBER(TRIM(TASK_ID))                AS TASK_ID,
    TRIM(TASK)                                  AS TASK_STATEMENT,
    TRIM(TASK_TYPE)                             AS TASK_TYPE
FROM RAW.ONET_TASK_STATEMENTS_RAW
WHERE "ONET_SOC_CODE" IS NOT NULL
  AND TASK_ID IS NOT NULL;

/* ============================================================================
   3. O*NET Task Ratings - cleaned + standardized OCC_CODE
   ----------------------------------------------------------------------------
   Scale IDs:  IM = Importance, RT = Relevance, FT = Frequency.
   We keep all three but flag importance, which drives the exposure weighting.
   ============================================================================ */
CREATE OR REPLACE VIEW STAGING.STG_ONET_TASK_RATINGS AS
SELECT
    TRIM("ONET_SOC_CODE")                       AS ONET_SOC_CODE,
    LEFT(TRIM("ONET_SOC_CODE"), 7)              AS OCC_CODE,
    TRY_TO_NUMBER(TRIM(TASK_ID))                AS TASK_ID,
    TRIM(SCALE_ID)                              AS SCALE_ID,
    TRY_TO_DOUBLE(TRIM(DATA_VALUE))             AS DATA_VALUE,
    TRY_TO_NUMBER(TRIM(N))                       AS N,
    TRIM(RECOMMEND_SUPPRESS)                    AS RECOMMEND_SUPPRESS
FROM RAW.ONET_TASK_RATINGS_RAW
WHERE "ONET_SOC_CODE" IS NOT NULL
  AND TASK_ID IS NOT NULL
  AND TRY_TO_DOUBLE(TRIM(DATA_VALUE)) IS NOT NULL;

/* ---- Importance-only ratings (one importance value per task) ---------------
   SCALE_ID = 'IM' is the task-importance rating on a 1-5 scale. We normalize it
   to 0-1 ( (IM-1)/4 ) so it can act as a task-level weight later.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE VIEW STAGING.STG_ONET_TASK_IMPORTANCE AS
SELECT
    OCC_CODE,
    ONET_SOC_CODE,
    TASK_ID,
    DATA_VALUE                       AS IMPORTANCE_RAW,     -- 1..5
    (DATA_VALUE - 1) / 4.0           AS IMPORTANCE_NORM     -- 0..1
FROM STAGING.STG_ONET_TASK_RATINGS
WHERE SCALE_ID = 'IM';

/* ============================================================================
   4. Task-level joined view: statements + their importance rating
   ----------------------------------------------------------------------------
   Joins ratings to statements by BOTH Task ID and O*NET SOC code, as required.
   ============================================================================ */
CREATE OR REPLACE VIEW STAGING.STG_ONET_TASKS AS
SELECT
    s.OCC_CODE,
    s.ONET_SOC_CODE,
    s.TASK_ID,
    s.TASK_STATEMENT,
    s.TASK_TYPE,
    i.IMPORTANCE_RAW,
    i.IMPORTANCE_NORM
FROM STAGING.STG_ONET_TASK_STATEMENTS s
LEFT JOIN STAGING.STG_ONET_TASK_IMPORTANCE i
       ON s.TASK_ID       = i.TASK_ID
      AND s.ONET_SOC_CODE = i.ONET_SOC_CODE;

/* ============================================================================
   5. Quick preview
   ============================================================================ */
SELECT 'STG_BLS_OEWS_NATIONAL' AS view_name, COUNT(*) AS row_count FROM STAGING.STG_BLS_OEWS_NATIONAL
UNION ALL SELECT 'STG_ONET_TASK_STATEMENTS', COUNT(*) FROM STAGING.STG_ONET_TASK_STATEMENTS
UNION ALL SELECT 'STG_ONET_TASK_RATINGS',    COUNT(*) FROM STAGING.STG_ONET_TASK_RATINGS
UNION ALL SELECT 'STG_ONET_TASKS',           COUNT(*) FROM STAGING.STG_ONET_TASKS;
