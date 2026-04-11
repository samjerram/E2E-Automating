# P2NNI CSV Regression — LinkedIn Project Description (Data Roles)

Use or adapt the text below for your LinkedIn profile, "Projects" section, or applications for **Data Analyst, Data Engineer, Business Intelligence, or Analytics** roles.

---

## Short version (2–3 sentences)

**P2NNI CSV Upload & Regression** — End-to-end data pipeline that ingests structured CSV (product type, postcodes, bearer/bandwidth, site config, billing), validates rows against business rules, runs browser automation to generate quotes and orders in a telecom portal, and outputs a Power BI–ready summary dataset (pricing, order/quote IDs, pass/fail, duration, timestamps). Built with Python, Flask, and Playwright; summary outputs include CSV/Excel with clickable Order/Quote links and optional manual upload to SharePoint for live reporting.

---

## Medium version (paragraph, ~150 words)

**P2NNI CSV Regression** is a data pipeline and regression-testing tool for a telecom quote-to-order portal. Users upload a CSV (product type, B-end postcode, bearer, bandwidth, site configuration, and billing fields). The system validates each row against product constraints (e.g. valid bearer/bandwidth combinations and connector/media options), then runs headless browser automation (Playwright) to complete the quote and order flow for every row. Results are written to a structured summary: Preset ID, postcodes, company name, supplier, port speeds, path speed, term length, install price, annual rental, FTTP aggregation, Order and Quote references (with hyperlinks), pass/fail, duration, and date completed — aligned with Power BI for reporting. The stack is Python, Flask, openpyxl for Excel output, and config-driven behaviour; the UI offers a formatting guide, CSV upload, run progress, and a link to the SharePoint folder for manual upload of summaries. The project demonstrates data validation, batch processing, structured output design for BI, and automation as a way to collect and standardise business data at scale.

---

## Detailed version (for "About this project" or portfolio)

**What it does**

- **Input:** A CSV (or Excel-saved-as-CSV) describing multiple quote/order scenarios: product type (P2NNI), B-end postcode, bearer (e.g. 10G/1G/100M), bandwidth, contract term, site config (connector type, media type, power, VLAN, access notice, etc.), and billing (company, contact, PO ref, floor/room, VLAN IDs). Users get a formatting guide and template so the data is consistent.

- **Validation:** Each row is validated before any automation runs. Business rules (e.g. from `p2nni_constraints`) enforce valid bearer/bandwidth combinations and allowed options for connector type, media type, power supply, auto-negotiation, and VLAN tagging. Invalid rows are reported with clear errors so the dataset is clean before processing.

- **Automation:** For each valid row, a Playwright script drives the portal (location, product/config selection, site config, billing). It generates a quote and completes an order, then scrapes the order (and quote) pages to extract pricing (install price, annual rental, FTTP aggregation), order/quote IDs, and supplier — turning UI actions into structured data.

- **Output:** A summary CSV and Excel file with one row per scenario. Columns are aligned with Power BI: Preset ID, Start/End Postcode, Company Name, Usage, Start/End Supplier, Start/End Port Speed, Path Speed, Term Length, Install Price, Annual Rental, FTTP Aggregation, Quote, Order, Result (Pass/Fail), Duration (seconds), Date Completed, Error. Order and Quote are written as hyperlinks so reviewers can jump to the portal. The app also exposes a link to the SharePoint/Power BI folder so summaries can be uploaded manually for live dashboards.

- **Operational details:** Runs in a Flask web app (upload, progress, download). Session/auth is checked before runs. Config (e.g. portal URL, optional SharePoint folder) is externalised so the same code can target different environments. Timeouts and per-row errors are captured so the summary doubles as a regression and data-quality report.

**Why it’s relevant for data roles**

- **Data pipeline:** CSV in → validation → automated data collection → structured summary out; clear stages and error handling.
- **Data quality:** Validation rules, constraint checks, and per-row pass/fail with error messages support reliable inputs and auditable outputs.
- **Structured output for BI:** Summary schema is designed for Power BI (naming, currency formatting, hyperlinks); output can be uploaded to SharePoint for reporting.
- **Automation as data collection:** Browser automation is used to generate and then scrape business data (pricing, IDs) from a web app, turning a manual process into a repeatable dataset.
- **Batch processing:** Handles many rows per run, with progress reporting and timeouts so the pipeline is observable and safe in production.
- **Tooling:** Python, Flask, Playwright, CSV/Excel (openpyxl), optional SharePoint integration; config-driven and suitable for staging vs production.

You can summarise in one line as: *"Data pipeline that validates CSV input against business rules, runs browser automation to generate telecom quotes/orders, and produces a Power BI–ready summary dataset with pricing, order/quote IDs, and regression results."*
