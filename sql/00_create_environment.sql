/* ============================================================================
   00_create_environment.sql
   ----------------------------------------------------------------------------
   Purpose : Create the warehouse, database, and the four-layer schema
             structure for the AI labor exposure analytics project.

   Layers  :
     RAW       -> exact, untransformed copies of the source files
     STAGING   -> cleaned column names, standardized codes, cast numbers
     ANALYTICS -> star schema (fact + dimensions) for Tableau
     QUALITY   -> data-quality check queries and results

   Run this FIRST, once, with a role that can create warehouses & databases
   (for example ACCOUNTADMIN or SYSADMIN). Everything here is idempotent:
   "CREATE ... IF NOT EXISTS" means it is safe to re-run.
   ============================================================================ */

-- If your login role cannot create objects, switch to one that can.
-- (Comment this out if your default role is already sufficient.)
USE ROLE SYSADMIN;

/* ----------------------------------------------------------------------------
   1. Virtual warehouse (the compute that runs our queries).
      XSMALL is plenty for this data size and keeps costs low.
      AUTO_SUSPEND stops the warehouse after 60s idle so you are not billed
      while nothing is running.
   ---------------------------------------------------------------------------- */
CREATE WAREHOUSE IF NOT EXISTS AI_LABOR_WH
    WAREHOUSE_SIZE   = 'XSMALL'
    AUTO_SUSPEND     = 60
    AUTO_RESUME      = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Compute warehouse for the AI labor exposure analytics project';

/* ----------------------------------------------------------------------------
   2. Database
   ---------------------------------------------------------------------------- */
CREATE DATABASE IF NOT EXISTS AI_LABOR_ANALYTICS
    COMMENT = 'Combines BLS OEWS employment/wage data with O*NET task data';

/* ----------------------------------------------------------------------------
   3. Schemas (the four analytics layers)
   ---------------------------------------------------------------------------- */
CREATE SCHEMA IF NOT EXISTS AI_LABOR_ANALYTICS.RAW
    COMMENT = 'Untransformed copies of source files (BLS OEWS, O*NET)';

CREATE SCHEMA IF NOT EXISTS AI_LABOR_ANALYTICS.STAGING
    COMMENT = 'Cleaned + standardized views/tables built on top of RAW';

CREATE SCHEMA IF NOT EXISTS AI_LABOR_ANALYTICS.ANALYTICS
    COMMENT = 'Star schema (fact + dimensions) for Tableau dashboards';

CREATE SCHEMA IF NOT EXISTS AI_LABOR_ANALYTICS.QUALITY
    COMMENT = 'Data-quality checks and their results';

/* ----------------------------------------------------------------------------
   4. Set the working context for the rest of the session.
      (Later scripts also set this so each can be run independently.)
   ---------------------------------------------------------------------------- */
USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    RAW;

/* ----------------------------------------------------------------------------
   5. Sanity check - confirm the context is what we expect.
   ---------------------------------------------------------------------------- */
SELECT CURRENT_WAREHOUSE() AS warehouse,
       CURRENT_DATABASE()  AS database,
       CURRENT_SCHEMA()    AS schema,
       CURRENT_ROLE()      AS role;
