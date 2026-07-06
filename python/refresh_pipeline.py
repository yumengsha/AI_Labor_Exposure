"""
refresh_pipeline.py
===================
One-command end-to-end refresh of the AI-labor warehouse:

    1. fetch_sources.py   - download any new BLS OEWS / O*NET files
    2. prepare_data.py    - convert the new downloads to Snowflake-ready CSVs
    3. load_local_files   - PUT to stage + COPY INTO RAW  (writes to Snowflake)
    4. run SQL 03/04/05/06 - rebuild STAGING, ANALYTICS, QUALITY, refresh log

This is the script a scheduler (cron / launchd / GitHub Actions / Snowflake
Task-via-external) invokes. It is safe to run repeatedly: every stage is
idempotent and it exits early with "nothing to do" when no new data exists.

>>> HEADS UP: steps 3-4 WRITE to your Snowflake database (COPY INTO, CREATE OR
    REPLACE). If your policy is "read-only / never write to the remote DB",
    run with --no-snowflake to do only fetch + prepare locally, then load
    yourself when ready. By default this script will NOT run the Snowflake
    write steps unless you pass --load. <<<

Authentication for the write steps uses sf_connect (set SNOWFLAKE_AUTHENTICATOR=
snowflake_jwt with a key pair for unattended runs - see sql/07).

Usage:
    python python/refresh_pipeline.py                 # fetch + prepare only (no writes)
    python python/refresh_pipeline.py --load          # full pipeline incl. Snowflake writes
    python python/refresh_pipeline.py --load --force   # re-download + full rebuild
    python python/refresh_pipeline.py --check-only     # just report if updates exist
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SQL_DIR = ROOT / "sql"
PY = sys.executable


def run_py(script: str, *args) -> subprocess.CompletedProcess:
    """Run one of our python/ scripts, streaming its output."""
    cmd = [PY, str(HERE / script), *args]
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT))


def capture_py(script: str, *args) -> str:
    """Run a python/ script and capture stdout (for parsing the RESULT line)."""
    cmd = [PY, str(HERE / script), *args]
    print(f"\n$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.stdout


# ---------------------------------------------------------------------------
# SQL execution
# ---------------------------------------------------------------------------
def split_sql(text: str) -> list[str]:
    """Split a SQL script into individual statements on ';'.

    Handles '$$'-delimited blocks and single-quoted string literals so a ';'
    inside them does not split a statement. Line (--) and block (/* */)
    comments are stripped first.
    """
    import re
    # strip block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # strip line comments
    text = "\n".join(re.sub(r"--.*$", "", ln) for ln in text.splitlines())

    stmts, buf = [], []
    in_str = False
    in_dollar = False
    i = 0
    while i < len(text):
        ch = text[i]
        two = text[i:i+2]
        if not in_str and two == "$$":
            in_dollar = not in_dollar
            buf.append(two)
            i += 2
            continue
        if not in_dollar and ch == "'":
            in_str = not in_str
            buf.append(ch)
            i += 1
            continue
        if ch == ";" and not in_str and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def run_sql_file(cur, path: Path) -> None:
    """Execute every statement in a .sql file, in order."""
    print(f"\n-- running {path.name} --")
    stmts = split_sql(path.read_text())
    for n, stmt in enumerate(stmts, 1):
        head = " ".join(stmt.split())[:70]
        print(f"  [{n}/{len(stmts)}] {head}...")
        cur.execute(stmt)


def run_snowflake_rebuild(sql_files: list[str]) -> None:
    """Connect once and run the given SQL files in order."""
    from sf_connect import get_connection
    conn = get_connection(schema="RAW")
    cur = conn.cursor()
    try:
        for name in sql_files:
            run_sql_file(cur, SQL_DIR / name)
        # Print the latest refresh-log row as confirmation.
        cur.execute("SELECT VERDICT, FACT_ROWS, QUALITY_FAILS, QUALITY_WARNS, "
                    "BLS_LATEST_YEAR, REFRESHED_AT FROM QUALITY.REFRESH_LOG "
                    "ORDER BY REFRESHED_AT DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            print(f"\nRefresh verdict: {row[0]} | fact_rows={row[1]} "
                  f"| fails={row[2]} warns={row[3]} | bls_year={row[4]} "
                  f"| at {row[5]}")
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--load", action="store_true",
                    help="Also run the Snowflake WRITE steps (load RAW + rebuild). "
                         "Omit to do local fetch+prepare only.")
    ap.add_argument("--force", action="store_true",
                    help="Force re-download and a full reload/rebuild.")
    ap.add_argument("--check-only", action="store_true",
                    help="Only report whether new source data exists; do nothing else.")
    ap.add_argument("--current-year", type=int,
                    help="Passed through to fetch_sources for the OEWS year probe.")
    args = ap.parse_args()

    print("=" * 64)
    print("AI-LABOR WAREHOUSE REFRESH")
    print("=" * 64)

    # ---- Stage 1: detect / fetch ----------------------------------------
    fetch_args = []
    if args.force:
        fetch_args.append("--force")
    if args.check_only:
        fetch_args.append("--check-only")
    if args.current_year:
        fetch_args += ["--current-year", str(args.current_year)]

    out = capture_py("fetch_sources.py", *fetch_args)
    updates = "RESULT: UPDATES_FOUND" in out

    if args.check_only:
        print("\nCheck complete.", "Updates available." if updates
              else "Everything current.")
        return

    if not updates and not args.force:
        print("\nNo new source data. Nothing to prepare or load. Done.")
        return

    # ---- Stage 2: prepare (xlsx -> csv, extract O*NET) ------------------
    r = run_py("prepare_data.py")
    if r.returncode != 0:
        sys.exit("prepare_data.py failed; aborting.")

    if not args.load:
        print("\n" + "=" * 64)
        print("LOCAL PREP COMPLETE (no Snowflake writes performed).")
        print("Prepared CSVs are in data/raw/. To load into Snowflake, re-run")
        print("with --load, or run python/load_local_files.py yourself.")
        print("=" * 64)
        return

    # ---- Stage 3: load RAW (writes to Snowflake) ------------------------
    load_args = ["--truncate"] if args.force else []
    r = run_py("load_local_files.py", *load_args)
    if r.returncode != 0:
        sys.exit("load_local_files.py failed; aborting before rebuild.")

    # ---- Stage 4: rebuild derived layers --------------------------------
    print("\n-- rebuilding STAGING / ANALYTICS / QUALITY --")
    run_snowflake_rebuild([
        "03_create_staging_views.sql",
        "04_create_analytics_tables.sql",
        "05_quality_checks.sql",
        "06_refresh_analytics.sql",
    ])

    print("\n" + "=" * 64)
    print("REFRESH COMPLETE.")
    print("=" * 64)


if __name__ == "__main__":
    main()
