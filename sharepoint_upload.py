"""
Upload regression summary files to SharePoint/Power BI via Microsoft Graph.

Destination folder (full URL): https://kinnersleyanalytics.sharepoint.com/sites/PowerBI/Shared Documents/Neos/Regression Testing/

Configuration lives in config.json alongside portal_url, for example:

{
  "portal_url": "https://staging.digital-foundations.co.uk",
  "sharepoint": {
    "tenant_id": "YOUR_TENANT_ID",
    "client_id": "YOUR_APP_CLIENT_ID",
    "client_secret": "YOUR_APP_CLIENT_SECRET",
    "site_url": "https://kinnersleyanalytics.sharepoint.com/sites/PowerBI",
    "document_library": "Shared Documents",
    "folder_path": "Neos/Regression Testing"
  }
}

If any of these values are missing or blank, uploads are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

try:
    import requests
except ImportError:
    requests = None  # optional: app still runs; upload returns "install requests"

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def _load_sharepoint_config() -> Optional[dict]:
    if not CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    sp = data.get("sharepoint") or {}
    required = ("tenant_id", "client_id", "client_secret", "site_url", "document_library", "folder_path")
    if not all(str(sp.get(k, "")).strip() for k in required):
        return None
    return {k: str(sp[k]).strip() for k in required}


def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    resp = requests.post(token_url, data=data, timeout=20)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _resolve_site_and_drive(token: str, site_url: str, document_library: str) -> Tuple[str, str]:
    # site_url looks like: https://host/sites/PowerBI
    # Graph: GET /sites/{hostname}:{site-path}
    from urllib.parse import urlparse

    parsed = urlparse(site_url)
    hostname = parsed.hostname
    site_path = parsed.path  # e.g. "/sites/PowerBI"
    api_site = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(api_site, headers=headers, timeout=20)
    r.raise_for_status()
    site_id = r.json()["id"]

    # Find drive (document library) by name, e.g. "Shared Documents"
    r = requests.get(f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives", headers=headers, timeout=20)
    r.raise_for_status()
    drives = r.json().get("value", [])
    for d in drives:
        if d.get("name") == document_library:
            return site_id, d["id"]
    raise RuntimeError(f"Document library '{document_library}' not found on site {site_url}")


def upload_summary_to_sharepoint(summary_path: Path) -> Tuple[bool, str]:
    """
    Upload summary_path to configured SharePoint folder.
    Returns (ok, message). If config is missing, returns (False, reason).
    """
    if requests is None:
        return False, "SharePoint upload requires 'requests'. Run: pip install requests (in your venv)."
    cfg = _load_sharepoint_config()
    if not cfg:
        return False, "SharePoint upload skipped (sharepoint config missing or incomplete in config.json)."
    if not summary_path or not summary_path.exists():
        return False, f"Summary file not found: {summary_path}"

    try:
        token = _get_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])
        site_id, drive_id = _resolve_site_and_drive(token, cfg["site_url"], cfg["document_library"])
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
        }
        # Ensure folder path uses forward slashes and no leading slash
        folder = cfg["folder_path"].strip().lstrip("/").rstrip("/")
        upload_name = summary_path.name
        item_path = f"{folder}/{upload_name}" if folder else upload_name
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:/{item_path}:/content"
        data = summary_path.read_bytes()
        resp = requests.put(url, headers=headers, data=data, timeout=60)
        resp.raise_for_status()
        return True, f"Uploaded to SharePoint: {item_path}"
    except Exception as e:
        return False, f"SharePoint upload failed: {e}"


def upload_summary_if_configured(summary_path: Path) -> dict:
    """
    Convenience wrapper for callers (Flask app).
    Returns dict with keys: enabled (bool), ok (bool), message (str).
    """
    if requests is None:
        return {
            "enabled": False,
            "ok": False,
            "message": "SharePoint upload requires 'requests'. Run: pip install requests (in your venv).",
        }
    cfg = _load_sharepoint_config()
    if not cfg:
        return {
            "enabled": False,
            "ok": False,
            "message": "SharePoint upload not configured.",
        }
    ok, msg = upload_summary_to_sharepoint(summary_path)
    return {
        "enabled": True,
        "ok": ok,
        "message": msg,
    }

