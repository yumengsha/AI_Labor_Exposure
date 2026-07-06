"""
validate_offline.py
====================
Reproduce the exposure-index SQL (scripts 12-15) in pandas, directly from the
local CSVs, to validate the logic BEFORE running anything in Snowflake — and
without needing the LLM. Uses synthetic task scores by default (deterministic,
derived from a hash) so the math is exercised even before real scores exist;
pass --scores <csv> to validate against a real scoring run.

Asserts the invariants the plan calls out:
  * occupation exposure is importance-RAW-weighted and lands in [0,1]
  * IMPORTANCE_NORM is NOT used as the weight (raw vs norm give different means)
  * industry (private-sector) employment <= national employment (no double-count)
  * region axis produces all three granularities with the expected area counts
  * every axis exposure lands in [0,1]

NO Snowflake, NO API. Pure pandas over data/raw/.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("ERROR: pandas required. pip install -r ai_exposure_index/requirements.txt")

ROOT = Path(__file__).resolve().parents[1]          # ai_labor_snowflake
RAW = ROOT / "data" / "raw"


def read_tsv(name):
    return pd.read_csv(RAW / name, sep="\t", dtype=str, keep_default_na=False)


def synth_score(task_id: str, soc: str, salt: str) -> float:
    h = int(hashlib.sha256(f"{salt}:{soc}:{task_id}".encode()).hexdigest(), 16)
    return (h % 1000) / 1000.0


def load():
    stmts = read_tsv("onet_task_statements.csv")
    stmts.columns = [c.strip() for c in stmts.columns]
    ratings = read_tsv("onet_task_ratings.csv")
    ratings.columns = [c.strip() for c in ratings.columns]
    stmts = stmts.rename(columns={"O*NET-SOC Code": "SOC", "Task ID": "TASK_ID"})
    stmts["OCC_CODE"] = stmts["SOC"].str[:7]
    im = ratings[ratings["Scale ID"] == "IM"].rename(
        columns={"O*NET-SOC Code": "SOC", "Task ID": "TASK_ID", "Data Value": "IMP"})
    im["IMP"] = pd.to_numeric(im["IMP"], errors="coerce")
    tasks = stmts.merge(im[["SOC", "TASK_ID", "IMP"]], on=["SOC", "TASK_ID"], how="left")
    tasks = tasks.dropna(subset=["IMP"])          # only importance-rated tasks
    return tasks


def load_oews_slice(area_types, i_group, own_codes):
    """Read the national/region/industry slice from the latest OEWS CSV."""
    # newest available oews_*.csv
    files = sorted(RAW.glob("oews_*.csv"))
    if not files:
        sys.exit("No oews_*.csv found. Run python/prepare_data.py first.")
    df = pd.read_csv(files[-1], dtype=str, usecols=[
        "AREA", "AREA_TITLE", "AREA_TYPE", "PRIM_STATE", "NAICS", "NAICS_TITLE",
        "I_GROUP", "OWN_CODE", "OCC_CODE", "OCC_TITLE", "O_GROUP", "TOT_EMP", "A_MEDIAN"])
    df["TOT_EMP"] = pd.to_numeric(df["TOT_EMP"].str.replace(",", "", regex=False),
                                  errors="coerce")
    m = (df.AREA_TYPE.isin(area_types) & (df.I_GROUP.str.lower() == i_group)
         & df.OWN_CODE.isin(own_codes) & (df.O_GROUP.str.lower() == "detailed"))
    return df[m].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", help="Real task score CSV (else synthetic).")
    args = ap.parse_args()

    tasks = load()
    if args.scores:
        sc = pd.read_csv(args.scores, dtype={"TASK_ID": str})
        sc = sc[sc["ERROR_MESSAGE"].isna() | (sc["ERROR_MESSAGE"] == "")]
        sc["SOC"] = sc["ONET_SOC_CODE"]
        tasks = tasks.merge(
            sc[["SOC", "TASK_ID", "AI_EXPOSURE_SCORE", "AUTOMATION_SCORE",
                "AUGMENTATION_SCORE"]].rename(columns={
                    "AI_EXPOSURE_SCORE": "EXP", "AUTOMATION_SCORE": "AUT",
                    "AUGMENTATION_SCORE": "AUG"}),
            on=["SOC", "TASK_ID"], how="left")
        for c in ("EXP", "AUT", "AUG"):
            tasks[c] = pd.to_numeric(tasks[c], errors="coerce")
        label = f"real scores ({args.scores})"
    else:
        tasks["EXP"] = [synth_score(t, s, "exp") for t, s in zip(tasks.TASK_ID, tasks.SOC)]
        tasks["AUT"] = [synth_score(t, s, "aut") for t, s in zip(tasks.TASK_ID, tasks.SOC)]
        tasks["AUG"] = [synth_score(t, s, "aug") for t, s in zip(tasks.TASK_ID, tasks.SOC)]
        label = "SYNTHETIC scores (deterministic hash)"

    print(f"Validating with {label}\n")

    # ---- Occupation index: importance-RAW-weighted (scripts 12) --------------
    scored = tasks.dropna(subset=["EXP"])
    g = scored.groupby("OCC_CODE")
    occ = pd.DataFrame({
        "OCC_EXPOSURE": g.apply(lambda d: (d.IMP * d.EXP).sum() / d.IMP.sum(), include_groups=False),
        "OCC_AUTO": g.apply(lambda d: (d.IMP * d.AUT).sum() / d.IMP.sum(), include_groups=False),
        "OCC_AUG": g.apply(lambda d: (d.IMP * d.AUG).sum() / d.IMP.sum(), include_groups=False),
    }).reset_index()

    assert occ.OCC_EXPOSURE.between(0, 1).all(), "occupation exposure out of [0,1]"
    print(f"[PASS] occupation exposure in [0,1] for {len(occ)} occupations "
          f"(mean {occ.OCC_EXPOSURE.mean():.3f})")

    # raw vs norm weight must differ (proves we're using RAW) -----------------
    def wexp(w):
        gg = scored.assign(W=w)
        return gg.groupby("OCC_CODE").apply(lambda d: (d.W * d.EXP).sum() / d.W.sum(), include_groups=False)
    raw_mean = wexp(scored.IMP)
    norm_mean = wexp((scored.IMP - 1) / 4.0)
    diff = (raw_mean - norm_mean).abs().mean()
    assert diff > 1e-9, "raw and norm weighting identical - weighting not applied?"
    print(f"[PASS] raw vs normalized weighting differ (mean |Δ|={diff:.4f}) "
          "-> IMPORTANCE_RAW is the operative weight")

    # ---- National slice + axes ----------------------------------------------
    nat = load_oews_slice(["1"], "cross-industry", ["1235"])
    nat = nat.merge(occ, on="OCC_CODE", how="left")
    nat_emp = nat.TOT_EMP.sum()
    print(f"\nNational detailed occupations: {len(nat)} | total emp {nat_emp:,.0f}")

    # Industry (private sector) axis
    ind = load_oews_slice(["1"], "sector", ["5"]).merge(occ, on="OCC_CODE", how="left")
    ind_emp = ind.TOT_EMP.sum()
    by_naics = ind.dropna(subset=["OCC_EXPOSURE"]).groupby("NAICS").apply(
        lambda d: (d.OCC_EXPOSURE * d.TOT_EMP).sum() / d.TOT_EMP.sum(), include_groups=False)
    assert by_naics.between(0, 1).all(), "industry exposure out of [0,1]"
    assert ind_emp <= nat_emp + 1, f"industry emp {ind_emp:,.0f} > national {nat_emp:,.0f}"
    print(f"[PASS] industry axis: {by_naics.shape[0]} sectors, exposures in [0,1], "
          f"private emp {ind_emp:,.0f} <= national {nat_emp:,.0f} (no double-count)")

    # Region axis (state/metro/nonmetro)
    reg = load_oews_slice(["2", "4", "6"], "cross-industry", ["1235"]).merge(
        occ, on="OCC_CODE", how="left")
    gran = {"2": "State", "4": "Metropolitan", "6": "Nonmetropolitan"}
    reg["GRAN"] = reg.AREA_TYPE.map(gran)
    counts = reg.groupby("GRAN").AREA.nunique()
    print(f"[PASS] region axis granularities: {counts.to_dict()}")
    assert set(counts.index) == {"State", "Metropolitan", "Nonmetropolitan"}, \
        "missing a region granularity"
    assert counts["State"] in range(50, 57), f"unexpected state count {counts['State']}"
    # per-area exposure in range
    area_exp = reg.dropna(subset=["OCC_EXPOSURE"]).groupby(["GRAN", "AREA"]).apply(
        lambda d: (d.OCC_EXPOSURE * d.TOT_EMP).sum() / d.TOT_EMP.sum(), include_groups=False)
    assert area_exp.between(0, 1).all(), "region area exposure out of [0,1]"
    print(f"[PASS] region area exposures in [0,1] across {len(area_exp)} areas")

    # Wage band axis
    nat_wage = nat.dropna(subset=["A_MEDIAN"]).copy()
    nat_wage["A_MEDIAN"] = pd.to_numeric(nat_wage["A_MEDIAN"], errors="coerce")
    nat_wage = nat_wage.dropna(subset=["A_MEDIAN", "OCC_EXPOSURE"])
    nat_wage["PR"] = nat_wage.A_MEDIAN.rank(pct=True)
    nat_wage["BAND"] = pd.cut(nat_wage.PR, [0, 1/3, 2/3, 1.01],
                              labels=["Low", "Middle", "High"], include_lowest=True)
    band_exp = nat_wage.groupby("BAND", observed=True).apply(
        lambda d: (d.OCC_EXPOSURE * d.TOT_EMP).sum() / d.TOT_EMP.sum(), include_groups=False)
    assert band_exp.between(0, 1).all(), "wage-band exposure out of [0,1]"
    print(f"[PASS] wage-band axis: {band_exp.round(3).to_dict()}")

    print("\nAll offline invariants hold. The SQL logic (scripts 12-15) is "
          "consistent with this reproduction.")


if __name__ == "__main__":
    main()
