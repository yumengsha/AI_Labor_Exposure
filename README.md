# AI Labor Exposure Analytics — Snowflake Data Warehouse

A beginner-friendly Snowflake data warehouse that combines **BLS OEWS**
(occupational employment & wage) data with **O\*NET task** data to support
analysis of **AI exposure by occupation, industry, wage level, and region** —
built for downstream **Tableau** dashboards.

> **Why this project?** It studies how AI may affect different occupations. The
> aim is not just a technical exposure score, but helping non-technical
> stakeholders see *which workers are more exposed*, *how exposure varies by
> industry/region/wage*, and *how results can guide workforce planning and
> reskilling*.

---

## 1. What gets built

A single database **`AI_LABOR_ANALYTICS`** with a clean four-layer structure:

| Schema | Purpose |
|--------|---------|
| `RAW` | Exact, untransformed copies of the source files (loaded as text). |
| `STAGING` | Cleaned column names, standardized occupation codes, cast numbers, filtered rows (views). |
| `ANALYTICS` | **Star schema** (fact + dimensions) for Tableau. |
| `QUALITY` | 10 data-quality checks with a PASS/WARN/FAIL results table. |

Compute runs on the **`AI_LABOR_WH`** warehouse (XSMALL, auto-suspend).

### The star schema

```
                        ┌──────────────────────┐
                        │   DIM_OCCUPATION      │
                        │  OCC_CODE (PK)        │
                        │  OCC_TITLE, O_GROUP   │
                        └───────────┬──────────┘
                                    │
   ┌────────────────┐   ┌───────────┴───────────────┐   ┌────────────────┐
   │  DIM_REGION    │   │ OCCUPATION_EXPOSURE_FACT   │   │  DIM_INDUSTRY  │
   │  AREA (PK)     ├──►│  OCC_CODE, OCC_TITLE       │◄──┤  NAICS (PK)    │
   │  AREA_TITLE    │   │  TOT_EMP, A_MEAN, A_MEDIAN │   │  INDUSTRY_TITLE│
   │  STATE         │   │  WAGE_PERCENTILE, WAGE_BAND│   └────────────────┘
   └────────────────┘   │  AI_EXPOSURE (placeholder) │
                        │  WEIGHTED_EXPOSURE         │   ┌────────────────┐
   ┌────────────────┐   │  EXPOSURE_RANK             │   │ DIM_WAGE_BAND  │
   │   DIM_TASK     │   │  AREA, STATE, NAICS ...    ├──►│ WAGE_BAND (PK) │
   │  TASK_ID (PK)  ├──►│                            │   │ PCTL_MIN/MAX   │
   │  OCC_CODE      │   └────────────────────────────┘   └────────────────┘
   │  TASK_STATEMENT│
   │  TASK_TYPE     │   Fact grain: one row per detailed occupation
   └────────────────┘   (latest BLS year, national, cross-industry).
```

- **`OCCUPATION_EXPOSURE_FACT`** — one row per detailed occupation with
  employment, wages, wage percentile/band, AI exposure, weighted exposure, and
  region/industry attributes.
- **Dimensions** — `DIM_OCCUPATION`, `DIM_TASK`, `DIM_REGION`, `DIM_INDUSTRY`,
  `DIM_WAGE_BAND`.

### ⚠️ The AI exposure score is a **placeholder**

We don't have an external AI-exposure dataset yet, so `AI_EXPOSURE` is a
**transparent proxy**: the average *normalized O\*NET task importance* per
occupation, scaled to `0–1`. It lives in its own table
`ANALYTICS.AI_EXPOSURE_PLACEHOLDER` and every row is tagged
`SCORE_SOURCE = 'PLACEHOLDER_ONET_IMPORTANCE_PROXY'`. **Replace it** by
overwriting that table with real scores keyed on `OCC_CODE` — the fact table
picks them up automatically. No real score is fabricated.

---

## 2. The occupation-code join (important!)

O\*NET and BLS use *almost* the same occupation codes:

| Source | Example code |
|--------|-------------|
| O\*NET | `11-1021.00` |
| BLS    | `11-1021` |

We standardize by taking the **first 7 characters** of the O\*NET SOC code:

```sql
OCC_CODE = LEFT("O*NET-SOC Code", 7)   -- 11-1021.00 -> 11-1021
```

This `OCC_CODE` is the shared join key throughout STAGING and ANALYTICS.

---

## 3. Project layout

```
ai_labor_snowflake/
├── README.md                     ← you are here
├── .env.example                  ← copy to .env, fill in account + user
├── requirements.txt
├── AUTOMATION.md                 ← how to auto-update from BLS/O*NET
├── sql/
│   ├── 00_create_environment.sql ← warehouse, database, schemas
│   ├── 01_create_raw_tables.sql  ← RAW landing tables (text)
│   ├── 02_load_raw_data.sql      ← stage + COPY INTO (reference/manual)
│   ├── 03_create_staging_views.sql ← clean, cast, standardize OCC_CODE
│   ├── 04_create_analytics_tables.sql ← star schema + placeholder exposure
│   ├── 05_quality_checks.sql     ← 10 data-quality checks
│   ├── 06_refresh_analytics.sql  ← rebuild log for automated refreshes
│   └── 07_create_service_user.sql ← TYPE=SERVICE user + key-pair auth (automation)
├── python/
│   ├── sf_connect.py             ← shared connector (browser OR key-pair auth)
│   ├── prepare_data.py           ← xlsx → CSV; stage O*NET txt files
│   ├── test_connection.py        ← verify Snowflake connection
│   ├── load_local_files.py       ← PUT files to stage + COPY INTO
│   ├── fetch_sources.py          ← auto-download new BLS/O*NET files
│   ├── refresh_pipeline.py       ← one-command end-to-end refresh
│   └── build_report.py           ← builds the visualizations + HTML report
├── scheduling/                   ← cron / launchd / GitHub Actions examples
│   ├── run_refresh.sh
│   ├── crontab.example
│   ├── com.ailabor.refresh.plist
│   └── .github/workflows/refresh.yml
├── data/
│   ├── raw/                       ← prepared CSVs land here (git-ignored)
│   └── processed/
└── reports/                       ← interactive HTML report + chart images
    └── index.html
```

---

## 4. Setup — step by step

### 4.1 Python environment

```bash
cd ai_labor_snowflake
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4.2 Create your `.env`

```bash
cp .env.example .env
```

Then edit `.env` and set **`SNOWFLAKE_ACCOUNT`** and **`SNOWFLAKE_USER`**.
Leave `SNOWFLAKE_AUTHENTICATOR=externalbrowser` — **no password is needed or
stored**. When you connect, Snowflake opens your browser to log in.

### 4.3 Test the connection

```bash
python python/test_connection.py
```

A browser window opens for SSO. On success it prints:

```
CURRENT_USER()      : ...
CURRENT_ROLE()      : ...
CURRENT_WAREHOUSE() : AI_LABOR_WH
CURRENT_DATABASE()  : AI_LABOR_ANALYTICS
```

---

## 5. Where to put the source data

The four **BLS OEWS** yearly zips and the **O\*NET** text bundle live in the
sibling `data_warehouse/` folder by default. The prep script reads them from
there and writes clean CSVs into `data/raw/`:

| Source download | What it is |
|-----------------|-----------|
| `oesm22all.zip … oesm25all.zip` | BLS OEWS workbooks, 2022–2025 (`.xlsx`) |
| `db_30_3_text.zip` | O\*NET text bundle (contains Task Statements + Ratings) |
| `Task Ratings.txt` | O\*NET task ratings (used preferentially if present) |

Prepare the data (converts Excel → CSV; Snowflake can't load `.xlsx` directly):

```bash
python python/prepare_data.py
# or point at a custom folder:
python python/prepare_data.py --source /path/to/downloads
```

This produces in `data/raw/`:
`oews_2022.csv … oews_2025.csv`, `onet_task_ratings.csv`,
`onet_task_statements.csv`.

---

## 6. Run the SQL scripts **in order**

Run these in a Snowflake worksheet, SnowSQL, or your IDE — **in numeric order**.
Use a role that can create warehouses/databases for `00` (e.g. `SYSADMIN`).

| # | Script | Does |
|---|--------|------|
| 00 | `sql/00_create_environment.sql` | Warehouse, database, 4 schemas |
| 01 | `sql/01_create_raw_tables.sql`  | RAW landing tables |
| 02 | `sql/02_load_raw_data.sql`      | File formats + stage + COPY INTO *(reference)* |
| 03 | `sql/03_create_staging_views.sql` | Cleaned/standardized STAGING views |
| 04 | `sql/04_create_analytics_tables.sql` | Star schema + placeholder exposure |
| 05 | `sql/05_quality_checks.sql`     | Data-quality checks → `QUALITY.DQ_RESULTS` |

### Loading the data (step 02, the easy way)

The web worksheet **cannot** run `PUT` (it has no access to your local disk).
Use the Python loader, which does `PUT` + `COPY INTO` for you:

```bash
# after running 00 and 01, and after prepare_data.py:
python python/load_local_files.py
# full refresh (empties RAW tables first):
python python/load_local_files.py --truncate
```

Then continue with `03`, `04`, `05`.

---

## 7. Data-quality checks

`sql/05_quality_checks.sql` writes one row per check into
`QUALITY.DQ_RESULTS` with a `PASS` / `WARN` / `FAIL` / `INFO` status:

1. Missing `OCC_CODE` in BLS staging
2. Missing/short `OCC_CODE` after O\*NET standardization
3. BLS → O\*NET join completeness (% matched)
4. Duplicate keys in each dimension table
5. Missing/invalid `TOT_EMP`
6. Missing/invalid `A_MEDIAN`
7. Exposure scores outside `0–1`
8. Record counts before and after joins (retention %)
9. BLS occupations with no O\*NET match
10. O\*NET occupations with no BLS match

Final verdict row: `BUILD OK` when there are zero `FAIL`s.

---

## 7b. Keeping the data up to date automatically

BLS and O\*NET publish new data periodically (BLS ~yearly, O\*NET quarterly).
To auto-download new source files and refresh the warehouse, see
**[AUTOMATION.md](AUTOMATION.md)**. In short:

```bash
python python/fetch_sources.py --check-only     # is there anything new?
python python/refresh_pipeline.py               # fetch + prepare (no writes)
python python/refresh_pipeline.py --load        # + load into Snowflake & rebuild
```

Unattended runs need **key-pair auth** on a `TYPE=SERVICE` user (see
`sql/07_create_service_user.sql`) because Snowflake is retiring password auth
for service accounts. Schedule it with launchd / cron / GitHub Actions
(examples in `scheduling/`).

---

## 8. Connecting Tableau to the final tables

1. In Tableau: **Connect → To a Server → Snowflake**.
2. **Server** = your account URL (e.g. `abcd-xy12345.snowflakecomputing.com`),
   **Authentication** = *Sign in using browser* (OAuth/SSO — matches this
   project's no-password design).
3. Choose **Warehouse** `AI_LABOR_WH`, **Database** `AI_LABOR_ANALYTICS`,
   **Schema** `ANALYTICS`.
4. Drag **`OCCUPATION_EXPOSURE_FACT`** to the canvas as the central table, then
   join the dimensions:
   - `DIM_OCCUPATION` on `OCC_CODE`
   - `DIM_REGION` on `AREA`
   - `DIM_INDUSTRY` on `NAICS`
   - `DIM_WAGE_BAND` on `WAGE_BAND`
   - `DIM_TASK` on `OCC_CODE` (for task-level drill-down)
5. Suggested dashboards: exposure by wage band, top-N most-exposed occupations
   (`EXPOSURE_RANK`), employment-weighted exposure by region/industry.

> Because `ANALYTICS` is a proper star schema, Tableau treats the fact table as
> the center and each dimension as a filter/grouping — no extra modeling needed.

---

## 9. Reports & visualizations

Open **`reports/index.html`** in any browser for an interactive summary of the
whole build: data profile, pipeline layers, star schema, exposure distribution,
and quality checks. Regenerate it anytime with:

```bash
python python/build_report.py
```

---

## 10. Notes & conventions

- **Security:** `.env` and everything in `data/` are for your machine only —
  don't commit them. External browser auth means **no password is stored**.
- **Idempotent SQL:** scripts use `CREATE OR REPLACE` / `IF NOT EXISTS`, so
  re-running is safe.
- **Clarity first:** RAW is all text; all cleaning/casting happens in STAGING;
  analytics logic uses CTEs and window functions you can read top-to-bottom.
