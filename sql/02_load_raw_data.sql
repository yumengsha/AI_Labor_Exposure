/* ============================================================================
   02_load_raw_data.sql
   ----------------------------------------------------------------------------
   Purpose : Load the prepared local files into the RAW tables using an internal
             stage + COPY INTO.

   Prerequisites:
     1. Run 00_create_environment.sql and 01_create_raw_tables.sql first.
     2. Run  python/prepare_data.py  to produce the CSVs in data/raw/:
            oews_2022.csv ... oews_2025.csv   (comma separated, header row)
            onet_task_ratings.csv             (TAB separated, header row)
            onet_task_statements.csv          (TAB separated, header row)
     3. Upload those files to the stage. TWO options:
          (a) Easiest: run  python/load_local_files.py  (does PUT + COPY for you).
          (b) Manual: use SnowSQL and the PUT commands shown in section 2 below,
              then run the COPY INTO statements in section 3.
        NOTE: the Snowflake web UI worksheet cannot run PUT (it has no access to
        your local disk). Use SnowSQL, the Python loader, or drag-and-drop upload.
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    RAW;

/* ============================================================================
   1. FILE FORMATS
   ----------------------------------------------------------------------------
   Two formats: one for the comma-separated OEWS CSVs, one for the tab-separated
   O*NET text files. Both skip the header row and treat common "missing value"
   tokens as NULL so the text stays clean.
   ============================================================================ */

-- OEWS: comma separated, values may be quoted (titles contain commas).
CREATE OR REPLACE FILE FORMAT RAW.FF_OEWS_CSV
    TYPE = 'CSV'
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    TRIM_SPACE = TRUE
    EMPTY_FIELD_AS_NULL = TRUE
    NULL_IF = ('', '*', '#', '**', 'NA', 'N/A')
    ENCODING = 'UTF8'
    COMMENT = 'Comma-separated OEWS files produced by prepare_data.py';

-- O*NET: tab separated. The task statement text can contain commas and quotes,
-- so a tab delimiter avoids any comma-splitting problems.
CREATE OR REPLACE FILE FORMAT RAW.FF_ONET_TSV
    TYPE = 'CSV'
    FIELD_DELIMITER = '\t'
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = NONE
    TRIM_SPACE = TRUE
    EMPTY_FIELD_AS_NULL = TRUE
    NULL_IF = ('', 'n/a', 'N/A')
    ENCODING = 'UTF8'
    COMMENT = 'Tab-separated O*NET files';

/* ============================================================================
   2. INTERNAL STAGE + FILE UPLOAD (PUT)
   ----------------------------------------------------------------------------
   One named internal stage holds every input file. PUT copies a local file to
   the stage; it must be run from SnowSQL or the Python connector (not the web
   worksheet). The commands below assume this project lives at the path shown -
   adjust the local path to match your machine, or just use the Python loader.
   ============================================================================ */

CREATE STAGE IF NOT EXISTS RAW.LOCAL_STAGE
    COMMENT = 'Internal stage for local BLS OEWS + O*NET files';

/* ---- Example PUT commands (SnowSQL only) --------------------------------
   AUTO_COMPRESS gzips the file in transit; COPY INTO reads gzip transparently.

   PUT 'file://.../ai_labor_snowflake/data/raw/oews_2022.csv'            @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
   PUT 'file://.../ai_labor_snowflake/data/raw/oews_2023.csv'            @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
   PUT 'file://.../ai_labor_snowflake/data/raw/oews_2024.csv'            @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
   PUT 'file://.../ai_labor_snowflake/data/raw/oews_2025.csv'            @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
   PUT 'file://.../ai_labor_snowflake/data/raw/onet_task_ratings.csv'    @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
   PUT 'file://.../ai_labor_snowflake/data/raw/onet_task_statements.csv' @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;

   -- confirm the uploads:
   LIST @RAW.LOCAL_STAGE;
   -------------------------------------------------------------------------- */

/* ============================================================================
   3. COPY INTO
   ----------------------------------------------------------------------------
   OEWS: we add the DATA_YEAR literal per file by loading through a SELECT that
   reads the 32 staged columns positionally ($1..$32) and appends the year.
   Re-running is safe: FORCE=FALSE (default) skips files already loaded. To
   force a full reload, TRUNCATE the table first or add FORCE=TRUE.
   ============================================================================ */

-- ---- BLS OEWS 2022 -------------------------------------------------------
COPY INTO RAW.BLS_OEWS_RAW
    (AREA, AREA_TITLE, AREA_TYPE, PRIM_STATE, NAICS, NAICS_TITLE, I_GROUP,
     OWN_CODE, OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, EMP_PRSE, JOBS_1000,
     LOC_QUOTIENT, PCT_TOTAL, PCT_RPT, H_MEAN, A_MEAN, MEAN_PRSE, H_PCT10,
     H_PCT25, H_MEDIAN, H_PCT75, H_PCT90, A_PCT10, A_PCT25, A_MEDIAN, A_PCT75,
     A_PCT90, ANNUAL, HOURLY, DATA_YEAR)
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
           $20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32, 2022
    FROM @RAW.LOCAL_STAGE
)
FILES = ('oews_2022.csv.gz')
FILE_FORMAT = (FORMAT_NAME = RAW.FF_OEWS_CSV)
ON_ERROR = 'CONTINUE';

-- ---- BLS OEWS 2023 -------------------------------------------------------
COPY INTO RAW.BLS_OEWS_RAW
    (AREA, AREA_TITLE, AREA_TYPE, PRIM_STATE, NAICS, NAICS_TITLE, I_GROUP,
     OWN_CODE, OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, EMP_PRSE, JOBS_1000,
     LOC_QUOTIENT, PCT_TOTAL, PCT_RPT, H_MEAN, A_MEAN, MEAN_PRSE, H_PCT10,
     H_PCT25, H_MEDIAN, H_PCT75, H_PCT90, A_PCT10, A_PCT25, A_MEDIAN, A_PCT75,
     A_PCT90, ANNUAL, HOURLY, DATA_YEAR)
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
           $20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32, 2023
    FROM @RAW.LOCAL_STAGE
)
FILES = ('oews_2023.csv.gz')
FILE_FORMAT = (FORMAT_NAME = RAW.FF_OEWS_CSV)
ON_ERROR = 'CONTINUE';

-- ---- BLS OEWS 2024 -------------------------------------------------------
COPY INTO RAW.BLS_OEWS_RAW
    (AREA, AREA_TITLE, AREA_TYPE, PRIM_STATE, NAICS, NAICS_TITLE, I_GROUP,
     OWN_CODE, OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, EMP_PRSE, JOBS_1000,
     LOC_QUOTIENT, PCT_TOTAL, PCT_RPT, H_MEAN, A_MEAN, MEAN_PRSE, H_PCT10,
     H_PCT25, H_MEDIAN, H_PCT75, H_PCT90, A_PCT10, A_PCT25, A_MEDIAN, A_PCT75,
     A_PCT90, ANNUAL, HOURLY, DATA_YEAR)
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
           $20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32, 2024
    FROM @RAW.LOCAL_STAGE
)
FILES = ('oews_2024.csv.gz')
FILE_FORMAT = (FORMAT_NAME = RAW.FF_OEWS_CSV)
ON_ERROR = 'CONTINUE';

-- ---- BLS OEWS 2025 -------------------------------------------------------
COPY INTO RAW.BLS_OEWS_RAW
    (AREA, AREA_TITLE, AREA_TYPE, PRIM_STATE, NAICS, NAICS_TITLE, I_GROUP,
     OWN_CODE, OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, EMP_PRSE, JOBS_1000,
     LOC_QUOTIENT, PCT_TOTAL, PCT_RPT, H_MEAN, A_MEAN, MEAN_PRSE, H_PCT10,
     H_PCT25, H_MEDIAN, H_PCT75, H_PCT90, A_PCT10, A_PCT25, A_MEDIAN, A_PCT75,
     A_PCT90, ANNUAL, HOURLY, DATA_YEAR)
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
           $20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32, 2025
    FROM @RAW.LOCAL_STAGE
)
FILES = ('oews_2025.csv.gz')
FILE_FORMAT = (FORMAT_NAME = RAW.FF_OEWS_CSV)
ON_ERROR = 'CONTINUE';

-- ---- O*NET Task Ratings --------------------------------------------------
COPY INTO RAW.ONET_TASK_RATINGS_RAW
FROM @RAW.LOCAL_STAGE
FILES = ('onet_task_ratings.csv.gz')
FILE_FORMAT = (FORMAT_NAME = RAW.FF_ONET_TSV)
ON_ERROR = 'CONTINUE';

-- ---- O*NET Task Statements ----------------------------------------------
COPY INTO RAW.ONET_TASK_STATEMENTS_RAW
FROM @RAW.LOCAL_STAGE
FILES = ('onet_task_statements.csv.gz')
FILE_FORMAT = (FORMAT_NAME = RAW.FF_ONET_TSV)
ON_ERROR = 'CONTINUE';

/* ============================================================================
   4. QUICK LOAD VERIFICATION
   ============================================================================ */
SELECT 'BLS_OEWS_RAW'            AS table_name, COUNT(*) AS row_count,
       COUNT(DISTINCT DATA_YEAR) AS years FROM RAW.BLS_OEWS_RAW
UNION ALL
SELECT 'ONET_TASK_RATINGS_RAW', COUNT(*), NULL FROM RAW.ONET_TASK_RATINGS_RAW
UNION ALL
SELECT 'ONET_TASK_STATEMENTS_RAW', COUNT(*), NULL FROM RAW.ONET_TASK_STATEMENTS_RAW;

-- Rows loaded per OEWS year (sanity: each year should be a few hundred thousand)
SELECT DATA_YEAR, COUNT(*) AS rows
FROM RAW.BLS_OEWS_RAW
GROUP BY DATA_YEAR
ORDER BY DATA_YEAR;
