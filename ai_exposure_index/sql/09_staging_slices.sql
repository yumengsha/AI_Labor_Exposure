/* ============================================================================
   09_staging_slices.sql  -  Extra STAGING views for the industry + region axes
   ----------------------------------------------------------------------------
   Parallels STAGING.STG_BLS_OEWS_NATIONAL (in sql/03), but slices the other
   AREA_TYPE / I_GROUP combinations the axes need. Authored here (not by editing
   sql/03) so the exposure-index work is self-contained.

   All views read the latest DATA_YEAR from the already-cleaned STG_BLS_OEWS.

   Run after sql/03_create_staging_views.sql, before the axis scripts (13, 14).
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    STAGING;

/* ---- Industry axis source: national, sector, PRIVATE ownership, detailed ----
   v1 uses OWN_CODE='5' (private) only - there is no single all-ownership sector
   figure in OEWS, and mixing ownership codes would double-count employment. */
CREATE OR REPLACE VIEW STAGING.STG_BLS_OEWS_INDUSTRY AS
WITH latest AS (SELECT MAX(DATA_YEAR) AS max_year FROM STAGING.STG_BLS_OEWS)
SELECT
    b.DATA_YEAR, b.OCC_CODE, b.OCC_TITLE, b.O_GROUP,
    b.NAICS, b.INDUSTRY_TITLE, b.OWN_CODE,
    b.TOT_EMP, b.A_MEAN, b.A_MEDIAN
FROM STAGING.STG_BLS_OEWS b, latest
WHERE b.DATA_YEAR = latest.max_year
  AND b.AREA_TYPE = '1'                 -- national
  AND b.I_GROUP   = 'sector'            -- 2-digit NAICS sectors only
  AND b.OWN_CODE  = '5'                 -- private ownership (v1)
  AND b.O_GROUP   = 'detailed';

/* ---- Region axis source: State + Metro + Nonmetro, cross-industry, detailed ----
   One view spanning all three geographic granularities; GRANULARITY is derived
   from AREA_TYPE so scripts group by (GRANULARITY, AREA). All rows are
   OWN_CODE='1235' cross-industry detailed (verified single-ownership slices). */
CREATE OR REPLACE VIEW STAGING.STG_BLS_OEWS_REGION AS
WITH latest AS (SELECT MAX(DATA_YEAR) AS max_year FROM STAGING.STG_BLS_OEWS)
SELECT
    b.DATA_YEAR,
    CASE b.AREA_TYPE
        WHEN '2' THEN 'State'
        WHEN '4' THEN 'Metropolitan'
        WHEN '6' THEN 'Nonmetropolitan'
    END                                 AS GRANULARITY,
    b.AREA, b.AREA_TITLE, b.STATE,
    b.OCC_CODE, b.OCC_TITLE, b.O_GROUP,
    b.TOT_EMP, b.A_MEAN, b.A_MEDIAN
FROM STAGING.STG_BLS_OEWS b, latest
WHERE b.DATA_YEAR = latest.max_year
  AND b.AREA_TYPE IN ('2', '4', '6')    -- state / metro / nonmetro
  AND b.I_GROUP   = 'cross-industry'
  AND b.OWN_CODE  = '1235'              -- all ownerships (only code at these levels)
  AND b.O_GROUP   = 'detailed';

/* ---- preview ---- */
SELECT 'INDUSTRY' AS slice, COUNT(*) AS rows, COUNT(DISTINCT NAICS) AS keys
FROM STAGING.STG_BLS_OEWS_INDUSTRY
UNION ALL
SELECT 'REGION ' || GRANULARITY, COUNT(*), COUNT(DISTINCT AREA)
FROM STAGING.STG_BLS_OEWS_REGION
GROUP BY GRANULARITY;
