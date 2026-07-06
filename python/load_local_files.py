"""
load_local_files.py
====================
Upload the prepared local files from data/raw/ into the Snowflake internal
stage and run COPY INTO to populate the RAW tables.

This automates section 2 (PUT) and section 3 (COPY INTO) of
sql/02_load_raw_data.sql, which the Snowflake web worksheet cannot do because
PUT needs access to your local disk.

Prerequisites
-------------
1. Run sql/00_create_environment.sql and sql/01_create_raw_tables.sql once
   (creates the warehouse, database, schemas, RAW tables).
2. Run: python python/prepare_data.py   (creates the CSVs in data/raw/).
3. Configure .env (see .env.example) - external browser auth, no password.
4. python python/load_local_files.py

Notes
-----
* Uses external browser authentication (same as test_connection.py).
* This script also creates the file formats + stage if they do not exist, so it
  can run even if you only executed scripts 00 and 01.
* Re-running is safe: PUT uses OVERWRITE, and each OEWS COPY targets one file.
  Pass --truncate to empty the RAW tables before loading (full refresh).
"""

from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Paths & file lists
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

STAGE = "RAW.LOCAL_STAGE"

# OEWS files -> the DATA_YEAR literal to stamp on each row during COPY.
OEWS_FILES = {
    "oews_2022.csv": 2022,
    "oews_2023.csv": 2023,
    "oews_2024.csv": 2024,
    "oews_2025.csv": 2025,
}
ONET_RATINGS_FILE = "onet_task_ratings.csv"
ONET_STATEMENTS_FILE = "onet_task_statements.csv"

# The 32 positional OEWS columns, in file order, for the COPY SELECT.
OEWS_COLUMNS = (
    "AREA, AREA_TITLE, AREA_TYPE, PRIM_STATE, NAICS, NAICS_TITLE, I_GROUP, "
    "OWN_CODE, OCC_CODE, OCC_TITLE, O_GROUP, TOT_EMP, EMP_PRSE, JOBS_1000, "
    "LOC_QUOTIENT, PCT_TOTAL, PCT_RPT, H_MEAN, A_MEAN, MEAN_PRSE, H_PCT10, "
    "H_PCT25, H_MEDIAN, H_PCT75, H_PCT90, A_PCT10, A_PCT25, A_MEDIAN, A_PCT75, "
    "A_PCT90, ANNUAL, HOURLY"
)


# ---------------------------------------------------------------------------
# Connection - shared helper supports both externalbrowser and key-pair auth.
# ---------------------------------------------------------------------------
from sf_connect import get_connection


def connect():
    # schema=RAW because this script stages + COPYs into RAW.
    return get_connection(schema="RAW")


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------
def run(cur, sql: str, label: str | None = None) -> None:
    """Execute one statement and print a short status line."""
    if label:
        print(f"  -> {label}")
    cur.execute(sql)


def ensure_objects(cur) -> None:
    """Create the file formats + stage if scripts 00/01 didn't (idempotent)."""
    run(cur, "USE SCHEMA RAW", "USE SCHEMA RAW")
    run(cur, """
        CREATE FILE FORMAT IF NOT EXISTS RAW.FF_OEWS_CSV
            TYPE='CSV' FIELD_DELIMITER=',' SKIP_HEADER=1
            FIELD_OPTIONALLY_ENCLOSED_BY='"' TRIM_SPACE=TRUE
            EMPTY_FIELD_AS_NULL=TRUE
            NULL_IF=('','*','#','**','NA','N/A') ENCODING='UTF8'
    """, "file format FF_OEWS_CSV")
    run(cur, r"""
        CREATE FILE FORMAT IF NOT EXISTS RAW.FF_ONET_TSV
            TYPE='CSV' FIELD_DELIMITER='\t' SKIP_HEADER=1
            FIELD_OPTIONALLY_ENCLOSED_BY=NONE TRIM_SPACE=TRUE
            EMPTY_FIELD_AS_NULL=TRUE NULL_IF=('','n/a','N/A') ENCODING='UTF8'
    """, "file format FF_ONET_TSV")
    run(cur, f"CREATE STAGE IF NOT EXISTS {STAGE}", f"stage {STAGE}")


def put_file(cur, local_path: str) -> None:
    """PUT a local file to the stage (gzip-compressed, overwrite)."""
    if not os.path.exists(local_path):
        print(f"  [skip] not found: {local_path}")
        return
    # Forward slashes work cross-platform inside the file:// URI.
    uri = "file://" + local_path.replace("\\", "/")
    print(f"  PUT {os.path.basename(local_path)} ...")
    cur.execute(f"PUT '{uri}' @{STAGE} AUTO_COMPRESS=TRUE OVERWRITE=TRUE")


def copy_oews(cur, filename: str, year: int) -> None:
    """COPY one OEWS file, appending the DATA_YEAR literal."""
    gz = filename + ".gz"
    sql = f"""
        COPY INTO RAW.BLS_OEWS_RAW ({OEWS_COLUMNS}, DATA_YEAR)
        FROM (
            SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                   $18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,
                   {year}
            FROM @{STAGE}
        )
        FILES = ('{gz}')
        FILE_FORMAT = (FORMAT_NAME = RAW.FF_OEWS_CSV)
        ON_ERROR = 'CONTINUE'
    """
    print(f"  COPY INTO BLS_OEWS_RAW  <- {gz} (year {year})")
    cur.execute(sql)
    for row in cur.fetchall():
        print(f"     {row}")


def copy_onet(cur, filename: str, table: str) -> None:
    gz = filename + ".gz"
    sql = f"""
        COPY INTO RAW.{table}
        FROM @{STAGE}
        FILES = ('{gz}')
        FILE_FORMAT = (FORMAT_NAME = RAW.FF_ONET_TSV)
        ON_ERROR = 'CONTINUE'
    """
    print(f"  COPY INTO {table}  <- {gz}")
    cur.execute(sql)
    for row in cur.fetchall():
        print(f"     {row}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--truncate", action="store_true",
                        help="Empty the RAW tables before loading (full refresh).")
    args = parser.parse_args()

    if not os.path.isdir(RAW_DIR):
        sys.exit(f"ERROR: {RAW_DIR} not found. Run prepare_data.py first.")

    conn = connect()   # get_connection() loads .env internally
    cur = conn.cursor()

    try:
        ensure_objects(cur)

        if args.truncate:
            print("\nTruncating RAW tables (full refresh) ...")
            for t in ("BLS_OEWS_RAW", "ONET_TASK_RATINGS_RAW",
                      "ONET_TASK_STATEMENTS_RAW"):
                run(cur, f"TRUNCATE TABLE IF EXISTS RAW.{t}", f"truncate {t}")

        # ---- Upload every prepared file to the stage --------------------
        print("\n[1/2] Uploading files to stage ...")
        for fname in list(OEWS_FILES) + [ONET_RATINGS_FILE, ONET_STATEMENTS_FILE]:
            put_file(cur, os.path.join(RAW_DIR, fname))

        # ---- COPY INTO the RAW tables -----------------------------------
        print("\n[2/2] Loading staged files into RAW tables ...")
        for fname, year in OEWS_FILES.items():
            if os.path.exists(os.path.join(RAW_DIR, fname)):
                copy_oews(cur, fname, year)
        if os.path.exists(os.path.join(RAW_DIR, ONET_RATINGS_FILE)):
            copy_onet(cur, ONET_RATINGS_FILE, "ONET_TASK_RATINGS_RAW")
        if os.path.exists(os.path.join(RAW_DIR, ONET_STATEMENTS_FILE)):
            copy_onet(cur, ONET_STATEMENTS_FILE, "ONET_TASK_STATEMENTS_RAW")

        # ---- Row-count summary ------------------------------------------
        print("\nRow counts after load:")
        for t in ("BLS_OEWS_RAW", "ONET_TASK_RATINGS_RAW",
                  "ONET_TASK_STATEMENTS_RAW"):
            cur.execute(f"SELECT COUNT(*) FROM RAW.{t}")
            print(f"  RAW.{t:<26} {cur.fetchone()[0]:>12,}")

        print("\nDONE. Next: run sql/03, sql/04, sql/05 in the worksheet or "
              "SnowSQL to build STAGING, ANALYTICS, and QUALITY.")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"\nLOAD FAILED: {exc}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
