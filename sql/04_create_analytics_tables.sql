/* ============================================================================
   04_create_analytics_tables.sql
   ----------------------------------------------------------------------------
   Purpose : Build the ANALYTICS star schema for Tableau:

       FACT      ANALYTICS.OCCUPATION_EXPOSURE_FACT
       DIMS      ANALYTICS.DIM_OCCUPATION
                 ANALYTICS.DIM_TASK
                 ANALYTICS.DIM_REGION
                 ANALYTICS.DIM_INDUSTRY
                 ANALYTICS.DIM_WAGE_BAND
       SEED      ANALYTICS.AI_EXPOSURE_PLACEHOLDER   (easy to swap for real scores)

   Key techniques (as requested):
     * CTEs for step-by-step transformations.
     * Window functions for wage percentiles + ranking high-exposure occupations.
     * A clearly-labelled PLACEHOLDER exposure score - NOT a real AI score.

   Run after 03_create_staging_views.sql.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    ANALYTICS;

/* ============================================================================
   1. AI EXPOSURE - PLACEHOLDER SEED TABLE
   ----------------------------------------------------------------------------
   >>> THIS IS A PLACEHOLDER. IT IS NOT A REAL AI EXPOSURE SCORE. <<<

   We do not have an external AI exposure dataset yet, so we derive a transparent
   PROXY from O*NET task importance: the average normalized importance of an
   occupation's tasks (0..1). This is a stand-in that lets the whole pipeline and
   Tableau dashboards work end to end.

   HOW TO REPLACE WITH A REAL SCORE:
     Option A - overwrite this table's AI_EXPOSURE column from your real source
                keyed by OCC_CODE, and set SCORE_SOURCE accordingly.
     Option B - CREATE OR REPLACE this table by loading a real scores file.
   The fact table reads AI_EXPOSURE from here, so swapping this table is all it
   takes to move from placeholder to production.
   ============================================================================ */
CREATE OR REPLACE TABLE ANALYTICS.AI_EXPOSURE_PLACEHOLDER AS
WITH task_importance AS (
    -- one importance value per (occupation, task); fall back to task count if a
    -- task has no importance rating so every occupation still gets a proxy.
    SELECT
        OCC_CODE,
        COUNT(*)                         AS task_count,
        COUNT(IMPORTANCE_NORM)           AS rated_task_count,
        AVG(IMPORTANCE_NORM)             AS avg_importance_norm
    FROM STAGING.STG_ONET_TASKS
    GROUP BY OCC_CODE
)
SELECT
    OCC_CODE,
    -- Proxy exposure in [0,1]. COALESCE guards occupations with no IM ratings.
    ROUND(COALESCE(avg_importance_norm, 0), 4)          AS AI_EXPOSURE,
    task_count,
    rated_task_count,
    'PLACEHOLDER_ONET_IMPORTANCE_PROXY'                 AS SCORE_SOURCE,
    'Avg normalized O*NET task importance ((IM-1)/4). Replace with real score.'
                                                        AS SCORE_NOTE
FROM task_importance;

/* ============================================================================
   2. DIMENSION TABLES
   ============================================================================ */

/* ---- 2.1 DIM_OCCUPATION --------------------------------------------------
   Distinct detailed occupations from the BLS national slice.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE ANALYTICS.DIM_OCCUPATION AS
SELECT DISTINCT
    OCC_CODE,
    OCC_TITLE,
    O_GROUP
FROM STAGING.STG_BLS_OEWS_NATIONAL;

/* ---- 2.2 DIM_TASK --------------------------------------------------------
   One row per O*NET task, with the standardized OCC_CODE for joining.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE ANALYTICS.DIM_TASK AS
SELECT
    TASK_ID,
    OCC_CODE,
    ONET_SOC_CODE,
    TASK_STATEMENT,
    TASK_TYPE,
    IMPORTANCE_RAW,
    IMPORTANCE_NORM
FROM STAGING.STG_ONET_TASKS;

/* ---- 2.3 DIM_REGION ------------------------------------------------------
   Distinct areas across all years/levels so region-level BLS slices (state,
   metro) can still join even though the fact table below is national.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE ANALYTICS.DIM_REGION AS
WITH candidates AS (
    SELECT DISTINCT
        DATA_YEAR,
        AREA,
        AREA_TITLE,
        STATE,
        CASE AREA_TYPE
            WHEN '1' THEN 'National'
            WHEN '2' THEN 'State'
            WHEN '3' THEN 'Territory'
            WHEN '4' THEN 'Metropolitan'
            WHEN '6' THEN 'Nonmetropolitan'
            ELSE 'Other'
        END AS AREA_TYPE_LABEL
    FROM STAGING.STG_BLS_OEWS
    WHERE AREA IS NOT NULL
)
SELECT
    AREA,
    AREA_TITLE,
    STATE,
    AREA_TYPE_LABEL
FROM candidates
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY AREA
    ORDER BY DATA_YEAR DESC, AREA_TITLE, STATE
) = 1;

/* ---- 2.4 DIM_INDUSTRY ----------------------------------------------------
   Distinct NAICS industries seen in the data.
   ---------------------------------------------------------------------------- */

CREATE OR REPLACE TABLE ANALYTICS.DIM_INDUSTRY AS
WITH candidates AS (
    SELECT DISTINCT
        DATA_YEAR,
        NAICS,
        INDUSTRY_TITLE
    FROM STAGING.STG_BLS_OEWS
    WHERE NAICS IS NOT NULL
)
SELECT
    NAICS,
    INDUSTRY_TITLE
FROM candidates
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY NAICS
    ORDER BY DATA_YEAR DESC, INDUSTRY_TITLE
) = 1;

/* ---- 2.5 DIM_WAGE_BAND ---------------------------------------------------
   Static definition of three percentile-based wage bands. WAGE_PERCENTILE is
   0..1 (from PERCENT_RANK on A_MEDIAN in the fact build), so the bands below
   partition that range into Low / Middle / High thirds.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE ANALYTICS.DIM_WAGE_BAND (
    WAGE_BAND               VARCHAR,
    WAGE_PERCENTILE_MIN     FLOAT,
    WAGE_PERCENTILE_MAX     FLOAT,
    BAND_ORDER              INTEGER
);
INSERT INTO ANALYTICS.DIM_WAGE_BAND VALUES
    ('Low',    0.00, 0.3333, 1),
    ('Middle', 0.3333, 0.6667, 2),
    ('High',   0.6667, 1.01,  3);   -- max slightly > 1 so the top row is inclusive

/* ============================================================================
   3. FACT TABLE: OCCUPATION_EXPOSURE_FACT
   ----------------------------------------------------------------------------
   Built step by step with CTEs:
     base       -> national detailed occupations from BLS
     exposure   -> attach the placeholder AI exposure
     ranked     -> wage percentile via window function + weighted exposure
     banded     -> map percentile to a wage band label
   ============================================================================ */
CREATE OR REPLACE TABLE ANALYTICS.OCCUPATION_EXPOSURE_FACT AS
WITH base AS (
    SELECT
        OCC_CODE, OCC_TITLE, O_GROUP,
        TOT_EMP, A_MEAN, A_MEDIAN,
        AREA, STATE, NAICS, INDUSTRY_TITLE
    FROM STAGING.STG_BLS_OEWS_NATIONAL
),
exposure AS (
    SELECT
        b.*,
        e.AI_EXPOSURE,                -- placeholder proxy in [0,1]
        e.SCORE_SOURCE
    FROM base b
    LEFT JOIN ANALYTICS.AI_EXPOSURE_PLACEHOLDER e
           ON b.OCC_CODE = e.OCC_CODE
),
ranked AS (
    SELECT
        *,
        -- wage percentile 0..1 across all occupations by median annual wage
        PERCENT_RANK() OVER (ORDER BY A_MEDIAN)              AS WAGE_PERCENTILE,
        -- rank occupations by exposure (1 = most exposed) for dashboards
        RANK()         OVER (ORDER BY AI_EXPOSURE DESC)      AS EXPOSURE_RANK,
        -- weighted exposure = exposure * employment
        AI_EXPOSURE * TOT_EMP                                AS WEIGHTED_EXPOSURE
    FROM exposure
    WHERE A_MEDIAN IS NOT NULL          -- percentile needs a wage
)
SELECT
    r.OCC_CODE,
    r.OCC_TITLE,
    r.O_GROUP,
    r.TOT_EMP,
    r.A_MEAN,
    r.A_MEDIAN,
    r.WAGE_PERCENTILE,
    wb.WAGE_BAND,
    r.AI_EXPOSURE,
    r.WEIGHTED_EXPOSURE,
    r.EXPOSURE_RANK,
    r.AREA,
    r.STATE,
    r.NAICS,
    r.INDUSTRY_TITLE,
    r.SCORE_SOURCE                       AS EXPOSURE_SOURCE
FROM ranked r
LEFT JOIN ANALYTICS.DIM_WAGE_BAND wb
       ON r.WAGE_PERCENTILE >= wb.WAGE_PERCENTILE_MIN
      AND r.WAGE_PERCENTILE <  wb.WAGE_PERCENTILE_MAX;

/* ============================================================================
   4. EXAMPLE ANALYTICS QUERIES (window functions + ranking)
   ----------------------------------------------------------------------------
   These are illustrative - safe to run, they only SELECT.
   ============================================================================ */

-- Top 15 most-exposed occupations by placeholder score
SELECT OCC_CODE, OCC_TITLE, TOT_EMP, A_MEDIAN, WAGE_BAND,
       AI_EXPOSURE, WEIGHTED_EXPOSURE, EXPOSURE_RANK
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
ORDER BY AI_EXPOSURE DESC
LIMIT 15;

-- Employment-weighted average exposure by wage band
SELECT WAGE_BAND,
       COUNT(*)                                   AS occupations,
       SUM(TOT_EMP)                               AS total_employment,
       ROUND(SUM(WEIGHTED_EXPOSURE)/NULLIF(SUM(TOT_EMP),0), 4)
                                                  AS emp_weighted_exposure
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
GROUP BY WAGE_BAND
ORDER BY MIN(WAGE_PERCENTILE);
