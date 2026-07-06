"""
score_tasks.py
==============
Score O*NET tasks for AI exposure with Claude, producing the real Task AI Score that
replaces the placeholder in the warehouse.

Each task is scored **in the context of its occupation** (title + description) on
three independent 0-1 dimensions — exposure, automation, augmentation — plus a
confidence and a one-sentence rationale (see ../rubric/rubric.md).

>>> This script NEVER connects to Snowflake. It reads local CSVs and writes a local
    CSV of scores. Loading into Snowflake is a separate, user-run step. <<<

Modes
-----
    --dry-run            Assemble + print prompts and validate the schema. No API calls.
    --pilot N            Score the first N tasks (smoke test of code/format/distribution).
    --task-ids CSV       Score exactly the tasks whose TASK_IDs are in CSV (e.g. the
                         calibration sample) - the correct set for calibration.
    --all                Score every task via the Batch API (50% cheaper; resumable).
    --resume             Skip tasks already present for this run's model+rubric+prompt.

Calibration comparison must score the SAME tasks the humans annotated, so use
--task-ids with the calibration sample (NOT --pilot, which takes the first N).

Examples
--------
    python scoring/score_tasks.py --dry-run --pilot 5
    python scoring/score_tasks.py --pilot 100
    python scoring/score_tasks.py --all --resume

Credentials
-----------
Uses the standard Anthropic resolution (ANTHROPIC_API_KEY, or an `ant auth` profile).
A local .env at the project root is loaded if python-dotenv is installed. No Snowflake
credentials are read or used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent               # ai_exposure_index/scoring
INDEX_ROOT = HERE.parent                              # ai_exposure_index
PROJECT_ROOT = INDEX_ROOT.parent                     # ai_labor_snowflake
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_DIR = INDEX_ROOT / "data"
RUBRIC_PATH = INDEX_ROOT / "rubric" / "rubric.md"
PROMPT_PATH = INDEX_ROOT / "rubric" / "prompt_template.md"

STATEMENTS_CSV = RAW_DIR / "onet_task_statements.csv"   # tab-sep
RATINGS_CSV = RAW_DIR / "onet_task_ratings.csv"         # tab-sep
OCCDATA_CSV = RAW_DIR / "onet_occupation_data.csv"      # tab-sep

MODEL_ID = "claude-opus-4-8"
OUTPUT_COLUMNS = [
    "TASK_ID", "ONET_SOC_CODE",
    "AI_EXPOSURE_SCORE", "AUTOMATION_SCORE", "AUGMENTATION_SCORE",
    "CONFIDENCE", "RATIONALE", "REVIEW_STATUS",
    "SCORING_RUN_ID", "RUBRIC_VERSION", "RUBRIC_HASH", "PROMPT_VERSION",
    "MODEL_ID", "SCORED_AT", "ERROR_MESSAGE",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass  # env / ant-auth profile may already provide credentials


def frontmatter_version(path: Path, key: str) -> str:
    """Read a `key: value` from a markdown YAML frontmatter block."""
    if not path.exists():
        return "unknown"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        block = text[3:end] if end != -1 else ""
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip() == key:
                    return v.strip()
    return "unknown"


def sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def read_tsv(path: Path):
    """Yield dict rows from a tab-separated file (utf-8, tolerant)."""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        yield from csv.DictReader(fh, delimiter="\t")


# ---------------------------------------------------------------------------
# Build the task work-list (statements + importance + occupation context)
# ---------------------------------------------------------------------------
def load_tasks() -> list[dict]:
    """Join task statements to importance (raw 1-5) and occupation title/description."""
    for p in (STATEMENTS_CSV, OCCDATA_CSV):
        if not p.exists():
            sys.exit(f"ERROR: missing {p}. Run python/prepare_data.py first.")

    # Occupation context by full SOC code.
    occ = {}
    for r in read_tsv(OCCDATA_CSV):
        occ[r["O*NET-SOC Code"].strip()] = (
            r.get("Title", "").strip(),
            r.get("Description", "").strip(),
        )

    # Importance (IM) by (SOC, Task ID), raw value.
    importance = {}
    if RATINGS_CSV.exists():
        for r in read_tsv(RATINGS_CSV):
            if r.get("Scale ID", "").strip() == "IM":
                key = (r["O*NET-SOC Code"].strip(), r["Task ID"].strip())
                try:
                    importance[key] = float(r["Data Value"])
                except (ValueError, KeyError):
                    pass

    tasks = []
    for r in read_tsv(STATEMENTS_CSV):
        soc = r["O*NET-SOC Code"].strip()
        tid = r["Task ID"].strip()
        title, desc = occ.get(soc, ("", ""))
        tasks.append({
            "task_id": tid,
            "onet_soc_code": soc,
            "task_statement": r.get("Task", "").strip(),
            "task_type": r.get("Task Type", "").strip() or "n/a",
            "importance_raw": importance.get((soc, tid)),   # may be None
            "occupation_title": title,
            "occupation_description": desc,
        })
    return tasks


def build_user_message(t: dict) -> str:
    imp = f"{t['importance_raw']:.2f}" if t["importance_raw"] is not None else "not rated"
    return (
        "Score this single task for AI exposure, using the rubric.\n\n"
        "OCCUPATION\n"
        f"  O*NET-SOC code: {t['onet_soc_code']}\n"
        f"  Title: {t['occupation_title'] or '(not available)'}\n"
        f"  Description: {t['occupation_description'] or '(not available)'}\n\n"
        "TASK\n"
        f"  Task ID: {t['task_id']}\n"
        f"  Type: {t['task_type']}            (Core = central; Supplemental = secondary)\n"
        f"  Importance to the occupation: {imp} on a 1-5 scale\n"
        f"  Statement: {t['task_statement']}\n\n"
        "Judge the task as it is actually performed in THIS occupation. Return the "
        "three independent scores (ai_exposure_score, automation_score, "
        "augmentation_score), a confidence, and a one-sentence rationale."
    )


# ---------------------------------------------------------------------------
# Output CSV (append-only)
# ---------------------------------------------------------------------------
def out_path(run_id: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / f"task_ai_scores_{run_id}.csv"


def already_scored(path: Path) -> set[str]:
    """TASK_IDs with a successful (non-error) row already in this run's CSV."""
    done = set()
    if path.exists():
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if not r.get("ERROR_MESSAGE"):
                    done.add(r["TASK_ID"])
    return done


def open_appender(path: Path):
    """Return (file, writer), writing a header only if the file is new/empty."""
    new = not path.exists() or path.stat().st_size == 0
    fh = open(path, "a", encoding="utf-8", newline="")
    w = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
    if new:
        w.writeheader()
    return fh, w


def row_from(t, score, meta, error="", scored_at=""):
    """Assemble one output row (score is a TaskScore or None)."""
    return {
        "TASK_ID": t["task_id"],
        "ONET_SOC_CODE": t["onet_soc_code"],
        "AI_EXPOSURE_SCORE": "" if score is None else round(score.ai_exposure_score, 4),
        "AUTOMATION_SCORE": "" if score is None else round(score.automation_score, 4),
        "AUGMENTATION_SCORE": "" if score is None else round(score.augmentation_score, 4),
        "CONFIDENCE": "" if score is None else round(score.confidence, 4),
        "RATIONALE": "" if score is None else score.rationale,
        "REVIEW_STATUS": "unreviewed",
        "SCORING_RUN_ID": meta["run_id"],
        "RUBRIC_VERSION": meta["rubric_version"],
        "RUBRIC_HASH": meta["rubric_hash"],
        "PROMPT_VERSION": meta["prompt_version"],
        "MODEL_ID": MODEL_ID,
        "SCORED_AT": scored_at,
        "ERROR_MESSAGE": error,
    }


# ---------------------------------------------------------------------------
# Scoring backends
# ---------------------------------------------------------------------------
def make_client():
    try:
        import anthropic
    except ImportError:
        sys.exit("ERROR: `anthropic` not installed. Run: pip install -r requirements.txt")
    return anthropic.Anthropic()


def score_sync(tasks, meta, system_prompt, out_file, now_iso):
    """Score tasks one-by-one (used for --pilot). Streams rows to CSV as it goes."""
    from schema import TaskScore
    client = make_client()
    fh, w = open_appender(out_file)
    ok = err = 0
    try:
        for i, t in enumerate(tasks, 1):
            try:
                resp = client.messages.parse(
                    model=MODEL_ID,
                    max_tokens=1024,
                    thinking={"type": "adaptive"},
                    system=[{"type": "text", "text": system_prompt,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": build_user_message(t)}],
                    output_format=TaskScore,
                )
                w.writerow(row_from(t, resp.parsed_output, meta, scored_at=now_iso))
                ok += 1
            except Exception as exc:  # noqa: BLE001 - record and continue
                w.writerow(row_from(t, None, meta, error=str(exc)[:500], scored_at=now_iso))
                err += 1
            if i % 10 == 0:
                print(f"  scored {i}/{len(tasks)} (ok={ok}, err={err})")
                fh.flush()
    finally:
        fh.close()
    print(f"Done: {ok} scored, {err} errored -> {out_file}")


def score_batch(tasks, meta, system_prompt, out_file, now_iso):
    """Score all tasks via the Batch API (50% cheaper). Submits, polls, writes rows.

    NOTE: the Batch API takes the *raw* create shape, so structured output is
    requested with `output_config={"format": {"type": "json_schema", "schema": ...}}`
    (the JSON schema derived from the Pydantic model) rather than the `messages.parse`
    convenience `output_format=`. This path is exercised only in the gated full run
    (after calibration, with credentials) — re-verify the exact param name against the
    installed anthropic SDK version at that point.
    """
    import time
    from schema import TaskScore
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = make_client()
    schema = TaskScore.model_json_schema()
    schema["additionalProperties"] = False
    output_config = {"format": {"type": "json_schema", "schema": schema}}

    # custom_id must be unique + <=64 chars; TASK_ID is a short integer string.
    requests = [
        Request(
            custom_id=f"task-{t['task_id']}",
            params=MessageCreateParamsNonStreaming(
                model=MODEL_ID,
                max_tokens=1024,
                thinking={"type": "adaptive"},
                system=[{"type": "text", "text": system_prompt,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": build_user_message(t)}],
                output_config=output_config,
            ),
        )
        for t in tasks
    ]
    by_id = {f"task-{t['task_id']}": t for t in tasks}

    print(f"Submitting Batch API job for {len(requests):,} tasks ...")
    batch = client.messages.batches.create(requests=requests)
    print(f"  batch id: {batch.id}")
    while True:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        print(f"  status={b.processing_status} "
              f"processing={b.request_counts.processing}")
        time.sleep(30)

    fh, w = open_appender(out_file)
    ok = err = 0
    try:
        for result in client.messages.batches.results(batch.id):
            t = by_id.get(result.custom_id)
            if t is None:
                continue
            if result.result.type == "succeeded":
                msg = result.result.message
                try:
                    parsed = TaskScore.model_validate_json(
                        next(b.text for b in msg.content if b.type == "text"))
                    w.writerow(row_from(t, parsed, meta, scored_at=now_iso))
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    w.writerow(row_from(t, None, meta, error=f"parse: {exc}"[:500],
                                        scored_at=now_iso))
                    err += 1
            else:
                w.writerow(row_from(t, None, meta,
                                    error=f"{result.result.type}", scored_at=now_iso))
                err += 1
    finally:
        fh.close()
    print(f"Done: {ok} scored, {err} errored -> {out_file}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Assemble + validate prompts, no API calls.")
    ap.add_argument("--pilot", type=int, metavar="N",
                    help="Score only the first N tasks (sync).")
    ap.add_argument("--task-ids", metavar="CSV",
                    help="Score exactly the tasks whose TASK_IDs appear in this CSV "
                         "(e.g. the calibration sample) - the correct apples-to-apples "
                         "set for calibration. Scored synchronously.")
    ap.add_argument("--all", action="store_true",
                    help="Score every task via the Batch API.")
    ap.add_argument("--resume", action="store_true",
                    help="Skip tasks already scored in this run's CSV.")
    ap.add_argument("--run-id", help="Scoring run id (default: derived from versions).")
    args = ap.parse_args()

    load_env()
    rubric_md = RUBRIC_PATH.read_text(encoding="utf-8")
    meta = {
        "rubric_version": frontmatter_version(RUBRIC_PATH, "rubric_version"),
        "rubric_hash": sha8(rubric_md),
        "prompt_version": frontmatter_version(PROMPT_PATH, "prompt_version"),
    }
    # Deterministic run id (no timestamp -> reproducible/resumable). SCORED_AT is
    # passed in per invocation for the audit column.
    meta["run_id"] = args.run_id or (
        f"{meta['rubric_version']}_{meta['prompt_version']}_{meta['rubric_hash']}")
    # SCORED_AT: avoid datetime.now() flakiness in constrained envs; use env override
    # or leave to the loader. A plain wall-clock stamp is fine here (not resume-keyed).
    now_iso = os.getenv("SCORED_AT", "")

    tasks = load_tasks()
    print(f"Loaded {len(tasks):,} tasks | run_id={meta['run_id']} "
          f"| rubric={meta['rubric_version']}({meta['rubric_hash']}) "
          f"prompt={meta['prompt_version']}")

    if args.task_ids:
        wanted = set()
        with open(args.task_ids, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if "TASK_ID" not in (reader.fieldnames or []):
                sys.exit(f"ERROR: {args.task_ids} has no TASK_ID column.")
            for r in reader:
                tid = (r.get("TASK_ID") or "").strip()
                if tid:
                    wanted.add(tid)
        tasks = [t for t in tasks if t["task_id"] in wanted]
        missing = len(wanted) - len(tasks)
        print(f"--task-ids: {len(wanted):,} ids requested, {len(tasks):,} matched"
              + (f", {missing:,} not found in the task list" if missing else ""))

    if args.pilot:
        tasks = tasks[: args.pilot]

    of = out_path(meta["run_id"])
    if args.resume:
        done = already_scored(of)
        before = len(tasks)
        tasks = [t for t in tasks if t["task_id"] not in done]
        print(f"Resume: {len(done):,} already scored; {before - len(tasks):,} skipped, "
              f"{len(tasks):,} to score.")

    if args.dry_run:
        system_len = len(rubric_md)
        print(f"\n[dry-run] system prompt (rubric) = {system_len:,} chars, cached")
        for t in tasks[: min(len(tasks), 5)]:
            print("\n" + "=" * 70)
            print(build_user_message(t))
        # validate the schema loads
        from schema import TaskScore
        TaskScore(ai_exposure_score=0.5, automation_score=0.4,
                  augmentation_score=0.6, confidence=0.7, rationale="ok")
        print(f"\n[dry-run] schema validates OK. {len(tasks):,} tasks would be scored. "
              "No API calls made.")
        return

    if not tasks:
        print("Nothing to score (all done for this run). Use a new --run-id to re-score.")
        return

    system_prompt = rubric_md
    if args.all:
        score_batch(tasks, meta, system_prompt, of, now_iso)
    elif args.pilot or args.task_ids:
        # both are bounded, synchronous runs (calibration-scale)
        score_sync(tasks, meta, system_prompt, of, now_iso)
    else:
        ap.error("choose a mode: --dry-run, --pilot N, --task-ids CSV, or --all")


if __name__ == "__main__":
    main()
