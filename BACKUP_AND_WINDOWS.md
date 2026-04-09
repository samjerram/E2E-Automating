# Portable backup & running on Windows

## What’s in a backup zip

The script `make_backup_zip.sh` builds a **portable archive** (no `venv/`, no `__pycache__`) you can upload to **Google Drive** and unzip on another machine.

**Security:** The zip may include **`config.json`** and **`auth.json`** if they exist on your Mac (passwords / session). Treat the zip like a secret, or use Drive with a **private** folder only you can access. For sharing code only, delete those two files before zipping or use a zip that excludes them.

**Checkpoint:** This repo includes git tag `checkpoint-v6-2026-03-25` (see `CHECKPOINT.md`) for a known-good state.

---

## Google Drive

1. On your Mac, run: `./make_backup_zip.sh` (or run the `zip` command inside that script manually).
2. Upload the generated `E2E_Automating_backup_YYYY-MM-DD.zip` to Drive.
3. On Windows: download → **Extract All…** to a folder with a **short path** (e.g. `C:\dev\E2E-Automating`) to avoid Windows path-length issues.

---

## Windows setup (Cursor / VS Code)

1. **Install Python 3.10+** from [python.org](https://www.python.org/downloads/windows/).  
   During setup, enable **“Add python.exe to PATH”**.

2. **Open the extracted folder in Cursor** (File → Open Folder).

3. **First-time install** (PowerShell or `cmd` in the project folder):

   ```bat
   python -m venv venv
   venv\Scripts\activate.bat
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Config:** Copy `config.example.json` to `config.json` and fill in real values (portal URL, `neos_internal` for Demo 2, `customer` for Demo 4 if you use it).

5. **Customer session:** After `config.json` is set, start the app and use **“Login to portal”** in the web UI once so `auth.json` is created (same as on Mac).

6. **Run the app:** Double-click **`start_app.bat`** or:

   ```bat
   venv\Scripts\activate.bat
   python app.py
   ```

   Open the URL shown (often `http://127.0.0.1:5001`).

---

## Mac vs Windows — same behaviour

- **Demo 1 / 2 / 3 / 4** logic lives in `run_preset.py` and `run_csv_regression.py`; Playwright uses Chromium the same way on both OSes.
- Optional env vars (e.g. `P2NNI_DEMO2_HEADLESS`, `P2NNI_PLAYWRIGHT_SLOW_MO`) work the same in both shells; on Windows use `set VAR=value` in `cmd` or `$env:VAR="value"` in PowerShell for the session.

---

## Regenerating Excel templates

```bash
python create_csv_template.py
```

(Run with venv activated.) Produces Demo 12 / Demo 34 templates as configured in that script.
