# Automating data updates from BLS & O\*NET

This guide explains how to keep the warehouse up to date automatically, what
the sources' real-world quirks are, and the authentication you need. It answers
three questions:

1. Is my account + password enough? **(No — and here's why.)**
2. How do updates get detected on the BLS/O\*NET sites?
3. What exactly do I run to auto-update Snowflake?

---

## 1. Authentication: password is NOT enough for automation

Your interactive scripts use **external browser SSO** (no password) — perfect
for running things by hand, but a scheduled job has no human to click the
browser prompt. And a stored **password won't work either**, because Snowflake
is phasing out password auth for automated/service accounts:

| Phase | Timing | What changes |
|-------|--------|--------------|
| 1 | Sep 2025 – Jan 2026 | MFA required for human users in Snowsight |
| 2 | May 2026 – Jul 2026 | New service users must be `TYPE=SERVICE` (no password-only) |
| 3 | **Aug 2026 – Oct 2026** | **All non-human users blocked from password auth** |

**The supported method for unattended jobs is key-pair (RSA) authentication on a
`TYPE=SERVICE` user.** No password, no browser, no MFA prompt.

### One-time setup

```bash
# 1. Generate a key pair (keep the PRIVATE key secret).
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

2. Create the service user + attach the **public** key: run
   [`sql/07_create_service_user.sql`](sql/07_create_service_user.sql) (paste
   your `rsa_key.pub` body into the `ALTER USER ... SET RSA_PUBLIC_KEY` line).

3. Point your `.env` (or CI secrets) at it:
   ```ini
   SNOWFLAKE_USER=SVC_AI_LABOR_LOADER
   SNOWFLAKE_ROLE=AI_LABOR_LOADER
   SNOWFLAKE_AUTHENTICATOR=snowflake_jwt
   SNOWFLAKE_PRIVATE_KEY_PATH=/secure/path/rsa_key.p8
   # SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=   # only if you encrypted the key
   ```

4. Verify: `python python/test_connection.py` (same script, now non-interactive).

> The password sitting in `data_warehouse/account_info.txt` is never used by any
> of this — and shouldn't be. It's kept read-only and out of every config file.

---

## 2. How updates are detected on the source sites

I verified both sites live. They behave differently:

| | BLS OEWS | O\*NET |
|---|----------|--------|
| **Release cadence** | ~once a year (May reference period, published the following spring) | quarterly (main update Q3) |
| **URL pattern** | `bls.gov/oes/special.requests/oesm{YY}all.zip` | `onetcenter.org/dl_files/database/db_{VER}_text.zip` |
| **Versioning** | by year (`oesm24all.zip`) | by version (`db_30_3_text.zip` → `db_30_4_…`) |
| **Bot protection** | ⚠️ **Akamai** — plain scripts get HTTP 403; needs browser-like headers + a `Referer`, and rate-limits rapid requests | none; even exposes `ETag`/`Last-Modified` |
| **Gotcha** | **soft-404**: returns HTTP 200 with an HTML page for years that don't exist yet | version-pinned URLs (no "latest" alias) |

[`python/fetch_sources.py`](python/fetch_sources.py) handles all of this:
- sends a full browser header set + `Referer` so BLS accepts it;
- **polite delays + exponential backoff** so it doesn't trip Akamai's limiter;
- **validates the download is a real ZIP** (Content-Type + `PK` magic bytes) so a
  soft-404 HTML page is never saved as a `.zip`;
- **auto-discovers the newest O\*NET version** by scraping the downloads page;
- records each file's ETag/size in `data_warehouse/.source_manifest.json` and
  **skips anything unchanged** — so running it often is cheap.

Check for updates without downloading anything:

```bash
python python/fetch_sources.py --check-only
```

---

## 3. What to run to auto-update Snowflake

One command does the whole chain — **fetch → prepare → load → rebuild**:

```bash
# Local only (fetch new files + convert to CSV; NO Snowflake writes):
python python/refresh_pipeline.py

# Full pipeline including Snowflake writes (COPY INTO + rebuild star schema):
python python/refresh_pipeline.py --load

# Force a full re-download and rebuild:
python python/refresh_pipeline.py --load --force
```

What each stage does:

1. **fetch_sources.py** — download anything new (exits early if nothing changed).
2. **prepare_data.py** — convert new OEWS `.xlsx` → CSV, extract O\*NET text.
3. **load_local_files.py** — `PUT` to the stage + `COPY INTO` the RAW tables.
4. **SQL 03→04→05→06** — rebuild STAGING views, the ANALYTICS star schema, the
   QUALITY checks, and append a row to `QUALITY.REFRESH_LOG` (verdict + counts).

Every stage is **idempotent** and **incremental**: OEWS rows are tagged by
`DATA_YEAR`, dimensions dedup by key across years, and the analytics layer always
rebuilds from the latest year. Re-running never double-counts.

> ⚠️ **Read-only policy note:** stages 3–4 *write* to Snowflake. If you'd rather
> keep writes manual, run `refresh_pipeline.py` **without** `--load` (fetch +
> prepare only), then run `load_local_files.py` yourself when you're ready.

### Scheduling it

Because BLS is annual and O\*NET is quarterly, a **weekly check is plenty** (it
no-ops when nothing changed). Pick whichever scheduler fits:

| Option | File | Best for |
|--------|------|----------|
| **launchd** (macOS native) | [`scheduling/com.ailabor.refresh.plist`](scheduling/com.ailabor.refresh.plist) | Your Mac; survives reboots, runs missed jobs on wake |
| **cron** (Linux/macOS) | [`scheduling/crontab.example`](scheduling/crontab.example) | Always-on machine / server |
| **GitHub Actions** | [`scheduling/.github/workflows/refresh.yml`](scheduling/.github/workflows/refresh.yml) | Runs in the cloud without your laptop on |

All three call [`scheduling/run_refresh.sh`](scheduling/run_refresh.sh), which
activates the venv and logs each run to `logs/`.

macOS quick start (launchd):
```bash
# edit the two paths in the plist first, then:
cp scheduling/com.ailabor.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ailabor.refresh.plist
launchctl start com.ailabor.refresh   # test it now
```

---

## 4. Alternative: Snowflake-native scheduling

If you'd prefer Snowflake to drive the schedule (instead of your machine), you
can wrap the rebuild SQL in a **Snowflake Task** (`CREATE TASK … SCHEDULE = 'USING CRON …'`).
Note a Task can't reach out to the web or read your local disk, so you'd still
need an external step (this pipeline, or Snowflake's `EXECUTE IMMEDIATE FROM`/
external functions/Snowpark) to get the new files into a stage first. For this
project's scale, the Python pipeline + a weekly launchd/cron trigger is simpler
and fully sufficient.

---

## Summary

- **Password alone won't work** — set up **key-pair auth on a `TYPE=SERVICE`
  user** (`sql/07`). This is also future-proof against the 2026 password
  deprecation.
- **Update detection is automatic** via `fetch_sources.py` (handles BLS bot
  protection, soft-404s, and O\*NET version discovery).
- **`python python/refresh_pipeline.py --load`** runs the whole update; schedule
  it weekly with launchd/cron/Actions.
- Keep it read-only by omitting `--load` and loading manually — your choice.
