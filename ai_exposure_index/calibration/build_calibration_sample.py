"""
build_calibration_sample.py
===========================
Emit a stratified sample of tasks for INDEPENDENT HUMAN annotation, so the rubric can
be *calibrated* against human judgment before it is called a validated metric.

Why: a 100-task model run proves the code and output format work; it does NOT prove
the scores are correct. Calibration needs humans to score the same tasks blind, then
we measure agreement (see compare_scores.py).

Output: a CSV with the task + occupation context and BLANK score columns for two
annotators. The model's own scores are deliberately NOT included (blind annotation).

Sampling: stratified by O*NET major group (first 2 chars of the SOC code) so the
sample spans the occupational spectrum, not just common jobs. ~250 tasks by default.

This script makes NO API calls and does NOT touch Snowflake.

Usage:
    python calibration/build_calibration_sample.py                 # ~250 tasks, 2 annotators
    python calibration/build_calibration_sample.py --n 300 --annotators 3 --seed 7
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX_ROOT = HERE.parent
sys.path.insert(0, str(INDEX_ROOT / "scoring"))
from score_tasks import load_tasks  # reuse the exact same task assembly  # noqa: E402

OUT = HERE / "calibration_sample.csv"

# Deterministic pseudo-shuffle without Math.random / global RNG surprises:
# order tasks within each stratum by a hash of (seed, task_id).
import hashlib  # noqa: E402


def _rank(seed: int, task_id: str) -> str:
    return hashlib.sha256(f"{seed}:{task_id}".encode()).hexdigest()


def major_group(soc: str) -> str:
    return soc[:2] if len(soc) >= 2 else "??"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=250, help="Target sample size (default 250).")
    ap.add_argument("--annotators", type=int, default=2, help="Blank score columns per metric.")
    ap.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed.")
    args = ap.parse_args()

    tasks = [t for t in load_tasks() if t["importance_raw"] is not None]
    if not tasks:
        sys.exit("No tasks with importance found. Run python/prepare_data.py first.")

    # Group by major group, then take a proportional, deterministic slice.
    by_group: dict[str, list] = defaultdict(list)
    for t in tasks:
        by_group[major_group(t["onet_soc_code"])].append(t)

    total = len(tasks)
    sample: list = []
    for g, items in sorted(by_group.items()):
        items.sort(key=lambda t: _rank(args.seed, t["task_id"]))
        # proportional allocation, at least 1 per present group
        take = max(1, round(args.n * len(items) / total))
        sample.extend(items[:take])

    # Trim/pad to ~n deterministically.
    sample.sort(key=lambda t: _rank(args.seed, t["task_id"]))
    sample = sample[: args.n]

    metrics = ["ai_exposure", "automation", "augmentation"]
    ann_cols = [f"{m}_annot{a}" for a in range(1, args.annotators + 1) for m in metrics]

    header = (["TASK_ID", "ONET_SOC_CODE", "MAJOR_GROUP", "OCCUPATION_TITLE",
               "TASK_TYPE", "IMPORTANCE_RAW", "TASK_STATEMENT",
               "OCCUPATION_DESCRIPTION"] + ann_cols + ["annotator_notes"])

    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for t in sample:
            w.writerow([
                t["task_id"], t["onet_soc_code"], major_group(t["onet_soc_code"]),
                t["occupation_title"], t["task_type"],
                f"{t['importance_raw']:.2f}", t["task_statement"],
                t["occupation_description"],
            ] + [""] * len(ann_cols) + [""])

    groups = len(by_group)
    print(f"Wrote {len(sample)} tasks across {groups} major groups -> {OUT}")
    print(f"Blank annotation columns ({args.annotators} annotators x {len(metrics)} "
          f"metrics): {', '.join(ann_cols)}")
    print("\nInstructions for annotators:")
    print("  * Score each metric 0.0-1.0 using ai_exposure_index/rubric/rubric.md.")
    print("  * Annotate INDEPENDENTLY (do not confer, do not look at model scores).")
    print("  * Leave a note for any task you found ambiguous.")
    print("Then run: python calibration/compare_scores.py "
          "--human calibration_sample.csv --model <model_scores.csv>")


if __name__ == "__main__":
    main()
