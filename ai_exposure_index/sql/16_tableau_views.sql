/* ============================================================================
   16_tableau_views.sql  -  Dashboard-facing views
   ----------------------------------------------------------------------------
   A Tableau parameter cannot swap a worksheet's data source, so the three axes
   are unioned into ONE long-format view. A single AXIS_TYPE parameter (plus a
   GRANULARITY parameter for the region axis) drives one chart.

   Also: three SEPARATE occupation-grain views. We never put region and industry
   keys in the same view - a national occupation is one row, but regions and
   industries are many-to-one against it, so combining them would multiply rows
   and double-count employment.

   Run after scripts 13, 14, 15.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    ANALYTICS;

/* ============================================================================
   VW_EXPOSURE_AXIS - long format, one row per (axis, granularity, key).
   AXIS_TYPE in {INDUSTRY, REGION, WAGE_BAND}; GRANULARITY only meaningful for
   REGION (else 'n/a'). One parameter picks AXIS_TYPE; for REGION a second picks
   GRANULARITY (incl. Metropolitan vs Nonmetropolitan comparison).
   ============================================================================ */
CREATE OR REPLACE VIEW ANALYTICS.VW_EXPOSURE_AXIS AS
    SELECT
        'INDUSTRY'          AS AXIS_TYPE,
        'n/a'               AS GRANULARITY,
        NAICS               AS AXIS_KEY,
        INDUSTRY_TITLE      AS AXIS_LABEL,
        AI_EXPOSURE, AUTOMATION, AUGMENTATION,
        TOTAL_EMP, EMP_COVERAGE, EXPOSURE_RANK, EXPOSURE_MODE
    FROM ANALYTICS.INDUSTRY_EXPOSURE_FACT
UNION ALL
    SELECT
        'REGION'            AS AXIS_TYPE,
        GRANULARITY,
        AREA                AS AXIS_KEY,
        AREA_TITLE          AS AXIS_LABEL,
        AI_EXPOSURE, AUTOMATION, AUGMENTATION,
        TOTAL_EMP, EMP_COVERAGE, EXPOSURE_RANK, EXPOSURE_MODE
    FROM ANALYTICS.REGION_EXPOSURE_FACT
UNION ALL
    SELECT
        'WAGE_BAND'         AS AXIS_TYPE,
        'n/a'               AS GRANULARITY,
        WAGE_BAND           AS AXIS_KEY,
        WAGE_BAND           AS AXIS_LABEL,
        AI_EXPOSURE, AUTOMATION, AUGMENTATION,
        TOTAL_EMP, EMP_COVERAGE,
        BAND_ORDER          AS EXPOSURE_RANK,   -- natural Low<Mid<High order
        EXPOSURE_MODE
    FROM ANALYTICS.WAGE_BAND_EXPOSURE_FACT;

/* ============================================================================
   Occupation-grain views - THREE separate views (never region+industry in one).
   ============================================================================ */

-- National occupation index (one row per occupation) - the default drill grain.
CREATE OR REPLACE VIEW ANALYTICS.VW_OCCUPATION_NATIONAL AS
SELECT
    OCC_CODE, OCC_TITLE, O_GROUP,
    TOT_EMP, A_MEAN, A_MEDIAN,
    WAGE_PERCENTILE, WAGE_BAND,
    EXPOSURE_MODE, SCORE_STATUS,
    AI_EXPOSURE, AUTOMATION, AUGMENTATION, EXPOSURE_CONFIDENCE,
    WEIGHTED_EXPOSURE, EXPOSURE_RANK,
    IMPORTANCE_WEIGHT_COVERAGE, TASK_COUNT_COVERAGE,
    PLACEHOLDER_EXPOSURE
FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT;

-- Region × occupation drill-down (carries GRANULARITY: State/Metro/Nonmetro).
CREATE OR REPLACE VIEW ANALYTICS.VW_REGION_OCCUPATION AS
SELECT
    GRANULARITY, AREA, AREA_TITLE, STATE,
    OCC_CODE, OCC_TITLE,
    AREA_OCC_EMP,
    AI_EXPOSURE, AUTOMATION, AUGMENTATION,
    SCORE_STATUS, EXPOSURE_MODE
FROM ANALYTICS.REGION_OCCUPATION_EXPOSURE_FACT;

-- Industry × occupation drill-down (NAICS sector, private).
CREATE OR REPLACE VIEW ANALYTICS.VW_INDUSTRY_OCCUPATION AS
SELECT
    NAICS, INDUSTRY_TITLE,
    OCC_CODE, OCC_TITLE,
    SECTOR_OCC_EMP,
    AI_EXPOSURE, AUTOMATION, AUGMENTATION,
    SCORE_STATUS, EXPOSURE_MODE
FROM ANALYTICS.INDUSTRY_OCCUPATION_EXPOSURE_FACT;

/* ---- preview: axis coverage ---- */
SELECT AXIS_TYPE, GRANULARITY, COUNT(*) AS cells,
       ROUND(AVG(AI_EXPOSURE), 4) AS avg_exposure
FROM ANALYTICS.VW_EXPOSURE_AXIS
GROUP BY AXIS_TYPE, GRANULARITY
ORDER BY AXIS_TYPE, GRANULARITY;
