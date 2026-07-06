/* ============================================================================
   15_axis_wage_band.sql  -  Analytical axis 3: Wage percentile band
   ----------------------------------------------------------------------------
   Employment-weighted rollup of the occupation index to Low/Middle/High wage
   bands (from WAGE_PERCENTILE = PERCENT_RANK on A_MEDIAN, mapped via
   DIM_WAGE_BAND in script 12):
       WageBand Exposure = Σ(OCC_AI_EXPOSURE × TOT_EMP) / Σ(TOT_EMP)

   National occupation grain (wage percentile does not need a region/industry
   cross). LOW_COVERAGE/NO_ONET occupations (NULL exposure) excluded; EMP_COVERAGE
   reports the scored share.

   Run after 12_occupation_exposure.sql.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    ANALYTICS;

CREATE OR REPLACE TABLE ANALYTICS.WAGE_BAND_EXPOSURE_FACT AS
WITH agg AS (
    SELECT
        WAGE_BAND,
        SUM(TOT_EMP)                                          AS TOTAL_EMP,
        COUNT(*)                                              AS OCC_COUNT,
        SUM(IFF(AI_EXPOSURE IS NOT NULL, TOT_EMP, 0))         AS SCORED_EMP,
        SUM(AI_EXPOSURE  * TOT_EMP) / NULLIF(SUM(IFF(AI_EXPOSURE  IS NOT NULL, TOT_EMP, 0)), 0) AS AI_EXPOSURE,
        SUM(AUTOMATION   * TOT_EMP) / NULLIF(SUM(IFF(AUTOMATION   IS NOT NULL, TOT_EMP, 0)), 0) AS AUTOMATION,
        SUM(AUGMENTATION * TOT_EMP) / NULLIF(SUM(IFF(AUGMENTATION IS NOT NULL, TOT_EMP, 0)), 0) AS AUGMENTATION,
        ANY_VALUE(EXPOSURE_MODE)                              AS EXPOSURE_MODE
    FROM ANALYTICS.OCCUPATION_EXPOSURE_FACT
    WHERE WAGE_BAND IS NOT NULL
    GROUP BY WAGE_BAND
)
SELECT
    a.WAGE_BAND, a.EXPOSURE_MODE,
    b.BAND_ORDER,
    a.TOTAL_EMP, a.OCC_COUNT,
    ROUND(DIV0(a.SCORED_EMP, a.TOTAL_EMP), 4) AS EMP_COVERAGE,
    ROUND(a.AI_EXPOSURE, 4)                   AS AI_EXPOSURE,
    ROUND(a.AUTOMATION, 4)                    AS AUTOMATION,
    ROUND(a.AUGMENTATION, 4)                  AS AUGMENTATION
FROM agg a
LEFT JOIN ANALYTICS.DIM_WAGE_BAND b ON a.WAGE_BAND = b.WAGE_BAND
ORDER BY b.BAND_ORDER;

SELECT * FROM ANALYTICS.WAGE_BAND_EXPOSURE_FACT;
