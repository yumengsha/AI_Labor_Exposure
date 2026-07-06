/* ============================================================================
   01_create_raw_tables.sql
   ----------------------------------------------------------------------------
   Purpose : Create the RAW landing tables that mirror the source files
             column-for-column.

   Design rule for RAW:
     * Load everything as VARCHAR (text). We do NOT clean or cast here.
       Numbers in the BLS files contain commas, asterisks ("*"), pound signs
       ("#") and blanks; loading as text guarantees COPY INTO never fails on a
       stray character. All casting/cleaning happens later in STAGING.
     * Column order matches the CSV column order exactly so COPY INTO can load
       positionally.

   Source layouts (verified against the actual files):
     BLS OEWS  : 32 columns, one workbook per year (2022-2025).
     O*NET Task Ratings    : 12 tab-separated columns.
     O*NET Task Statements :  7 tab-separated columns.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    RAW;

/* ----------------------------------------------------------------------------
   1. BLS OEWS - one table holding all years.
      A DATA_YEAR column is added (populated during load) so we can keep 2022,
      2023, 2024, and 2025 side by side and pick the latest for analytics.
      The 32 data columns below are in the exact order of the OEWS files.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE RAW.BLS_OEWS_RAW (
    AREA          VARCHAR,   -- area code (99 = U.S., state FIPS, MSA code, ...)
    AREA_TITLE    VARCHAR,   -- human-readable area name
    AREA_TYPE     VARCHAR,   -- 1=National 2=State 3=Territory 4=Metro 6=Nonmetro
    PRIM_STATE    VARCHAR,   -- primary state postal abbreviation
    NAICS         VARCHAR,   -- industry code (000000 = cross-industry)
    NAICS_TITLE   VARCHAR,   -- industry name
    I_GROUP       VARCHAR,   -- industry aggregation level (cross-industry, sector, ...)
    OWN_CODE      VARCHAR,   -- ownership code
    OCC_CODE      VARCHAR,   -- SOC occupation code, e.g. 11-1021
    OCC_TITLE     VARCHAR,   -- occupation title
    O_GROUP       VARCHAR,   -- total / major / minor / broad / detailed
    TOT_EMP       VARCHAR,   -- total employment (may contain commas / blanks)
    EMP_PRSE      VARCHAR,   -- percent relative standard error for TOT_EMP
    JOBS_1000     VARCHAR,   -- jobs per 1,000 (area/industry specific)
    LOC_QUOTIENT  VARCHAR,   -- location quotient
    PCT_TOTAL     VARCHAR,   -- percent of industry total employment
    PCT_RPT       VARCHAR,   -- percent of establishments reporting
    H_MEAN        VARCHAR,   -- mean hourly wage
    A_MEAN        VARCHAR,   -- mean annual wage
    MEAN_PRSE     VARCHAR,   -- percent relative standard error for the mean
    H_PCT10       VARCHAR,   -- hourly wage 10th percentile
    H_PCT25       VARCHAR,
    H_MEDIAN      VARCHAR,   -- hourly median wage
    H_PCT75       VARCHAR,
    H_PCT90       VARCHAR,
    A_PCT10       VARCHAR,   -- annual wage 10th percentile
    A_PCT25       VARCHAR,
    A_MEDIAN      VARCHAR,   -- annual median wage
    A_PCT75       VARCHAR,
    A_PCT90       VARCHAR,
    ANNUAL        VARCHAR,   -- "TRUE" if only annual wages are released
    HOURLY        VARCHAR,   -- "TRUE" if only hourly wages are released
    DATA_YEAR     INTEGER    -- populated by COPY INTO (see 02_load_raw_data.sql)
)
COMMENT = 'Raw BLS OEWS rows, all years, loaded as text. Clean in STAGING.';

/* ----------------------------------------------------------------------------
   2. O*NET Task Ratings (tab separated, 12 columns).
      Scale ID meanings:  IM = Importance, RT = Relevance, FT = Frequency.
      "Data Value" is the rating we aggregate later.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE RAW.ONET_TASK_RATINGS_RAW (
    ONET_SOC_CODE       VARCHAR,   -- e.g. 11-1011.00
    TASK_ID             VARCHAR,   -- integer id linking to a task statement
    SCALE_ID            VARCHAR,   -- IM / RT / FT
    CATEGORY            VARCHAR,   -- frequency category bucket (mostly for FT)
    DATA_VALUE          VARCHAR,   -- the rating value
    N                   VARCHAR,   -- sample size
    STANDARD_ERROR      VARCHAR,
    LOWER_CI_BOUND      VARCHAR,
    UPPER_CI_BOUND      VARCHAR,
    RECOMMEND_SUPPRESS  VARCHAR,   -- Y / N
    DATE_UPDATED        VARCHAR,   -- MM/YYYY
    DOMAIN_SOURCE       VARCHAR
)
COMMENT = 'Raw O*NET task ratings (tab separated), loaded as text.';

/* ----------------------------------------------------------------------------
   3. O*NET Task Statements (tab separated, 7 columns).
      Task Type: Core / Supplemental / n/a.
   ---------------------------------------------------------------------------- */
CREATE OR REPLACE TABLE RAW.ONET_TASK_STATEMENTS_RAW (
    ONET_SOC_CODE           VARCHAR,   -- e.g. 11-1011.00
    TASK_ID                 VARCHAR,   -- integer id (links to task ratings)
    TASK                    VARCHAR,   -- the task statement text
    TASK_TYPE               VARCHAR,   -- Core / Supplemental / n/a
    INCUMBENTS_RESPONDING   VARCHAR,
    DATE_UPDATED            VARCHAR,
    DOMAIN_SOURCE           VARCHAR
)
COMMENT = 'Raw O*NET task statements (tab separated), loaded as text.';

/* ----------------------------------------------------------------------------
   4. Confirm the tables exist.
   ---------------------------------------------------------------------------- */
SHOW TABLES IN SCHEMA RAW;
