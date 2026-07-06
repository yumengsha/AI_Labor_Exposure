#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_refresh.sh - wrapper that a scheduler (cron / launchd) calls.
#
# It activates the project's virtualenv and runs the refresh pipeline, logging
# output with a timestamp. Edit PROJECT_DIR to match your machine.
#
# By default it runs the FULL pipeline (--load), which WRITES to Snowflake.
# If your policy is read-only, drop the --load flag to fetch+prepare only.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- EDIT THIS to your absolute project path -------------------------------
PROJECT_DIR="${AI_LABOR_HOME:-$HOME/ai_labor_snowflake}"

cd "$PROJECT_DIR"

# Activate virtualenv if present (created via: python3 -m venv .venv).
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$LOG_DIR/refresh_$STAMP.log"

echo "=== AI-labor refresh started $(date) ===" | tee "$LOG"

# --load  -> also perform Snowflake writes (COPY INTO + rebuild).
# Remove --load to do local fetch+prepare only (no remote writes).
python python/refresh_pipeline.py --load >>"$LOG" 2>&1

echo "=== finished $(date) ===" | tee -a "$LOG"
