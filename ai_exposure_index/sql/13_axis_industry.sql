/* ============================================================================
   13_axis_industry.sql  -  Analytical axis 1: Industry (NAICS sector)
   ----------------------------------------------------------------------------
   Employment-weighted rollup of the occupation index to NAICS sectors:
     Industry Exposure = Σ(OCC_AI_EXPOSURE × TOT_EMP) / Σ(TOT_EMP)

   v1 scope: PRIVATE ownership only (OWN_CODE='5'). There is no single all-
   ownership sector figure in OEWS (sector rows split across ownership codes),
   so private-only is the clean, no-double-count choice. Government-heavy sectors
   will therefore be sparse - documented as a known limitation.

   LOW_COVERAGE / NO_ONET occupations (AI_EXPOSURE IS NULL) are excluded from the
   weighted mean; EMP_COVERAGE reports how much of each sector's employment came
   from occupations that actually had a valid score.

   Run after 12_occupation_exposure.sql. Requires STG_BLS_OEWS_INDUSTRY (added to
   sql/03 per the plan): AREA_TYPE='1' AND I_GROUP='sector' AND OWN_CODE='5'
   AND O_GROUP='detailed'.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    ANALYTICS;

/* ---- sector × occupation drill grain (also the base for the aggregate) ----
   Joins the sector employment slice to the national occupation exposure. Note
   the exposure is the NATIONAL occupation index (one index per occupation),
   applied to each sector's employment for that occupation. */
CREATE OR REPLACE TABLE ANALYTICS.INDUSTRY_OCCUPATION_EXPOSURE_FACT AS
SELECT
    s.NAICS,
    s.INDUSTRY_TITLE,
    s.OCC_CODE,
    s.OCC_TITLE,
    s.TOT_EMP                              AS SECTOR_OCC_EMP,
    o.AI_EXPOSURE,
    o.AUTOMATION,
    o.AUGMENTATION,
    o.SCORE_STATUS,
    o.EXPOSURE_MODE
FROM STAGING.STG_BLS_OEWS_INDUSTRY s
JOIN ANALYTICS.OCCUPATION_EXPOSURE_FACT o
     ON s.OCC_CODE = o.OCC_CODE;

/* ---- per-sector aggregate ---- */
CREATE OR REPLACE TABLE ANALYTICS.INDUSTRY_EXPOSURE_FACT AS
WITH agg AS (
    SELECT
        NAICS,
        ANY_VALUE(INDUSTRY_TITLE)                             AS INDUSTRY_TITLE,
        SUM(SECTOR_OCC_EMP)                                   AS TOTAL_EMP,
        COUNT(*)                                              AS OCC_COUNT,
        SUM(IFF(AI_EXPOSURE IS NOT NULL, SECTOR_OCC_EMP, 0))  AS SCORED_EMP,
        -- employment-weighted means over occupations that HAVE a score
        SUM(AI_EXPOSURE  * SECTOR_OCC_EMP) / NULLIF(SUM(IFF(AI_EXPOSURE  IS NOT NULL, SECTOR_OCC_EMP, 0)), 0) AS AI_EXPOSURE,
        SUM(AUTOMATION   * SECTOR_OCC_EMP) / NULLIF(SUM(IFF(AUTOMATION   IS NOT NULL, SECTOR_OCC_EMP, 0)), 0) AS AUTOMATION,
        SUM(AUGMENTATION * SECTOR_OCC_EMP) / NULLIF(SUM(IFF(AUGMENTATION IS NOT NULL, SECTOR_OCC_EMP, 0)), 0) AS AUGMENTATION,
        ANY_VALUE(EXPOSURE_MODE)                              AS EXPOSURE_MODE
    FROM ANALYTICS.INDUSTRY_OCCUPATION_EXPOSURE_FACT
    GROUP BY NAICS
)
SELECT
    NAICS, INDUSTRY_TITLE, EXPOSURE_MODE,
    TOTAL_EMP, OCC_COUNT,
    ROUND(DIV0(SCORED_EMP, TOTAL_EMP), 4)   AS EMP_COVERAGE,
    ROUND(AI_EXPOSURE, 4)                    AS AI_EXPOSURE,
    ROUND(AUTOMATION, 4)                     AS AUTOMATION,
    ROUND(AUGMENTATION, 4)                   AS AUGMENTATION,
    RANK() OVER (ORDER BY AI_EXPOSURE DESC NULLS LAST) AS EXPOSURE_RANK
FROM agg;

SELECT NAICS, INDUSTRY_TITLE, TOTAL_EMP, EMP_COVERAGE, AI_EXPOSURE, EXPOSURE_RANK
FROM ANALYTICS.INDUSTRY_EXPOSURE_FACT
ORDER BY AI_EXPOSURE DESC NULLS LAST;
