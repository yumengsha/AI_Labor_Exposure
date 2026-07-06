"""
compare_scores.py
=================
Measure how well the model's task scores agree with independent human annotation,
so we can decide whether the rubric is calibrated enough to run at full scale.

Computes, per metric (ai_exposure / automation / augmentation):
  * Human-vs-model agreement: mean absolute error, Pearson & Spearman correlation,
    and exact-band agreement (Low/Med/High bucketing).
  * Inter-annotator agreement: same stats between the human annotators (the ceiling
    the model can reasonably reach).
  * Test-retest stability: if a re-score CSV is supplied, model-vs-model consistency.
  * Automation/augmentation confusion: flags tasks where model and humans disagree in
    OPPOSITE directions on automation vs augmentation (the known failure mode).

No API calls, no Snowflake. Pure stdlib + pandas (no scipy needed).

Usage:
    python calibration/compare_scores.py --human calibration_sample.csv \
        --model ../data/task_ai_scores_<run>.csv [--retest ../data/task_ai_scores_<run2>.csv]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("ERROR: pandas required. pip install -r ai_exposure_index/requirements.txt")

METRICS = ["ai_exposure", "automation", "augmentation"]
MODEL_COL = {
    "ai_exposure": "AI_EXPOSURE_SCORE",
    "automation": "AUTOMATION_SCORE",
    "augmentation": "AUGMENTATION_SCORE",
}


# ---- small stats (no scipy) ------------------------------------------------
def _clean(xs, ys):
    pairs = [(a, b) for a, b in zip(xs, ys)
             if a is not None and b is not None
             and not (isinstance(a, float) and math.isnan(a))
             and not (isinstance(b, float) and math.isnan(b))]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def mae(xs, ys):
    xs, ys = _clean(xs, ys)
    return sum(abs(a - b) for a, b in zip(xs, ys)) / len(xs) if xs else float("nan")


def pearson(xs, ys):
    xs, ys = _clean(xs, ys)
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    vy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return cov / (vx * vy) if vx and vy else float("nan")


def _ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    xs, ys = _clean(xs, ys)
    if len(xs) < 2:
        return float("nan")
    return pearson(_ranks(xs), _ranks(ys))


def band(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return "Low" if v < 0.3333 else ("Mid" if v < 0.6667 else "High")


def band_agree(xs, ys):
    xs, ys = _clean(xs, ys)
    if not xs:
        return float("nan")
    hit = sum(1 for a, b in zip(xs, ys) if band(a) == band(b))
    return hit / len(xs)


def report_pair(label, xs, ys):
    print(f"  {label:<28} MAE={mae(xs,ys):.3f}  Pearson={pearson(xs,ys):.3f}  "
          f"Spearman={spearman(xs,ys):.3f}  band-agree={band_agree(xs,ys):.0%}")


# ---- main ------------------------------------------------------------------
def human_mean(df, metric, n_annot):
    cols = [f"{metric}_annot{a}" for a in range(1, n_annot + 1) if f"{metric}_annot{a}" in df]
    if not cols:
        return None, []
    hm = df[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    return hm, cols


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--human", required=True, help="Filled calibration_sample.csv")
    ap.add_argument("--model", required=True, help="Model score CSV for the same tasks")
    ap.add_argument("--retest", help="Second model run for test-retest stability")
    ap.add_argument("--max-annotators", type=int, default=4)
    args = ap.parse_args()

    human = pd.read_csv(args.human, dtype={"TASK_ID": str})
    model = pd.read_csv(args.model, dtype={"TASK_ID": str})
    model = model[model["ERROR_MESSAGE"].isna() | (model["ERROR_MESSAGE"] == "")]

    merged = human.merge(model, on="TASK_ID", suffixes=("_h", "_m"), how="inner")
    print(f"Matched {len(merged)} tasks (human {len(human)}, model {len(model)}).\n")
    if merged.empty:
        sys.exit("No overlapping TASK_IDs between human and model files.")

    n_annot = max((a for a in range(1, args.max_annotators + 1)
                   if f"ai_exposure_annot{a}" in human.columns), default=0)

    print("HUMAN vs MODEL")
    for m in METRICS:
        hm, cols = human_mean(merged, m, n_annot)
        if hm is None:
            print(f"  {m}: no human columns found")
            continue
        report_pair(m, hm.tolist(), pd.to_numeric(merged[MODEL_COL[m]], errors="coerce").tolist())

    if n_annot >= 2:
        print("\nINTER-ANNOTATOR (agreement ceiling)")
        for m in METRICS:
            a1 = pd.to_numeric(merged.get(f"{m}_annot1"), errors="coerce")
            a2 = pd.to_numeric(merged.get(f"{m}_annot2"), errors="coerce")
            if a1 is not None and a2 is not None:
                report_pair(f"{m} (annot1 vs annot2)", a1.tolist(), a2.tolist())

    if args.retest:
        retest = pd.read_csv(args.retest, dtype={"TASK_ID": str})
        rt = merged.merge(retest, on="TASK_ID", suffixes=("", "_rt"))
        print("\nTEST-RETEST (model stability)")
        for m in METRICS:
            c = MODEL_COL[m]
            report_pair(f"{m} (run1 vs run2)",
                        pd.to_numeric(rt[c], errors="coerce").tolist(),
                        pd.to_numeric(rt[f"{c}_rt"], errors="coerce").tolist())

    # Automation/augmentation confusion: model and humans disagree in OPPOSITE
    # directions on the two dimensions for the same task.
    print("\nAUTOMATION/AUGMENTATION CONFUSION CHECK")
    hm_auto, _ = human_mean(merged, "automation", n_annot)
    hm_aug, _ = human_mean(merged, "augmentation", n_annot)
    if hm_auto is not None and hm_aug is not None:
        m_auto = pd.to_numeric(merged["AUTOMATION_SCORE"], errors="coerce")
        m_aug = pd.to_numeric(merged["AUGMENTATION_SCORE"], errors="coerce")
        d_auto = m_auto - hm_auto
        d_aug = m_aug - hm_aug
        # flag: model pushes automation up while pushing augmentation down (or vice
        # versa) by a meaningful margin -> likely swapped the two concepts.
        flag = ((d_auto > 0.25) & (d_aug < -0.25)) | ((d_auto < -0.25) & (d_aug > 0.25))
        n_flag = int(flag.sum())
        print(f"  tasks where model likely swapped automation/augmentation: {n_flag} "
              f"({n_flag/len(merged):.0%})")
        if n_flag:
            cols = ["TASK_ID", "OCCUPATION_TITLE", "TASK_STATEMENT"]
            have = [c for c in cols if c in merged.columns]
            print("  examples:")
            for _, r in merged[flag].head(5)[have].iterrows():
                print("   ", " | ".join(str(r[c])[:60] for c in have))

    print("\nGuidance: model-vs-human agreement should approach inter-annotator "
          "agreement. If MAE is much worse than the annotator ceiling, or the "
          "confusion count is high, revise the rubric before the full run.")


if __name__ == "__main__":
    main()
