"""
Portal URL and app config. Read from config.json so the same package can be used for staging or production.
"""
import json
from pathlib import Path
from typing import Optional, Dict

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_PORTAL_URL = "https://staging.digital-foundations.co.uk"


def _load_config() -> Dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_portal_base_url() -> str:
    """Portal base URL for login and automation. From config.json or default (staging)."""
    data = _load_config()
    url = (data.get("portal_url") or "").strip()
    if url:
        return url.rstrip("/")
    return DEFAULT_PORTAL_URL


def get_neos_internal_creds() -> Optional[dict]:
    """
    Internal NEOS login (Demo 2).

    Expected shape in config.json:
    {
      "neos_internal": {
        "email": "user@example.com",
        "password": "secret"
      }
    }
    """
    data = _load_config()
    neos = data.get("neos_internal") or {}
    email = (neos.get("email") or "").strip()
    password = (neos.get("password") or "").strip()
    if email and password:
        return {"email": email, "password": password}
    return None


def get_customer_creds() -> Optional[dict]:
    """
    Customer / approved purchaser login (Demo 3–5: customer submit-for-review step).

    Same shape as neos_internal. Use this when you want Demo 4 to log in as
    customer automatically instead of using a pre-saved auth.json session.

    config.json:
    {
      "customer": {
        "email": "customer@example.com",
        "password": "secret"
      }
    }
    """
    data = _load_config()
    cust = data.get("customer") or {}
    email = (cust.get("email") or "").strip()
    password = (cust.get("password") or "").strip()
    if email and password:
        return {"email": email, "password": password}
    return None
