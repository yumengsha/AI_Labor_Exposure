/* ============================================================================
   10_task_ai_scores_raw.sql
   ----------------------------------------------------------------------------
   Purpose : RAW landing table for the real Task AI Scores produced by Claude
             (ai_exposure_index/scoring/score_tasks.py).

   Design:
     * APPEND-ONLY. Every scoring run inserts rows tagged with its SCORING_RUN_ID
       and full provenance (rubric version+hash, prompt version, model id). We
       never truncate, so historical runs remain reproducible and comparable.
       STAGING (script 11) selects the single "current approved" run.
     * All columns VARCHAR in RAW (consistent with the rest of the warehouse);
       casting + range checks happen in STAGING.
     * Provenance is split into separate columns - MODEL_ID / RUBRIC_VERSION /
       RUBRIC_HASH / PROMPT_VERSION - never one overloaded "version" field.

   Load: score_tasks.py writes ai_exposure_index/data/task_ai_scores_<run>.csv;
   upload it to a stage and COPY INTO this table (see the loader note at bottom).

   Run after the base warehouse exists (sql/00, sql/01).
   ============================================================================ */

USE WAREHOUSE AI_LABOR_WH;
USE DATABASE  AI_LABOR_ANALYTICS;
USE SCHEMA    RAW;

/* ----------------------------------------------------------------------------
   Scores table (append-only). CREATE IF NOT EXISTS so re-running this script
   never drops accumulated runs.
   ---------------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS RAW.TASK_AI_SCORES_RAW (
    TASK_ID             VARCHAR,   -- O*NET Task ID (integer as text)
    ONET_SOC_CODE       VARCHAR,   -- full O*NET SOC, e.g. 11-1011.00
    AI_EXPOSURE_SCORE   VARCHAR,   -- 0..1 overall exposure
    AUTOMATION_SCORE    VARCHAR,   -- 0..1 replace-the-human
    AUGMENTATION_SCORE  VARCHAR,   -- 0..1 assist-the-human
    CONFIDENCE          VARCHAR,   -- 0..1 model confidence
    RATIONALE           VARCHAR,   -- one-sentence reason
    REVIEW_STATUS       VARCHAR,   -- unreviewed / approved / rejected
    SCORING_RUN_ID      VARCHAR,   -- groups a run (rubric+prompt+hash by default)
    RUBRIC_VERSION      VARCHAR,
    RUBRIC_HASH         VARCHAR,
    PROMPT_VERSION      VARCHAR,
    MODEL_ID            VARCHAR,   -- e.g. claude-opus-4-8
    SCORED_AT           VARCHAR,   -- ISO timestamp (optional)
    ERROR_MESSAGE       VARCHAR,   -- non-empty => this task failed to score
    LOADED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Append-only Claude task AI scores with full provenance. Clean in STAGING.';

/* ----------------------------------------------------------------------------
   File format for the score CSV (comma-separated, header, quoted rationale).
   ---------------------------------------------------------------------------- */
CREATE FILE FORMAT IF NOT EXISTS RAW.FF_TASK_SCORES_CSV
    TYPE = 'CSV'
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    TRIM_SPACE = TRUE
    EMPTY_FIELD_AS_NULL = TRUE
    ENCODING = 'UTF8'
    COMMENT = 'Task AI score CSVs from score_tasks.py';

/* ----------------------------------------------------------------------------
   Which scoring run is authoritative for STAGING/ANALYTICS. One row; update it
   to promote a new run after calibration + review. Kept as a table (not a
   hardcoded constant) so promoting a run is a single UPDATE, fully auditable.
   ---------------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS RAW.TASK_AI_SCORES_APPROVED_RUN (
    SCORING_RUN_ID  VARCHAR,
    APPROVED_AT     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    NOTE            VARCHAR
);
-- Example (run after loading + approving a run):
--   DELETE FROM RAW.TASK_AI_SCORES_APPROVED_RUN;
--   INSERT INTO RAW.TASK_AI_SCORES_APPROVED_RUN (SCORING_RUN_ID, NOTE)
--   VALUES ('v1_v1_eb9e00b9', 'Calibrated 2026-07, MAE within annotator ceiling');

/* ----------------------------------------------------------------------------
   Loader note (run via SnowSQL / the Python loader, not the web worksheet):
     PUT 'file://.../ai_exposure_index/data/task_ai_scores_<run>.csv'
         @RAW.LOCAL_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
     COPY INTO RAW.TASK_AI_SCORES_RAW
         (TASK_ID, ONET_SOC_CODE, AI_EXPOSURE_SCORE, AUTOMATION_SCORE,
          AUGMENTATION_SCORE, CONFIDENCE, RATIONALE, REVIEW_STATUS,
          SCORING_RUN_ID, RUBRIC_VERSION, RUBRIC_HASH, PROMPT_VERSION,
          MODEL_ID, SCORED_AT, ERROR_MESSAGE)
     FROM @RAW.LOCAL_STAGE
     FILES = ('task_ai_scores_<run>.csv.gz')
     FILE_FORMAT = (FORMAT_NAME = RAW.FF_TASK_SCORES_CSV)
     ON_ERROR = 'CONTINUE';
   ---------------------------------------------------------------------------- */

SELECT 'TASK_AI_SCORES_RAW' AS table_name, COUNT(*) AS rows,
       COUNT(DISTINCT SCORING_RUN_ID) AS runs
FROM RAW.TASK_AI_SCORES_RAW;
