#!/usr/bin/env python3
"""
Simple local demo: CSV upload → run automation → get summary.

Run: python app.py (or double-click start_app.command / start_app.bat).
Browser opens automatically.
"""
import logging
import os
import platform
import subprocess
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file

# Import our existing CSV regression logic
from run_csv_regression import run_csv_regression, validate_csv, RowResult

# SharePoint: manual upload only (link shown after run); no automatic upload to avoid extra runtime
SHAREPOINT_FOLDER_URL = "https://kinnersleyanalytics.sharepoint.com/sites/PowerBI/Shared%20Documents/Neos/Regression%20Testing/"

app = Flask(__name__)
# Allow larger file uploads (CSV is small, but just in case)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB

# Suppress request logging for progress polling so the terminal stays readable
class SuppressProgressLogs(logging.Filter):
    def filter(self, record=None):
        if record is None:
            return True
        try:
            msg = getattr(record, "msg", None) or ""
            if not msg and hasattr(record, "getMessage"):
                msg = record.getMessage()
            if not msg:
                msg = str(record)
            return "run-progress" not in (msg or "")
        except Exception:
            return True

_wz = logging.getLogger("werkzeug")
_progress_filter = SuppressProgressLogs()
_wz.addFilter(_progress_filter)
for _h in _wz.handlers:
    _h.addFilter(_progress_filter)

from config import get_portal_base_url

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_XLSX_DEMO12 = BASE_DIR / "P2NNI_CSV_Template_Demo12.xlsx"
TEMPLATE_XLSX_DEMO34 = BASE_DIR / "P2NNI_CSV_Template_Demo34.xlsx"
AUTH_STATE_PATH = BASE_DIR / "auth.json"
RUN_PROGRESS = {
    "active": False,
    "total": 0,
    "completed": 0,
    "last_row": None,
    "last_preset_id": None,
    "last_status": None,
    "current_preset": None,
    "current_index": None,
    "current_started_at": None,
}


def ensure_template_exists():
    """Generate Excel template if missing (customers get it via download link)."""
    if not TEMPLATE_XLSX_DEMO12.exists() and not TEMPLATE_XLSX_DEMO34.exists():
        try:
            from create_csv_template import create_template
            create_template("demo12")
            create_template("demo34")
        except Exception as e:
            print(f"  ⚠️ Could not generate template: {e}")


def check_session_ok():
    """Return True if auth.json exists and portal accepts it (no redirect to /login)."""
    if not AUTH_STATE_PATH.exists():
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(AUTH_STATE_PATH))
            page = context.new_page()
            page.goto(get_portal_base_url(), wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1500)
            url = page.url or ""
            context.close()
            browser.close()
            return "/login" not in url
    except Exception:
        return False


def run_login_flow():
    """Open browser for user to log in; wait until they're in; save auth. Returns (success, error_message)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(f"{get_portal_base_url()}/login", wait_until="domcontentloaded", timeout=20000)
            # Poll until user has left login page (max 5 minutes)
            for _ in range(150):
                page.wait_for_timeout(2000)
                if "/login" not in (page.url or ""):
                    break
            else:
                context.close()
                browser.close()
                return False, "Login timed out. Please try again."
            context.storage_state(path=str(AUTH_STATE_PATH))
            context.close()
            browser.close()
            return True, None
    except Exception as e:
        return False, str(e)


@app.route("/api/session-status", methods=["GET"])
def api_session_status():
    """Return whether the portal session is valid (no terminal login needed)."""
    ok = check_session_ok()
    return jsonify({"ok": ok})


@app.route("/api/run-progress", methods=["GET"])
def api_run_progress():
    """Return progress for the current CSV run (rows completed / total)."""
    data = dict(RUN_PROGRESS)
    total = data.get("total") or 0
    completed = data.get("completed") or 0
    percent = 0.0
    if total > 0:
        percent = round((completed / total) * 100.0, 1)
    data["percent"] = percent
    # Elapsed seconds for current preset (10 Gbps can take 2–5 min)
    started_at = data.get("current_started_at")
    if started_at:
        data["current_elapsed_sec"] = round(time.time() - started_at)
    else:
        data["current_elapsed_sec"] = None
    return jsonify(data)


@app.route("/api/login", methods=["POST"])
def api_login():
    """Start login flow: open browser, wait for user to log in, save auth. Blocks until done or timeout."""
    success, err = run_login_flow()
    if success:
        # After the Playwright login window closes, focus often jumps back to Terminal.
        # Gently bring the real browser (Chrome) with the existing frontend tab to the front,
        # without opening a new tab.
        _bring_frontend_to_front()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err or "Login failed"}), 400


def _frontend_port():
    """Port the Flask app runs on (single source of truth for open_browser and api_login)."""
    return 5001


def _bring_frontend_to_front():
    """
    Try to bring the existing browser window (with the frontend tab) to the front
    without opening a new tab.

    On macOS we use AppleScript to activate Google Chrome; on other platforms
    this is a no-op.
    """
    try:
        if platform.system() == "Darwin":
            # Activate Chrome if installed; if not, this silently fails.
            subprocess.run(
                ["osascript", "-e", 'tell application "Google Chrome" to activate'],
                check=False,
            )
    except Exception:
        # Best-effort only; failure here should never break the main flow.
        pass


@app.route("/")
def index():
    """Show the upload page."""
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run():
    """
    Receive uploaded CSV or sample name, run automation, return results.
    """
    tmp_path = None
    use_temp = False

    if "csv" in request.files and request.files["csv"].filename:
        file = request.files["csv"]
        if not file.filename.lower().endswith(".csv"):
            return jsonify({"ok": False, "error": "File must be a CSV"}), 400
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)
            use_temp = True
    else:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    try:
        if not check_session_ok():
            return jsonify({
                "ok": False,
                "error": "Portal session expired or not logged in",
                "code": "SESSION_EXPIRED",
            }), 401

        # Validate first
        rows, errors = validate_csv(tmp_path)
        if errors:
            return jsonify({
                "ok": False,
                "error": "Invalid CSV",
                "details": errors,
            }), 400

        if not rows:
            return jsonify({"ok": False, "error": "No valid rows in CSV"}), 400

        # Initialise run progress so frontend can poll status while automation runs.
        RUN_PROGRESS.update({
            "active": True,
            "total": len(rows),
            "completed": 0,
            "last_row": None,
            "last_preset_id": None,
            "last_status": None,
            "current_preset": None,
            "current_index": None,
            "current_started_at": None,
        })

        def _progress_callback(index: int, total: int, row_result: RowResult):
            RUN_PROGRESS.update({
                "active": True,
                "total": total,
                "completed": index,
                "last_row": row_result.row,
                "last_preset_id": row_result.preset_id,
                "last_status": row_result.result,
            })

        # Run the automation (verbose so terminal shows where it fails; no browser popup)
        mode = request.form.get("mode", "demo1")
        if mode == "demo1":
            os.environ["P2NNI_DEMO1_HEADLESS"] = "0" if request.form.get("show_browser") == "1" else "1"
        exit_code, results, summary_path, summary_path_powerbi = run_csv_regression(
            tmp_path,
            quiet=False,
            verbose=True,
            progress_callback=_progress_callback,
            progress_dict=RUN_PROGRESS,
            mode=mode,
        )

        # Manual SharePoint upload: return folder link only (no automatic upload, no extra runtime)
        sp_upload = {"folder_url": SHAREPOINT_FOLDER_URL, "manual": True}

        # Build response
        passed = sum(1 for r in results if r.exit_code == 0)
        failed = len(results) - passed

        return jsonify({
            "ok": True,
            "exit_code": exit_code,
            "passed": passed,
            "failed": failed,
            "total": len(results),
            "results": [
                {
                    "row": r.row,
                    "preset_id": r.preset_id,
                    "postcode": r.postcode or "",
                    "result": r.result,
                    "duration_sec": round(r.duration_sec, 1),
                    "error_detail": getattr(r, "error_detail", "") or "",
                }
                for r in results
            ],
            "summary_filename": summary_path.name if summary_path else None,
            "summary_powerbi_filename": summary_path_powerbi.name if summary_path_powerbi else None,
            "sharepoint": sp_upload,
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "Server error while processing CSV",
            "details": [str(e)],
        }), 500
    finally:
        RUN_PROGRESS["active"] = False
        if use_temp and tmp_path:
            tmp_path.unlink(missing_ok=True)


@app.route("/download/template")
def download_template():
    """Serve the Excel formatting guide (with dropdowns) for download. Regenerate so download always has latest columns."""
    mode = (request.args.get("mode") or "").strip().lower()
    if mode not in ("demo12", "demo34"):
        mode = "demo12"

    template_path = TEMPLATE_XLSX_DEMO34 if mode == "demo34" else TEMPLATE_XLSX_DEMO12

    try:
        from create_csv_template import create_template
        if not template_path.exists():
            create_template(mode)
    except Exception as e:
        print(f"  ⚠️ Could not regenerate template: {e}")
    if not template_path.exists():
        ensure_template_exists()
    if not template_path.exists():
        return "Template not available", 404
    return send_file(
        template_path,
        as_attachment=True,
        download_name=(
            "P2NNI_CSV_Formatting_Guide_Demo34.xlsx"
            if mode == "demo34"
            else "P2NNI_CSV_Formatting_Guide_Demo12.xlsx"
        ),
    )


@app.route("/download/<path:filename>")
def download(filename):
    """Serve the summary CSV file for download."""
    # Security: only allow files from our results dir
    base = Path(__file__).resolve().parent / "p2nni_regression_results"
    path = (base / filename).resolve()
    if not str(path).startswith(str(base.resolve())):
        return "Forbidden", 403
    if not path.exists():
        return "Not found", 404
    return send_file(path, as_attachment=True, download_name=path.name)


if __name__ == "__main__":
    ensure_template_exists()
    port = _frontend_port()  # 5000 often used by macOS AirPlay Receiver
    url = f"http://127.0.0.1:{port}"

    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print("\n" + "=" * 50)
    print("  P2NNI CSV Upload")
    print("=" * 50)
    print(f"  Browser should open to: {url}")
    print("  Keep this window open. Close it to stop the app.")
    print("=" * 50 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
