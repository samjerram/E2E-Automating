# Telecom Quote-to-Order Automation System — CV / Portfolio Summary

**Full breakdown of the end-to-end automation platform built for Neos Networks / Kinnersley Analytics.**

---

## Overview

I designed and built a **full-stack automation system** that turns a previously **fully manual** telecom quote-to-order process into a fast, repeatable, CSV-driven workflow. The system serves two distinct business uses: **regression testing** (pre- and post-deployment) and **bulk order processing** for customer CSVs, with rich output (including scraped Basket IDs) for both internal and external stakeholders.

**Products covered (built by me):**
- **DIA** (also has an EoFTTX variant)
- **EP2P** (also has an EoFTTX variant)
- **P2NNI** (also has an EoFTTX variant)
- **P2CC**
- **NNI2CC**
- **OP2P** (Optical P2P)

The automation was **initially all manually done**; I have **dramatically improved speed** and consistency by automating the entire journey from CSV input to summary outputs (and optional Basket ID capture) with no manual clicking required during a run.

---

## What the System Does

### 1. **Two primary use cases**

| Use case | Description |
|----------|-------------|
| **Regression packs** | Run CSV-based regression packs **before and after deployments** for each product (DIA, EP2P, P2NNI, P2CC, NNI2CC, OP2P, including EoFTTX variants where applicable). Validates that the digital portal and pricing engine behave correctly end-to-end with minimal manual effort. |
| **Bulk order processing** | When customers send **bulk order CSVs**, NEOS/Kinnersley staff would previously have had to re-key or click through every order manually in the portal. The system now ingests these CSVs and runs the full quote-to-order flow automatically. Customers (or internal users) use a **formatting guide** where **every single field matches the portal UI** (bearer, bandwidth, term, supplier, site config, billing, etc.), so no guesswork is required. |

### 2. **Two automation modes (Demo 1 & Demo 2)**

- **Demo 1 — Customer flow**  
  Logs in as the customer, runs each row through: product selection → quote → order → **Submit order for review**. Output includes Order/Quote IDs, Install/Annual/FTTP pricing, supplier chosen, and pass/fail per row. Optimised for **speed** (~65–75 seconds per row); used for regression and for bulk orders where only “submitted for review” is needed.

- **Demo 2 — Internal flow + Basket ID**  
  Performs the same customer journey, then **logs out**, **logs in as an internal NEOS user**, opens each order, clicks **Place order** and **OK**, and **scrapes the Basket ID** from the order page after it appears. Delivers a **deeper, more detailed response** from the pricing engine (Basket IDs) so customers and internal users can track orders into downstream systems (e.g. Cerillion). Fully automated; no manual steps during the run.

### 3. **Basket ID scraping**

- **Basket IDs** are unique identifiers produced by the pricing/order engine after an order is placed. They are not visible in the customer-only flow.
- I implemented **automatic scraping** of Basket IDs in Demo 2: the script waits for the “Order is placed” state, reloads the order page periodically, and extracts the Basket ID from the page text (e.g. `Basket Id: 220075`) using the same kind of logic as Install/Annual/FTTP scraping. This gives **richer, more detailed output** for reporting and integration (e.g. Power BI, internal tools).

### 4. **Formatting guide = full UI parity**

- I created an **Excel formatting guide** (with dropdowns and validation) so that **every configurable detail** in the portal can be specified in the CSV: product type, postcode, bearer, bandwidth, term, pay upfront, shadow VLAN, FTTP aggregation, **preferred supplier**, company/contact/billing, floor/room/rack, connector type, power, media type, VLAN tagging, access notice, auto negotiation, hazards, asbestos, tenant, landowner, VLAN IDs, PO reference, etc.
- **Preferred supplier** is optional: users can pick a specific broadband supplier (e.g. Virgin, BT Wholesale, Sky via Openreach, PXC) or “No Specified Supplier” (cheapest/default). The automation handles multi-tile carousels (e.g. clicking “Next” to find off-screen suppliers like Sky via Openreach) and uses logo-based detection where the UI only shows “via Openreach” in text.
- This **formatting guide** is what allows bulk customer CSVs to be processed without staff re-entering data manually; the guide aligns 1:1 with the portal UI.

### 5. **Outputs**

- **Human-readable summary CSV** — £-formatted pricing, clickable Order/Quote links (Excel HYPERLINK formulas), pass/fail, duration, Basket ID (Demo 2).
- **Power BI–friendly summary CSV** — Numeric currency (no £), plain Order/Quote IDs, Basket ID; suitable for dashboards and reporting.
- **Excel summary** — Same data with clickable Order/Quote hyperlinks and column sizing.
- **Manual SharePoint/Power BI link** — Shown in the UI after each run so users can upload the summary to the designated folder without adding runtime or auth complexity to the app.

---

## Technical architecture (high level)

- **Front end:** Local web UI (Flask + HTML/JS): session check, login-to-portal, CSV upload, run mode (Demo 1 / Demo 2), progress polling, dual download buttons (summary CSV + Power BI CSV), SharePoint link.
- **Back end:** Python (Flask): CSV validation, orchestration of per-row automation, optional Demo 2 Basket ID flow, generation of both summary CSVs and Excel.
- **Automation:** Playwright (Chromium): browser automation for customer and internal flows — login, product/quote/order navigation, form filling, price-tile selection (including carousel and preferred supplier by text/logo), Place order / OK, and DOM-based scraping (pricing, Order/Quote IDs, Basket ID). Demo 1 runs headless for speed; Demo 2 uses a visible browser for transparency.
- **Configuration:** `config.json` for portal URL and (for Demo 2) internal NEOS credentials; no secrets in code. Session state (e.g. `auth.json`) for customer login reuse.
- **Data:** Input = CSV (from formatting guide or customer bulk files). Output = two CSVs + Excel, with optional Basket ID column populated in Demo 2.

---

## How each technology was used (end-to-end)

| Technology | Role in the project |
|------------|----------------------|
| **Python** | Core logic end-to-end: CSV validation and parsing, preset building from rows, orchestration of the automation runner, Basket ID extraction and polling, summary generation (both CSVs and Excel), and configuration loading. All business logic and file I/O live in Python. |
| **Flask** | Web application backend: serves the upload UI, session-status and login APIs, run endpoint (receives CSV + mode), progress polling endpoint, and file-download routes. Flask ties the browser-based UI to the Python automation and returns summary filenames and SharePoint link in the JSON response. |
| **Playwright** | Browser automation: drives the digital portal in Chromium for both customer and internal flows—login, product/quote/order navigation, form filling, price-tile selection (including carousel “Next” and logo-based supplier detection), Place order / OK clicks, and DOM scraping (pricing, Order/Quote IDs, Basket ID). Demo 1 runs headless; Demo 2 runs visible for transparency. |
| **Excel (formatting guide)** | User-facing input specification: I built an Excel formatting guide (with data validation and dropdowns) so every portal field (product, postcode, bearer, bandwidth, term, supplier, site config, billing, etc.) can be chosen in one place. Users fill the guide, save as CSV, and upload; the automation reads that CSV and runs the flow. Excel ensures non-technical users can prepare bulk orders and regression packs without touching the UI directly. |
| **Power BI** | Reporting and dashboards: the system produces a **Power BI–friendly summary CSV** (numeric currency, plain Order/Quote IDs, Basket ID) and exposes a manual link to the SharePoint/Power BI folder so teams can upload results and build dashboards. Power BI consumes the automated output for visibility into regression and bulk order outcomes. |

---

## Impact (for CV bullets)

- **Replaced a fully manual process** with a single CSV upload and one-click run, **dramatically improving speed** and consistency for both regression and bulk orders.
- **Extended coverage** across **six products**: DIA, EP2P, P2NNI, P2CC, NNI2CC, OP2P (DIA, EP2P, and P2NNI each have an EoFTTX variant), with the same automation and formatting-guide approach.
- **Introduced Basket ID scraping** so outputs include **deeper, more detailed data** from the pricing engine for customers and internal users (e.g. reporting, Cerillion integration).
- **Dual use:** (1) **Regression packs** for each product before/after deployments; (2) **Bulk order processing** so NEOS/Kinnersley staff no longer have to manually enter customer bulk orders — customers can follow the formatting guide and submit CSVs that match the UI field-for-field.
- **End-to-end ownership:** Design, implementation, and behaviour (customer vs internal flow, carousel/supplier selection, Basket ID polling, dual CSVs, formatting guide) were **fully built by me**; the automation was initially all manual and is now a repeatable, scalable pipeline.

---

## Suggested CV / LinkedIn wording (short)

**Telecom Quote-to-Order Automation Platform**  
Designed and built an end-to-end automation system for Neos Networks digital portal quote-to-order flows. Supports **six products**: DIA, EP2P, P2NNI, P2CC, NNI2CC, OP2P (DIA, EP2P, and P2NNI each have an EoFTTX variant). **Python** underpins the full pipeline (CSV validation, orchestration, Basket ID scraping, summary generation); **Flask** serves the web UI, run API, and download routes; **Playwright** automates the portal (login, forms, price-tile selection, Place order, DOM scraping); an **Excel formatting guide** (dropdowns and validation) lets users specify every portal field before saving as CSV for upload; and a **Power BI–friendly summary CSV** plus SharePoint link feed reporting and dashboards. Two modes: (1) fast customer-only flow for regression and bulk submit-for-review; (2) internal-user flow with **automatic Basket ID scraping** for deeper pricing-engine data. **Replaced fully manual process** with CSV-driven runs; **dramatically improved speed** and consistency. Used for **regression packs** (pre/post deployment) and **bulk order processing** — customers submit CSVs aligned to the formatting guide, eliminating manual data entry by NEOS/Kinnersley staff. Fully built by me.

---

*You can copy from this document into your CV, LinkedIn, or application answers. Adjust product names or emphasis as needed for each role.*
