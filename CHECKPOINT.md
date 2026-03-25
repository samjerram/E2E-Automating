# Official checkpoints — verified working

This file records **official, known-good checkpoints** you can roll back to or reference later.

**Latest:** **v6** (2026-03-25) — robustness (VLAN, FTTP, upfront, submit-for-review, pricing wait) + Demo 2 speed.

---

## OFFICIAL CHECKPOINT v6 — VLAN/FTTP/submit/pricing robustness + Demo 2 speed (2026-03-25)

**Status:** OFFICIAL CHECKPOINT v6 — stable customer + internal flows with faster headful runs, supplier-aware option fallbacks, and reliable “Submit for review”.

### What this checkpoint adds (on top of v5)

- **A-End VLAN (Site Config)**  
  - Fast path fills `#aEndLocation_vlanId` and `#aEndLocation_shadowVLANId` first with shorter settle times, then falls back to section/role locators.  
  - Post-save verification uses those IDs when visible and fixes label regex (`\s*`, not over-escaped).  
  - `shadow_value` defined for all paths so retry logic cannot reference an undefined variable.

- **FTTP aggregation**  
  - `apply_fttp_aggregation_with_fallback`: if CSV asks for **Yes** but the portal disables it (e.g. some suppliers), logs clearly and selects **No** so the journey continues.  
  - `toggle_fttp_aggregation` returns `bool` and **never** forces clicks on disabled radios.

- **Pay upfront**  
  - If the CSV choice’s radio is **disabled** for that quote, selects the opposite option with a one-level nested fallback so recursion cannot loop if both are disabled.

- **Submit order for review (customer)**  
  - Removed the false “success” path that treated the **step heading** “Submit order for review” as completion.  
  - Terms: **JS tick first**, broader copy/ancestor matching, then Playwright strategies; shorter waits for enabled **Submit for review** and post-click confirmation.  
  - `fill_order_billing_screen` only prints preset-complete when submit actually reports success.

- **Pricing UI wait (after Get price)**  
  - `_wait_for_pricing_ui_ready`: in-browser `wait_for_function` with **75ms** polling plus earlier signals (e.g. `img.supplier_image`, slick track tiles, FTTP section text).  
  - **Updating…** overlay cleared right after **Get price** and again before readiness.  
  - Shorter log line: `⏳ Waiting for pricing UI…` and `✅ Pricing UI ready` (with optional elapsed seconds).

- **Demo 2 / headful speed**  
  - Default Playwright **slow_mo** when headful reduced (**~35ms**; override with `P2NNI_PLAYWRIGHT_SLOW_MO`).  
  - Shorter post–**Find** settle, faster Basket Id polling interval (~3.2s, 25 attempts).  
  - Web UI run-progress polling **~2s** for snappier updates during runs.

### How to lock / revert exactly

Locked as git tag **`checkpoint-v6-2026-03-25`**.

```bash
git fetch --tags
git switch -c recover-v6 checkpoint-v6-2026-03-25
```

### Key files in this checkpoint

- `run_preset.py` — VLAN id path, FTTP/upfront fallbacks, `submit_order_for_review` / terms helpers, `_wait_for_pricing_ui_ready`, `select_access_and_configuration` overlay after Get price, headful `slow_mo` + `import os`.  
- `run_csv_regression.py` — Basket Id poll timing for Demo 2/4.  
- `templates/index.html` — progress poll interval.  
- `CHECKPOINT.md` — this entry.

Use **v6** as the primary “known good” reference for current P2NNI automation behaviour. **v5** and earlier remain historical.

---

## OFFICIAL CHECKPOINT v4 — Demo 1 + Demo 2 with automated BasketId capture (2026-03-04)

**Status:** OFFICIAL CHECKPOINT v4 — current state with Demo 1 unchanged and Demo 2 fully automated end‑to‑end, including BasketId scraping for internal NEOS users.

### What was validated

- **Demo 1 (customer flow) unchanged from v3**:
  - Uses the existing customer login/session.
  - Runs each CSV row through quote → order → “Submit order for review” with the same ~65–75s per row performance.
  - Continues to populate all existing summary fields (Install, Annual, FTTP Aggregation, Quote/Order IDs, etc.) exactly as in v3.
- **Demo 2 (internal NEOS flow with BasketId)**:
  - After Demo 1 completes for each successful row, a separate, visible Playwright browser logs in as an internal NEOS user using `neos_internal` credentials from `config.json`.
  - For each passed row with an `order_url`, Demo 2:
    - Opens the order URL as the internal user.
    - Scrolls, clicks **“Place order”**, waits for and clicks **“OK”** on the confirmation dialog.
    - Navigates back to the specific `order_url` and then **reloads and waits** in a loop (about every 10 seconds for up to ~3 minutes), mirroring the manual “refresh and wait” behaviour.
    - Scrapes the **Basket Id** text (e.g. `Basket Id: 220075`) from `document.body.innerText` using a robust, case‑insensitive regex.
    - Writes the captured BasketId into the new `BasketId` field on the in‑memory `RowResult` for that row.
  - Runs fully automatically from CSV upload → “Run Demo 2” → visible Playwright steps → CSV download, with **no manual clicking** required.
- **Summary outputs (v3 features retained, plus BasketId)**:
  - `P2NNI_regression_summary.csv` (pretty CSV):
    - Still matches v3: currency formatted with `£`, `Quote`/`Order` as Excel‑style `HYPERLINK(...)` formulas.
    - Now includes a **`BasketId` column** populated for Demo 2 rows (left blank for Demo 1).
  - `P2NNI_regression_summary_powerbi.csv` (Power BI CSV):
    - Same numeric currency behaviour as v3 (no `£`, no commas).
    - `Quote` and `Order` remain plain IDs (no formulas).
    - Includes the same **`BasketId` column** for modelling in Power BI.
  - `.xlsx` summary still generated with clickable `Order`/`Quote` links and now includes `BasketId` as a regular column.
- **Front‑end UX for mode selection**:
  - The UI exposes a **Run mode** toggle (e.g. radio buttons) between **Demo 1** and **Demo 2**.
  - The selected mode is posted to the Flask `/run` endpoint, which passes it through to `run_csv_regression` so the internal‑user BasketId flow is only executed for Demo 2 runs.

### Key files in this checkpoint

- `run_csv_regression.py`
  - Extends `RowResult` and `SUMMARY_CSV_HEADERS` to include `BasketId`.
  - Adds `fill_basket_ids_with_internal_user(results, mode)` which:
    - Reads NEOS internal credentials via `get_neos_internal_creds()` from `config.py`.
    - Uses a visible Playwright browser (`headless=False, slow_mo=200`) to:
      - Log in as the internal user.
      - Open each successful `order_url`, click **Place order** and **OK**, navigate back, and **poll with reloads** until BasketId text appears.
      - Scrape BasketId from `document.body.innerText` using a forgiving, case‑insensitive regex and update each `RowResult`.
  - Calls `fill_basket_ids_with_internal_user` at the end of `run_csv_regression` only when `mode == "demo2"`, keeping Demo 1 runtimes unchanged.
  - Updates `print_summary` and `_write_summary_xlsx` to propagate the new `BasketId` column into both CSVs and the Excel summary.
- `config.py` + `config.json`
  - Provide `get_neos_internal_creds()` and store the `neos_internal` email/password used for Demo 2 internal login.
- `app.py`
  - Accepts a `mode` form field from the frontend (defaulting to `demo1`) and passes it to `run_csv_regression`.
  - Continues to expose both `summary_filename` and `summary_powerbi_filename` in the JSON response, plus the manual SharePoint/Power BI folder link from v3.
- `templates/index.html`
  - Contains the **Demo 1 / Demo 2** mode selector and sends the chosen mode in the `/run` POST.
  - Retains the dual download buttons (pretty CSV + Power BI CSV) and the manual SharePoint upload link from v3.

Use **v4** as the main “known good” reference for the full Demo 1 + Demo 2 experience, including automated BasketId capture. v3 and v2 remain below as historical checkpoints.

---

## OFFICIAL CHECKPOINT v5 — Demo 1/2/3 speedups + split Excel templates (2026-03-18)

**Status:** OFFICIAL CHECKPOINT v5 — current “working really good” state for Demo 1, Demo 2, and Demo 3, with additional speed/robustness improvements and separate Excel templates for the different demo journeys.

### What was validated

- **Demo 1 (customer flow)**:
  - Runs quote → order → “Submit order for review”.
  - Skips unnecessary waiting when the portal indicates there are **no up-front charges** (message includes “Amounts shown … and no up-front charges”).
  - After selecting **FTTP** it clicks **“Proceed to order”** as soon as it’s visible/enabled (and does not rely on “Publish” being present).
  - Reduces/removes fixed delays around FTTP → “Proceed to order” so the post-FTTP gap is as small as possible.

- **Demo 2 (internal NEOS flow with automated BasketId)**:
  - Continues to log in with `neos_internal` credentials and capture `Basket Id` into the per-row `BasketId` field.

- **Demo 3 (internal adjust quote pricing)**:
  - Works with negotiated/list annual/install fields present in the CSV template for Demo 3/4.

- **Front-end & CSV templates**:
  - UI exposes **two explicit** formatting guide downloads:
    - Demo 1/2 template excludes negotiated/list annual/install pricing columns.
    - Demo 3/4 template includes negotiated annual/install and list annual/install pricing columns.
  - Backend regenerates/serves the correct template when downloading via `/download/template?mode=demo12` vs `/download/template?mode=demo34`.

### How to lock/revert exactly

This checkpoint is locked as git tag **`checkpoint-v5-2026-03-18`**.

To revert later to this exact code state, use:
- `git switch checkpoint-v5-2026-03-18`

### Key files in this checkpoint

- `run_preset.py`
  - Demo 1/2 customer-flow robustness:
    - Upfront “no up-front charges” skip.
    - Faster FTTP → proceed-to-order behaviour.
    - Click “Proceed to order” immediately when already on screen.
- `run_csv_regression.py`
  - Support for visible Demo 1 via `P2NNI_DEMO1_HEADLESS` (used for watching where it’s slow).
  - Missing `os` import fix.
- `create_csv_template.py`
  - Generates two Excel template variants:
    - `P2NNI_CSV_Template_Demo12.xlsx`
    - `P2NNI_CSV_Template_Demo34.xlsx`
- `app.py`
  - Serves the correct template based on `mode=demo12|demo34`.
- `templates/index.html`
  - Two explicit “Download formatting guide” buttons (Demo 1/2 vs Demo 3/4).

---

## OFFICIAL CHECKPOINT v3 — dual CSV outputs + manual SharePoint (2026-02-27)

**Status:** OFFICIAL CHECKPOINT v3 — current state with Power BI–optimised summary and manual SharePoint workflow.

### What was validated

- **Core regression flow unchanged from v2**: existing 20-row and 40-row CSVs still run end-to-end to “Submit order for review” with stable NNI/location handling, VLAN filling, and order-page scraping.
- **Dual summary outputs per run**:
  - `P2NNI_regression_summary.csv` — human-friendly CSV with `InstallPrice`, `AnnualRental`, and `FTTP Aggregation` formatted as `£` values and `Quote` / `Order` as clickable Excel-style `HYPERLINK(...)` formulas.
  - `P2NNI_regression_summary_powerbi.csv` — Power BI–optimised CSV with:
    - Numeric money fields only (no `£`, no commas): `InstallPrice`, `AnnualRental`, `FTTP Aggregation` (e.g. `0`, `4054.05`).
    - `Quote` and `Order` as **plain IDs** (no hyperlink formulas) for easier ingestion and modelling.
    - All other columns aligned with the main summary, including `PathSpeed`, `TermLength`, `Result`, `Duration (seconds)`, and `Date Completed`.
- **Excel summary**: `.xlsx` export still generated with clickable `Order` and `Quote` hyperlinks and sensible column widths.
- **SharePoint / Power BI integration (manual)**:
  - Automatic upload to SharePoint is disabled to avoid extra runtime and tenant configuration.
  - UI now shows a **manual upload link** after each run: “Upload summary manually: Open Power BI folder”, pointing at  
    `https://kinnersleyanalytics.sharepoint.com/sites/PowerBI/Shared Documents/Neos/Regression Testing/`.
  - This keeps the run time ~70 seconds while still supporting a consistent place for Power BI to read summaries from.
- **Front-end UX**:
  - Results panel exposes **two download buttons** when a run completes: `Download summary CSV` and `Download Power BI CSV`.
  - SharePoint status area explains the manual-upload workflow and links directly to the target folder.

### Key files in this checkpoint

- `run_csv_regression.py`
  - Adds `_currency_numeric` helper and extended `print_summary` that writes **two CSVs** (pretty + Power BI), plus Excel.
  - Extends `run_csv_regression` return signature to include both `summary_path` and `summary_path_powerbi`.
- `app.py`
  - Consumes the new return signature and returns both `summary_filename` and `summary_powerbi_filename` to the frontend.
  - Simplifies SharePoint behaviour to a fixed `SHAREPOINT_FOLDER_URL` and **manual** upload only.
- `templates/index.html`
  - Adds a second download button for the Power BI CSV and a clear “Upload summary manually” link to the SharePoint folder.
- `SHAREPOINT_SETUP.md`, `LINKEDIN_PROJECT_DESCRIPTION.md`
  - Documentation for SharePoint expectations and for describing the project in data-focused roles.

Use **v3** as the primary “known good” reference for the current behaviour (dual CSV outputs + manual SharePoint link).

---

## OFFICIAL CHECKPOINT v2 — updated regression and summary shape (2026-02-26)

**Status:** OFFICIAL CHECKPOINT v2 — updated “better than before” state.

### What was validated

- **20-row + 40-row CSV runs**: full journeys reach “Submit order for review”; location/NNI selection is stable (including first-row cold start).
- **VLAN ID + Shadow VLAN ID**: fills reliably for single and dual VLAN journeys (A-End card, primary + secondary where present).
- **Order-page scraping only**: broadband provider (B-End), Install, FTTP Aggregation, Annual lifted from the final order page; no navigation to “From quote”; summary now has **Start Supplier, InstallPrice, AnnualRental, FTTP Aggregation** only (PE/DP/TCV removed).
- **Summary outputs**:
  - `PathSpeed` correctly populated for all bandwidths (100/200/500/1000/10000 Mbps).
  - `Add-on` column removed; **Quote** and **Order** columns are clickable hyperlinks in both CSV (as formulas) and Excel.
  - **Quote** column appears before **Order**; per-row **Date Completed** uses the actual finish time of each preset.
- **Formatting guide**: latest Excel template has **no RO2 Diversity column**, and RO2 behaviour is disabled end-to-end (CSV column ignored; RO2 flow not executed).
- **Front-end UX**: progress text no longer shows “usually ~1 min”; long-running location / toggle messages are informative only and do not break runs.

### Key files in this checkpoint

- `run_preset.py` — NNI/location robustness, VLAN fill improvements, RO2 disabled, order-page scraping for pricing.
- `run_csv_regression.py` — CSV/Excel summary shape (no PE/DP/TCV/Add-on; FTTP Aggregation; Quote/Order hyperlinks; PathSpeed + per-row Date Completed).
- `create_csv_template.py` + `csv_dropdown_options.csv` — updated formatting guide (no RO2), dropdown options aligned with portal constraints.
- `templates/index.html` — cleaner progress label.
- `p2nni_20rows_SP28NJ.csv`, `p2nni_40rows_SP28NJ.csv` — example multi-row CSVs that exercise the full matrix of bearer/bandwidth options.

Use **v2** as the historical reference for the first “official” stable regression pack before the dual-CSV/SharePoint changes.
