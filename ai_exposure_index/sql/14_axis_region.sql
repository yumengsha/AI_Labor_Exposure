/* ============================================================================
   14_axis_region.sql  -  Analytical axis 2: Region (State / Metro / Nonmetro)
   ----------------------------------------------------------------------------
   Employment-weighted rollup of the occupation index to geographic areas, at
   three granularities selected by a GRANULARITY column:
       State           (AREA_TYPE='2', 51 areas incl. DC)
       Metropolitan    (AREA_TYPE='4', ~393 MSAs)
       Nonmetropolitan (AREA_TYPE='6', ~137 areas)
   All three are single I_GROUP='cross-industry' / OWN_CODE='1235' / detailed
   slices (verified), so one query with GROUP BY (GRANULARITY, AREA) builds all
   levels with no double-count.

     Region Exposure = Σ(OCC_AI_EXPOSURE × AREA_OCC_EMP) / Σ(AREA_OCC_EMP)

   The occupation-exposure factor is always the NATIONAL occupation index; here
   it is re-weighted by each area's occupational employment mix. Metro/nonmetro
   areas are smaller and more suppressed, so EMP_COVERAGE will be lower there.

   Run after 12_occupation_exposure.sql. Requires STG_BLS_OEWS_REGION (added to
   sql/03 per the plan): AREA_TYPE IN ('2','4','6') AND I_GROUP='cross-industry'
   AND OWN_CODE='1235' AND O_GROUP='detailed', with GRANULARITY derived from
   AREA_TYPE.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    ANALYTICS;

/* ---- area × occupation drill grain (carries GRANULARITY) ---- */
CREATE OR REPLACE TABLE ANALYTICS.REGION_OCCUPATION_EXPOSURE_FACT AS
SELECT
    s.GRANULARITY,
    s.AREA,
    s.AREA_TITLE,
    s.STATE,
    s.OCC_CODE,
    s.OCC_TITLE,
    s.TOT_EMP                              AS AREA_OCC_EMP,
    o.AI_EXPOSURE,
    o.AUTOMATION,
    o.AUGMENTATION,
    o.SCORE_STATUS,
    o.EXPOSURE_MODE
FROM STAGING.STG_BLS_OEWS_REGION s
JOIN ANALYTICS.OCCUPATION_EXPOSURE_FACT o
     ON s.OCC_CODE = o.OCC_CODE;

/* ---- per-area aggregate, one row per (GRANULARITY, AREA) ---- */
CREATE OR REPLACE TABLE ANALYTICS.REGION_EXPOSURE_FACT AS
WITH agg AS (
    SELECT
        GRANULARITY,
        AREA,
        ANY_VALUE(AREA_TITLE)                                 AS AREA_TITLE,
        ANY_VALUE(STATE)                                      AS STATE,
        SUM(AREA_OCC_EMP)                                     AS TOTAL_EMP,
        COUNT(*)                                              AS OCC_COUNT,
        SUM(IFF(AI_EXPOSURE IS NOT NULL, AREA_OCC_EMP, 0))    AS SCORED_EMP,
        SUM(AI_EXPOSURE  * AREA_OCC_EMP) / NULLIF(SUM(IFF(AI_EXPOSURE  IS NOT NULL, AREA_OCC_EMP, 0)), 0) AS AI_EXPOSURE,
        SUM(AUTOMATION   * AREA_OCC_EMP) / NULLIF(SUM(IFF(AUTOMATION   IS NOT NULL, AREA_OCC_EMP, 0)), 0) AS AUTOMATION,
        SUM(AUGMENTATION * AREA_OCC_EMP) / NULLIF(SUM(IFF(AUGMENTATION IS NOT NULL, AREA_OCC_EMP, 0)), 0) AS AUGMENTATION,
        ANY_VALUE(EXPOSURE_MODE)                              AS EXPOSURE_MODE
    FROM ANALYTICS.REGION_OCCUPATION_EXPOSURE_FACT
    GROUP BY GRANULARITY, AREA
)
SELECT
    GRANULARITY, AREA, AREA_TITLE, STATE, EXPOSURE_MODE,
    TOTAL_EMP, OCC_COUNT,
    ROUND(DIV0(SCORED_EMP, TOTAL_EMP), 4)   AS EMP_COVERAGE,
    ROUND(AI_EXPOSURE, 4)                    AS AI_EXPOSURE,
    ROUND(AUTOMATION, 4)                     AS AUTOMATION,
    ROUND(AUGMENTATION, 4)                   AS AUGMENTATION,
    -- rank WITHIN each granularity (states vs states, metros vs metros)
    RANK() OVER (PARTITION BY GRANULARITY ORDER BY AI_EXPOSURE DESC NULLS LAST) AS EXPOSURE_RANK
FROM agg;

/* ---- sanity: counts per granularity + top states ---- */
SELECT GRANULARITY, COUNT(*) AS areas,
       ROUND(AVG(AI_EXPOSURE), 4) AS avg_area_exposure,
       ROUND(AVG(EMP_COVERAGE), 3) AS avg_emp_coverage
FROM ANALYTICS.REGION_EXPOSURE_FACT
GROUP BY GRANULARITY
ORDER BY GRANULARITY;
