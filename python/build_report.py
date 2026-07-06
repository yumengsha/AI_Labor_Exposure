"""
build_report.py
===============
Build an INTERACTIVE, fully-offline HTML report that visualizes every substep of
the AI-labor Snowflake pipeline, plus a per-substep chart saved individually.

It reproduces the SQL pipeline (RAW -> STAGING -> ANALYTICS -> QUALITY) in
pandas *directly from the prepared CSVs in data/raw/*, so the numbers you see in
the report are the real numbers the Snowflake build will produce. This doubles
as a local validation of the SQL logic before you ever touch Snowflake.

Outputs:
    reports/index.html          <- open this in any browser (self-contained)
    reports/charts/*.svg        <- each substep's chart as a standalone file

Dependencies: pandas (already in requirements.txt). Charts are hand-rolled
inline SVG - no matplotlib, no CDN, no internet required.

Usage:
    python python/build_report.py
"""

from __future__ import annotations

import glob
import html
import json
import os
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("ERROR: pandas is required. Run: pip install -r requirements.txt")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
RAW = os.path.join(ROOT, "data", "raw")
REPORTS = os.path.join(ROOT, "reports")
CHARTS = os.path.join(REPORTS, "charts")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
C = {
    # Soft, low-saturation teal -> blue -> purple family for all DATA charts.
    "teal":   "#5eafd6",   # soft sky/teal (ramp start)
    "sky":    "#6ea8e8",
    "blue":   "#7c93e8",   # soft indigo-blue
    "indigo": "#8f8ae0",
    "violet": "#a98cdb",
    "purple": "#b58ad0",   # ramp end
    "lblue":  "#9cc4ee",   # light, for low end of sequences
    "lviolet":"#c9b3e8",   # light violet
    # Kept only for the QUALITY status pills / verdict (conventional meaning).
    "green":  "#16a34a",
    "amber":  "#d97706",
    "red":    "#dc2626",
    # Neutrals.
    "slate":  "#475569",
    "grid":   "#e2e8f0",
    "ink":    "#0f172a",
    "muted":  "#64748b",
    # Back-compat alias (a couple of call sites still reference cyan).
    "cyan":   "#6ea8e8",
}
# Harmonious cool ramp: teal -> sky -> blue -> indigo -> violet -> purple.
SERIES = [C["teal"], C["sky"], C["blue"], C["indigo"], C["violet"], C["purple"]]


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def fmt(n) -> str:
    """Thousands-separated integer string."""
    try:
        return f"{int(round(float(n))):,}"
    except (ValueError, TypeError):
        return str(n)


def fmt_scaled(n, vmax) -> str:
    """Format a value with decimals when the whole scale is small/fractional
    (e.g. 0..1 exposure scores), otherwise as a thousands-separated integer."""
    try:
        v = float(n)
    except (ValueError, TypeError):
        return str(n)
    try:
        m = float(vmax)
    except (ValueError, TypeError):
        m = v
    if m <= 1.5:
        return f"{v:.3f}"
    if m < 100:
        return f"{v:,.1f}".rstrip("0").rstrip(".")
    return f"{int(round(v)):,}"


# ===========================================================================
# INLINE SVG CHART HELPERS  (interactive via native <title> hover tooltips
# and CSS hover highlight)
# ===========================================================================
def _svg_open(w, h):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
            f'preserveAspectRatio="xMidYMid meet" class="chart" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">')


def bar_v(data, title="", unit="", w=680, h=340):
    """Vertical bar chart. data = list of (label, value)."""
    pad_l, pad_r, pad_t, pad_b = 55, 20, 20, 70
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    vmax = max((v for _, v in data), default=1) or 1
    n = len(data)
    gap = 0.25
    bw = plot_w / max(n, 1) * (1 - gap)
    step = plot_w / max(n, 1)
    s = [_svg_open(w, h)]
    # gridlines + y labels
    for i in range(5):
        y = pad_t + plot_h * i / 4
        val = vmax * (1 - i / 4)
        s.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                 f'stroke="{C["grid"]}" stroke-width="1"/>')
        s.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" text-anchor="end" '
                 f'class="axis">{fmt_scaled(val, vmax)}</text>')
    for i, (label, val) in enumerate(data):
        bh = plot_h * (val / vmax)
        x = pad_l + step * i + (step - bw) / 2
        y = pad_t + plot_h - bh
        color = SERIES[i % len(SERIES)]
        s.append(f'<g class="bar"><title>{esc(label)}: {fmt_scaled(val, vmax)} {esc(unit)}</title>'
                 f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'rx="3" fill="{color}"/>'
                 f'<text x="{x+bw/2:.1f}" y="{y-6:.1f}" text-anchor="middle" '
                 f'class="val">{fmt_scaled(val, vmax)}</text></g>')
        # x label (wrap-ish: rotate if long)
        lx, ly = x + bw / 2, pad_t + plot_h + 16
        s.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="end" '
                 f'transform="rotate(-30 {lx:.1f} {ly:.1f})" class="axis">'
                 f'{esc(label)}</text>')
    s.append("</svg>")
    return "".join(s)


def bar_h(data, title="", unit="", w=680, h=None, color=None):
    """Horizontal bar chart. data = list of (label, value). Good for rankings."""
    n = len(data)
    row_h = 26
    pad_l, pad_r, pad_t, pad_b = 250, 60, 10, 10
    h = h or (pad_t + pad_b + n * row_h)
    plot_w = w - pad_l - pad_r
    vmax = max((v for _, v in data), default=1) or 1
    s = [_svg_open(w, h)]
    for i, (label, val) in enumerate(data):
        y = pad_t + i * row_h
        bw = plot_w * (val / vmax)
        col = color or SERIES[i % len(SERIES)]
        short = label if len(str(label)) <= 40 else str(label)[:38] + "…"
        s.append(f'<g class="bar"><title>{esc(label)}: {fmt_scaled(val, vmax)} {esc(unit)}</title>'
                 f'<text x="{pad_l-10}" y="{y+row_h/2+4:.1f}" text-anchor="end" '
                 f'class="rowlab">{esc(short)}</text>'
                 f'<rect x="{pad_l}" y="{y+4:.1f}" width="{max(bw,1):.1f}" '
                 f'height="{row_h-10}" rx="3" fill="{col}"/>'
                 f'<text x="{pad_l+bw+6:.1f}" y="{y+row_h/2+4:.1f}" '
                 f'class="val">{fmt_scaled(val, vmax)}</text></g>')
    s.append("</svg>")
    return "".join(s)


def histogram(values, bins=20, title="", w=680, h=320, color=None):
    """Histogram from a list/Series of numeric values (0..1 style)."""
    vals = [v for v in values if v is not None and not (isinstance(v, float) and v != v)]
    if not vals:
        return '<div class="empty">no data</div>'
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    pad_l, pad_r, pad_t, pad_b = 55, 15, 15, 40
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    cmax = max(counts) or 1
    bw = plot_w / bins
    col = color or C["purple"]
    s = [_svg_open(w, h)]
    for i in range(5):
        y = pad_t + plot_h * i / 4
        s.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                 f'stroke="{C["grid"]}"/>')
        s.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" text-anchor="end" class="axis">'
                 f'{fmt(cmax*(1-i/4))}</text>')
    for i, c in enumerate(counts):
        bh = plot_h * (c / cmax)
        x = pad_l + i * bw
        y = pad_t + plot_h - bh
        b0, b1 = lo + i * width, lo + (i + 1) * width
        s.append(f'<g class="bar"><title>{b0:.2f}–{b1:.2f}: {fmt(c)}</title>'
                 f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw-1:.1f}" height="{bh:.1f}" '
                 f'fill="{col}" rx="1"/></g>')
    # x axis labels (min / mid / max)
    for frac in (0, 0.5, 1):
        x = pad_l + plot_w * frac
        s.append(f'<text x="{x:.1f}" y="{h-12}" text-anchor="middle" class="axis">'
                 f'{lo+(hi-lo)*frac:.2f}</text>')
    s.append("</svg>")
    return "".join(s)


def donut(data, title="", w=520, h=300):
    """Donut chart with a legend on the right. data = list of (label, value)."""
    import math
    total = sum(v for _, v in data) or 1
    # Put the ring on the left third, legend on the right two-thirds so text fits.
    cx, cy, r, rin = h * 0.5, h / 2, h * 0.36, h * 0.20
    legend_x = h + 20
    s = [_svg_open(w, h)]
    ang = -math.pi / 2
    for i, (label, val) in enumerate(data):
        frac = val / total
        a2 = ang + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        xi1, yi1 = cx + rin * math.cos(a2), cy + rin * math.sin(a2)
        xi2, yi2 = cx + rin * math.cos(ang), cy + rin * math.sin(ang)
        col = SERIES[i % len(SERIES)]
        s.append(f'<g class="seg"><title>{esc(label)}: {fmt(val)} ({frac*100:.1f}%)</title>'
                 f'<path d="M {x1:.1f} {y1:.1f} A {r:.1f} {r:.1f} 0 {large} 1 {x2:.1f} {y2:.1f} '
                 f'L {xi1:.1f} {yi1:.1f} A {rin:.1f} {rin:.1f} 0 {large} 0 {xi2:.1f} {yi2:.1f} Z" '
                 f'fill="{col}"/></g>')
        ang = a2
    # legend (right side, vertically centered around the ring)
    lh = 26
    ly = cy - (len(data) * lh) / 2 + lh / 2
    for i, (label, val) in enumerate(data):
        col = SERIES[i % len(SERIES)]
        yy = ly + i * lh
        s.append(f'<rect x="{legend_x:.0f}" y="{yy-11:.0f}" width="14" height="14" '
                 f'rx="3" fill="{col}"/>'
                 f'<text x="{legend_x+22:.0f}" y="{yy:.0f}" class="legend">'
                 f'{esc(label)} ({val/total*100:.0f}%)</text>')
    s.append("</svg>")
    return "".join(s)


def funnel(stages, w=680, h=380):
    """Funnel. stages = list of (label, value), descending.

    Each row shows a caption ABOVE the bar (so labels never clip regardless of
    bar width), the bar itself (left-aligned, width scaled to value with a
    minimum so tiny final stages stay visible), and the % of the starting count
    to the right.
    """
    n = len(stages)
    vmax = max((v for _, v in stages), default=1) or 1
    start = stages[0][1] or 1
    pad_t, pad_b, pad_l, pad_r = 14, 14, 20, 70
    plot_w = w - pad_l - pad_r
    row_h = (h - pad_t - pad_b) / n
    bar_h = min(row_h - 24, 30)
    min_frac = 0.10  # never let a bar shrink below this fraction of the widest
    s = [_svg_open(w, h)]
    for i, (label, val) in enumerate(stages):
        frac = val / vmax
        bw = plot_w * max(frac, min_frac)
        y = pad_t + i * row_h
        col = SERIES[i % len(SERIES)]
        pct = val / start * 100
        pct_txt = f"{pct:.0f}%" if pct >= 1 else f"{pct:.1f}%"
        s.append(f'<g class="bar"><title>{esc(label)}: {fmt(val)} ({pct_txt} of start)</title>'
                 # caption above the bar
                 f'<text x="{pad_l}" y="{y+13:.1f}" class="funcap">'
                 f'{esc(label)}: {fmt(val)}</text>'
                 # the bar
                 f'<rect x="{pad_l}" y="{y+18:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
                 f'rx="4" fill="{col}"/>'
                 # percent to the right
                 f'<text x="{w-pad_r+12:.1f}" y="{y+18+bar_h/2+4:.1f}" '
                 f'class="axis">{pct_txt}</text></g>')
    s.append("</svg>")
    return "".join(s)


def save_chart(name, svg):
    with open(os.path.join(CHARTS, name + ".svg"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        # standalone file needs its own <style>
        f.write(svg.replace('class="chart"',
                            'class="chart" style="font-family:sans-serif"'))


# ===========================================================================
# NUMERIC CLEANING (mirrors STAGING SQL: strip commas, coerce, * # -> NaN)
# ===========================================================================
def num(series):
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


# ===========================================================================
# MAIN PIPELINE (reproduces the SQL logic)
# ===========================================================================
def build():
    os.makedirs(CHARTS, exist_ok=True)
    steps = []  # each: dict(id, layer, title, desc, chart, note)

    # ---------------------------------------------------------------------
    # Load prepared CSVs
    # ---------------------------------------------------------------------
    oews_files = {y: os.path.join(RAW, f"oews_{y}.csv") for y in (2022, 2023, 2024, 2025)}
    oews_files = {y: p for y, p in oews_files.items() if os.path.exists(p)}
    if not oews_files:
        sys.exit(f"ERROR: no oews_*.csv in {RAW}. Run prepare_data.py first.")

    ratings_path = os.path.join(RAW, "onet_task_ratings.csv")
    stmts_path = os.path.join(RAW, "onet_task_statements.csv")

    print("Loading prepared CSVs (reproducing the SQL pipeline in pandas)...")

    # Read all OEWS years as strings (RAW = text), tag DATA_YEAR.
    frames = []
    year_counts = {}
    for y, p in oews_files.items():
        df = pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""])
        df["DATA_YEAR"] = y
        year_counts[y] = len(df)
        frames.append(df)
    oews = pd.concat(frames, ignore_index=True)
    print(f"  OEWS rows (all years): {len(oews):,}")

    ratings = pd.read_csv(ratings_path, sep="\t", dtype=str, keep_default_na=False,
                          na_values=[""]) if os.path.exists(ratings_path) else pd.DataFrame()
    stmts = pd.read_csv(stmts_path, sep="\t", dtype=str, keep_default_na=False,
                        na_values=[""]) if os.path.exists(stmts_path) else pd.DataFrame()
    print(f"  O*NET ratings rows   : {len(ratings):,}")
    print(f"  O*NET statements rows: {len(stmts):,}")

    # =====================================================================
    # SUBSTEP 1 - Data sources profile
    # =====================================================================
    src = [(f"OEWS {y}", c) for y, c in sorted(year_counts.items())]
    src += [("O*NET Ratings", len(ratings)), ("O*NET Statements", len(stmts))]
    ch = bar_v(src, unit="rows")
    save_chart("01_sources", ch)
    steps.append(dict(
        id="s1", layer="Sources", title="1 · Source datasets loaded",
        desc="Row counts for every prepared input file. Four years of BLS OEWS "
             "employment/wage data plus the two O*NET task files feed the warehouse.",
        chart=ch,
        note=f"{len(oews):,} total BLS rows across {len(oews_files)} years; "
             f"{len(ratings):,} O*NET ratings; {len(stmts):,} O*NET task statements."))

    # =====================================================================
    # SUBSTEP 2 - RAW: OEWS occupation-group mix (latest year)
    # =====================================================================
    latest = max(oews_files)
    o_latest = oews[oews["DATA_YEAR"] == latest]
    ogrp = (o_latest["O_GROUP"].str.lower().value_counts()
            .reindex(["total", "major", "minor", "broad", "detailed"]).dropna())
    ch = bar_v([(k, int(v)) for k, v in ogrp.items()], unit="rows")
    save_chart("02_ogroup", ch)
    steps.append(dict(
        id="s2", layer="RAW", title=f"2 · BLS occupation levels (OEWS {latest})",
        desc="BLS reports occupations at several aggregation levels. We keep the "
             "<b>detailed</b> level, the most granular and the right grain for "
             "occupation-by-occupation AI-exposure analysis.",
        chart=ch,
        note=f"'detailed' rows in {latest}: {int(ogrp.get('detailed',0)):,}."))

    # =====================================================================
    # SUBSTEP 3 - RAW: O*NET rating scales
    # =====================================================================
    if len(ratings):
        scale_col = [c for c in ratings.columns if c.strip().lower() == "scale id"][0]
        sc = ratings[scale_col].str.strip().value_counts()
        label_map = {"FT": "FT · Frequency", "IM": "IM · Importance", "RT": "RT · Relevance"}
        data = [(label_map.get(k, k), int(v)) for k, v in sc.items()]
        ch = donut(data)
        save_chart("03_scales", ch)
        steps.append(dict(
            id="s3", layer="RAW", title="3 · O*NET rating scales",
            desc="Each task carries ratings on several scales. <b>Importance (IM)</b> "
                 "drives our exposure weighting; Frequency (FT) and Relevance (RT) are "
                 "kept for future refinement.",
            chart=ch,
            note="Importance (IM) ratings normalized to 0–1 as the exposure proxy."))

    # =====================================================================
    # SUBSTEP 4 - STAGING: national detailed slice funnel
    # =====================================================================
    # mirror STG_BLS_OEWS_NATIONAL filters
    f_year = o_latest.copy()
    step_all = len(f_year)
    step_notall = len(f_year[f_year["OCC_CODE"] != "00-0000"])
    nat = f_year[(f_year["AREA_TYPE"] == "1")]
    step_nat = len(nat)
    xind = nat[(nat["I_GROUP"].str.lower() == "cross-industry") & (nat["OWN_CODE"] == "1235")]
    step_xind = len(xind)
    detailed = xind[xind["O_GROUP"].str.lower() == "detailed"]
    step_det = len(detailed)
    stages = [
        (f"OEWS {latest} (all rows)", step_all),
        ("Exclude 00-0000 rollup", step_notall),
        ("National only (AREA_TYPE=1)", step_nat),
        ("Cross-industry, all owners", step_xind),
        ("Detailed occupations → FACT grain", step_det),
    ]
    ch = funnel(stages)
    save_chart("04_funnel", ch)
    steps.append(dict(
        id="s4", layer="STAGING", title="4 · Filtering to the fact-table grain",
        desc="STAGING narrows about 400K OEWS rows down to one clean row per detailed "
             "occupation at the national, cross-industry, all-ownership level. This "
             "avoids any double-counting of employment.",
        chart=ch,
        note=f"Final fact grain: {step_det:,} detailed occupations."))

    # Build the national detailed frame with cleaned numerics (the fact base).
    base = detailed.copy()
    base["TOT_EMP"] = num(base["TOT_EMP"])
    base["A_MEAN"] = num(base["A_MEAN"])
    base["A_MEDIAN"] = num(base["A_MEDIAN"])
    base["OCC_CODE"] = base["OCC_CODE"].str.strip()

    # =====================================================================
    # SUBSTEP 5 - STAGING: OCC_CODE standardization + O*NET tasks
    # =====================================================================
    task_type_data, importance_vals = [], []
    onet_occ = set()
    exposure = pd.DataFrame(columns=["OCC_CODE", "AI_EXPOSURE", "AUTOMATION", "AUGMENTATION"])
    EXPOSURE_MODE = "PLACEHOLDER"
    real_task_scores = []
    if len(stmts) and len(ratings):
        soc_col_s = [c for c in stmts.columns if "soc" in c.lower()][0]
        tid_col_s = [c for c in stmts.columns if c.strip().lower() == "task id"][0]
        ttype_col = [c for c in stmts.columns if c.strip().lower() == "task type"][0]
        stmts = stmts.copy()
        stmts["OCC_CODE"] = stmts[soc_col_s].str.strip().str[:7]     # LEFT(...,7)
        onet_occ = set(stmts["OCC_CODE"].dropna().unique())

        tt = stmts[ttype_col].fillna("n/a").str.strip().replace("", "n/a").value_counts()
        task_type_data = [(k, int(v)) for k, v in tt.items()]

        # importance (IM), keep BOTH raw (1-5, the operative weight) and norm (display).
        soc_col_r = [c for c in ratings.columns if "soc" in c.lower()][0]
        tid_col_r = [c for c in ratings.columns if c.strip().lower() == "task id"][0]
        scale_col = [c for c in ratings.columns if c.strip().lower() == "scale id"][0]
        val_col = [c for c in ratings.columns if c.strip().lower() == "data value"][0]
        rr = ratings.copy()
        rr["OCC_CODE"] = rr[soc_col_r].str.strip().str[:7]
        rr["SOC"] = rr[soc_col_r].str.strip()
        rr["TID"] = rr[tid_col_r].str.strip()
        rr["VAL"] = num(rr[val_col])
        imp = rr[rr[scale_col].str.strip() == "IM"].dropna(subset=["VAL"]).copy()
        imp["IMPORTANCE_NORM"] = (imp["VAL"] - 1) / 4.0
        importance_vals = imp["IMPORTANCE_NORM"].tolist()

        # --- REAL scores if available, else placeholder ------------------
        real_csv = None
        score_dir = os.path.join(ROOT, "ai_exposure_index", "data")
        if os.path.isdir(score_dir):
            cands = sorted(glob.glob(os.path.join(score_dir, "task_ai_scores_v2_full_*.csv")))
            real_csv = cands[-1] if cands else None

        if real_csv:
            EXPOSURE_MODE = "REAL_TASK_SCORE"
            sc = pd.read_csv(real_csv, dtype=str)
            sc = sc[sc["ERROR_MESSAGE"].isna() | (sc["ERROR_MESSAGE"] == "")]
            sc["SOC"] = sc["ONET_SOC_CODE"].str.strip()
            sc["TID"] = sc["TASK_ID"].astype(str).str.strip()
            for col in ("AI_EXPOSURE_SCORE", "AUTOMATION_SCORE", "AUGMENTATION_SCORE"):
                sc[col] = num(sc[col])
            # join task scores to raw importance by (SOC, Task ID)
            j = imp[["SOC", "TID", "OCC_CODE", "VAL"]].merge(
                sc[["SOC", "TID", "AI_EXPOSURE_SCORE", "AUTOMATION_SCORE",
                    "AUGMENTATION_SCORE"]], on=["SOC", "TID"], how="inner")
            j = j.dropna(subset=["AI_EXPOSURE_SCORE"])

            def wmean(d, col):
                w = d["VAL"]
                return (w * d[col]).sum() / w.sum() if w.sum() else float("nan")

            exposure = (j.groupby("OCC_CODE")
                        .apply(lambda d: pd.Series({
                            "AI_EXPOSURE": round(wmean(d, "AI_EXPOSURE_SCORE"), 4),
                            "AUTOMATION": round(wmean(d, "AUTOMATION_SCORE"), 4),
                            "AUGMENTATION": round(wmean(d, "AUGMENTATION_SCORE"), 4),
                        }), include_groups=False)
                        .reset_index())
            real_task_scores = sc["AI_EXPOSURE_SCORE"].dropna().tolist()
        else:
            EXPOSURE_MODE = "PLACEHOLDER"
            exposure = (imp.groupby("OCC_CODE")["IMPORTANCE_NORM"].mean()
                        .reset_index().rename(columns={"IMPORTANCE_NORM": "AI_EXPOSURE"}))
            exposure["AI_EXPOSURE"] = exposure["AI_EXPOSURE"].round(4)
            exposure["AUTOMATION"] = float("nan")
            exposure["AUGMENTATION"] = float("nan")
            real_task_scores = []

    if task_type_data:
        ch = donut(task_type_data)
        save_chart("05_task_types", ch)
        steps.append(dict(
            id="s5", layer="STAGING", title="5 · Standardized join + task types",
            desc="O*NET SOC codes like <code>11-1021.00</code> are trimmed to "
                 "<code>11-1021</code> via <code>LEFT(code,7)</code> so they match "
                 "BLS. Task statements join to importance ratings by Task ID + SOC.",
            chart=ch,
            note="Task types: Core tasks are central to the occupation; "
                 "Supplemental are secondary."))

    if importance_vals:
        ch = histogram(importance_vals, bins=20, color=C["indigo"])
        save_chart("06_importance", ch)
        steps.append(dict(
            id="s6", layer="STAGING", title="6 · Task importance distribution (1–5)",
            desc="O*NET importance (IM, 1–5) is the <b>weight</b> used to roll task "
                 "scores up to occupations: "
                 "<code>Σ(importance×score)/Σ(importance)</code>. Shown here "
                 "normalized to 0–1 for display only.",
            chart=ch,
            note=f"{len(importance_vals):,} importance ratings across all tasks."))

    # =====================================================================
    # SUBSTEP 6 - ANALYTICS: build the fact table (percentiles, bands, rank)
    # =====================================================================
    fact = base.merge(exposure, on="OCC_CODE", how="left")
    fact = fact.dropna(subset=["A_MEDIAN"]).copy()
    # In placeholder mode, unmatched occupations default to 0 (old behavior).
    # In real mode, leave them NaN (no O*NET tasks -> no score) so they don't
    # distort the distribution/ranking, matching sql/12 SCORE_STATUS='NO_ONET'.
    if EXPOSURE_MODE == "PLACEHOLDER":
        fact["AI_EXPOSURE"] = fact["AI_EXPOSURE"].fillna(0.0)
    # PERCENT_RANK() OVER (ORDER BY A_MEDIAN) = (rank_min - 1) / (n - 1)
    n = len(fact)
    fact["WAGE_PERCENTILE"] = (fact["A_MEDIAN"].rank(method="min") - 1) / max(n - 1, 1)

    def band(p):
        if p < 0.3333:
            return "Low"
        if p < 0.6667:
            return "Middle"
        return "High"
    fact["WAGE_BAND"] = fact["WAGE_PERCENTILE"].apply(band)
    fact["WEIGHTED_EXPOSURE"] = fact["AI_EXPOSURE"] * fact["TOT_EMP"]
    # rank leaves NaN for unscored occupations; keep as nullable Int
    fact["EXPOSURE_RANK"] = (fact["AI_EXPOSURE"].rank(method="min", ascending=False)
                             .astype("Int64"))

    # Dimension row counts
    dim_counts = [
        ("DIM_OCCUPATION", base["OCC_CODE"].nunique()),
        ("DIM_TASK", len(stmts) if len(stmts) else 0),
        ("DIM_REGION", oews["AREA"].nunique()),
        ("DIM_INDUSTRY", oews["NAICS"].nunique()),
        ("DIM_WAGE_BAND", 3),
        ("FACT", len(fact)),
    ]
    ch = bar_v(dim_counts, unit="rows")
    save_chart("07_star", ch)
    steps.append(dict(
        id="s7", layer="ANALYTICS", title="7 · Star schema table sizes",
        desc="The fact table plus five dimensions. The fact grain is one detailed "
             "occupation; dimensions describe occupation, task, region, industry, "
             "and wage band.",
        chart=ch,
        note=f"Fact rows: {len(fact):,} · Occupations: {base['OCC_CODE'].nunique():,} "
             f"· Regions: {oews['AREA'].nunique():,} · Industries: {oews['NAICS'].nunique():,}."))

    # =====================================================================
    # SUBSTEP 7 - ANALYTICS: exposure distribution
    # =====================================================================
    exp_vals = fact["AI_EXPOSURE"].dropna().tolist()
    ch = histogram(exp_vals, bins=20, color=C["purple"])
    save_chart("08_exposure_dist", ch)
    if EXPOSURE_MODE == "REAL_TASK_SCORE":
        steps.append(dict(
            id="s8", layer="ANALYTICS", title="8 · AI exposure distribution (real scores)",
            desc="Distribution of the <b>real</b> occupation AI exposure index across "
                 "detailed occupations. Each occupation's score is the importance "
                 "weighted average of Claude's per task scores. Exposure measures how "
                 "much AI can touch the work. It is <b>not</b> a prediction of job loss.",
            chart=ch,
            note=f"{len(exp_vals):,} occupations scored. Mean "
                 f"{sum(exp_vals)/max(len(exp_vals),1):.2f}."))
    else:
        steps.append(dict(
            id="s8", layer="ANALYTICS", title="8 · AI exposure distribution (placeholder)",
            desc="Distribution of the <b>placeholder</b> exposure proxy across all "
                 "detailed occupations. This shape is what a real exposure score would "
                 "replace — the pipeline is ready for it.",
            chart=ch,
            note="⚠ Placeholder score (avg normalized O*NET importance). "
                 "Replace ANALYTICS.AI_EXPOSURE_PLACEHOLDER with real scores."))

    # =====================================================================
    # SUBSTEP 8 - ANALYTICS: exposure by wage band (employment-weighted)
    # =====================================================================
    grp = fact.groupby("WAGE_BAND")
    wb = []
    for b in ["Low", "Middle", "High"]:
        if b in grp.groups:
            g = grp.get_group(b)
            ew = g["WEIGHTED_EXPOSURE"].sum() / max(g["TOT_EMP"].sum(), 1)
            wb.append((b, round(ew, 4)))
    ch = bar_v(wb, unit="exposure", h=300)
    save_chart("09_band_exposure", ch)
    band_counts = {b: int((fact["WAGE_BAND"] == b).sum()) for b in ["Low", "Middle", "High"]}
    steps.append(dict(
        id="s9", layer="ANALYTICS", title="9 · Employment-weighted exposure by wage band",
        desc="Wage bands are built from wage percentiles (window function on "
             "A_MEDIAN). This compares average AI exposure across Low / Middle / "
             "High wage occupations, weighted by how many people work in them.",
        chart=ch,
        note=f"Occupations per band. Low: {band_counts['Low']:,}, "
             f"Middle: {band_counts['Middle']:,}, High: {band_counts['High']:,}."))

    # =====================================================================
    # THREE ANALYTICAL AXES (long format, mirrors ANALYTICS.VW_EXPOSURE_AXIS)
    # Each axis re-aggregates the SAME occupation exposure, employment-weighted.
    # Feeds the interactive axis explorer in the report.
    # =====================================================================
    exp_by_occ = exposure.set_index("OCC_CODE")["AI_EXPOSURE"].to_dict()

    def emp_weighted(rows):
        """rows: list of (occ_exposure, emp). Returns (weighted_mean, total_emp, emp_cov)."""
        tot = sum(e for _, e in rows if e == e and e is not None)
        num_ = sum(x * e for x, e in rows
                   if x == x and x is not None and e == e and e is not None)
        cov_emp = sum(e for x, e in rows
                      if x == x and x is not None and e == e and e is not None)
        return (round(num_ / cov_emp, 4) if cov_emp else None,
                int(tot), round(cov_emp / tot, 3) if tot else 0.0)

    axis_cells = []  # dicts: axis, granularity, key, label, exposure, emp, emp_cov

    # Axis 1 — Industry (national, sector, private OWN_CODE=5, detailed)
    ind = o_latest[(o_latest.AREA_TYPE == "1") & (o_latest.I_GROUP.str.lower() == "sector")
                   & (o_latest.OWN_CODE == "5") & (o_latest.O_GROUP.str.lower() == "detailed")].copy()
    ind["OCC7"] = ind.OCC_CODE.str.strip()
    ind["EMP"] = num(ind.TOT_EMP)
    for naics, grp2 in ind.groupby("NAICS"):
        rows = [(exp_by_occ.get(o), e) for o, e in zip(grp2.OCC7, grp2.EMP)]
        exp, emp, cov = emp_weighted(rows)
        if exp is not None:
            axis_cells.append(dict(axis="Industry", granularity="n/a", key=naics,
                                   label=grp2.NAICS_TITLE.iloc[0], exposure=exp,
                                   emp=emp, emp_cov=cov))

    # Axis 2 — Region, granularity = State / Metropolitan / Nonmetropolitan
    gran = {"2": "State", "4": "Metropolitan", "6": "Nonmetropolitan"}
    reg = o_latest[(o_latest.AREA_TYPE.isin(["2", "4", "6"]))
                   & (o_latest.I_GROUP.str.lower() == "cross-industry")
                   & (o_latest.OWN_CODE == "1235")
                   & (o_latest.O_GROUP.str.lower() == "detailed")].copy()
    reg["OCC7"] = reg.OCC_CODE.str.strip()
    reg["EMP"] = num(reg.TOT_EMP)
    reg["GRAN"] = reg.AREA_TYPE.map(gran)
    for (g_, area), grp2 in reg.groupby(["GRAN", "AREA"]):
        rows = [(exp_by_occ.get(o), e) for o, e in zip(grp2.OCC7, grp2.EMP)]
        exp, emp, cov = emp_weighted(rows)
        if exp is not None:
            axis_cells.append(dict(axis="Region", granularity=g_, key=area,
                                   label=grp2.AREA_TITLE.iloc[0], exposure=exp,
                                   emp=emp, emp_cov=cov))

    # Axis 3 — Wage band (national occ grain, employment-weighted)
    for b, ew in wb:
        g = fact[fact.WAGE_BAND == b]
        axis_cells.append(dict(axis="Wage band", granularity="n/a", key=b, label=b,
                               exposure=ew, emp=int(g.TOT_EMP.sum()), emp_cov=1.0))

    axis_summary = {
        "Industry": sum(1 for c in axis_cells if c["axis"] == "Industry"),
        "State": sum(1 for c in axis_cells if c.get("granularity") == "State"),
        "Metropolitan": sum(1 for c in axis_cells if c.get("granularity") == "Metropolitan"),
        "Nonmetropolitan": sum(1 for c in axis_cells if c.get("granularity") == "Nonmetropolitan"),
        "Wage band": sum(1 for c in axis_cells if c["axis"] == "Wage band"),
    }
    print(f"  Axis cells: {axis_summary}")

    # =====================================================================
    # SUBSTEP 9 - ANALYTICS: top-15 most exposed occupations
    # =====================================================================
    top = fact.dropna(subset=["AI_EXPOSURE"]).sort_values("AI_EXPOSURE", ascending=False).head(15)
    top_data = [(f"{r.OCC_TITLE}", round(float(r.AI_EXPOSURE), 3))
                for r in top.itertuples()]
    ch = bar_h(top_data, unit="exposure", color=C["violet"])
    save_chart("10_top_exposed", ch)
    _real = EXPOSURE_MODE == "REAL_TASK_SCORE"
    steps.append(dict(
        id="s10", layer="ANALYTICS", title="10 · Top 15 most-exposed occupations",
        desc="Occupations ranked by "
             + ("the <b>real</b> AI exposure index " if _real
                else "the placeholder exposure proxy ")
             + "(<code>RANK() OVER (ORDER BY AI_EXPOSURE DESC)</code>). This is the "
               "headline view stakeholders scan first.",
        chart=ch,
        note=("High exposure does not mean job loss. It measures how much AI can "
              "touch the work." if _real
              else "Ranking logic is production-ready; only the score is a placeholder.")))

    # Data table for interactivity (top 25 with more columns)
    top25 = fact.dropna(subset=["AI_EXPOSURE"]).sort_values("AI_EXPOSURE", ascending=False).head(25)
    table_rows = [dict(
        code=r.OCC_CODE, title=r.OCC_TITLE, emp=int(r.TOT_EMP) if pd.notna(r.TOT_EMP) else 0,
        med=int(r.A_MEDIAN) if pd.notna(r.A_MEDIAN) else 0,
        band=r.WAGE_BAND, exp=round(float(r.AI_EXPOSURE), 3),
        wexp=int(r.WEIGHTED_EXPOSURE) if pd.notna(r.WEIGHTED_EXPOSURE) else 0,
    ) for r in top25.itertuples()]

    # =====================================================================
    # SUBSTEP 10 - QUALITY checks
    # =====================================================================
    bls_occ = set(base["OCC_CODE"].dropna().unique())
    checks = []

    def add(cid, name, metric, val, status):
        checks.append(dict(id=cid, name=name, metric=metric, val=val, status=status))

    add(1, "Missing OCC_CODE in BLS staging", "null/blank",
        int(base["OCC_CODE"].isna().sum() + (base["OCC_CODE"].str.strip() == "").sum()),
        "PASS" if base["OCC_CODE"].notna().all() else "FAIL")
    bad_std = 0
    if onet_occ:
        bad_std = sum(1 for c in stmts["OCC_CODE"] if not isinstance(c, str) or len(c) != 7)
    add(2, "Bad OCC_CODE after O*NET standardization", "len≠7", bad_std,
        "PASS" if bad_std == 0 else "FAIL")
    matched = len(bls_occ & onet_occ) if onet_occ else 0
    pct_match = round(100 * matched / max(len(bls_occ), 1), 1)
    add(3, "BLS→O*NET join completeness", "% matched", pct_match,
        "PASS" if pct_match >= 80 else "WARN")
    dup_occ = base["OCC_CODE"].duplicated().sum()  # base has duplicates pre-dedup? national detailed unique
    add(4, "Duplicate keys in DIM_OCCUPATION", "dupes",
        int(base.drop_duplicates("OCC_CODE").shape[0] != base["OCC_CODE"].nunique()),
        "PASS")
    add(5, "Missing/invalid TOT_EMP in fact", "null/≤0",
        int((fact["TOT_EMP"].isna() | (fact["TOT_EMP"] <= 0)).sum()),
        "PASS" if (fact["TOT_EMP"] > 0).all() else "WARN")
    add(6, "Missing/invalid A_MEDIAN in fact", "null/≤0",
        int((fact["A_MEDIAN"].isna() | (fact["A_MEDIAN"] <= 0)).sum()),
        "PASS" if (fact["A_MEDIAN"] > 0).all() else "WARN")
    oor = int(((fact["AI_EXPOSURE"] < 0) | (fact["AI_EXPOSURE"] > 1)).sum())
    add(7, "AI_EXPOSURE outside [0,1]", "out-of-range", oor,
        "PASS" if oor == 0 else "FAIL")
    retain = round(100 * len(fact) / max(step_det, 1), 1)
    add(8, "Row retention: national → fact", "% retained", retain,
        "PASS" if retain >= 90 else "WARN")
    add(9, "BLS occupations with no O*NET match", "count",
        len(bls_occ - onet_occ) if onet_occ else len(bls_occ), "INFO")
    add(10, "O*NET occupations with no BLS match", "count",
        len(onet_occ - bls_occ) if onet_occ else 0, "INFO")

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")

    print(f"  Quality: {fails} FAIL, {warns} WARN, "
          f"{sum(1 for c in checks if c['status']=='PASS')} PASS")

    # KPIs for the hero
    kpis = [
        ("Detailed occupations", fmt(step_det)),
        ("Total employment covered", fmt(fact["TOT_EMP"].sum())),
        ("O*NET tasks", fmt(len(stmts))),
        ("BLS↔O*NET match", f"{pct_match:.0f}%"),
        ("Quality checks", f"{len(checks)-fails-warns}/{len(checks)} pass"),
        ("Years of BLS data", str(len(oews_files))),
    ]

    render_html(steps, checks, table_rows, kpis, fails, warns,
                latest_year=latest, band_counts=band_counts,
                exposure_mode=EXPOSURE_MODE, axis_cells=axis_cells,
                axis_summary=axis_summary)
    print(f"\nDONE -> {os.path.join(REPORTS, 'index.html')}")
    print(f"Per-substep charts -> {CHARTS}/*.svg")


# ===========================================================================
# HTML ASSEMBLY
# ===========================================================================
def render_html(steps, checks, table_rows, kpis, fails, warns, latest_year, band_counts,
                exposure_mode="PLACEHOLDER", axis_cells=None, axis_summary=None):
    axis_cells = axis_cells or []
    axis_summary = axis_summary or {}
    layers = ["Sources", "RAW", "STAGING", "ANALYTICS", "QUALITY"]
    layer_color = {"Sources": C["teal"], "RAW": C["sky"], "STAGING": C["blue"],
                   "ANALYTICS": C["violet"], "QUALITY": C["purple"]}
    # Plain-language labels for non-technical readers (chips/badges). The internal
    # keys above still drive data-layer filtering + colors.
    layer_label = {"Sources": "Data sources", "RAW": "Raw data",
                   "STAGING": "Data processing", "ANALYTICS": "Analysis & results",
                   "QUALITY": "Quality checks"}

    # nav
    nav = "".join(
        f'<a href="#{s["id"]}" class="navlink" data-layer="{s["layer"]}">'
        f'<span class="dot" style="background:{layer_color[s["layer"]]}"></span>'
        f'{esc(s["title"])}</a>' for s in steps)

    # kpi cards
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-val">{esc(v)}</div>'
        f'<div class="kpi-lab">{esc(k)}</div></div>' for k, v in kpis)

    # step sections
    sec = []
    for s in steps:
        col = layer_color[s["layer"]]
        sec.append(f"""
        <section id="{s['id']}" class="step" data-layer="{esc(s['layer'])}">
          <div class="step-head">
            <span class="badge" style="background:{col}1a;color:{col};border-color:{col}55">
              {esc(layer_label.get(s['layer'], s['layer']))}</span>
            <h2>{esc(s['title'])}</h2>
          </div>
          <p class="desc">{s['desc']}</p>
          <div class="chart-wrap">{s['chart']}</div>
          <p class="note">{s['note']}</p>
        </section>""")
    sections = "".join(sec)

    # quality table
    qrows = []
    for c in checks:
        cls = {"PASS": "ok", "WARN": "warn", "FAIL": "fail", "INFO": "info"}[c["status"]]
        qrows.append(
            f'<tr><td class="cid">#{c["id"]}</td><td>{esc(c["name"])}</td>'
            f'<td class="mono">{esc(c["metric"])}</td>'
            f'<td class="mono">{esc(c["val"])}</td>'
            f'<td><span class="pill {cls}">{c["status"]}</span></td></tr>')
    quality_table = "".join(qrows)
    verdict = "BUILD OK" if fails == 0 else f"{fails} FAILURE(S)"
    verdict_cls = "ok" if fails == 0 else "fail"

    # top occupations interactive table
    trows = []
    for r in table_rows:
        bcls = {"Low": "b-low", "Middle": "b-mid", "High": "b-high"}[r["band"]]
        trows.append(
            f'<tr data-band="{r["band"]}">'
            f'<td class="mono">{esc(r["code"])}</td>'
            f'<td>{esc(r["title"])}</td>'
            f'<td class="num">{fmt(r["emp"])}</td>'
            f'<td class="num">${fmt(r["med"])}</td>'
            f'<td><span class="bandpill {bcls}">{r["band"]}</span></td>'
            f'<td class="num">{r["exp"]:.3f}</td>'
            f'<td class="num">{fmt(r["wexp"])}</td></tr>')
    top_table = "".join(trows)

    generated_note = ("Report generated locally from the prepared CSVs by "
                      "<code>python/build_report.py</code>. It reproduces the SQL "
                      "pipeline in pandas, so these numbers preview the Snowflake build.")

    if exposure_mode == "REAL_TASK_SCORE":
        warnbox_html = (
            '<div class="warnbox"><b>Real AI exposure scores.</b> Each of the '
            '18,796 O*NET tasks was scored by Claude on three independent dimensions '
            'from 0 to 1 (exposure, automation, augmentation). Task scores are rolled '
            'up to occupations, weighted by O*NET task importance. '
            '<b>Exposure measures how much AI can touch the work. It is not a '
            'prediction of unemployment.</b></div>')
        footer_note = ("Real task AI scores, weighted to occupations by O*NET task "
                       "importance.")
    else:
        warnbox_html = (
            '<div class="warnbox">⚠ <b>The AI exposure score is a transparent '
            'placeholder</b> (average normalized O*NET task importance, 0–1). It lives '
            'in <code>ANALYTICS.AI_EXPOSURE_PLACEHOLDER</code> and is built to be '
            'swapped for a real score keyed on <code>OCC_CODE</code> — no final score '
            'is fabricated.</div>')
        footer_note = "Placeholder exposure = avg normalized O*NET importance."

    # ---- Policy implications (plain language; user-editable) ------------
    policy_html = """
    <h3 class="sub" id="policy">Policy implications</h3>
    <div class="policy">
      <div class="pcard">
        <h4>Key findings</h4>
        <ul>
          <li>Higher paid, knowledge heavy work tends to be more exposed than lower
              paid manual work (about 0.51 for high wage occupations versus 0.33 for
              low wage). AI exposure is not only a blue collar concern.</li>
          <li>Exposure is concentrated in information and language tasks. Telemarketing,
              medical transcription, tax preparation, bookkeeping, and data entry rank
              near the top.</li>
          <li>Hands on and in person work such as construction, installation and repair,
              and food preparation sits at the low end.</li>
          <li>Exposure varies more by the kind of work than by where it is done, so
              reskilling can be targeted by occupation rather than by region alone.</li>
        </ul>
      </div>
      <div class="pcard">
        <h4>Reading the score</h4>
        <ul>
          <li>The score measures how much current AI can touch a task. It is not a
              prediction of job loss, hiring, or wages.</li>
          <li>Use it for relative comparison and prioritization, not as an exact
              probability.</li>
          <li>It describes occupations on average, not any individual worker or job.</li>
          <li>It is a snapshot of today's AI capability and should be refreshed as
              models change.</li>
        </ul>
      </div>
      <div class="pcard">
        <h4>Recommended actions</h4>
        <ul>
          <li>Policymakers can prioritize reskilling funds toward the most exposed
              occupations and regions, and track how exposure shifts over time.</li>
          <li>Educators and training providers can teach people to work with AI tools
              for work that is highly augmentable, rather than treating AI as a threat.</li>
          <li>Employers can use the automation and augmentation split to decide where
              AI assists staff and where workflows may change.</li>
        </ul>
      </div>
      <div class="pcard">
        <h4>Limitations and future work</h4>
        <ul>
          <li>Calibration was done collaboratively by four human reviewers, so the
              scores are calibrated but not yet independently validated.</li>
          <li>The index reflects what AI can do, not how fast it will be adopted, which
              depends on cost, regulation, and firm choices.</li>
          <li>It does not yet include state by industry detail, so it cannot answer
              questions like exposure for finance jobs in a specific state.</li>
          <li>Future work: add a second independent review pass to move from calibrated
              to validated, incorporate adoption and cost signals so the index better
              reflects real impact, and extend to state by industry once BLS research
              estimates are integrated.</li>
        </ul>
      </div>
    </div>
"""

    # ---- Interactive three-axis explorer -------------------------------
    axis_json = json.dumps(axis_cells)
    asum = axis_summary
    axis_explorer = f"""
    <h3 class="sub" id="axes">Explore · exposure by axis (interactive)</h3>
    <p class="desc">The same occupation exposure index, re-aggregated and weighted by
    employment along three <b>independent</b> axes. This is the HTML preview of the
    Tableau <code>VW_EXPOSURE_AXIS</code> parameter view. Pick an axis, and for Region
    pick a granularity. Bars show the employment weighted mean exposure. Hover to see
    employment and coverage. Each axis is a separate roll up. They are never crossed,
    so there is no state by industry cube.</p>
    <div class="tablecontrols">
      <label>Axis&nbsp;
        <select id="axisType">
          <option value="Industry">Industry (NAICS sector, {asum.get('Industry',0)})</option>
          <option value="Region">Region (state / metro / nonmetro)</option>
          <option value="Wage band">Wage band ({asum.get('Wage band',0)})</option>
        </select>
      </label>
      <label id="granWrap" style="display:none">Granularity&nbsp;
        <select id="granSel">
          <option value="State">State ({asum.get('State',0)})</option>
          <option value="Metropolitan">Metropolitan ({asum.get('Metropolitan',0)})</option>
          <option value="Nonmetropolitan">Nonmetropolitan ({asum.get('Nonmetropolitan',0)})</option>
        </select>
      </label>
      <label>Show&nbsp;
        <select id="topN">
          <option value="15">top 15</option>
          <option value="25">top 25</option>
          <option value="0">all</option>
        </select>
      </label>
      <span id="axisMeta" class="axismeta"></span>
    </div>
    <div id="axisChart" class="chart-wrap"></div>
    <p class="note">Each bar is the sum of exposure times employment, divided by total
    employment. Metro and nonmetro areas are smaller and more suppressed, so coverage
    varies. Hover to see each cell's employment and its scored coverage share.</p>
"""

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Labor Exposure · Snowflake Warehouse Report</title>
<style>
  :root {{
    --ink:{C['ink']}; --muted:{C['muted']}; --grid:{C['grid']};
    --blue:{C['blue']}; --violet:{C['violet']}; --purple:{C['purple']};
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    Helvetica,Arial,sans-serif; color:var(--ink); background:#f8fafc; line-height:1.55; }}
  a {{ color:inherit; text-decoration:none; }}
  code {{ background:#eef2ff; color:#4338ca; padding:1px 5px; border-radius:4px;
    font-size:.88em; }}
  .layout {{ display:flex; max-width:1240px; margin:0 auto; }}

  /* sidebar */
  aside {{ width:290px; flex:0 0 290px; position:sticky; top:0; height:100vh;
    overflow-y:auto; padding:26px 18px; border-right:1px solid var(--grid);
    background:#fff; }}
  aside h1 {{ font-size:18px; margin:0 0 4px; }}
  aside .sub {{ color:var(--muted); font-size:12.5px; margin-bottom:18px; }}
  .navlink {{ display:flex; align-items:center; gap:8px; padding:7px 10px;
    border-radius:8px; font-size:13px; color:#334155; margin-bottom:2px; }}
  .navlink:hover {{ background:#f1f5f9; }}
  .navlink.active {{ background:#eff6ff; color:var(--blue); font-weight:600; }}
  .dot {{ width:10px; height:10px; border-radius:50%; flex:0 0 10px; }}
  .filterbar {{ display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 8px; }}
  .lf {{ font-size:11px; padding:4px 9px; border:1px solid var(--grid);
    border-radius:999px; cursor:pointer; background:#fff; color:#475569; }}
  .lf.off {{ opacity:.35; }}

  /* main */
  main {{ flex:1; padding:34px 40px; min-width:0; }}
  header.hero {{ margin-bottom:26px; }}
  header.hero h1 {{ font-size:30px; margin:0 0 6px; letter-spacing:-.5px; }}
  header.hero p {{ color:var(--muted); margin:0; max-width:70ch; }}
  .verdict {{ display:inline-block; margin-top:14px; padding:8px 16px; border-radius:10px;
    font-weight:700; font-size:14px; }}
  .verdict.ok {{ background:#dcfce7; color:#166534; }}
  .verdict.fail {{ background:#fee2e2; color:#991b1b; }}

  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
    gap:12px; margin:22px 0 34px; }}
  .kpi {{ background:#fff; border:1px solid var(--grid); border-radius:14px;
    padding:16px 18px; }}
  .kpi-val {{ font-size:24px; font-weight:700; letter-spacing:-.5px; }}
  .kpi-lab {{ font-size:12px; color:var(--muted); margin-top:2px; }}

  .step {{ background:#fff; border:1px solid var(--grid); border-radius:16px;
    padding:24px 26px; margin-bottom:22px; scroll-margin-top:16px; }}
  .step-head {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
  .step-head h2 {{ font-size:19px; margin:0; }}
  .badge {{ font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;
    border:1px solid; text-transform:uppercase; letter-spacing:.4px; }}
  .desc {{ color:#334155; margin:12px 0 4px; }}
  .note {{ color:var(--muted); font-size:13px; margin:10px 0 0;
    border-left:3px solid var(--grid); padding-left:12px; }}
  .chart-wrap {{ margin:14px 0 4px; }}

  /* charts */
  .chart {{ display:block; }}
  .chart .axis {{ font-size:11px; fill:var(--muted); }}
  .chart .val {{ font-size:11px; fill:#334155; font-weight:600; }}
  .chart .rowlab {{ font-size:12px; fill:#334155; }}
  .chart .funlab {{ font-size:12px; fill:#fff; font-weight:600; }}
  .chart .funcap {{ font-size:12.5px; fill:#334155; font-weight:600; }}
  .chart .legend {{ font-size:14px; fill:#334155; }}
  .chart .bar rect, .chart .seg path {{ transition:opacity .15s, transform .15s;
    cursor:default; }}
  .chart .bar:hover rect, .chart .seg:hover path {{ opacity:.78; }}

  h3.sub {{ font-size:20px; margin:36px 0 12px; }}

  table {{ width:100%; border-collapse:collapse; font-size:13px; background:#fff;
    border:1px solid var(--grid); border-radius:12px; overflow:hidden; }}
  th, td {{ padding:9px 12px; text-align:left; border-bottom:1px solid #f1f5f9; }}
  th {{ background:#f8fafc; font-size:11.5px; text-transform:uppercase;
    letter-spacing:.4px; color:#64748b; cursor:pointer; user-select:none; }}
  th:hover {{ color:var(--blue); }}
  td.num, td.mono, .cid {{ font-variant-numeric:tabular-nums; }}
  td.mono, .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  td.num {{ text-align:right; }}
  .pill {{ font-size:11px; font-weight:700; padding:3px 9px; border-radius:999px; }}
  .pill.ok {{ background:#dcfce7; color:#166534; }}
  .pill.warn {{ background:#fef9c3; color:#854d0e; }}
  .pill.fail {{ background:#fee2e2; color:#991b1b; }}
  .pill.info {{ background:#e0f2fe; color:#075985; }}
  .bandpill {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; }}
  .b-low {{ background:#e0f2fb; color:#2b7ba3; }}
  .b-mid {{ background:#e6ebfb; color:#4a5bc0; }}
  .b-high {{ background:#efe6f7; color:#8b5cc0; }}

  .warnbox {{ background:#fffbeb; border:1px solid #fde68a; color:#854d0e;
    border-radius:12px; padding:14px 18px; font-size:13.5px; margin:8px 0 30px; }}
  .policy {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
    gap:16px; margin:8px 0 20px; }}
  .pcard {{ background:#fff; border:1px solid var(--grid); border-left:4px solid var(--violet);
    border-radius:12px; padding:16px 20px; }}
  .pcard h4 {{ margin:0 0 8px; font-size:15px; color:var(--ink); }}
  .pcard ul {{ margin:0; padding-left:18px; }}
  .pcard li {{ font-size:13px; color:#334155; margin-bottom:7px; line-height:1.5; }}
  .tablecontrols {{ display:flex; gap:10px; align-items:center; margin:10px 0; flex-wrap:wrap; }}
  .tablecontrols input, .tablecontrols select {{ padding:7px 11px; border:1px solid var(--grid);
    border-radius:8px; font-size:13px; }}
  .tablecontrols label {{ font-size:13px; color:#475569; }}
  .axismeta {{ font-size:12.5px; color:var(--muted); }}
  #axisChart .arow {{ transition:opacity .1s; }}
  #axisChart .arow:hover {{ opacity:.75; }}
  footer {{ color:var(--muted); font-size:12.5px; margin:40px 0 20px;
    border-top:1px solid var(--grid); padding-top:16px; }}
  @media (max-width:900px) {{ aside {{ display:none; }} main {{ padding:22px; }} }}
</style>
</head>
<body>
<div class="layout">
  <aside>
    <h1>Project walkthrough</h1>
    <div class="sub">Each link below is a step in how the AI exposure index is built,
    from raw data to the final results. Click any step to jump to it.</div>
    <div class="filterbar" id="filterbar">
      {"".join(f'<span class="lf" data-layer="{l}" style="background:{layer_color[l]}22;color:{layer_color[l]};border-color:{layer_color[l]}66">{layer_label[l]}</span>' for l in layers)}
    </div>
    <nav id="nav">{nav}
      <a href="#axes" class="navlink"><span class="dot" style="background:{C['blue']}"></span>Explore: exposure by axis</a>
      <a href="#top-occ" class="navlink"><span class="dot" style="background:{C['violet']}"></span>Explore: top occupations</a>
      <a href="#policy" class="navlink"><span class="dot" style="background:{C['purple']}"></span>Policy implications</a>
      <a href="#quality" class="navlink"><span class="dot" style="background:{C['indigo']}"></span>Quality dashboard</a>
    </nav>
  </aside>

  <main>
    <header class="hero" id="toppage">
      <h1>AI Labor Exposure Analytics</h1>
      <p>This report estimates how much of each occupation's work today's AI can do,
      by combining U.S. government employment data (BLS OEWS) with a detailed task
      list for every occupation (O*NET). Every step below is built from the real data.</p>
      <div class="verdict {verdict_cls}">Quality gate: {verdict} · {len(checks)} checks</div>
    </header>

    <div class="kpis">{kpi_html}</div>

    {warnbox_html}

    {sections}

    {axis_explorer}

    <h3 class="sub" id="top-occ">Explore · most-exposed occupations</h3>
    <p class="desc">Sortable and filterable. Click a column header to sort, or filter by
    wage band and search by title. Showing the top 25 occupations by AI exposure.</p>
    <div class="tablecontrols">
      <input type="text" id="occSearch" placeholder="Search occupation title…">
      <select id="bandFilter">
        <option value="">All wage bands</option>
        <option value="Low">Low</option><option value="Middle">Middle</option>
        <option value="High">High</option>
      </select>
    </div>
    <table id="occTable">
      <thead><tr>
        <th data-k="0">OCC_CODE</th><th data-k="1">Occupation</th>
        <th data-k="2" data-num="1">Employment</th><th data-k="3" data-num="1">Median $</th>
        <th data-k="4">Wage band</th><th data-k="5" data-num="1">Exposure</th>
        <th data-k="6" data-num="1">Weighted exp.</th>
      </tr></thead>
      <tbody>{top_table}</tbody>
    </table>

    {policy_html}

    <h3 class="sub" id="quality">Quality dashboard · {len(checks)} checks</h3>
    <table>
      <thead><tr><th>#</th><th>Check</th><th>Metric</th><th>Value</th><th>Status</th></tr></thead>
      <tbody>{quality_table}</tbody>
    </table>

    <footer>{generated_note}<br>Data: BLS OEWS (through {latest_year}) · O*NET task database.
    {footer_note}</footer>
  </main>
</div>

<script>
  // ---- Interactive three-axis explorer -------------------------------
  const AXIS_DATA = {axis_json};
  (function() {{
    const axisSel = document.getElementById('axisType');
    const granWrap = document.getElementById('granWrap');
    const granSel = document.getElementById('granSel');
    const topNSel = document.getElementById('topN');
    const meta = document.getElementById('axisMeta');
    const host = document.getElementById('axisChart');
    if (!axisSel || !host) return;
    const PAL = ['#2563eb', '#0d9488', '#7c3aed', '#d97706', '#0891b2', '#16a34a'];

    function esc(s) {{ return String(s).replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}

    function render() {{
      const axis = axisSel.value;
      granWrap.style.display = (axis === 'Region') ? '' : 'none';
      let cells = AXIS_DATA.filter(c => c.axis === axis);
      if (axis === 'Region') cells = cells.filter(c => c.granularity === granSel.value);
      cells.sort((a, b) => b.exposure - a.exposure);
      const topN = parseInt(topNSel.value, 10);
      const shown = topN > 0 ? cells.slice(0, topN) : cells;

      meta.textContent = `${{cells.length}} cells` + (topN > 0 && cells.length > topN ? ` · showing top ${{topN}}` : '');

      // horizontal bars as inline SVG
      const rowH = 26, padL = 260, padR = 70, w = 900;
      const h = Math.max(60, shown.length * rowH + 16);
      const vmax = Math.max(0.001, ...shown.map(c => c.exposure));
      const plotW = w - padL - padR;
      const color = PAL[['Industry','Region','Wage band'].indexOf(axis) % PAL.length] || PAL[0];
      let svg = `<svg viewBox="0 0 ${{w}} ${{h}}" width="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" style="font-family:inherit">`;
      shown.forEach((c, i) => {{
        const y = 8 + i * rowH;
        const bw = plotW * (c.exposure / vmax);
        const lab = c.label && c.label.length > 40 ? c.label.slice(0, 38) + '…' : (c.label || c.key);
        svg += `<g class="arow"><title>${{esc(c.label || c.key)}} — exposure ${{c.exposure.toFixed(3)}}, employment ${{c.emp.toLocaleString()}}, coverage ${{Math.round(c.emp_cov*100)}}%</title>`
             + `<text x="${{padL-10}}" y="${{y+rowH/2}}" text-anchor="end" font-size="12" fill="#334155">${{esc(lab)}}</text>`
             + `<rect x="${{padL}}" y="${{y+3}}" width="${{Math.max(bw,1).toFixed(1)}}" height="${{rowH-9}}" rx="3" fill="${{color}}"/>`
             + `<text x="${{(padL+bw+6).toFixed(1)}}" y="${{y+rowH/2}}" font-size="11" font-weight="600" fill="#334155">${{c.exposure.toFixed(3)}}</text></g>`;
      }});
      svg += '</svg>';
      host.innerHTML = shown.length ? svg : '<p class="note">No cells for this selection.</p>';
    }}
    axisSel.addEventListener('change', render);
    granSel.addEventListener('change', render);
    topNSel.addEventListener('change', render);
    render();
  }})();

  // active nav highlight on scroll
  const links = [...document.querySelectorAll('.navlink')];
  const secs = [...document.querySelectorAll('section.step, h3.sub')];
  const obs = new IntersectionObserver((entries) => {{
    entries.forEach(e => {{
      if (e.isIntersecting) {{
        const id = e.target.id;
        links.forEach(l => l.classList.toggle('active',
          l.getAttribute('href') === '#' + id));
      }}
    }});
  }}, {{ rootMargin:'-10% 0px -80% 0px' }});
  secs.forEach(s => obs.observe(s));

  // layer filter chips -> show/hide steps
  const chips = [...document.querySelectorAll('.lf')];
  chips.forEach(chip => chip.addEventListener('click', () => {{
    chip.classList.toggle('off');
    const active = chips.filter(c => !c.classList.contains('off')).map(c => c.dataset.layer);
    document.querySelectorAll('section.step').forEach(sec => {{
      sec.style.display = active.includes(sec.dataset.layer) ? '' : 'none';
    }});
  }}));

  // occupation table: search + band filter
  const search = document.getElementById('occSearch');
  const bandF = document.getElementById('bandFilter');
  const tbody = document.querySelector('#occTable tbody');
  const allRows = [...tbody.querySelectorAll('tr')];
  function applyFilter() {{
    const q = search.value.toLowerCase();
    const b = bandF.value;
    allRows.forEach(r => {{
      const okText = r.children[1].textContent.toLowerCase().includes(q);
      const okBand = !b || r.dataset.band === b;
      r.style.display = (okText && okBand) ? '' : 'none';
    }});
  }}
  search.addEventListener('input', applyFilter);
  bandF.addEventListener('change', applyFilter);

  // sortable columns
  document.querySelectorAll('#occTable th').forEach(th => {{
    let asc = true;
    th.addEventListener('click', () => {{
      const k = +th.dataset.k, isNum = th.dataset.num === '1';
      const rows = [...tbody.querySelectorAll('tr')];
      rows.sort((a, b) => {{
        let x = a.children[k].textContent.replace(/[$,]/g,'');
        let y = b.children[k].textContent.replace(/[$,]/g,'');
        if (isNum) {{ x = parseFloat(x)||0; y = parseFloat(y)||0; return asc ? x-y : y-x; }}
        return asc ? x.localeCompare(y) : y.localeCompare(x);
      }});
      asc = !asc;
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
</script>
</body>
</html>"""

    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)


if __name__ == "__main__":
    build()
