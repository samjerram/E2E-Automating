import json
import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, expect

try:
    from config import get_neos_internal_creds
except ImportError:
    get_neos_internal_creds = None

# Optional customer credentials helper (for Demo 3/4 customer submit step)
try:
    from config import get_customer_creds  # type: ignore[attr-defined]
except ImportError:  # or function not present in older config.py
    get_customer_creds = None  # type: ignore[assignment]

AUTH_STATE_PATH = Path(__file__).resolve().parent / "auth.json"

# ============================
# Generic helpers
# ============================
def wait_visible(locator, timeout=20000):
    locator.first.wait_for(state="visible", timeout=timeout)

def safe_click(locator, timeout=20000):
    wait_visible(locator, timeout=timeout)
    locator.first.scroll_into_view_if_needed()
    locator.first.click()

def safe_fill(locator, value: str, timeout=20000, clear_first=True):
    wait_visible(locator, timeout=timeout)
    locator.first.scroll_into_view_if_needed()
    locator.first.click()
    if clear_first:
        try:
            locator.first.fill("")
        except Exception:
            pass
    locator.first.fill(value)

def click_first_visible_option(page, timeout=12000):
    options = page.get_by_role("option")
    options.first.wait_for(state="visible", timeout=timeout)
    count = options.count()
    for i in range(count):
        opt = options.nth(i)
        try:
            if opt.is_visible():
                opt.click()
                return True
        except Exception:
            continue
    options.first.click()
    return True

def click_get_price_when_enabled(page):
    btn = page.get_by_role("button", name=re.compile(r"^Get price$", re.IGNORECASE)).first
    btn.wait_for(state="visible", timeout=30000)
    expect(btn).to_be_enabled(timeout=90000)
    btn.scroll_into_view_if_needed()
    btn.click()

def click_when_enabled(locator, timeout_ms=90000):
    # Use full timeout for visibility so "Proceed to order" has time to appear after price/publish
    locator.first.wait_for(state="visible", timeout=timeout_ms)
    expect(locator.first).to_be_enabled(timeout=timeout_ms)
    locator.first.scroll_into_view_if_needed()
    locator.first.click()

# ============================
# Step detection
# ============================
def is_on_new_quote_location(page) -> bool:
    return "/quotes/new/location" in page.url

def is_on_order_page(page) -> bool:
    return "/orders/" in page.url

# ============================
# Quote step: optional dropdowns
# ============================
def optional_choose_location_dropdown(page, enabled: bool):
    """
    Choose location dropdown (address picker after Find). Only when enabled.
    Some postcodes return multiple addresses and require a selection to avoid 'Missing address info'.
    Scoped to Location section — never touches NNI fields.
    """
    if not enabled:
        return
    # 1) Combobox/input with placeholder "Choose location" (unique to address picker, not NNI)
    try:
        choose_inp = page.get_by_placeholder(re.compile(r"^Choose location$", re.IGNORECASE))
        if choose_inp.count() > 0 and choose_inp.first.is_visible(timeout=1500):
            choose_inp.first.scroll_into_view_if_needed(timeout=1500)
            choose_inp.first.click(timeout=1500)
            click_first_visible_option(page, timeout=2000)
            page.wait_for_timeout(200)
            print("✅ Choose location selected (first option, placeholder).")
            return
    except PWTimeoutError:
        pass
    except Exception:
        pass

    # 2) Label "Choose location" → combobox in same block
    choose_text = page.get_by_text(re.compile(r"^Choose location$", re.IGNORECASE))
    try:
        choose_text.first.wait_for(state="visible", timeout=1500)
    except PWTimeoutError:
        return  # Dropdown not present - no action needed

    # Try: find a combobox near the label (more stable than css classes)
    try:
        parent = choose_text.first.locator("xpath=ancestor::div[1]")
        combobox = parent.get_by_role("combobox")
        if combobox.count() > 0:
            combobox.first.scroll_into_view_if_needed(timeout=1500)
            combobox.first.click(timeout=1500)
            click_first_visible_option(page, timeout=2000)
            page.wait_for_timeout(200)
            print("✅ Choose location selected (first option).")
            return
    except Exception:
        pass

    # Fallback: old css selector
    try:
        parent = choose_text.first.locator("xpath=ancestor::div[1]")
        dropdown_control = parent.first.locator(".css-19bb58m").first
        dropdown_control.scroll_into_view_if_needed(timeout=1500)
        dropdown_control.click(timeout=1500)
        click_first_visible_option(page, timeout=2000)
        page.wait_for_timeout(200)
        print("✅ Choose location selected (first option).")
    except Exception as e:
        print(f"⚠️ Choose location visible but could not select an option. Continuing. ({e})")

def _click_nni_and_select_option(page, trigger, timeout_ms: int = 5000, type_to_search: bool = True, b_end_postcode: str | None = None) -> bool:
    """
    Click NNI trigger and select first option.
    Uses NNI-specific option filter to avoid picking 'Choose location' address options.
    For SP2 8NJ (Salisbury): try click-only first (no London typing); fall back to typing only if needed.
    """
    try:
        trigger.wait_for(state="visible", timeout=timeout_ms)
        trigger.scroll_into_view_if_needed(timeout=3000)
        trigger.click(timeout=5000)
        page.wait_for_timeout(700)  # HICCUP: Let NNI options load
        opts = page.get_by_role("option")
        # Wait for dropdown options without typing first (avoids "London" flash when the list is already coming up).
        # Previously only SP2 did this; other postcodes always typed London, then cleared — noisy in demos.
        options_loaded = False
        if type_to_search:
            try:
                opts.first.wait_for(state="visible", timeout=4500)
                options_loaded = True
            except Exception:
                pass
        if not options_loaded and type_to_search:
            try:
                trigger.fill("London")
            except Exception:
                try:
                    page.keyboard.type("London", delay=80)
                except Exception:
                    pass
                    page.wait_for_timeout(1500)  # HICCUP: NNI options load after type fail
        opts.first.wait_for(state="visible", timeout=timeout_ms + 5000)  # Options can load slowly
        # Prefer options that look like NNI/data centre (not address) to avoid Choose location
        nni_like = re.compile(r"Gbps|ETH\d|London|Data\s*[Cc]entre|Manchester|Slough", re.IGNORECASE)
        for i in range(opts.count()):
            opt = opts.nth(i)
            try:
                if opt.is_visible():
                    txt = opt.text_content() or ""
                    if nni_like.search(txt):
                        opt.click()
                        page.wait_for_timeout(200)
                        return True
            except Exception:
                continue
        # Fallback: first visible option
        opts.first.click()
        page.wait_for_timeout(200)
        return True
    except Exception:
        return False


def optional_select_nni_dropdown(page, enabled: bool, b_end_postcode: str | None = None):
    if not enabled:
        return

    print("🌐 Checking for NNI dropdown ('Search for NNI and data centre')...")
    # Wait for NNI section to appear (first CSV row / cold start often renders slower)
    try:
        page.get_by_role("heading", name=re.compile(r"Select your NNI", re.IGNORECASE)).first.wait_for(state="visible", timeout=10000)
    except Exception:
        try:
            page.get_by_text("Search for NNI and data centre", exact=True).first.wait_for(state="visible", timeout=6000)
        except Exception:
            pass
    page.wait_for_timeout(800)  # Let dropdown be interactive after visible

    # IMPORTANT: Target ONLY main "Select your NNI" — never Choose location or Shadow VLAN NNI.

    # 1) XPath: dropdown following h4 "Select your NNI" (excludes Shadow VLAN NNI which has different heading)
    try:
        nni_dropdown = page.locator("xpath=//h4[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'select your nni')]/following-sibling::div[contains(@class,'dropdown')]").first
        if nni_dropdown.is_visible(timeout=2000):
            inner = nni_dropdown.locator(".css-19bb58m, .css-13cymwt-control, [class*='control']")
            trig = inner.first if inner.count() > 0 else nni_dropdown
            if _click_nni_and_select_option(page, trig, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (Select your NNI, XPath).")
                return
    except Exception:
        pass

    # 2) Section with "Select your NNI" heading — input, combobox, or div (react-select may use div for placeholder)
    try:
        nni_heading = page.get_by_role("heading", name=re.compile(r"^Select your NNI$", re.IGNORECASE))
        if nni_heading.count() > 0:
            section = nni_heading.first.locator("xpath=..")
            inp = section.get_by_placeholder("Search for NNI and data centre").first
            if inp.count() > 0 and inp.is_visible(timeout=2000) and _click_nni_and_select_option(page, inp, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (NNI heading block).")
                return
            cb = section.get_by_role("combobox").first
            if cb.count() > 0 and cb.is_visible(timeout=2000) and _click_nni_and_select_option(page, cb, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (NNI heading combobox).")
                return
            # react-select: placeholder is often a div with that text, not input
            divs = section.locator("div").filter(has_text=re.compile(r"^Search for NNI and data centre$", re.IGNORECASE))
            for idx in range(min(3, divs.count())):
                el = divs.nth(idx)
                if el.is_visible(timeout=1500):
                    control = el.locator("xpath=ancestor::div[contains(@class,'control') or contains(@class,'dropdown')][1]")
                    trig = control.first if control.count() > 0 else el
                    if _click_nni_and_select_option(page, trig, timeout_ms=10000, b_end_postcode=b_end_postcode):
                        print("✅ Selected first NNI option (NNI div filter).")
                        return
    except Exception:
        pass

    # 3) Broader section fallback
    try:
        section = page.locator("section, div").filter(has_text=re.compile(r"Select your NNI", re.IGNORECASE)).filter(has_text=re.compile(r"Search for NNI", re.IGNORECASE)).first
        if section.is_visible(timeout=2000):
            inp = section.get_by_placeholder("Search for NNI and data centre").first
            if inp.is_visible(timeout=2000) and _click_nni_and_select_option(page, inp, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (NNI section).")
                return
            cb = section.get_by_role("combobox").first
            if cb.is_visible(timeout=2000) and _click_nni_and_select_option(page, cb, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (combobox).")
                return
    except Exception:
        pass

    # 4) Page-level div filter (exclude Shadow VLAN) — try nth(0), nth(1), nth(2)
    try:
        all_divs = page.locator("div").filter(has_text=re.compile(r"^Search for NNI and data centre$", re.IGNORECASE))
        for idx in range(min(4, all_divs.count())):
            el = all_divs.nth(idx)
            try:
                if el.locator("xpath=ancestor::*[contains(@class,'shadow-vlan') or contains(@class,'shadow_vlan')]").count() > 0:
                    continue  # Skip Shadow VLAN NNI
                if el.is_visible(timeout=1500):
                    control = el.locator("xpath=ancestor::div[contains(@class,'control') or contains(@class,'dropdown')][1]")
                    trig = control.first if control.count() > 0 else el
                    if _click_nni_and_select_option(page, trig, timeout_ms=12000, b_end_postcode=b_end_postcode):
                        print("✅ Selected first NNI option (div filter nth).")
                        return
            except Exception:
                continue
    except Exception:
        pass

    # 5) Visible text "Search for NNI and data centre" — react-select may use div, not input placeholder
    try:
        ph = page.get_by_text("Search for NNI and data centre", exact=True)
        if ph.count() > 0 and ph.first.is_visible(timeout=2000):
            # Click the placeholder's control container (parent of parent often)
            control = ph.locator("xpath=(ancestor::div[contains(@class,'control') or contains(@class,'dropdown')])[1]")
            if control.count() > 0 and control.first.is_visible(timeout=2000) and _click_nni_and_select_option(page, control.first, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (placeholder text).")
                return
    except Exception:
        pass

    # 6) react-select placeholder ID — only use if inside "Select your NNI" block (excludes Choose location & Shadow VLAN)
    try:
        nni_heading = page.get_by_role("heading", name=re.compile(r"^Select your NNI$", re.IGNORECASE))
        nni_section = nni_heading.first.locator("xpath=..") if nni_heading.count() > 0 else None
        for pid in ["react-select-2-placeholder", "react-select-3-placeholder"]:
            ph_el = page.locator(f"#{pid}")
            if ph_el.count() == 0 or not ph_el.first.is_visible(timeout=1500):
                continue
            if ph_el.first.locator("xpath=ancestor::*[contains(@class,'shadow-vlan')]").count() > 0:
                continue  # Skip — Shadow VLAN NNI
            if not nni_section or nni_section.count() == 0 or nni_section.locator(f"#{pid}").count() == 0:
                continue  # Not in Select your NNI section
            control = ph_el.first.locator("xpath=ancestor::div[contains(@class,'control') or contains(@class,'dropdown')][1]")
            trig = control.first if control.count() > 0 else ph_el.first
            if _click_nni_and_select_option(page, trig, timeout_ms=10000, b_end_postcode=b_end_postcode):
                print(f"✅ Selected first NNI option ({pid}).")
                return
    except Exception:
        pass

    # 7) data-testid only (if present)
    try:
        nni = page.get_by_test_id("nni_dropdown")
        if nni.count() > 0 and nni.first.is_visible(timeout=2000):
            if _click_nni_and_select_option(page, nni.first, timeout_ms=6000, b_end_postcode=b_end_postcode):
                print("✅ Selected first NNI option (nni_dropdown).")
                return
    except Exception:
        pass

    print("ℹ️ No NNI dropdown visible or could not select.")

def optional_shadow_vlan(page, enabled: bool):
    if not enabled:
        return

    checkbox = page.get_by_role("checkbox", name=re.compile(r"^Shadow VLAN required\?$", re.IGNORECASE))
    try:
        checkbox.first.wait_for(state="visible", timeout=3000)
    except PWTimeoutError:
        print("ℹ️ No Shadow VLAN option on this journey.")
        return

    aria_checked = checkbox.first.get_attribute("aria-checked")
    if aria_checked != "true":
        checkbox.first.click()
    print("✅ Shadow VLAN required checked.")

    # 1) Label "Shadow VLAN NNI" → combobox in same block
    label = page.get_by_text(re.compile(r"Shadow VLAN NNI", re.IGNORECASE))
    try:
        label.first.wait_for(state="visible", timeout=6000)
        parent = label.first.locator("xpath=ancestor::div[1]")
        combobox = parent.get_by_role("combobox")
        if combobox.count() > 0:
            combobox.first.scroll_into_view_if_needed()
            combobox.first.click()
            click_first_visible_option(page, timeout=12000)
            page.wait_for_timeout(200)
            print("✅ Selected first Shadow VLAN NNI option.")
            return
    except Exception:
        pass

    # 2) Scoped to .shadow-vlan (Playwright Inspector: excludes main NNI)
    for sel in [
        ".shadow-vlan > .dropdown > .css-13cymwt-control > .css-hlgwow",
        ".shadow-vlan > .dropdown > .css-13cymwt-control > .css-hlgwow > .css-19bb58m",
    ]:
        try:
            shadow_dropdown = page.locator(sel)
            shadow_dropdown.first.wait_for(state="visible", timeout=12000)
            shadow_dropdown.first.scroll_into_view_if_needed()
            shadow_dropdown.first.click()
            click_first_visible_option(page, timeout=12000)
            page.wait_for_timeout(200)
            print("✅ Selected first Shadow VLAN NNI option.")
            return
        except Exception:
            continue

# ============================
# Quote step: access/config selection
# ============================
def click_choice_fast(page, label: str, retries: int = 6, delay_ms: int = 150):
    """
    Faster + more stable than clicking the <input> radio directly.
    Strategy:
      1) click the visible tile text (usually the fastest)
      2) fallback to role=radio if needed
      Retry a few times because UI re-renders.
    """
    label = str(label)
    use_string_match = "/" in label  # regex with / breaks Playwright's attribute selector (e.g. 115/20 Mbps)

    # Special-case: your UI often shows "1Gbps" (no space) instead of "1 Gbps"
    variants = [label]
    if label.lower() == "1 gbps":
        variants.append("1Gbps")
    if label.lower() == "10 gbps":
        variants.append("10Gbps")
    if label.lower() == "100 mbps":
        variants.append("100Mbps")
    if label.lower() == "500 mbps":
        variants.append("500Mbps")

    for attempt in range(retries):
        for v in variants:
            if use_string_match:
                txt = page.get_by_text(v)
                if txt.count() > 0:
                    try:
                        if txt.first.is_visible():
                            txt.first.scroll_into_view_if_needed()
                            txt.first.click(timeout=5000)
                            return True
                    except Exception:
                        pass
                cb = page.get_by_role("checkbox", name=v)
                if cb.count() > 0:
                    try:
                        cb.first.scroll_into_view_if_needed()
                        cb.first.click(timeout=5000)
                        return True
                    except Exception:
                        pass
            else:
                # 1) click the visible tile label text
                txt = page.get_by_text(re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if txt.count() > 0:
                    try:
                        if txt.first.is_visible():
                            txt.first.scroll_into_view_if_needed()
                            txt.first.click(timeout=5000)
                            return True
                    except Exception:
                        pass
                # 2) fallback: click role radio/checkbox
                radio = page.get_by_role("radio", name=re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if radio.count() > 0:
                    try:
                        radio.first.click(timeout=5000)
                        return True
                    except Exception:
                        pass
                cb = page.get_by_role("checkbox", name=re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if cb.count() > 0:
                    try:
                        cb.first.scroll_into_view_if_needed()
                        cb.first.click(timeout=5000)
                        return True
                    except Exception:
                        pass

        page.wait_for_timeout(delay_ms)

    return False

def _wait_for_bandwidth_section(page) -> bool:
    """Wait for Bandwidth section to render after bearer selection. HICCUP: needs generous wait."""
    try:
        heading = page.get_by_text(re.compile(r"Bandwidth sizes?", re.IGNORECASE))
        heading.first.wait_for(state="visible", timeout=10000)
        page.wait_for_timeout(220)  # Faster settle; long waits hurt 1 Gbps path
        return True
    except Exception:
        page.wait_for_timeout(200)
        return False


def _is_bandwidth_1gbps_checked(page) -> bool:
    """Check if 1 Gbps bandwidth is selected."""
    try:
        cb = page.locator("#bandwidth--1000")
        return cb.count() > 0 and cb.first.is_checked()
    except Exception:
        return False


def _select_bandwidth_1gbps(page):
    """
    Single, minimal-click 1 Gbps bandwidth selection.
    We deliberately avoid retry loops here so the UI doesn’t visibly toggle on/off.
    """
    _wait_for_bandwidth_section(page)
    # 1) Prefer the dedicated wrapper for bandwidth 1 Gbps
    try:
        wrapper = page.locator("#wrapper-bandwidth--1000")
        if wrapper.count() > 0 and wrapper.first.is_visible(timeout=2500):
            wrapper.first.scroll_into_view_if_needed()
            wrapper.first.click(force=True, timeout=3000)
            page.wait_for_timeout(200)
            if _is_bandwidth_1gbps_checked(page):
                return
    except Exception:
        pass
    # 2) Single JS-assisted fallback on the checkbox itself
    try:
        ok = page.evaluate("""() => {
            const cb = document.querySelector("#bandwidth--1000");
            if (cb) {
                cb.checked = true;
                cb.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
            }
            return false;
        }""")
        page.wait_for_timeout(200)
        if ok and _is_bandwidth_1gbps_checked(page):
            return
    except Exception:
        pass
    # If we reach here we didn’t manage to set it, but we still avoid multiple visible toggles.
    raise RuntimeError("Could not select 1 Gbps bandwidth (may be disabled for this bearer).")

def _is_1gbps_bandwidth(bandwidth: str) -> bool:
    if not bandwidth:
        return False
    s = str(bandwidth).strip().lower()
    return s in ("1 gbps", "1gbps")

def _select_bandwidth_10gbps(page):
    """
    Special-case for 10 Gbps bandwidth: use id-based scoped clicking.
    Falls back to click_choice_fast if wrapper not visible (e.g. bearer not selected).
    """
    try:
        wrapper = page.locator("#wrapper-bandwidth--10000")
        wrapper.wait_for(state="visible", timeout=2000)
        wrapper.scroll_into_view_if_needed(timeout=2000)
        wrapper.click(timeout=2000)
        page.wait_for_timeout(150)
    except Exception:
        if not click_choice_fast(page, "10 Gbps", retries=6, delay_ms=80):
            raise RuntimeError("Could not select 10 Gbps bandwidth (id-based or text).")

def _is_10gbps_bandwidth(bandwidth: str) -> bool:
    if not bandwidth:
        return False
    s = str(bandwidth).strip().lower()
    return s in ("10 gbps", "10gbps")

# Locators from Configuration section (bearer, bandwidth, contract term)
# Bearer wrapper IDs can vary; try multiple patterns
BEARER_WRAPPERS = {
    "100 mbps": "#wrapper-bearer--Port_100Mbits",
    "100mbps": "#wrapper-bearer--Port_100Mbits",
    "1 gbps": "#wrapper-bearer--Port_1000Mbits",
    "1gbps": "#wrapper-bearer--Port_1000Mbits",
    "10 gbps": "#wrapper-bearer--Port_10000Mbits",
    "10gbps": "#wrapper-bearer--Port_10000Mbits",
}
# Alternate bearer wrapper IDs (site may use different naming)
BEARER_ALT_SELECTORS = {
    "1 gbps": [
        "#wrapper-bearer--Port_1000Mbits",
        "#wrapper-bearer--Port_1Gbps",
        "[id*='bearer'][id*='1000']",
        "[id*='bearer'][id*='1Gbps']",
    ],
    "100 mbps": ["#wrapper-bearer--Port_100Mbits", "[id*='bearer'][id*='100']"],
    "10 gbps": ["#wrapper-bearer--Port_10000Mbits", "[id*='bearer'][id*='10000']"],
}
CONTRACT_TERM_WRAPPERS = {
    "1 year": "#wrapper-contractTermLength--1year",
    "2 years": "#wrapper-contractTermLength--2years",
    "3 years": "#wrapper-contractTermLength--3years",
    "4 years": "#wrapper-contractTermLength--4years",
    "5 years": "#wrapper-contractTermLength--5years",
}
BANDWIDTH_WRAPPERS = {
    "100 mbps": "#wrapper-bandwidth--100",
    "100mbps": "#wrapper-bandwidth--100",
    "200 mbps": "#wrapper-bandwidth--200",
    "200mbps": "#wrapper-bandwidth--200",
    "500 mbps": "#wrapper-bandwidth--500",
    "500mbps": "#wrapper-bandwidth--500",
    "1 gbps": "#wrapper-bandwidth--1000",
    "1gbps": "#wrapper-bandwidth--1000",
    "10 gbps": "#wrapper-bandwidth--10000",
    "10gbps": "#wrapper-bandwidth--10000",
}


def _click_wrapper(page, selector: str, timeout_ms: int = 5000) -> bool:
    """Click wrapper element by selector. Returns True if successful."""
    try:
        el = page.locator(selector)
        el.first.wait_for(state="visible", timeout=timeout_ms)
        el.first.scroll_into_view_if_needed(timeout=2000)
        el.first.click(timeout=4000, force=True)
        page.wait_for_timeout(200)
        return True
    except Exception:
        return False


def select_access_and_configuration(page, access_type: str | None, bearer: str | None, bandwidth: str | None, contract_term: str | None = None, pause: bool = False):
    page.wait_for_timeout(120)  # Speed: shorter config settle

    # For 10 Gbps: do bearer FIRST (contract term click can cause re-render that breaks bearer selection)
    b_norm = str(bearer or "").strip().lower() if bearer else ""
    do_bearer_first = b_norm in ("10 gbps", "10gbps")

    # First row / cold page: 10 Gbps bearer needs extra time for config section to be interactive
    if do_bearer_first:
        page.wait_for_timeout(3200)  # Allow config section to fully initialize
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

    if not do_bearer_first:
        # Contract term: wrapper-contractTermLength--1year, --2years, --3years, etc.
        if contract_term:
            ct_norm = str(contract_term).strip().lower()
            if ct_norm == "3 years":
                print(f"ℹ️ Contract term '{contract_term}' is default (already selected).")
            else:
                sel = CONTRACT_TERM_WRAPPERS.get(ct_norm)
                if sel and _click_wrapper(page, sel):
                    page.wait_for_timeout(150)
                    _click_wrapper(page, "#wrapper-contractTermLength--3years", timeout_ms=3000)
                    page.wait_for_timeout(100)
                    print(f"✅ Selected contract term: {contract_term}")
                elif click_choice_fast(page, contract_term, retries=6, delay_ms=100):
                    page.wait_for_timeout(150)
                    _click_wrapper(page, "#wrapper-contractTermLength--3years", timeout_ms=3000)
                    page.wait_for_timeout(100)
                    print(f"✅ Selected contract term: {contract_term}")
                else:
                    print(f"ℹ️ Contract term '{contract_term}' not selected.")

    # Access type: skip if bearer journey
    if bearer:
        if access_type:
            print(f"ℹ️ Skipping access type (bearer journey).")
    elif access_type:
        if not click_choice_fast(page, access_type):
            print(f"ℹ️ Access type '{access_type}' not clickable (may already be selected).")
        else:
            print(f"✅ Selected access type: {access_type}")

    # Bearer: wrapper-bearer--Port_100Mbits, Port_1000Mbits, Port_10000Mbits
    # Bearer section typically appears BEFORE Bandwidth; first "1 Gbps" on page is usually bearer
    if bearer:
        b_key = str(bearer).strip().lower().replace(" ", "")
        b_norm = str(bearer).strip().lower()
        page.wait_for_timeout(160)  # Bearer section quick settle
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(120)
        if b_norm in ("10 gbps", "10gbps"):
            page.wait_for_timeout(400)
        if pause:
            print("⏸️  Pausing at Bearer: Use Playwright Inspector 'Pick locator' on the 1 Gbps bearer option.")
            page.pause()
        if b_norm in ("1 gbps", "1gbps"):
            try:
                page.locator("#wrapper-bearer--Port_1000Mbits").first.wait_for(state="visible", timeout=10000)
                page.wait_for_timeout(250)
            except Exception:
                pass
        elif b_norm in ("10 gbps", "10gbps"):
            try:
                page.locator("#wrapper-bearer--Port_10000Mbits").first.wait_for(state="visible", timeout=15000)
                page.wait_for_timeout(500)
            except Exception:
                pass
        sel = BEARER_WRAPPERS.get(b_norm) or BEARER_WRAPPERS.get(b_key)
        clicked = False
        # Check if already selected
        if b_norm in ("1 gbps", "1gbps"):
            try:
                if page.evaluate("() => { const r = document.querySelector('input[id*=\"bearer\"][id*=\"1000\"]'); return r && r.checked; }"):
                    clicked = True
            except Exception:
                pass
        elif b_norm in ("10 gbps", "10gbps"):
            try:
                if page.evaluate("() => { const r = document.querySelector('input[id*=\"bearer\"][id*=\"10000\"]'); return r && r.checked; }"):
                    clicked = True
            except Exception:
                pass
        # First: use confirmed Playwright locators (#wrapper-bearer--Port_100Mbits, Port_1000Mbits, Port_10000Mbits)
        if sel and not clicked:
            if _click_wrapper(page, sel, timeout_ms=12000):
                clicked = True
            elif b_norm in ("10 gbps", "10gbps"):
                for _ in range(3):
                    page.wait_for_timeout(1000)
                    if _click_wrapper(page, sel, timeout_ms=8000):
                        clicked = True
                        break
        # Fallback: JS click
        if not clicked and b_norm in ("1 gbps", "1gbps"):
            for _ in range(5):  # Retry up to 5 times - element may load slowly
                try:
                    js_ok = page.evaluate("""() => {
                        const ids = ['#wrapper-bearer--Port_1000Mbits', '#wrapper-bearer--Port_1Gbps', '#wrapper-bearer--1Gbps', '[id*="bearer"][id*="1000"]'];
                        for (const id of ids) {
                            const el = document.querySelector(id);
                            if (el && el.offsetParent) { el.click(); return true; }
                        }
                        const labels = document.querySelectorAll('label');
                        for (const lbl of labels) {
                            const t = (lbl.textContent||'').toLowerCase();
                            if ((t.includes('1 gbps') || t.includes('1000 mbits')) && !t.includes('bandwidth')) {
                                const inp = lbl.querySelector('input[type="radio"]');
                                if (inp && inp.offsetParent) { inp.click(); return true; }
                                lbl.click(); return true;
                            }
                        }
                        const radios = document.querySelectorAll('input[type="radio"]');
                        for (const r of radios) {
                            const v = ((r.value||'')+(r.id||'')+(r.getAttribute('name')||'')).toLowerCase();
                            if ((v.includes('1000') || v.includes('1gbps')) && !v.includes('bandwidth') && r.offsetParent) {
                                r.click(); return true;
                            }
                        }
                        return false;
                    }""")
                    if js_ok:
                        clicked = True
                        page.wait_for_timeout(300)
                        break
                except Exception:
                    pass
                page.wait_for_timeout(800)
        if not clicked and b_norm in ("1 gbps", "1gbps"):
            for sel_try in ["#wrapper-bearer--Port_1000Mbits", "#wrapper-bearer--Port_1000Mbits label", "#wrapper-bearer--Port_1000Mbits circle"]:
                try:
                    el = page.locator(sel_try).first
                    if el.is_visible(timeout=6000):
                        el.scroll_into_view_if_needed()
                        el.click(timeout=3000, force=True)
                        page.wait_for_timeout(200)
                        clicked = True
                        break
                except Exception:
                    continue
        if not clicked and b_norm in ("1 gbps", "1gbps"):
            # Scope to Bearer section to avoid clicking bandwidth "1 Gbps"
            bearer_section = page.locator("section, div").filter(has_text=re.compile(r"Bearer size|Ethernet fibre", re.IGNORECASE))
            bearer_container = bearer_section.first if bearer_section.count() > 0 else page
            for v in ["1 Gbps", "1Gbps", "1000 Mbits", "1000Mbits"]:
                radios = bearer_container.get_by_role("radio", name=re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if radios.count() == 0:
                    radios = page.get_by_role("radio", name=re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if radios.count() >= 1:
                    try:
                        radios.first.scroll_into_view_if_needed(timeout=4000)
                        radios.first.click(timeout=5000, force=True)
                        page.wait_for_timeout(200)
                        clicked = True
                        break
                    except Exception:
                        pass
        if not clicked and b_norm in BEARER_ALT_SELECTORS:
            for alt in BEARER_ALT_SELECTORS[b_norm]:
                try:
                    el = page.locator(alt).first
                    if el.is_visible(timeout=2000):
                        el.scroll_into_view_if_needed()
                        el.click(timeout=3000)
                        page.wait_for_timeout(200)
                        clicked = True
                        break
                except Exception:
                    continue
        if not clicked:
            # Scope to Bearer section to avoid clicking bandwidth "1 Gbps"
            bearer_section = page.locator("section, div").filter(has_text=re.compile(r"Bearer size|Ethernet fibre", re.IGNORECASE))
            if bearer_section.count() > 0 and bearer_section.first.is_visible(timeout=2000):
                variants = ["1 Gbps", "1Gbps", "1000 Mbits", "1000Mbits"] if ("1" in b_norm and "g" in b_norm) else [bearer]
                for v in variants:
                    txt = bearer_section.first.get_by_text(re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                    if txt.count() > 0 and txt.first.is_visible(timeout=1000):
                        try:
                            txt.first.scroll_into_view_if_needed()
                            txt.first.click(timeout=3000)
                            clicked = True
                            break
                        except Exception:
                            pass
                if not clicked:
                    # Try radio button within Bearer section
                    for v in variants:
                        radio = bearer_section.first.get_by_role("radio", name=re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                        if radio.count() > 0 and radio.first.is_visible(timeout=1000):
                            try:
                                radio.first.scroll_into_view_if_needed()
                                radio.first.click(timeout=3000)
                                clicked = True
                                break
                            except Exception:
                                pass
        if not clicked and b_norm in ("10 gbps", "10gbps"):
            # Retry loop for 10 Gbps (first row often needs more time)
            for _ in range(4):
                try:
                    js_ok = page.evaluate("""() => {
                        const ids = ['#wrapper-bearer--Port_10000Mbits', '[id*="bearer"][id*="10000"]'];
                        for (const id of ids) {
                            const el = document.querySelector(id);
                            if (el && el.offsetParent) { el.click(); return true; }
                        }
                        const lbls = document.querySelectorAll('label');
                        for (const lbl of lbls) {
                            const t = (lbl.textContent||'').toLowerCase();
                            if ((t.includes('10 gbps') || t.includes('10000')) && !t.includes('bandwidth')) {
                                const inp = lbl.querySelector('input[type="radio"]');
                                if (inp && inp.offsetParent) { inp.click(); return true; }
                                lbl.click(); return true;
                            }
                        }
                        return false;
                    }""")
                    if js_ok:
                        clicked = True
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    pass
                page.wait_for_timeout(1500)
        if not clicked and b_norm in ("10 gbps", "10gbps"):
            # get_by_label fallback for 10 Gbps
            for v in ["10 Gbps", "10Gbps", "10000 Mbits"]:
                lbl = page.get_by_label(re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if lbl.count() > 0 and lbl.first.is_visible(timeout=1000):
                    try:
                        lbl.first.scroll_into_view_if_needed()
                        lbl.first.click(timeout=3000, force=True)
                        page.wait_for_timeout(200)
                        clicked = True
                        break
                    except Exception:
                        pass
        if not clicked and b_norm in ("10 gbps", "10gbps"):
            # Retry for 10 Gbps: wrapper may load slowly
            page.wait_for_timeout(1500)
            try:
                js_ok = page.evaluate("""() => {
                    const ids = ['#wrapper-bearer--Port_10000Mbits', '[id*="bearer"][id*="10000"]'];
                    for (const id of ids) {
                        const el = document.querySelector(id);
                        if (el && el.offsetParent) { el.click(); return true; }
                    }
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        const t = (lbl.textContent||'').toLowerCase();
                        if ((t.includes('10 gbps') || t.includes('10000')) && !t.includes('bandwidth')) {
                            const inp = lbl.querySelector('input[type="radio"]');
                            if (inp && inp.offsetParent) { inp.click(); return true; }
                            lbl.click(); return true;
                        }
                    }
                    return false;
                }""")
                if js_ok:
                    clicked = True
                    page.wait_for_timeout(500)
            except Exception:
                pass
        if not clicked and b_norm in ("1 gbps", "1gbps"):
            # Last resort: get_by_label often works when radio has associated label
            for v in ["1 Gbps", "1Gbps", "1000 Mbits"]:
                lbl = page.get_by_label(re.compile(rf"^{re.escape(v)}$", re.IGNORECASE))
                if lbl.count() > 0 and lbl.first.is_visible(timeout=1000):
                    try:
                        lbl.first.scroll_into_view_if_needed()
                        lbl.first.click(timeout=3000)
                        clicked = True
                        break
                    except Exception:
                        pass
        if not clicked and b_norm in ("1 gbps", "1gbps"):
            # JS fallback: click bearer by ID or input value
            clicked_js = page.evaluate("""() => {
                const ids = ['#wrapper-bearer--Port_1000Mbits', '#wrapper-bearer--Port_1Gbps', '#wrapper-bearer--1Gbps',
                    '[id*="bearer"][id*="1000"]', '[id*="bearer"][id*="1Gbps"]', '[id*="bearer"][id*="1Gbit"]'];
                for (const id of ids) {
                    const el = document.querySelector(id);
                    if (el) { el.click(); return true; }
                }
                const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                for (const r of radios) {
                    const val = ((r.value||'')+(r.id||'')+(r.getAttribute('aria-label')||'')).toLowerCase();
                    const label = (r.closest('label')?.textContent||'').toLowerCase();
                    const combined = val + ' ' + label;
                    if ((combined.includes('1000') || combined.includes('1gbps') || combined.includes('1 gbps')) &&
                        !combined.includes('bandwidth') && r.offsetParent !== null) {
                        r.click(); return true;
                    }
                }
                return false;
            }""")
            if clicked_js:
                clicked = True
                page.wait_for_timeout(200)
        if not clicked:
            clicked = click_choice_fast(page, bearer, retries=15, delay_ms=200)
        if not clicked and bandwidth:
            # Final retry: wait longer and try JS + wrapper again (1G or 10G), with multiple attempts for 10G
            page.wait_for_timeout(1500)
            for attempt in range(6 if b_norm in ("10 gbps", "10gbps") else 1):
                try:
                    js_ids = ['#wrapper-bearer--Port_10000Mbits', '[id*="bearer"][id*="10000"]'] if b_norm in ("10 gbps", "10gbps") else ['#wrapper-bearer--Port_1000Mbits', 'input[id*="bearer"][id*="1000"]']
                    js_ok = page.evaluate("""(ids) => {
                        for (const id of ids) {
                            const el = document.querySelector(id);
                            if (el && el.offsetParent) { el.click(); return true; }
                        }
                        return false;
                    }""", js_ids)
                    if js_ok:
                        clicked = True
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    pass
                if attempt < 5:
                    page.wait_for_timeout(1200)
        if not clicked and b_norm in ("10 gbps", "10gbps"):
            # Last-ditch: scroll to top, wait, try label click (first row can lag)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(2000)
            for sel in ["#wrapper-bearer--Port_10000Mbits", "[id*='bearer'][id*='10000']"]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=5000):
                        el.scroll_into_view_if_needed()
                        el.click(timeout=5000, force=True)
                        page.wait_for_timeout(300)
                        clicked = True
                        break
                except Exception:
                    pass
        if clicked:
            print(f"✅ Selected bearer: {bearer}")
        else:
            if bandwidth and b_norm in ("10 gbps", "10gbps"):
                # Nuclear option: wait long, then one final comprehensive try
                print("⚠️ Bearer not selected yet. Waiting 10s then retrying...")
                page.wait_for_timeout(6000)
                page.evaluate("window.scrollTo(0, 0)")
                for sel in ["#wrapper-bearer--Port_10000Mbits", "input[id*='bearer'][id*='10000']", "[id*='bearer'][id*='10000']"]:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0 and el.is_visible(timeout=3000):
                            el.scroll_into_view_if_needed()
                            el.click(timeout=5000, force=True)
                            page.wait_for_timeout(500)
                            if page.evaluate("() => { const r = document.querySelector('input[id*=\"bearer\"][id*=\"10000\"]'); return r && r.checked; }"):
                                clicked = True
                                print(f"✅ Selected bearer: {bearer} (retry)")
                                break
                    except Exception:
                        pass
                if not clicked:
                    # Try bearer section scoped: find Bearer heading, then 10 Gbps within that section
                    try:
                        bearer_section = page.locator("section, div").filter(has_text=re.compile(r"Bearer|Ethernet fibre", re.IGNORECASE)).first
                        if bearer_section.is_visible(timeout=2000):
                            ten_g = bearer_section.get_by_text(re.compile(r"^10\s*Gbps$", re.IGNORECASE))
                            if ten_g.count() > 0 and ten_g.first.is_visible(timeout=2000):
                                ten_g.first.click(timeout=5000, force=True)
                                page.wait_for_timeout(500)
                                clicked = True
                                print(f"✅ Selected bearer: {bearer} (section scoped)")
                    except Exception:
                        pass
            if not clicked and bandwidth:
                raise RuntimeError(f"Could not select bearer '{bearer}'. Bandwidth requires bearer first.")
            elif not clicked:
                print(f"⚠️ Could not click bearer '{bearer}'.")
        page.wait_for_timeout(250)  # Let bandwidth options enable after bearer
        # Wait for 1 Gbps bandwidth option to become enabled (not disabled)
        if bandwidth and _is_1gbps_bandwidth(bandwidth):
            try:
                page.wait_for_function(
                    "() => { const inp = document.querySelector('#bandwidth--1000'); return inp && !inp.disabled; }",
                    timeout=12000
                )
            except Exception:
                pass

    # Bandwidth: use ID-scoped wrappers (wrapper-bandwidth--100, --1000, etc.) to avoid clicking bearer text
    if bandwidth:
        # Only one clean bandwidth selection; avoid double-click loops that toggle it off/on.
        page.wait_for_timeout(80)  # Shorter buffer before bandwidth click
        w_key = str(bandwidth).strip().lower().replace(" ", "")
        w_norm = str(bandwidth).strip().lower()
        clicked_bw = False
        # Special-case 1 Gbps / 10 Gbps: dedicated helpers with fallbacks
        if _is_1gbps_bandwidth(bandwidth):
            try:
                # Single, robust 1 Gbps selection – no retry loop, so we don't toggle the radio.
                _select_bandwidth_1gbps(page)
                clicked_bw = True
            except RuntimeError:
                page.wait_for_timeout(180)  # One extra wait before falling back to generic locators
        elif _is_10gbps_bandwidth(bandwidth):
            try:
                _select_bandwidth_10gbps(page)
                clicked_bw = True
            except RuntimeError:
                pass
        if not clicked_bw:
            sel = BANDWIDTH_WRAPPERS.get(w_norm) or BANDWIDTH_WRAPPERS.get(w_key)
            if sel and _click_wrapper(page, sel):
                clicked_bw = True
        if not clicked_bw and click_choice_fast(page, bandwidth, retries=14, delay_ms=120):
            clicked_bw = True
        if clicked_bw:
            print(f"✅ Selected bandwidth: {bandwidth}")
        else:
            raise RuntimeError(f"Could not click bandwidth '{bandwidth}' (may be disabled for this bearer).")

    # Contract term AFTER bearer when do_bearer_first (10 Gbps: avoid re-render from contract term breaking bearer)
    if do_bearer_first and contract_term:
        ct_norm = str(contract_term).strip().lower()
        if ct_norm != "3 years":
            page.wait_for_timeout(500)
            sel = CONTRACT_TERM_WRAPPERS.get(ct_norm)
            if sel and _click_wrapper(page, sel):
                page.wait_for_timeout(150)
                _click_wrapper(page, "#wrapper-contractTermLength--3years", timeout_ms=3000)
                page.wait_for_timeout(100)
                print(f"✅ Selected contract term: {contract_term}")
            elif click_choice_fast(page, contract_term, retries=6, delay_ms=100):
                page.wait_for_timeout(150)
                _click_wrapper(page, "#wrapper-contractTermLength--3years", timeout_ms=3000)
                page.wait_for_timeout(100)
                print(f"✅ Selected contract term: {contract_term}")

    print("💰 Clicking Get price...")
    click_get_price_when_enabled(page)
    print("✅ Get price clicked.")
    # Clear "Updating..." quickly so downstream readiness sees real pricing DOM sooner.
    _wait_for_updating_overlay_gone(page, timeout_ms=15000)

# ============================
# RO2 Diversity flow (no shadow VLAN, known postcode e.g. SP2 8NJ)
# ============================
def do_ro2_diversity_flow(page):
    """
    On quote screen: select Neos Openreach tile (Diverse Options Available),
    click Check Now, select Secondary NNI, then Load Prices.
    """
    print("🔄 Starting RO2 diversity flow...")
    page.wait_for_timeout(280)  # Let price tiles finish loading
    # 1) Click Neos Openreach tile - "Diverse Options Available" is a sibling of the button, not inside it.
    div_re = re.compile(r"Diverse.*Options.*Available", re.IGNORECASE)
    label = page.get_by_text(div_re)
    try:
        label.first.wait_for(state="visible", timeout=12000)
    except Exception as e:
        raise RuntimeError(
            f"Diverse Options Available tile not found (timeout). "
            f"This option may not be offered for this bearer/bandwidth. {e}"
        ) from e
    parent = label.first.locator("xpath=..")
    tile = parent.get_by_test_id("price-tile").first
    tile.wait_for(state="visible", timeout=12000)
    try:
        tile.scroll_into_view_if_needed()
        tile.click(timeout=5000)
        page.wait_for_timeout(200)
        print("✅ Selected Neos Openreach (Diverse Options Available) tile.")
    except Exception as e:
        raise RuntimeError(f"RO2: Neos Openreach tile with 'Diverse Options Available' not found. {e}")

    # 2) Click Check Now
    check_btn = page.get_by_test_id("check-now-button")
    try:
        check_btn.first.wait_for(state="visible", timeout=10000)
        check_btn.first.scroll_into_view_if_needed()
        check_btn.first.click(timeout=5000)
        page.wait_for_timeout(200)
        print("✅ Clicked Check Now.")
    except Exception as e:
        raise RuntimeError(f"RO2: Check Now button not found. {e}")

    # 3) Select Secondary NNI - open dropdown and pick first option
    page.wait_for_timeout(320)  # Let Diversity section render
    dropdown_trigger = None
    for _ in range(3):
        inp = page.get_by_placeholder(re.compile(r"Search for NNI", re.IGNORECASE))
        if inp.count() == 0:
            inp = page.get_by_label(re.compile(r"Search for NNI", re.IGNORECASE))
        if inp.count() == 0:
            inp = page.get_by_placeholder(re.compile(r"Search.*NNI.*data centre", re.IGNORECASE))
        if inp.count() > 0:
            try:
                inp.first.wait_for(state="visible", timeout=6000)
                dropdown_trigger = inp.first
                break
            except Exception:
                page.wait_for_timeout(280)
                continue
        page.wait_for_timeout(280)
    if dropdown_trigger is None:
        sec_nni = page.get_by_test_id("Secondary Circuits-secondary-nni")
        if sec_nni.count() > 0:
            combobox = sec_nni.get_by_role("combobox")
            if combobox.count() > 0:
                dropdown_trigger = combobox.first
            else:
                dropdown_trigger = sec_nni.locator("div[class*='dropdown'], [class*='control']").first
    if dropdown_trigger is None:
        h4 = page.locator("h4").filter(has_text=re.compile(r"Select Secondary NNI", re.IGNORECASE))
        if h4.count() > 0:
            cont = h4.first.locator("xpath=..")
            dd = cont.locator("div[class*='dropdown'], [role='combobox'], input")
            if dd.count() > 0:
                dropdown_trigger = dd.first
    if dropdown_trigger is None:
        div_section = page.locator("div, section").filter(has_text=re.compile(r"Select Secondary NNI", re.IGNORECASE))
        if div_section.count() > 0:
            inner = div_section.first.locator("div[class*='dropdown'] div[class*='control'], input, [role='combobox']")
            if inner.count() > 0:
                dropdown_trigger = inner.first
    if dropdown_trigger is None:
        dd = page.locator("div[class*='dropdown'][class*='container']")
        if dd.count() > 0 and dd.first.is_visible():
            dropdown_trigger = dd.first
    if dropdown_trigger is None:
        combos = page.get_by_role("combobox")
        if combos.count() > 0:
            for j in range(combos.count()):
                c = combos.nth(j)
                try:
                    al = c.get_attribute("aria-label") or ""
                    if c.is_visible() and ("NNI" in al or "Secondary" in al):
                        dropdown_trigger = c
                        break
                except Exception:
                    pass
            if dropdown_trigger is None:
                dropdown_trigger = combos.first
    if dropdown_trigger is None:
        raise RuntimeError("RO2: Select Secondary NNI dropdown not found.")
    dropdown_trigger.scroll_into_view_if_needed(timeout=10000)
    dropdown_trigger.click()
    page.wait_for_timeout(200)
    click_first_visible_option(page, timeout=8000)
    page.wait_for_timeout(150)
    print("✅ Selected Secondary NNI.")

    # 4) Click Load Prices
    load_btn = page.get_by_test_id("load-prices-button")
    try:
        load_btn.first.wait_for(state="visible", timeout=10000)
        load_btn.first.scroll_into_view_if_needed()
        load_btn.first.click(timeout=5000)
        page.wait_for_timeout(500)
        print("✅ Clicked Load Prices.")
    except Exception as e:
        raise RuntimeError(f"RO2: Load Prices button not found. {e}")

    print("✅ RO2 diversity flow complete.")

# ============================
# Quote page toggles
# ============================
def toggle_upfront_charge(page, pay_upfront: bool, *, _nested_fallback: bool = False):
    """Select Pay up-front / Pay no up-front. CSV 'Yes' = pay_upfront True = select 'Pay up-front circuit charge'."""
    # Only skip when upfront controls are truly absent.
    # Do NOT rely on "no up-front charges" text alone; that text can appear as informational copy.
    try:
        has_upfront_controls = (
            page.locator("#amortise-up-front").count() > 0
            or page.locator("#amortise-spread-costs").count() > 0
            or page.locator("#wrapper-amortise-up-front").count() > 0
            or page.locator("#wrapper-amortise-spread-costs").count() > 0
        )
        if not has_upfront_controls:
            no_upfront = page.get_by_text(re.compile(r"no up-front charges|no up-front charge", re.IGNORECASE))
            if no_upfront.count() > 0 and no_upfront.first.is_visible(timeout=1500):
                print("ℹ️ No up-front controls for this journey; skipping upfront toggle.")
                return
    except Exception:
        pass
    # Scroll to upfront section first (often below fold)
    try:
        section = page.get_by_text(re.compile(r"up-front|upfront|Amounts shown|circuit charge", re.IGNORECASE))
        if section.first.is_visible(timeout=1200):
            section.first.scroll_into_view_if_needed(timeout=1500)
            page.wait_for_timeout(120)
    except Exception:
        pass

    # Explicit mapping using your confirmed portal IDs:
    #   Yes -> #amortise-up-front
    #   No  -> #amortise-spread-costs
    wrapper_id = "#wrapper-amortise-up-front" if pay_upfront else "#wrapper-amortise-spread-costs"
    radio_id = "#amortise-up-front" if pay_upfront else "#amortise-spread-costs"
    other_radio_id = "#amortise-spread-costs" if pay_upfront else "#amortise-up-front"
    wanted_text = "Pay up-front circuit charge" if pay_upfront else "Pay no up-front circuit charge"
    print(f"🧭 Upfront target from CSV: {'Yes' if pay_upfront else 'No'} -> {wanted_text}")

    # Some supplier/journey combinations disable one of the upfront radios (greyed out).
    if not _nested_fallback:
        try:
            target_disabled = page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    return !!(el && el.disabled);
                }""",
                radio_id,
            )
            if target_disabled:
                print(
                    f"⚠️ Upfront '{wanted_text}' is disabled for this quote. "
                    f"Selecting the opposite option so the flow can continue."
                )
                toggle_upfront_charge(page, not pay_upfront, _nested_fallback=True)
                return
        except Exception:
            pass
    else:
        try:
            if page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    return !!(el && el.disabled);
                }""",
                radio_id,
            ):
                print("⚠️ Alternate upfront choice is also disabled; skipping upfront toggle.")
                return
        except Exception:
            pass

    # First, click the exact wrapper and verify the target radio became checked.
    for sel in [wrapper_id, radio_id]:
        try:
            el = page.locator(sel).first
            el.wait_for(state="attached", timeout=12000)
            el.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(80)
            el.click(timeout=5000, force=True)
            page.wait_for_timeout(100)
            target_radio = page.locator(radio_id).first
            if target_radio.is_checked():
                print(f"✅ Upfront toggle selected by id: {wanted_text}.")
                return
        except Exception:
            continue

    # Next, click by exact visible text and verify target radio checked.
    try:
        label_loc = page.get_by_text(re.compile(rf"^{re.escape(wanted_text)}$", re.IGNORECASE))
        if label_loc.count() > 0 and label_loc.first.is_visible(timeout=4000):
            label_loc.first.scroll_into_view_if_needed(timeout=3000)
            label_loc.first.click(timeout=5000, force=True)
            page.wait_for_timeout(100)
            if page.locator(radio_id).first.is_checked():
                print(f"✅ Upfront toggle selected by label: {wanted_text}.")
                return
    except Exception:
        pass

    # Final JS fallback: set checked directly and dispatch change/input events.
    try:
        js_ok = page.evaluate(
            """(targetSel, otherSel) => {
                const target = document.querySelector(targetSel);
                const other = document.querySelector(otherSel);
                if (!target) return false;
                if (other) other.checked = false;
                target.checked = true;
                target.dispatchEvent(new Event('input', { bubbles: true }));
                target.dispatchEvent(new Event('change', { bubbles: true }));
                const label = target.closest('label');
                if (label) label.click();
                return true;
            }""",
            radio_id,
            other_radio_id,
        )
        page.wait_for_timeout(120)
        if js_ok and page.locator(radio_id).first.is_checked():
            print(f"✅ Upfront toggle selected by JS fallback: {wanted_text}.")
            return
    except Exception:
        pass

    # Legacy wrapper IDs (some environments)
    for legacy_id in ["#wrapper-upfront-yes", "#wrapper-upfront-no"]:
        if (pay_upfront and "yes" in legacy_id) or (not pay_upfront and "no" in legacy_id):
            try:
                el = page.locator(legacy_id).first
                if el.is_visible(timeout=1500):
                    el.scroll_into_view_if_needed()
                    el.click(timeout=3000, force=True)
                    page.wait_for_timeout(300)
                    print("✅ Upfront toggle selected (wrapper).")
                    return
            except Exception:
                pass
            break

    if pay_upfront:
        maybe = page.get_by_text(re.compile(r"Pay (?!no )up-front circuit charge", re.IGNORECASE))
    else:
        maybe = page.get_by_text(re.compile(r"Pay no up-front circuit", re.IGNORECASE))

    if maybe.count() > 0 and maybe.first.is_visible():
        maybe.first.scroll_into_view_if_needed(timeout=2000)
        maybe.first.click(timeout=3000, force=True)
        page.wait_for_timeout(200)
        print("✅ Upfront toggle selected.")
    else:
        label = "Pay up-front circuit charge" if pay_upfront else "Pay no up-front circuit charge"
        radio = page.get_by_role("radio", name=re.compile(re.escape(label), re.IGNORECASE))
        if radio.count() > 0 and radio.first.is_visible(timeout=2000):
            radio.first.scroll_into_view_if_needed()
            radio.first.click(timeout=3000, force=True)
            page.wait_for_timeout(200)
            print("✅ Upfront toggle selected (radio).")
        else:
            # Quote page: try partial label match (e.g. "Pay up-front" / "Pay no up-front")
            part = "up-front" if pay_upfront else "no up-front"
            radio2 = page.get_by_role("radio").filter(has_text=re.compile(part, re.IGNORECASE))
            if radio2.count() > 0 and radio2.first.is_visible(timeout=2000):
                radio2.first.scroll_into_view_if_needed()
                radio2.first.click(timeout=3000, force=True)
                page.wait_for_timeout(200)
                print("✅ Upfront toggle selected (radio partial).")
            else:
                print("ℹ️ Upfront toggle not present here.")

def _fttp_input_id(want_yes: bool) -> str:
    return "#fttp-aggregation-yes" if want_yes else "#fttp-aggregation-no"


def _fttp_target_availability(page, want_yes: bool) -> str:
    """
    Inspect the portal's FTTP radio for the requested choice.
    Returns: 'ok' (present and enabled), 'disabled', or 'missing'.
    """
    sel = _fttp_input_id(want_yes)
    try:
        return page.evaluate(
            """(s) => {
                const el = document.querySelector(s);
                if (!el) return 'missing';
                if (el.disabled || el.getAttribute('aria-disabled') === 'true') return 'disabled';
                return 'ok';
            }""",
            sel,
        )
    except Exception:
        return "missing"


def _scroll_fttp_section_into_view(page) -> None:
    try:
        for hint in ["This connection will be used for FTTP", "FTTP Aggregation", "Adjust quote"]:
            el = page.get_by_text(re.compile(re.escape(hint), re.IGNORECASE))
            if el.count() > 0 and el.first.is_visible(timeout=2000):
                el.first.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(150)
                break
    except Exception:
        pass
    try:
        page.evaluate("window.scrollBy(0, 400)")
        page.wait_for_timeout(100)
    except Exception:
        pass


def _fttp_click_via_data_testid_stack(page, suffix: str, label_text: str, input_css: str) -> bool:
    """
    Portal markup: <div data-testid="fttp-aggregation-yes" id="wrapper-..."><label><input id="fttp-aggregation-yes" class="radioButton__input">...
    The label does NOT use for=; nested label + wrapper click is what React expects.
    """
    testid = f'[data-testid="fttp-aggregation-{suffix}"]'
    inp = page.locator(input_css)

    def _is_target_checked() -> bool:
        try:
            return inp.count() > 0 and inp.first.is_checked()
        except Exception:
            return False

    # Playwright test id + synthetic click first (matches portal e2e hooks)
    try:
        tid = page.get_by_test_id(f"fttp-aggregation-{suffix}")
        if tid.count() > 0:
            t0 = tid.first
            t0.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(80)
            try:
                t0.dispatch_event("click")
            except Exception:
                pass
            page.wait_for_timeout(120)
            if _is_target_checked():
                return True
            try:
                t0.dispatch_event("pointerdown")
                t0.dispatch_event("pointerup")
            except Exception:
                pass
            try:
                t0.click(timeout=6000, force=True)
            except Exception:
                pass
            page.wait_for_timeout(180)
            if _is_target_checked():
                return True
    except Exception:
        pass

    candidates = [
        lambda: page.locator(testid).first,
        lambda: page.locator(f"{testid} label").first,
        lambda: page.locator(f"{testid} p.radioButton__description").filter(
            has_text=re.compile(rf"^{re.escape(label_text)}$", re.IGNORECASE)
        ).first,
        lambda: page.locator(f"{testid} input.radioButton__input").first,
        lambda: page.locator(f"{testid} input[type='radio']").first,
    ]
    for get_loc in candidates:
        try:
            loc = get_loc()
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(70)
            loc.click(timeout=6000, force=True)
            page.wait_for_timeout(200)
            if _is_target_checked():
                return True
        except Exception:
            continue

    # Dispatch click on wrapper from browser (bubbles like a user tap on the card)
    try:
        page.evaluate(
            """(suffix) => {
                const w = document.querySelector('[data-testid="fttp-aggregation-' + suffix + '"]');
                if (!w) return false;
                const inp = w.querySelector('input[type="radio"]');
                if (inp && (inp.disabled || inp.getAttribute('aria-disabled') === 'true')) return false;
                w.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                return true;
            }""",
            suffix,
        )
        page.wait_for_timeout(200)
        if _is_target_checked():
            return True
    except Exception:
        pass

    # React controlled radios: sync group checked state + input/change (last resort before giving up)
    try:
        ok = page.evaluate(
            """(suffix) => {
                const el = document.querySelector('#fttp-aggregation-' + suffix);
                if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
                const name = el.name;
                if (name) {
                    const nodes = document.getElementsByName(name);
                    for (let i = 0; i < nodes.length; i++) {
                        const r = nodes[i];
                        if (r.type === 'radio') r.checked = r === el;
                    }
                } else {
                    el.checked = true;
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                return !!el.checked;
            }""",
            suffix,
        )
        page.wait_for_timeout(200)
        if ok and _is_target_checked():
            return True
    except Exception:
        pass
    return False


def toggle_fttp_aggregation(page, aggregation_yes: bool) -> bool:
    """Set FTTP Aggregation Yes/No. Staging: wrapper-fttp-aggregation-yes/no, data-testid, input id fttp-aggregation-*.
    Returns True if the requested option appears selected, False if the target control is disabled or could not be set."""
    suffix = "yes" if aggregation_yes else "no"
    label_text = "Yes" if aggregation_yes else "No"
    input_id = f"#fttp-aggregation-{suffix}"

    # Do not click disabled radios (e.g. Sky via Openreach when "Yes" is greyed out) — avoids false positives.
    avail = _fttp_target_availability(page, aggregation_yes)
    if avail == "disabled":
        return False

    _scroll_fttp_section_into_view(page)
    # Inputs can attach after recalculate / pricing; brief wait then re-check disabled
    try:
        page.wait_for_function(
            "() => document.querySelector('#fttp-aggregation-yes') || document.querySelector('#fttp-aggregation-no')",
            timeout=10000,
        )
    except Exception:
        pass
    avail2 = _fttp_target_availability(page, aggregation_yes)
    if avail2 == "disabled":
        return False

    # 1) data-testid wrapper + nested label / description / input (portal DOM; label has no for=)
    if _fttp_click_via_data_testid_stack(page, suffix, label_text, input_id):
        print(f"✅ FTTP aggregation set: {label_text.upper()} (data-testid stack)")
        return True

    # 2) Direct input click via JS (off-screen / hidden input)
    try:
        page.evaluate(
            f"""() => {{
            const el = document.querySelector('{input_id}');
            if (!el || el.disabled) return false;
            if (!el.checked) {{ el.click(); return true; }}
            return true;
        }}"""
        )
        page.wait_for_timeout(150)
        if page.locator(input_id).count() > 0 and page.locator(input_id).first.is_checked():
            print(f"✅ FTTP aggregation set: {label_text.upper()} (JS input click)")
            return True
    except Exception:
        pass

    def _try_select() -> bool:
        """Try to select FTTP option. Returns True if input ends up checked."""
        wrapper_id = f"#wrapper-fttp-aggregation-{suffix}"
        # 1) data-testid stack again (retry path)
        if _fttp_click_via_data_testid_stack(page, suffix, label_text, input_id):
            return True
        # 2) Legacy: wrapper id + inner text / label
        try:
            wrapper = page.locator(wrapper_id).first
            wrapper.wait_for(state="attached", timeout=10000)
            wrapper.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(100)
            inner = wrapper.get_by_text(label_text, exact=True)
            if inner.count() > 0:
                inner.first.click(timeout=5000, force=True)
            else:
                wrapper.locator("label").first.click(timeout=5000, force=True)
            page.wait_for_timeout(150)
            if page.locator(input_id).first.is_checked():
                return True
        except Exception:
            pass
        # 3) Click wrapper div (data-testid or id)
        for sel in [
            f"[data-testid='fttp-aggregation-{suffix}']",
            wrapper_id,
            f"{wrapper_id} label",
        ]:
            try:
                el = page.locator(sel).first
                el.wait_for(state="attached", timeout=5000)
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=5000, force=True)
                page.wait_for_timeout(150)
                if page.locator(input_id).first.is_checked():
                    return True
            except Exception:
                continue
        # 3) Check the radio input directly (may be hidden, force=True)
        try:
            inp = page.locator(input_id).first
            inp.wait_for(state="attached", timeout=5000)
            inp.scroll_into_view_if_needed(timeout=3000)
            inp.check(timeout=5000, force=True)
            page.wait_for_timeout(100)
            if inp.is_checked():
                return True
        except Exception:
            pass
        # 4) JavaScript click on the input (bypasses visibility) — never on disabled
        try:
            page.evaluate(f"""() => {{
                const el = document.querySelector('{input_id}');
                if (el && !el.disabled) {{ el.click(); return true; }}
                return false;
            }}""")
            page.wait_for_timeout(150)
            if page.locator(input_id).count() > 0 and page.locator(input_id).first.is_checked():
                return True
        except Exception:
            pass
        return False

    for attempt in range(3):
        if _try_select():
            print(f"✅ FTTP aggregation set: {label_text.upper()}")
            return True
        page.wait_for_timeout(150)

    # Fallback: radio role within section containing "FTTP"
    try:
        section = page.locator("div, section").filter(has_text=re.compile(r"FTTP Aggregation|This connection will be used for FTTP", re.IGNORECASE)).first
        if section.count() > 0 and section.first.is_visible(timeout=2000):
            section.first.scroll_into_view_if_needed(timeout=2000)
            page.wait_for_timeout(100)
            radio = section.get_by_role("radio", name=re.compile(label_text, re.IGNORECASE))
            if radio.count() > 0:
                r0 = radio.first
                try:
                    if not r0.is_enabled():
                        return False
                except Exception:
                    pass
                r0.scroll_into_view_if_needed(timeout=2000)
                r0.check(timeout=5000, force=True)
                page.wait_for_timeout(100)
                print(f"✅ FTTP aggregation set: {label_text.upper()}")
                return True
    except Exception:
        pass
    # Fallback: find any radio with "Yes"/"No" in a parent that contains "FTTP"
    try:
        radios = page.get_by_role("radio", name=re.compile(label_text, re.IGNORECASE))
        for i in range(min(radios.count(), 8)):
            r = radios.nth(i)
            try:
                ctx = r.evaluate("el => el.closest('div, section')?.innerText || ''")
                if ctx and "FTTP" in str(ctx):
                    try:
                        if not r.is_enabled():
                            continue
                    except Exception:
                        pass
                    r.scroll_into_view_if_needed(timeout=2000)
                    r.check(timeout=5000, force=True)
                    page.wait_for_timeout(100)
                    print(f"✅ FTTP aggregation set: {label_text.upper()}")
                    return True
            except Exception:
                continue
    except Exception:
        pass
    print("ℹ️ FTTP aggregation toggle not present or not clickable.")
    return False


def apply_fttp_aggregation_with_fallback(page, want_yes: bool) -> None:
    """
    Apply CSV / preset FTTP choice. Some supplier + product combinations disable 'Yes'
    (e.g. Sky via Openreach). If 'Yes' was requested but is not available, select 'No'
    and log clearly so the run can continue and order-page FTTP line reflects reality.
    """
    if not want_yes:
        toggle_fttp_aggregation(page, False)
        return

    _scroll_fttp_section_into_view(page)
    try:
        page.wait_for_function(
            "() => document.querySelector('#fttp-aggregation-yes') || document.querySelector('#fttp-aggregation-no')",
            timeout=10000,
        )
    except Exception:
        pass
    page.wait_for_timeout(400)

    yes_state = _fttp_target_availability(page, True)
    if yes_state == "disabled":
        print(
            "⚠️ FTTP Aggregation 'Yes' is disabled for this quote (supplier / journey rules). "
            "CSV asked for Yes — selecting 'No' so the flow can continue. "
            "Pick another supplier in the CSV if you must test FTTP Yes on this product."
        )
        if toggle_fttp_aggregation(page, False):
            print("✅ FTTP aggregation fallback: NO (Yes unavailable).")
        else:
            print("ℹ️ FTTP aggregation fallback: could not confirm 'No' selection.")
        return

    if toggle_fttp_aggregation(page, True):
        return
    for _ in range(4):
        page.wait_for_timeout(280)
        _scroll_fttp_section_into_view(page)
        if toggle_fttp_aggregation(page, True):
            return

    # Yes not disabled but click paths failed — do not silently fall back unless Yes is still not checked
    try:
        y = page.locator("#fttp-aggregation-yes")
        if y.count() > 0 and y.first.is_checked():
            return
    except Exception:
        pass

    if yes_state == "missing":
        print("ℹ️ FTTP 'Yes' control not found; portal may omit FTTP for this journey.")
    else:
        print("⚠️ Could not set FTTP to Yes; attempting 'No' so Proceed to order can enable.")
    toggle_fttp_aggregation(page, False)

def adjust_quote_discounts(page, install_discount: str, annual_discount: str) -> None:
    """
    On the quote page (Adjust quote section): set Install Discount and Annual Discount, then Recalculate.
    Values should be numeric only (e.g. '200', '0', '150.50') — no £ symbol.
    Clears the existing value (e.g. '0') before filling so typing '200' does not become '2000'.
    """
    install_val = (install_discount or "").strip().replace(",", "").lstrip("£") or "0"
    annual_val = (annual_discount or "").strip().replace(",", "").lstrip("£") or "0"

    install_loc = page.locator("#add__installDiscountinstallDiscount")
    annual_loc = page.locator("#add__annualDiscountannualDiscount")

    install_loc.wait_for(state="visible", timeout=10000)
    install_loc.scroll_into_view_if_needed()
    install_loc.click()
    install_loc.fill("")  # clear existing "0" so fill doesn't append
    install_loc.fill(install_val)

    annual_loc.wait_for(state="visible", timeout=10000)
    annual_loc.scroll_into_view_if_needed()
    annual_loc.click()
    annual_loc.fill("")
    annual_loc.fill(annual_val)

    recalc = page.get_by_role("button", name=re.compile(r"^Recalculate$", re.IGNORECASE))
    recalc.first.wait_for(state="visible", timeout=5000)
    recalc.first.scroll_into_view_if_needed()
    recalc.first.click()
    page.wait_for_timeout(800)  # let UI update after recalculate


def _parse_price(s) -> float:
    """Parse price string to float; strip £ and commas. Returns 0.0 if invalid."""
    if s is None:
        return 0.0
    t = str(s).strip().replace(",", "").lstrip("£").strip()
    if not t:
        return 0.0
    try:
        return float(t)
    except ValueError:
        return 0.0


def _scrape_list_prices_from_quote_page(page) -> tuple[str, str]:
    """Scrape Install and Annual list prices from quote page body (e.g. 'Install £4,072.00'). Returns (install_str, annual_str)."""
    try:
        body = page.evaluate("() => document.body ? (document.body.innerText || '') : ''") or ""
        body = str(body)
        install_m = re.search(r"Install\s*£\s*([0-9,]+\.\d{2})", body, re.IGNORECASE)
        annual_m = re.search(r"Annual\s*£\s*([0-9,]+\.\d{2})", body, re.IGNORECASE)
        install_str = (install_m.group(1).replace(",", "") if install_m else "") or ""
        annual_str = (annual_m.group(1).replace(",", "") if annual_m else "") or ""
        return (install_str, annual_str)
    except Exception:
        return ("", "")


def _wait_for_updating_overlay_gone(page, timeout_ms: int = 3000) -> None:
    """
    Wait for the quote page 'Updating...' overlay to disappear (max timeout_ms).
    Fast check (200ms) if overlay is present; only then wait for hidden.
    """
    try:
        updating = page.get_by_text(re.compile(r"Updating\.\.\.?", re.IGNORECASE))
        if updating.count() > 0 and updating.first.is_visible(timeout=200):
            updating.first.wait_for(state="hidden", timeout=timeout_ms)
    except Exception:
        pass


_PRICING_READY_JS = """() => {
    if (document.querySelector('[data-testid="price-tile"]')) return true;
    if (document.querySelector('button[data-testid="price-tile"]')) return true;
    if (document.querySelector('.slick-track [data-testid="price-tile"]')) return true;
    if (document.querySelector('img.supplier_image')) return true;
    if (document.querySelector('[class*="supplier_image"]')) return true;
    if (document.querySelector('#wrapper-amortise-up-front')) return true;
    if (document.querySelector('#wrapper-amortise-spread-costs')) return true;
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
    if (/Amounts shown are representative/i.test(bodyText)) return true;
    if (/Adjust\\s+quote/i.test(bodyText)) return true;
    if (/FTTP\\s+Aggregation/i.test(bodyText)) return true;
    if (/This connection will be used for FTTP/i.test(bodyText)) return true;
    const buttons = document.querySelectorAll('button');
    for (const b of buttons) {
        const text = (b.innerText || '').trim();
        if (/^Publish(\\s+quote)?$/i.test(text)) return true;
        if (b.getAttribute('data-testid') === 'proceed to order button') return true;
        if (/Proceed to order/i.test(text)) return true;
    }
    return false;
}"""


def _wait_for_pricing_ui_ready(page, timeout_ms: int) -> None:
    """
    After Get price: wait until pricing / quote-adjustment UI is present.
    Uses wait_for_function with tight in-page polling (avoids slow Python evaluate loops).
    """
    _wait_for_updating_overlay_gone(page, timeout_ms=min(timeout_ms, 15000))
    t0 = time.perf_counter()
    try:
        page.wait_for_function(_PRICING_READY_JS, timeout=timeout_ms, polling=75)
    except PWTimeoutError as e:
        raise RuntimeError("Pricing UI readiness signals not detected in time.") from e
    elapsed = time.perf_counter() - t0
    if elapsed > 0.5:
        print(f"✅ Pricing UI ready ({elapsed:.1f}s).")
    else:
        print("✅ Pricing UI ready.")


def _login_internal_neos(page, base_url: str, creds: dict) -> bool:
    """Log in as NEOS internal user. Returns True on success."""
    print("🔐 Logging in as NEOS internal user…")
    page.goto(f"{base_url.rstrip('/')}/login", wait_until="domcontentloaded", timeout=60000)
    candidates_email = [
        page.get_by_label("Email"),
        page.get_by_label(re.compile("email", re.IGNORECASE)),
        page.get_by_placeholder(re.compile("email", re.IGNORECASE)),
        page.get_by_label("Username"),
        page.get_by_label(re.compile("username", re.IGNORECASE)),
        page.locator("input[type='email']"),
        page.locator("input[name*='email' i]"),
        page.locator("input[name*='username' i]"),
    ]
    email_box = None
    for c in candidates_email:
        try:
            if c.count() > 0 and c.first.is_visible(timeout=2000):
                email_box = c.first
                break
        except Exception:
            continue
    candidates_pass = [
        page.get_by_label("Password"),
        page.get_by_placeholder(re.compile("password", re.IGNORECASE)),
        page.locator("input[type='password']"),
        page.locator("input[name*='password' i]"),
    ]
    pass_box = None
    for c in candidates_pass:
        try:
            if c.count() > 0 and c.first.is_visible(timeout=2000):
                pass_box = c.first
                break
        except Exception:
            continue
    if not email_box or not pass_box:
        print("⚠️ Could not find email/password fields on login page.")
        return False
    email_box.fill(creds["email"])
    pass_box.fill(creds["password"])
    btn = None
    for b in [
        page.get_by_role("button", name=re.compile("sign in", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile("log in|login", re.IGNORECASE)),
        page.get_by_role("button"),
    ]:
        try:
            if b.count() > 0 and b.first.is_visible(timeout=5000):
                btn = b.first
                break
        except Exception:
            continue
    if not btn:
        print("⚠️ Could not find Sign in button.")
        return False
    btn.click()
    try:
        page.wait_for_url(re.compile(r"/orders|/welcome|/dashboard"), timeout=60000)
    except Exception:
        pass
    print(f"✅ Logged in as internal user. URL: {page.url}")
    return True


def _login_customer_page(page, base_url: str, creds: dict) -> bool:
    """Log in as customer (username/email + password). Returns True if login succeeded (no longer on /login)."""
    login_url = base_url.rstrip("/") + "/login"
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass
    if "/login" not in (page.url or ""):
        return True
    email = (creds.get("email") or creds.get("username") or "").strip()
    password = (creds.get("password") or "").strip()
    if not email or not password:
        return False
    try:
        # Portal login forms vary: try multiple selectors for email/username + password.
        candidates_email = [
            page.get_by_label("Email address"),
            page.get_by_label(re.compile(r"Username|Email", re.IGNORECASE)),
            page.get_by_label(re.compile(r"email", re.IGNORECASE)),
            page.get_by_placeholder(re.compile(r"email|username", re.IGNORECASE)),
            page.locator("input[type='email']"),
            page.locator("input[name*='email' i]"),
            page.locator("input[name*='username' i]"),
        ]
        email_box = None
        for c in candidates_email:
            try:
                if c.count() > 0 and c.first.is_visible(timeout=2000):
                    email_box = c.first
                    break
            except Exception:
                continue

        candidates_pass = [
            page.get_by_label("Password"),
            page.get_by_placeholder(re.compile(r"password", re.IGNORECASE)),
            page.locator("input[type='password']"),
            page.locator("input[name*='password' i]"),
        ]
        pass_box = None
        for c in candidates_pass:
            try:
                if c.count() > 0 and c.first.is_visible(timeout=2000):
                    pass_box = c.first
                    break
            except Exception:
                continue

        # Final fallback: grab the first visible non-password input and the password input.
        if not email_box:
            try:
                fallback_email = page.locator("input[type='email'], input[type='text']").first
                if fallback_email.count() > 0 and fallback_email.is_visible(timeout=2000):
                    email_box = fallback_email
            except Exception:
                pass
        if not pass_box:
            try:
                fallback_pass = page.locator("input[type='password']").first
                if fallback_pass.count() > 0 and fallback_pass.is_visible(timeout=2000):
                    pass_box = fallback_pass
            except Exception:
                pass

        if not email_box or not pass_box:
            print("⚠️ Could not find customer email/password fields on login page.")
            return False

        email_box.wait_for(state="visible", timeout=8000)
        pass_box.wait_for(state="visible", timeout=8000)
        try:
            email_box.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            pass_box.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        email_box.fill(email)
        pass_box.fill(password)
        page.wait_for_timeout(300)

        # Try the most likely sign-in buttons.
        sign_in_btn = page.get_by_role("button", name=re.compile(r"Sign in|Log in|Login", re.IGNORECASE)).first
        if sign_in_btn.count() == 0:
            sign_in_btn = page.get_by_role("button", name=re.compile(r"sign in", re.IGNORECASE)).first
        if sign_in_btn.count() == 0:
            # Fallback: any visible button that contains "Sign in" text.
            btns = page.locator("button").filter(has_text=re.compile(r"sign in|log in|login", re.IGNORECASE))
            if btns.count() > 0:
                sign_in_btn = btns.first
        sign_in_btn.click(timeout=5000)
        try:
            page.wait_for_url(re.compile(r"/welcome|/orders|/dashboard"), timeout=25000)
        except Exception:
            page.wait_for_timeout(3000)
        if "/login" not in (page.url or ""):
            print("✅ Logged in as customer.")
            return True
    except Exception as e:
        print(f"ℹ️ Customer login attempt: {e}")
    return False


def _logout_portal(page) -> None:
    """Sign out from portal: user menu → Sign out, confirm if needed."""
    try:
        # Try avatar / user menu then "Sign out"
        sign_out = page.get_by_role("link", name=re.compile(r"Sign out", re.IGNORECASE))
        if sign_out.count() > 0 and sign_out.first.is_visible(timeout=3000):
            sign_out.first.click()
            page.wait_for_timeout(1500)
            ok_btn = page.get_by_role("button", name=re.compile(r"^OK$|Sign out", re.IGNORECASE))
            if ok_btn.count() > 0 and ok_btn.first.is_visible(timeout=2000):
                ok_btn.first.click()
            print("✅ Signed out.")
            return
        btn = page.get_by_role("button", name=re.compile(r"Sign out", re.IGNORECASE))
        if btn.count() > 0 and btn.first.is_visible(timeout=2000):
            btn.first.click()
            page.wait_for_timeout(1000)
            print("✅ Signed out.")
    except Exception as e:
        print(f"ℹ️ Logout attempt: {e}")


def publish_and_proceed_to_order(page):
    # Customer flow (Demo 1): Proceed to order is already on screen — click it immediately if visible & enabled.
    # Employee flow: Publish first, then Proceed to order.
    def _click_proceed_if_ready(timeout_ms: int) -> bool:
        proceed_btn = page.get_by_test_id("proceed to order button")
        if proceed_btn.count() == 0:
            proceed_btn = page.get_by_role("button", name=re.compile(r"Proceed to order", re.IGNORECASE))
        if proceed_btn.count() == 0:
            return False
        try:
            proceed_btn.first.wait_for(state="visible", timeout=timeout_ms)
            expect(proceed_btn.first).to_be_enabled(timeout=timeout_ms)
            proceed_btn.first.scroll_into_view_if_needed()
            proceed_btn.first.click()
            return True
        except Exception:
            return False

    if _click_proceed_if_ready(200):
        print("✅ Proceed to order clicked (already on screen).")
        return

    # Proceed not ready yet — try Publish (employee flow) then wait for Proceed
    pub_all = page.get_by_role("button", name=re.compile(r"^Publish(\s+quote)?$", re.IGNORECASE))
    try:
        if pub_all.count() == 0:
            pub_all = page.locator(
                "button.publish_btn_bottom, "
                "button.publish_btn_top, "
                "button.publish_btn, "
                "button.primaryOutline:has-text('Publish')"
            )
        if pub_all.count() == 0:
            raise RuntimeError("Publish button not found via role or CSS locators")

        pub_all.first.wait_for(state="attached", timeout=3000)
        print("🟧 Clicking Publish (employee flow)...")
        clicked = False
        max_candidates = min(pub_all.count(), 6)
        for i in range(max_candidates):
            try:
                b = pub_all.nth(i)
                if not b.is_visible(timeout=400):
                    continue
                b.scroll_into_view_if_needed(timeout=1000)
                page.wait_for_timeout(50)
                b.click()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            pub_all.first.scroll_into_view_if_needed(timeout=1000)
            page.wait_for_timeout(50)
            pub_all.first.click()
            page.wait_for_timeout(150)
    except Exception as e:
        print(f"ℹ️ No Publish button (customer flow or locator mismatch); going straight to Proceed to order. {e}")

    print("➡️ Clicking Proceed to order...")
    proceed_btn = page.get_by_test_id("proceed to order button")
    try:
        click_when_enabled(proceed_btn, timeout_ms=60000)  # 60s for employee flow (FTTP/recalc can be slow)
    except PWTimeoutError:
        fallback = page.get_by_role("button", name=re.compile(r"Proceed to order", re.IGNORECASE))
        if fallback.count() > 0:
            click_when_enabled(fallback, timeout_ms=30000)
        else:
            raise
    print("✅ Proceed to order clicked.")

# =========================================================
# Billing helpers (unchanged from your working version)
# =========================================================
def safe_wait_visible(locator, timeout_ms: int = 15000):
    locator.wait_for(state="visible", timeout=timeout_ms)

def safe_fill_textbox(locator, value: str, timeout_ms: int = 15000, verify: bool = True):
    safe_wait_visible(locator, timeout_ms=timeout_ms)
    locator.scroll_into_view_if_needed()
    locator.click()
    try:
        locator.fill("")
    except Exception:
        pass
    locator.fill(value)
    if verify:
        try:
            current = locator.input_value()
            if str(current).strip() != str(value).strip():
                locator.fill(value)
        except Exception:
            pass

def click_nth_visible_option(page, index: int, timeout_ms: int = 15000):
    options = page.get_by_role("option")
    options.first.wait_for(state="visible", timeout=timeout_ms)
    visible = []
    count = options.count()
    for i in range(count):
        opt = options.nth(i)
        try:
            if opt.is_visible():
                visible.append(opt)
        except Exception:
            continue
    if len(visible) <= index:
        raise RuntimeError(f"Dropdown opened, but only {len(visible)} option(s) visible; needed index {index}.")
    visible[index].click()

def open_dropdown_and_pick(page, combobox, option_index: int, timeout_ms: int = 15000):
    combobox.scroll_into_view_if_needed()
    combobox.click()
    click_nth_visible_option(page, index=option_index, timeout_ms=timeout_ms)


def fill_manual_address_fallback(page, b_end_card, billing: dict, postcode: str | None = None):
    """
    Only when 'Unable to fetch addresses' is visible: fill manual address fields as backup.
    Uses billing keys: address_building_number, address_street, address_town, address_county, address_postcode.
    Defaults are SP2 8NJ / Salisbury area (Montague Road) when not set in billing.
    """
    err = page.get_by_text("Unable to fetch addresses", exact=False)
    if err.count() == 0 or not err.first.is_visible(timeout=500):
        return False
    postcode = postcode or billing.get("address_postcode") or "SP2 8NJ"
    # Postcode-aware defaults (Salisbury / SP2 8NJ area)
    defaults = {
        "address_building_number": "1",
        "address_street": "Montague Road",
        "address_town": "Salisbury",
        "address_county": "Wiltshire",
        "address_postcode": postcode,
    }
    page.wait_for_timeout(250)
    filled_any = False
    for label_pattern, key in [
        (re.compile(r"^Building number\s*\*?$", re.IGNORECASE), "address_building_number"),
        (re.compile(r"^Building name\s*\*?$", re.IGNORECASE), "address_building_name"),
        (re.compile(r"^Street\s*\*$", re.IGNORECASE), "address_street"),
        (re.compile(r"^Town/city\s*\*$", re.IGNORECASE), "address_town"),
        (re.compile(r"^County\s*\*$", re.IGNORECASE), "address_county"),
        (re.compile(r"^Postcode\s*\*$", re.IGNORECASE), "address_postcode"),
    ]:
        val = billing.get(key) or defaults.get(key)
        if not val and key == "address_building_name":
            continue
        if not val and key == "address_building_number":
            val = defaults["address_building_number"]
        if not val:
            continue
        try:
            tb = b_end_card.get_by_label(label_pattern)
            if tb.count() == 0:
                tb = page.get_by_label(label_pattern)
            if tb.count() > 0 and tb.first.is_visible(timeout=500):
                safe_fill_textbox(tb.first, str(val), timeout_ms=5000)
                filled_any = True
        except Exception:
            pass
    if filled_any:
        print("✅ Manual address filled (Unable to fetch addresses fallback).")
    return filled_any


def select_b_end_address_dropdown(page, b_end_card, max_retries: int = 3):
    """
    Select the FIRST option from the B-End 'Choose location' dropdown.
    Tries test-id locator first (bEndLocation-addresses__wrapper), then placeholder, then combobox near Address label.
    Scopes option click to the open listbox so we don't pick an option from another dropdown.
    """
    page.wait_for_timeout(400)  # Let address dropdown/API populate before opening
    for attempt in range(max_retries):
        try:
            choose_trigger = None
            if b_end_card.get_by_test_id("bEndLocation-addresses__wrapper").count() > 0:
                w = b_end_card.get_by_test_id("bEndLocation-addresses__wrapper").first
                combobox = w.get_by_role("combobox")
                inp = w.locator("input")
                if combobox.count() > 0:
                    choose_trigger = combobox.first
                elif inp.count() > 0:
                    choose_trigger = inp.first
                else:
                    choose_trigger = w
            if choose_trigger is None:
                placeholders = b_end_card.get_by_placeholder(re.compile(r"Choose location", re.IGNORECASE))
                if placeholders.count() > 0:
                    choose_trigger = placeholders.first
            if choose_trigger is None:
                choose_trigger = find_combobox_near_label(
                    b_end_card, re.compile(r"^Address\s*\*$", re.IGNORECASE), which_combobox=0
                )

            choose_trigger.wait_for(state="visible", timeout=8000)
            choose_trigger.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(200)
            choose_trigger.click(timeout=3000)
            # Longer wait for options on later retries (address API can be slow)
            page.wait_for_timeout(350 if attempt == 0 else 550)

            # Prefer option inside the visible listbox so we don't pick from another dropdown
            clicked = False
            try:
                listbox = page.locator("[role='listbox']").filter(has=page.locator("[role='option']")).first
                listbox.wait_for(state="visible", timeout=6000)
                opt = listbox.get_by_role("option").first
                opt.wait_for(state="visible", timeout=4000)
                opt.click(timeout=3000)
                clicked = True
            except Exception:
                pass
            if not clicked:
                try:
                    first_option = page.get_by_role("option").first
                    first_option.wait_for(state="visible", timeout=5000)
                    first_option.click(timeout=3000)
                    clicked = True
                except Exception:
                    pass
            if not clicked:
                try:
                    click_nth_visible_option(page, index=0, timeout_ms=5000)
                    clicked = True
                except Exception:
                    opts = page.locator("[role='option'], [data-option]")
                    if opts.count() > 0:
                        opts.first.click(timeout=3000)
                        clicked = True
                    else:
                        raise
            page.wait_for_timeout(250)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"⚠️ Address dropdown attempt {attempt + 1} failed. Retrying...")
                page.wait_for_timeout(500)
            else:
                print(f"⚠️ Could not select Choose location ({e}). Continuing without it.")
                return False

def find_card_by_marker_text(page, marker_regex: re.Pattern):
    card = page.locator("section, div, article").filter(has_text=marker_regex).first
    safe_wait_visible(card, timeout_ms=20000)
    return card

def find_section_by_heading_text(page, heading_regex: re.Pattern, timeout_ms: int = 20000):
    heading = page.get_by_text(heading_regex).first
    heading.wait_for(state="visible", timeout=timeout_ms)
    heading.scroll_into_view_if_needed(timeout=timeout_ms)
    container = heading.locator("xpath=..")
    for _ in range(10):
        sec = container.locator("xpath=ancestor::section[1]")
        if sec.count() > 0:
            return sec.first
        container = container.locator("xpath=..")
    return heading.locator("xpath=..")

def find_combobox_near_label(container, label_regex: re.Pattern, which_combobox: int = 0, timeout_ms: int = 20000):
    label = container.get_by_text(label_regex).first
    label.wait_for(state="visible", timeout=timeout_ms)
    label.scroll_into_view_if_needed(timeout=timeout_ms)
    scope = label.locator("xpath=..")
    for _ in range(10):
        comboboxes = scope.locator('[role="combobox"]')
        if comboboxes.count() > 0:
            if which_combobox >= comboboxes.count():
                raise RuntimeError(
                    f"Found {comboboxes.count()} combobox(es) near label, but requested {which_combobox}."
                )
            return comboboxes.nth(which_combobox)
        scope = scope.locator("xpath=..")
    raise RuntimeError("Could not find any role='combobox' near the label. DOM may have changed.")

def _select_add_floor_or_room_via_click(page, site_config_section, field_name: str, max_retries: int = 3):
    """
    When UI shows '* Add floor' / '* Add room', click it to open dropdown then select first option.
    Tries multiple selection methods (option, listbox, click_nth) for different UI structures.
    """
    add_pattern = re.compile(rf"Add\s+{re.escape(field_name.lower())}", re.IGNORECASE)
    t = 1500  # regression stability
    for attempt in range(max_retries):
        try:
            add_el = site_config_section.get_by_text(add_pattern).first
            add_el.wait_for(state="visible", timeout=t)
            add_el.scroll_into_view_if_needed(timeout=t)
            add_el.click(timeout=t)
            page.wait_for_timeout(100)

            try:
                options = page.get_by_role("option")
                options.first.wait_for(state="visible", timeout=t)
                options.nth(1).click(timeout=t)
            except Exception:
                try:
                    listbox = page.locator("[role='listbox']").first
                    listbox.wait_for(state="visible", timeout=t)
                    listbox.get_by_role("option").nth(1).click(timeout=t)
                except Exception:
                    click_nth_visible_option(page, index=1, timeout_ms=t)
            page.wait_for_timeout(80)
            print(f"✅ {field_name} selected (Add -> 2nd option).")
            return True
        except Exception:
            pass
        if attempt < max_retries - 1:
            page.wait_for_timeout(100)
    return False

def _select_floor_or_room_via_keyboard(page, site_config_section, field_name: str, timeout_ms: int = 3000) -> bool:
    """
    Use get_by_label + keyboard (ArrowDown, Enter). Avoids waiting for option elements.
    """
    try:
        trigger = page.get_by_label(re.compile(rf"^{re.escape(field_name)}\s*\*$", re.IGNORECASE)).first
        trigger.wait_for(state="visible", timeout=timeout_ms)
        trigger.scroll_into_view_if_needed(timeout=timeout_ms)
        trigger.click(timeout=timeout_ms)
        page.wait_for_timeout(80)
        trigger.press("ArrowDown")  # open / go to first
        page.wait_for_timeout(40)
        trigger.press("ArrowDown")  # go to 2nd option
        page.wait_for_timeout(30)
        trigger.press("Enter")
        page.wait_for_timeout(50)
        print(f"✅ {field_name} selected (keyboard).")
        return True
    except Exception:
        return False

def _select_floor_or_room_via_coords_dropdown(page, site_config_section, field_name: str, timeout_ms: int = 3000) -> bool:
    """
    Use .coords-dropdown locators for Floor/Room dropdowns (from inspector).
    Floor = first .coords-dropdown, Room = second.
    Locators: .row.mb-2 > div > .coords-dropdown > .css-13cymwt-control > ... > div:nth-child(3)
    """
    index = 0 if field_name.lower() == "floor" else 1
    try:
        dropdowns = site_config_section.locator(".coords-dropdown")
        if dropdowns.count() <= index:
            return False
        box = dropdowns.nth(index)
        # Try control first, then container (single attempt each)
        for selector in [".css-13cymwt-control", ""]:
            trigger = box.locator(selector).first if selector else box
            try:
                trigger.wait_for(state="visible", timeout=timeout_ms)
                trigger.scroll_into_view_if_needed(timeout=timeout_ms)
                trigger.click(timeout=timeout_ms)
                break
            except Exception:
                continue
        else:
            return False
        page.wait_for_timeout(100)

        try:
            options = page.get_by_role("option")
            options.first.wait_for(state="visible", timeout=timeout_ms)
            options.nth(1).click(timeout=timeout_ms)
        except Exception:
            try:
                listbox = page.locator("[role='listbox']").first
                listbox.wait_for(state="visible", timeout=timeout_ms)
                listbox.get_by_role("option").nth(1).click(timeout=timeout_ms)
            except Exception:
                click_nth_visible_option(page, index=1, timeout_ms=timeout_ms)
        page.wait_for_timeout(50)
        print(f"✅ {field_name} selected (coords-dropdown).")
        return True
    except Exception:
        return False

def handle_floor_or_room(site_config_section, page, field_name: str, fallback_value: str, label_timeout_ms: int = 5000):
    label_regex = re.compile(rf"^{re.escape(field_name)}\s*\*$", re.IGNORECASE)

    # Path 1: Textbox (Preset 2 / some journeys have Floor/Room as text inputs, not dropdowns)
    for scope in [page, site_config_section]:
        try:
            tb = scope.get_by_role("textbox", name=re.compile(rf"^{re.escape(field_name)}\s*\*$", re.IGNORECASE)).first
            tb.wait_for(state="visible", timeout=250)  # fast fail for dropdown presets
            safe_fill_textbox(tb, fallback_value)
            print(f"✅ {field_name} filled as textbox.")
            return
        except Exception:
            pass

    # Path 2: Combobox — try to select option matching fallback_value (e.g. "002 - 2nd Floor")
    for attempt in range(1):  # single attempt to avoid retry delay
        try:
            combobox = find_combobox_near_label(site_config_section, label_regex, which_combobox=0, timeout_ms=label_timeout_ms)
            combobox.scroll_into_view_if_needed(timeout=label_timeout_ms)
            combobox.click(timeout=label_timeout_ms)
            page.wait_for_timeout(200)

            options = page.get_by_role("option")
            if options.count() == 0:
                options = page.locator("[role='listbox']").first.get_by_role("option")
            options.first.wait_for(state="visible", timeout=label_timeout_ms)

            target = str(fallback_value).strip()
            target_lower = target.lower()
            # Try to find and click option matching fallback_value (e.g. "002 - 2nd Floor", "CNTL - Control Room")
            for i in range(options.count()):
                try:
                    opt_text = options.nth(i).inner_text(timeout=500).strip()
                    if target_lower in opt_text.lower() or opt_text.lower() in target_lower:
                        options.nth(i).click(timeout=3000)
                        page.wait_for_timeout(100)
                        print(f"✅ {field_name} selected: {target}")
                        return
                except Exception:
                    continue
            # Fallback: click 2nd option if no match (legacy behaviour)
            if options.count() > 1:
                options.nth(1).click(timeout=3000)
            else:
                options.first.click(timeout=3000)
            page.wait_for_timeout(100)
            print(f"✅ {field_name} selected from dropdown.")
            return
        except Exception:
            pass
        page.wait_for_timeout(1)

    # Path 4: Label + following input
    try:
        label = site_config_section.get_by_text(label_regex).first
        safe_wait_visible(label, timeout_ms=250)
        possible_input = label.locator("xpath=following::input[1]")
        if possible_input.count() > 0:
            safe_fill_textbox(possible_input, fallback_value, verify=False)
            print(f"✅ {field_name} filled via label fallback.")
            return
    except Exception:
        pass

    print(f"⚠️ Could not fill {field_name}; skipping.")


def _radio_by_accessible_name(scope, name: str):
    """
    Resolve radio by accessible name. Playwright encodes regex names as /pattern/flags; a '/' inside the
    pattern (e.g. 'N/A') terminates the pattern early and raises InvalidSelectorError — avoid regex for those.
    """
    if not str(name).strip():
        return scope.locator("#__p2nni_empty_radio_name__")
    if "/" not in name:
        return scope.get_by_role("radio", name=re.compile(re.escape(name), re.IGNORECASE))
    for cand in (name, name.upper(), name.lower()):
        loc = scope.get_by_role("radio", name=cand, exact=True)
        if loc.count() > 0:
            return loc
    if name.replace(" ", "").lower() == "n/a":
        for spaced in ("N / A", "n / a"):
            loc = scope.get_by_role("radio", name=spaced, exact=True)
            if loc.count() > 0:
                return loc
    return scope.get_by_role("radio", name=name, exact=True)


def _click_radio_by_id(page, base_id: str, value_suffix: str, fallback_role_name: str = None):
    """
    Click a custom-styled radio. Prefer wrapper (#wrapper-{base_id}_{suffix}) as it's the visible element;
    fall back to input (#{base_id}_{suffix}) or role/name.
    """
    full_suffix = f"{base_id}_{value_suffix}"
    for selector in [f"#wrapper-{full_suffix}", f"#{full_suffix}", f"label[for='{full_suffix}']"]:
        el = page.locator(selector)
        if el.count() > 0:
            try:
                el.first.scroll_into_view_if_needed(timeout=3000)
                if el.first.is_visible(timeout=1500):
                    el.first.click(timeout=3000)
                    page.wait_for_timeout(200)
                    return True
            except Exception:
                pass
    if fallback_role_name:
        el = _radio_by_accessible_name(page, str(fallback_role_name))
        if el.count() > 0:
            try:
                el.first.scroll_into_view_if_needed(timeout=3000)
                el.first.click(timeout=3000)
                page.wait_for_timeout(200)
                return True
            except Exception:
                pass
    return False


def _coerce_b_end_media_to_tx_if_needed(page, preferred_mt: str) -> None:
    """If Single Mode radios did not stick, select TX when offered (1G/500–100 journeys only).

    Never fall back to TX when the CSV/preset asked for **multi mode** (SR/SX): that forces RJ45+TX
    in the portal and overwrites a correct LC+Multi selection.
    """
    if preferred_mt == "TX":
        return
    pref = (preferred_mt or "").strip().upper()
    if pref in ("SR", "SX") or "MULTI" in pref:
        return
    try:
        for _ in range(4):
            ok = page.evaluate(
                """() => {
                    const ids = ['bEndLocation_mediaType_LR','bEndLocation_mediaType_LX','bEndLocation_mediaType_SR',
                      'bEndLocation_mediaType_SX','bEndLocation_mediaType_TX','bEndLocation_mediaType_tx'];
                    for (const id of ids) {
                        const el = document.querySelector('#' + id);
                        if (el && el.checked) return true;
                    }
                    const any = document.querySelector('[id^="bEndLocation_mediaType_"]:checked');
                    return !!any;
                }"""
            )
            if ok:
                return
            page.wait_for_timeout(220)
    except Exception:
        pass
    if _click_radio_by_id(page, "bEndLocation_mediaType", "TX", fallback_role_name="TX"):
        print("ℹ️ Media type: selected TX (portal/journey did not keep Single/Multi Mode).")


def _b_end_connector_checked_suffix(page) -> str | None:
    """Return LC/SC/RJ45 for whichever bEndLocation_connectorType radio is checked, else None."""
    try:
        return page.evaluate(
            """() => {
                for (const suf of ['LC','SC','RJ45']) {
                    const el = document.querySelector('#bEndLocation_connectorType_' + suf);
                    if (el && el.checked) return suf;
                }
                return null;
            }"""
        )
    except Exception:
        return None


def _reassert_connector_after_media(page, site_config: dict) -> None:
    """Portal sometimes flips connector (e.g. LC→RJ45) after media/TX coercion; restore CSV intent."""
    mt_preset = str(site_config.get("media_type", "LR") or "LR").upper()
    if mt_preset == "TX":
        # RJ45+TX can be required (e.g. 1G/500–100, 100M); do not fight the portal.
        return
    want = str(site_config.get("connector_type", "LC") or "LC").upper()
    if want not in ("LC", "SC", "RJ45"):
        return
    got = _b_end_connector_checked_suffix(page)
    if got == want:
        return
    if got is not None and got != want:
        print(f"ℹ️ Connector was {got} after media step; re-applying {want} from preset.")
        _click_radio_by_id(page, "bEndLocation_connectorType", want, fallback_role_name=want)
        page.wait_for_timeout(250)


def _apply_building_prior_and_asbestos(page, site_config: dict) -> None:
    """Tick building pre-2000 when Yes; always align asbestos (N/A when building is not pre-2000)."""
    prior = bool(site_config.get("building_built_prior_2000", False))
    cb_id = "bEndLocation_buildingBuiltPriorTo2000"
    try:
        cb = page.locator(f"#{cb_id}")
        if cb.count() == 0:
            cb = page.get_by_test_id(cb_id)
        if cb.count() > 0 and cb.first.is_visible(timeout=1200):
            try:
                is_on = cb.first.is_checked()
            except Exception:
                is_on = False
            if prior and not is_on:
                cb.first.click(timeout=3000)
                page.wait_for_timeout(280)
            elif not prior and is_on:
                cb.first.click(timeout=3000)
                page.wait_for_timeout(200)
    except Exception:
        pass

    if prior:
        asbestos = bool(site_config.get("asbestos_register", False))
        ar_suffix = "yes" if asbestos else "no"
        _click_radio_by_id(
            page,
            "bEndLocation_asbestosRegister",
            ar_suffix,
            fallback_role_name="Yes" if asbestos else "No",
        )
        return

    for suffix in ("na", "n_a", "notApplicable", "not_applicable", "notapplicable"):
        if _click_radio_by_id(page, "bEndLocation_asbestosRegister", suffix, fallback_role_name="N/A"):
            print("✅ Asbestos register set to N/A (building not pre-2000).")
            return
    try:
        block = page.locator("div, section").filter(
            has_text=re.compile(r"asbestos register", re.IGNORECASE)
        )
        if block.count() > 0:
            na = None
            for label in ("N/A", "n/a", "N / A", "n / a"):
                cand = block.first.get_by_role("radio", name=label, exact=True)
                if cand.count() > 0:
                    na = cand
                    break
            if na is not None:
                na.first.scroll_into_view_if_needed(timeout=3000)
                na.first.click(timeout=3000)
                page.wait_for_timeout(180)
                print("✅ Asbestos register set to N/A (role).")
                return
    except Exception:
        pass
    print("ℹ️ Could not confirm Asbestos N/A — check portal if the field stays visible.")


def _fill_site_config_toggles(page, b_end_card, site_config: dict, billing: dict, bearer: str = "", bandwidth: str = ""):
    """
    Fill connector type, power supply, media type, VLAN tagging (+ VLAN ID if yes),
    site readiness (0-48 / Over 48 hours), auto negotiation (1 Gbps only), and 4 site-option checkboxes.
    Uses wrapper divs (#wrapper-bEndLocation_*) as primary click targets for custom-styled radios.
    site_config: connector_type (LC|SC|RJ45), power_supply (AC|DC), media_type (LR|SR|TX),
                 auto_negotiation (bool, 1 Gbps bearer+bandwidth only), vlan_tagging (bool),
                 access_notice (0-48|Over 48), more_than_one_tenant, building_built_prior_2000,
                 asbestos_register (bool, when building_built_prior_2000), hazards_on_site,
                 hazards_description (str, when hazards_on_site), land_owner_permission_required.
    """
    if not site_config:
        return
    page.wait_for_timeout(300)

    # Connector type: LC, SC, or RJ45
    ct = str(site_config.get("connector_type", "LC")).upper()
    if ct in ("LC", "SC", "RJ45"):
        _click_radio_by_id(page, "bEndLocation_connectorType", ct, fallback_role_name=ct)

    # Power supply: AC or DC
    ps = site_config.get("power_supply", "AC")
    if ps.upper() in ("AC", "DC"):
        _click_radio_by_id(page, "bEndLocation_powerType", ps.upper(), fallback_role_name=ps)

    # Media type: CSV uses LR/SR/TX. Portal: 10G bearer = Single Mode (LR); 1G/100M = Single Mode (LX).
    def _try_media_type_single_mode() -> bool:
        for suffix, role in [
            ("LR", "Single Mode (LR)"),  # 10G bearer
            ("LX", "Single Mode (LX)"), ("LX", "Single Mode"), ("LR", "LR"),
        ]:
            if _click_radio_by_id(page, "bEndLocation_mediaType", suffix, fallback_role_name=role):
                return True
        # Final fallback: click by visible text (portal label "Single Mode (LX)" or "Single Mode (LR)")
        try:
            el = page.get_by_text(re.compile(r"Single Mode\s*\((LX|LR)\)|^LX$|^LR$", re.IGNORECASE))
            if el.count() > 0 and el.first.is_visible(timeout=1500):
                el.first.scroll_into_view_if_needed()
                el.first.click(timeout=3000)
                page.wait_for_timeout(200)
                return True
        except Exception:
            pass
        return False

    mt = str(site_config.get("media_type", "LR")).upper()
    if mt == "TX":
        _click_radio_by_id(page, "bEndLocation_mediaType", "TX", fallback_role_name="TX")
    elif mt in ("LR", "LX", "SINGLE") or "single" in str(site_config.get("media_type", "")).lower():
        _try_media_type_single_mode()
    else:
        # SR/SX (Multi Mode) — CSV SR maps to portal SX
        if not _click_radio_by_id(page, "bEndLocation_mediaType", "SX", fallback_role_name="Multi Mode (SX)"):
            if not _click_radio_by_id(page, "bEndLocation_mediaType", "SX", fallback_role_name="Multi Mode"):
                _click_radio_by_id(page, "bEndLocation_mediaType", "SR", fallback_role_name="Multi Mode")

    page.wait_for_timeout(400)

    _coerce_b_end_media_to_tx_if_needed(page, str(site_config.get("media_type", "")).upper())
    _reassert_connector_after_media(page, site_config)

    # VLAN tagging
    vlan_tagging = site_config.get("vlan_tagging", False)
    vlan_suffix = "yes" if vlan_tagging else "no"
    if _click_radio_by_id(page, "bEndLocation_vlanTagging", vlan_suffix, fallback_role_name="Yes" if vlan_tagging else "No"):
        page.wait_for_timeout(400)
        vlan_tb = page.locator("#bEndLocation_vlanId")
        if vlan_tb.count() == 0:
            vlan_tb = page.get_by_label(re.compile(r"VLAN ID", re.IGNORECASE))
        if vlan_tb.count() > 0 and vlan_tb.first.is_visible(timeout=2000):
            if vlan_tagging:
                tag_val = str(
                    billing.get("vlan_tagging_value")
                    or billing.get("vlan_id")
                    or "100"
                ).strip()
            else:
                tag_val = "N/A"
            safe_fill_textbox(vlan_tb.first, tag_val, timeout_ms=5000)

    # Auto Negotiation: Yes/No (1 Gbps bearer with 1g/500m/200m/100m bandwidth, or 100 Mbps bearer)
    b_str = (str(bearer or "") or "").lower().replace(" ", "")
    w_str = (str(bandwidth or "") or "").lower().replace(" ", "")
    bearer_1g = b_str == "1gbps"
    bearer_100m = b_str == "100mbps"
    bw_1g = w_str == "1gbps"
    bw_500m, bw_200m, bw_100m = w_str == "500mbps", w_str == "200mbps", w_str == "100mbps"
    show_auto_neg = (
        (bearer_1g and (bw_1g or bw_500m or bw_200m or bw_100m)) or (bearer_100m and bw_100m)
    ) and "auto_negotiation" in site_config
    if show_auto_neg:
        an_val = site_config.get("auto_negotiation", False)
        an_suffix = "yes" if an_val else "no"
        _click_radio_by_id(page, "bEndLocation_autoNegotiation", an_suffix, fallback_role_name="Yes" if an_val else "No")

    # Access notice: 0-48 hours or Over 48 hours
    an = site_config.get("access_notice", "0-48 hours")
    want_over48 = "over" in str(an).lower()
    an_suffix = "over48hours" if want_over48 else "upTo48hours"
    _click_radio_by_id(page, "bEndLocation_accessNotice", an_suffix, fallback_role_name="Over 48 hours" if want_over48 else "0-48 hours")

    for key, checkbox_id in [
        ("more_than_one_tenant", "bEndLocation_moreThanOneTenant"),
        ("hazards_on_site", "bEndLocation_hazardsOnSite"),
        ("land_owner_permission_required", "bEndLocation_landOwnerPermissionRequired"),
    ]:
        if not site_config.get(key, False):
            continue
        try:
            cb = page.locator(f"#{checkbox_id}")
            if cb.count() == 0:
                cb = page.get_by_test_id(checkbox_id)
            if cb.count() > 0 and cb.first.is_visible(timeout=1000):
                if not cb.first.is_checked():
                    cb.first.click(timeout=3000)
                page.wait_for_timeout(200)
                if key == "hazards_on_site":
                    page.wait_for_timeout(300)
                    hazards_desc = site_config.get("hazards_description") or "Standard building hazards – site survey recommended prior to engineer visit."
                    hazards_tb = page.locator("#bEndLocation_hazardsOnSiteDescription")
                    if hazards_tb.count() > 0 and hazards_tb.first.is_visible(timeout=2000):
                        safe_fill_textbox(hazards_tb.first, hazards_desc, timeout_ms=5000)
                page.wait_for_timeout(150)
        except Exception:
            pass

    _apply_building_prior_and_asbestos(page, site_config)
    print("✅ Site Config toggles filled.")


def fill_b_end_section(page, billing: dict, ro2_diversity: bool = False, b_end_postcode: str | None = None, sc_toggles: dict | None = None, bearer: str = "", bandwidth: str = ""):
    print("🔎 Locating B-End card...")
    b_end_card = find_card_by_marker_text(page, re.compile(r"\(B-End Location\)", re.IGNORECASE))
    print("✅ B-End card found.")

    edit_btn = b_end_card.get_by_role("button", name=re.compile(r"^Edit", re.IGNORECASE))
    if edit_btn.count() > 0:
        print("🖱 Clicking B-End Edit...")
        edit_btn.first.click()
        page.wait_for_timeout(250)  # let form expand before filling

    print("⌨️ Filling End Company Name * ...")
    tb_company = page.get_by_role("textbox", name=re.compile(r"^End Company Name \*$", re.IGNORECASE)).first
    safe_fill_textbox(tb_company, billing["end_company"])
    print("✅ End Company Name filled.")

    print("🖱 Selecting Address * (Choose location, first option)...")
    if select_b_end_address_dropdown(page, b_end_card):
        print("✅ Address selected (first option).")
    else:
        print("⚠️ Address selection skipped - trying manual address fallback.")
    # Precautionary backup: when "Unable to fetch addresses" appears, fill manual address fields
    fill_manual_address_fallback(page, b_end_card, billing, postcode=b_end_postcode)

    print("⌨️ Filling Site Contact Information fields...")
    safe_fill_textbox(page.get_by_role("textbox", name=re.compile(r"^First name \*$", re.IGNORECASE)).first, billing["first_name"])
    safe_fill_textbox(page.get_by_role("textbox", name=re.compile(r"^Surname \*$", re.IGNORECASE)).first, billing["surname"])
    safe_fill_textbox(page.get_by_role("textbox", name=re.compile(r"^Mobile or landline phone number \*$", re.IGNORECASE)).first, billing["phone"])
    safe_fill_textbox(page.get_by_role("textbox", name=re.compile(r"^Email address \*$", re.IGNORECASE)).first, billing["email"])
    print("✅ Contact fields filled.")

    print("🔎 Filling Site Config...")
    page.set_default_timeout(3000)  # Floor/Room - allow time for dropdowns (regression stability)
    site_config = None
    try:
        # Prefer Site Config within B-End card (RO2 has multiple Site Config sections)
        site_config_heading = b_end_card.get_by_text(re.compile(r"^Site Config$", re.IGNORECASE))
        if site_config_heading.count() > 0:
            try:
                site_config_heading.first.scroll_into_view_if_needed(timeout=500)
                sec = site_config_heading.first.locator("xpath=ancestor::section[1]")
                if sec.count() > 0:
                    site_config = sec.first
                else:
                    site_config = site_config_heading.first.locator("xpath=..").first
            except Exception:
                pass
        if site_config is None:
            site_config = find_section_by_heading_text(page, re.compile(r"^Site Config$", re.IGNORECASE), timeout_ms=3000)

        print("🔎 Handling Floor * ...")
        handle_floor_or_room(site_config, page, field_name="Floor", fallback_value=billing.get("floor") or "001 - 1st Floor", label_timeout_ms=2000)
        page.wait_for_timeout(50)  # Minimal pause before Room

        print("🔎 Handling Room * ...")
        handle_floor_or_room(site_config, page, field_name="Room", fallback_value=billing.get("room") or "ADMN - Admin Room", label_timeout_ms=2000)
    finally:
        page.set_default_timeout(5000)  # Keep 5s cap; avoid 30s waits

    print("⌨️ Filling Rack ID * ...")
    rack_re = re.compile(r"^Rack ID\s*\*?$", re.IGNORECASE)
    rack_in_card = b_end_card.get_by_role("textbox", name=rack_re)
    if rack_in_card.count() == 0 and site_config:
        rack_in_card = site_config.get_by_role("textbox", name=rack_re)
    if rack_in_card.count() == 0:
        rack_in_card = page.get_by_role("textbox", name=rack_re)
    if rack_in_card.count() == 0:
        rack_in_card = b_end_card.get_by_label(re.compile(r"Rack ID", re.IGNORECASE))
    rack_tb = rack_in_card.first
    safe_fill_textbox(rack_tb, billing["rack_id"], timeout_ms=20000)
    print("✅ Rack ID filled.")

    _fill_site_config_toggles(page, b_end_card, sc_toggles or {}, billing, bearer=bearer, bandwidth=bandwidth)

    # RO2: Secondary Circuit needs Floor, Room, Rack ID filled too (under B-End)
    if ro2_diversity:
        _fill_secondary_circuit_site_config(page, billing)

    print("🟧 Clicking Save details (B-End)...")
    page.get_by_role("button", name=re.compile(r"^Save details$", re.IGNORECASE)).first.click()
    page.wait_for_timeout(250)  # Let save complete
    print("✅ Saved B-End details.")

def _fill_primary_circuit_site_config(page, billing: dict):
    """Fill Floor, Room, Rack ID for Primary Circuit Site Configuration (RO2 only)."""
    print("🔎 Filling Primary Circuit Site Config...")
    prim_link = page.get_by_text(re.compile(r"^Primary Circuit$", re.IGNORECASE))
    if prim_link.count() > 0 and prim_link.first.is_visible():
        try:
            prim_link.first.click()
            page.wait_for_timeout(400)
        except Exception:
            pass
    prim = page.locator("section, div, article").filter(
        has_text=re.compile(r"Primary Circuit Site Configuration|Primary Circuit", re.IGNORECASE)
    )
    if prim.count() == 0:
        print("ℹ️ Primary Circuit Site Config not found.")
        return
    prim_section = prim.first
    prim_section.scroll_into_view_if_needed(timeout=5000)
    page.wait_for_timeout(300)
    page.set_default_timeout(300)
    try:
        handle_floor_or_room(prim_section, page, field_name="Floor", fallback_value=billing.get("floor", "1"), label_timeout_ms=200)
        page.wait_for_timeout(100)
        handle_floor_or_room(prim_section, page, field_name="Room", fallback_value=billing.get("room", "A"), label_timeout_ms=200)
        rack_in_prim = prim_section.get_by_role("textbox", name=re.compile(r"^Rack ID\s*\*?$", re.IGNORECASE))
        if rack_in_prim.count() > 0:
            safe_fill_textbox(rack_in_prim.first, billing["rack_id"], timeout_ms=8000)
            print("✅ Primary Circuit Floor, Room, Rack ID filled.")
        else:
            rack_in_prim = prim_section.get_by_label(re.compile(r"Rack ID", re.IGNORECASE))
            if rack_in_prim.count() > 0:
                safe_fill_textbox(rack_in_prim.first, billing["rack_id"], timeout_ms=8000)
                print("✅ Primary Circuit Floor, Room, Rack ID filled.")
    finally:
        page.set_default_timeout(5000)

def _fill_secondary_circuit_site_config(page, billing: dict):
    """Fill Floor, Room, Rack ID for Secondary Circuit Site Configuration (RO2 only)."""
    print("🔎 Filling Secondary Circuit Site Config...")
    # Click Secondary Circuit tab/section to expand if needed
    sec_link = page.get_by_text(re.compile(r"^Secondary Circuit$", re.IGNORECASE))
    if sec_link.count() > 0 and sec_link.first.is_visible():
        try:
            sec_link.first.click()
            page.wait_for_timeout(350)
        except Exception:
            pass
    page.wait_for_timeout(200)

    # Find Secondary Circuit section and use same handle_floor_or_room logic as Primary
    sec = page.locator("section, div, article").filter(
        has_text=re.compile(r"Secondary Circuit Site Configuration|Secondary Circuit", re.IGNORECASE)
    )
    if sec.count() > 0:
        sec_section = sec.first
        sec_section.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(300)
        page.set_default_timeout(300)
        try:
            handle_floor_or_room(sec_section, page, field_name="Floor", fallback_value=billing.get("floor", "1"), label_timeout_ms=200)
            page.wait_for_timeout(50)  # Minimal pause before Room
            handle_floor_or_room(sec_section, page, field_name="Room", fallback_value=billing.get("room", "A"), label_timeout_ms=200)

            # Fallback: get_by_text("Room *Select an option") - targets Room field when it shows placeholder
            try:
                room_loc = page.get_by_text("Room *Select an option")
                if room_loc.count() > 0 and room_loc.first.is_visible(timeout=2000):
                    room_loc.first.scroll_into_view_if_needed(timeout=5000)
                    room_loc.first.click(timeout=5000)
                    page.wait_for_timeout(500)
                    opts = page.get_by_role("option")
                    opts.first.wait_for(state="visible", timeout=5000)
                    if opts.count() > 1:
                        opts.nth(1).click(timeout=5000)
                        page.wait_for_timeout(400)
                        print("✅ Secondary Room selected (Room *Select an option).")
            except Exception:
                pass

            # Fallback for Room when it still shows "* Add room" - explicitly click 2nd "Add room" (Secondary)
            add_room = page.get_by_text(re.compile(r"Add\s+room", re.IGNORECASE))
            if add_room.count() > 0:
                for nth in [1, 0]:  # try 2nd first (Secondary), then 1st
                    if add_room.count() <= nth:
                        continue
                    try:
                        el = add_room.nth(nth)
                        if el.is_visible(timeout=2000):
                            el.scroll_into_view_if_needed(timeout=5000)
                            page.wait_for_timeout(200)
                            el.click(timeout=5000)
                            page.wait_for_timeout(500)
                            opts = page.get_by_role("option")
                            opts.first.wait_for(state="visible", timeout=5000)
                            if opts.count() > 1:
                                opts.nth(1).click(timeout=5000)
                                page.wait_for_timeout(400)
                                print(f"✅ Secondary Room selected (Add room nth={nth}).")
                                break
                    except Exception:
                        pass

            # Fallback: "Select an option" nth(2)/nth(3) for Room dropdown
            placeholders = page.locator("div").filter(has_text=re.compile(r"^Select an option$", re.IGNORECASE))
            if placeholders.count() >= 2:
                for nth in [2, 3]:
                    if placeholders.count() <= nth:
                        continue
                    try:
                        ph = placeholders.nth(nth)
                        if ph.is_visible(timeout=1000):
                            ph.scroll_into_view_if_needed(timeout=5000)
                            ph.click(timeout=3000)
                            page.wait_for_timeout(350)
                            opts = page.get_by_role("option")
                            if opts.count() > 1:
                                opts.nth(1).click(timeout=3000)
                                page.wait_for_timeout(400)
                                print(f"✅ Secondary Room selected (Select an option nth={nth}).")
                                break
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            page.set_default_timeout(5000)
    # Rack ID: #bEndLocation_rackId nth(1) = Secondary Circuit
    rack_ids = page.locator("#bEndLocation_rackId")
    if rack_ids.count() >= 2:
        rack_el = rack_ids.nth(1)
        try:
            rack_el.scroll_into_view_if_needed(timeout=3000)
            safe_fill_textbox(rack_el, billing["rack_id"], timeout_ms=8000)
            print("✅ Secondary Circuit Rack ID filled.")
        except Exception:
            sec = page.locator("section, div").filter(has_text=re.compile(r"Secondary Circuit", re.IGNORECASE))
            if sec.count() > 0:
                rack_in_sec = sec.first.get_by_role("textbox", name=re.compile(r"^Rack ID\s*\*?$", re.IGNORECASE))
                if rack_in_sec.count() == 0:
                    rack_in_sec = sec.first.get_by_label(re.compile(r"Rack ID", re.IGNORECASE))
                if rack_in_sec.count() > 0:
                    safe_fill_textbox(rack_in_sec.first, billing["rack_id"], timeout_ms=8000)
                    print("✅ Secondary Circuit Rack ID filled (fallback).")

def _try_set_shadow_vlan_na(page, a_end_card) -> bool:
    """Select N/A for Shadow VLAN when the journey does not require a numeric shadow ID."""
    for root in (a_end_card, page):
        try:
            sec = root.locator("xpath=.").filter(has_text=re.compile(r"Shadow VLAN", re.IGNORECASE))
            if sec.count() == 0:
                continue
            na = None
            for label in ("N/A", "n/a", "N / A", "n / a"):
                cand = sec.first.get_by_role("radio", name=label, exact=True)
                if cand.count() > 0:
                    na = cand
                    break
            if na is not None and na.count() > 0 and na.first.is_visible(timeout=1200):
                na.first.scroll_into_view_if_needed(timeout=3000)
                na.first.click(timeout=3000)
                page.wait_for_timeout(150)
                return True
        except Exception:
            continue
    try:
        sid = page.locator("#aEndLocation_shadowVLANId")
        if sid.count() > 0 and sid.first.is_visible(timeout=900):
            safe_fill_textbox(sid.first, "N/A", timeout_ms=5000)
            page.wait_for_timeout(120)
            return True
    except Exception:
        pass
    return False


def fill_a_end_vlan_section(page, billing: dict, ro2_diversity: bool = False, shadow_vlan_required: bool = True):
    print("🔎 Locating A-End card...")
    a_end_card = find_card_by_marker_text(page, re.compile(r"\(A-End Location\)", re.IGNORECASE))
    print("✅ A-End card found.")

    did_any = False
    shadow_done = False

    edit_btn = a_end_card.get_by_role("button", name=re.compile(r"^Edit", re.IGNORECASE))
    if edit_btn.count() > 0:
        print("🖱 Clicking A-End Edit...")
        edit_btn.first.click()
        page.wait_for_timeout(450)  # Let VLAN section fully expand

    page.wait_for_timeout(350)  # Let fields stabilize before locating
    shadow_present = page.get_by_role("textbox", name=re.compile(r"Shadow VLAN ID", re.IGNORECASE)).count() > 0
    if shadow_present:
        page.wait_for_timeout(400)  # Extra wait for both sections to be ready
    else:
        page.wait_for_timeout(250)  # Non-shadow: single VLAN section can lag (e.g. last row in CSV run)
    # Wait for VLAN Reference section to be visible (reduces flakiness when section renders late)
    try:
        page.get_by_text(re.compile(r"VLAN Reference", re.IGNORECASE)).first.wait_for(state="visible", timeout=6000)
        page.wait_for_timeout(200)
    except Exception:
        pass

    if not shadow_vlan_required:
        if _try_set_shadow_vlan_na(page, a_end_card):
            print("✅ Shadow VLAN set to N/A (shadow not required).")
            shadow_done = True
            did_any = True
        else:
            print("ℹ️ Shadow VLAN N/A not applied (field may be hidden when shadow not required).")
            shadow_done = True

    # Prefer A-End–scoped "VLAN Reference" first so we don't fill another card's VLAN ID
    vlan_tb = None
    for scope in [a_end_card, page]:
        vlan_ref = (
            scope.locator("section, div")
            .filter(has_text=re.compile(r"VLAN Reference", re.IGNORECASE))
            .filter(has_not=scope.locator(":has-text('Shadow VLAN')"))
        )
        if vlan_ref.count() > 0:
            cand = vlan_ref.locator("input[type='text'], input[type='number'], input:not([type])")
            if cand.count() > 0:
                vlan_tb = cand
                break
    if vlan_tb is None or vlan_tb.count() == 0:
        for scope in [a_end_card, page]:
            vlan_ref = scope.locator("section, div").filter(has_text=re.compile(r"VLAN Reference", re.IGNORECASE))
            if vlan_ref.count() > 0:
                cand = vlan_ref.locator("input[type='text'], input[type='number'], input:not([type])")
                if cand.count() > 0:
                    vlan_tb = cand
                    break
    if vlan_tb is None or vlan_tb.count() == 0:
        vlan_tb = a_end_card.get_by_role("textbox", name=re.compile(r"VLAN ID", re.IGNORECASE))
    if vlan_tb is None or vlan_tb.count() == 0:
        vlan_tb = a_end_card.get_by_label(re.compile(r"VLAN ID", re.IGNORECASE))
    if vlan_tb is None or vlan_tb.count() == 0:
        vlan_tb = page.get_by_role("textbox", name="VLAN ID *", exact=True)
    if vlan_tb is None or vlan_tb.count() == 0:
        vlan_tb = page.get_by_role("textbox", name=re.compile(r"^VLAN ID\s*\*?$", re.IGNORECASE))
    if vlan_tb is None or vlan_tb.count() == 0:
        vlan_tb = page.get_by_label(re.compile(r"VLAN ID", re.IGNORECASE))
    if vlan_tb is None:
        vlan_tb = page.locator("input#p2nni-no-vlan-match")  # 0 matches, keeps vlan_tb a valid locator
    shadow_vlan_tb = page.get_by_role("textbox", name="Shadow VLAN ID *", exact=True)
    if shadow_vlan_tb.count() == 0:
        shadow_vlan_tb = page.get_by_role("textbox", name=re.compile(r"^Shadow VLAN ID\s*\*$", re.IGNORECASE))
    shadow_tb_selected = None

    vlan_value = str(billing.get("vlan_id") or "100").strip()
    if shadow_vlan_required:
        shadow_value = str(billing.get("shadow_vlan_id") or "100").strip()
    else:
        shadow_value = "N/A"

    # Wait for primary VLAN input to be visible before any fill (avoids filling a stale/hidden node)
    if vlan_tb.count() > 0:
        try:
            vlan_tb.first.wait_for(state="visible", timeout=8000)
            page.wait_for_timeout(150)
        except Exception:
            pass

    def _fill_vlan_and_verify(tb, value: str, *, settle_after_fill_ms: int = 400, settle_after_js_ms: int = 300) -> bool:
        """Fill VLAN input and ensure value sticks (React often needs input/change events)."""
        safe_fill_textbox(tb, value, timeout_ms=10000)
        page.wait_for_timeout(settle_after_fill_ms)
        current = (tb.input_value() or "").strip()
        if current == value:
            return True
        # Value didn't stick: set via JS and dispatch events so React state updates
        try:
            tb.evaluate("""(el, val) => {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""", value)
            page.wait_for_timeout(settle_after_js_ms)
            if (tb.input_value() or "").strip() == value:
                return True
        except Exception:
            pass
        safe_fill_textbox(tb, value, timeout_ms=8000)
        page.wait_for_timeout(120)
        return (tb.input_value() or "").strip() == value

    # Fast path: stable portal IDs (avoids ambiguous side-by-side section locators).
    _fast_vlan_settle = dict(settle_after_fill_ms=220, settle_after_js_ms=150)
    primary_done = False
    vlan_by_id = page.locator("#aEndLocation_vlanId")
    try:
        if vlan_by_id.count() > 0:
            tb_id = vlan_by_id.first
            tb_id.wait_for(state="visible", timeout=5000)
            tb_id.scroll_into_view_if_needed(timeout=3000)
            print(f"⌨️ Filling VLAN ID * (#aEndLocation_vlanId) with '{vlan_value}'...")
            if _fill_vlan_and_verify(tb_id, vlan_value, **_fast_vlan_settle):
                did_any = True
                primary_done = True
                print("✅ VLAN ID filled via id (verified).")
            else:
                print("⚠️ VLAN ID id-field fill did not verify; will try section/role locators.")
    except Exception as e:
        print(f"⚠️ VLAN ID id-field path failed ({e}); using section/role locators.")

    # Keep this simple/stable: fill ONLY the first visible primary VLAN input.
    # Filling multiple matching inputs can trigger React re-renders that clear values.
    primary_tb = None
    if not primary_done and vlan_tb.count() > 0:
        for i in range(vlan_tb.count()):
            tb = vlan_tb.nth(i)
            try:
                if tb.is_visible(timeout=2000):
                    primary_tb = tb
                    break
            except Exception:
                continue
    if not primary_done and primary_tb is not None:
        try:
            primary_tb.scroll_into_view_if_needed(timeout=5000)
            print(f"⌨️ Filling VLAN ID * with '{vlan_value}'...")
            _fill_vlan_and_verify(primary_tb, vlan_value)
            did_any = True
            print("✅ VLAN ID filled (verified).")
        except Exception as e:
            print(f"⚠️ Could not fill VLAN ID: {e}")
    elif not primary_done:
        print("ℹ️ No visible VLAN ID input found to fill.")

    # RO2: ensure Secondary Circuit VLAN is filled (first fill may leave it empty)
    if ro2_diversity:
        sec_vlan = None
        # Strategy 1: #aEndLocation_edit_secondary_nni scopes to Secondary Circuit NNI section
        sec_nni = page.locator("#aEndLocation_edit_secondary_nni")
        if sec_nni.count() > 0:
            sec_vlan = sec_nni.get_by_label(re.compile(r"VLAN ID", re.IGNORECASE))
            if sec_vlan.count() == 0:
                sec_vlan = sec_nni.locator("input[type='text'], input[type='number'], input:not([type])")
        # Strategy 2: section/div filter fallback
        if sec_vlan is None or sec_vlan.count() == 0:
            sec_vlan = (
                page.locator("section, div")
                .filter(has_text=re.compile(r"Secondary Circuit", re.IGNORECASE))
                .filter(has_text=re.compile(r"VLAN Reference", re.IGNORECASE))
                .locator("input[type='text'], input[type='number'], input:not([type])")
            )
        if sec_vlan and sec_vlan.count() > 0:
            try:
                tb = sec_vlan.first
                tb.scroll_into_view_if_needed(timeout=3000)
                if tb.input_value() != billing["vlan_id"]:
                    safe_fill_textbox(tb, billing["vlan_id"], timeout_ms=8000)
                    print("✅ Secondary Circuit VLAN ID filled.")
                    did_any = True
            except Exception:
                pass

    shadow_by_id = page.locator("#aEndLocation_shadowVLANId")
    try:
        if shadow_vlan_required and (not shadow_done) and shadow_by_id.count() > 0:
            stb = shadow_by_id.first
            stb.wait_for(state="visible", timeout=5000)
            stb.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(80)
            print(f"⌨️ Filling Shadow VLAN ID * (#aEndLocation_shadowVLANId) with '{shadow_value}'...")
            ok_id = False
            for attempt in range(2):
                try:
                    ok_id = bool(_fill_vlan_and_verify(stb, shadow_value, **_fast_vlan_settle))
                    if ok_id:
                        break
                except Exception:
                    pass
                page.wait_for_timeout(180)
            if ok_id:
                did_any = True
                shadow_done = True
                print("✅ Shadow VLAN ID filled via id (verified).")
            else:
                print("⚠️ Shadow VLAN ID id-field may not have stuck; will try role locator if present.")
    except Exception as e:
        print(f"⚠️ Shadow VLAN ID id-field path failed ({e}); using role locators if present.")

    if shadow_vlan_required and (not shadow_done) and shadow_vlan_tb.count() > 0:
        # Keep this simple/stable: fill ONLY the first visible shadow VLAN input.
        shadow_tb_selected = None
        for i in range(shadow_vlan_tb.count()):
            cand = shadow_vlan_tb.nth(i)
            try:
                if cand.is_visible(timeout=2000):
                    shadow_tb_selected = cand
                    break
            except Exception:
                continue
        if shadow_tb_selected is None:
            shadow_tb_selected = shadow_vlan_tb.first
        try:
            shadow_tb_selected.wait_for(state="visible", timeout=8000)
        except Exception:
            pass

        page.wait_for_timeout(120)  # small settle before fill
        try:
            print(f"⌨️ Filling Shadow VLAN ID * with '{shadow_value}'...")
            ok = False
            for attempt in range(2):  # 2 attempts max to handle React timing
                try:
                    ok = bool(_fill_vlan_and_verify(shadow_tb_selected, shadow_value))
                    if ok:
                        break
                except Exception:
                    pass
                page.wait_for_timeout(250)
            if ok:
                did_any = True
                print("✅ Shadow VLAN ID filled (verified).")
            else:
                print("⚠️ Shadow VLAN ID filled, but value may not have stuck immediately.")
        except Exception as e:
            print(f"⚠️ Could not fill Shadow VLAN ID: {e}")
    elif shadow_vlan_required and not shadow_done:
        print("ℹ️ No Shadow VLAN ID field found.")

    if not did_any:
        print("ℹ️ No VLAN fields to save (skipping A-End save).")
        return

    page.wait_for_timeout(300)  # Pause before save
    print("🟧 Clicking Save details (A-End)...")
    save_btn = a_end_card.get_by_role("button", name=re.compile(r"^Save details$", re.IGNORECASE))
    if save_btn.count() > 0:
        save_btn.first.click()
    else:
        page.get_by_role("button", name=re.compile(r"^Save details$", re.IGNORECASE)).first.click()
    page.wait_for_timeout(600)

    # Post-save verification:
    # The portal sometimes re-renders and clears VLAN inputs after save.
    # We re-open A-End Edit, verify values, and if needed re-fill + save once.
    def _get_first_visible_textbox(role_pat) -> any:
        tbs = a_end_card.get_by_role("textbox", name=role_pat)
        if tbs.count() == 0:
            return None
        for i in range(tbs.count()):
            cand = tbs.nth(i)
            try:
                if cand.is_visible(timeout=2000):
                    return cand
            except Exception:
                continue
        try:
            return tbs.first if tbs.first.is_visible(timeout=2000) else None
        except Exception:
            return None

    primary_tb_after = None
    shadow_tb_after = None
    try:
        # IMPORTANT: do NOT force-click A-End "Edit" here.
        # Clicking Edit re-expands the panel and can leave it open, blocking later steps.
        # Only verify if VLAN inputs are already visible after save.
        page.wait_for_timeout(200)
        primary_tb_after = None
        shadow_tb_after = None
        try:
            vid_after = page.locator("#aEndLocation_vlanId")
            if vid_after.count() > 0 and vid_after.first.is_visible():
                primary_tb_after = vid_after.first
        except Exception:
            pass
        if primary_tb_after is None:
            primary_tb_after = _get_first_visible_textbox(re.compile(r"^VLAN ID\s*\*?$", re.IGNORECASE))
        try:
            svid_after = page.locator("#aEndLocation_shadowVLANId")
            if svid_after.count() > 0 and svid_after.first.is_visible():
                shadow_tb_after = svid_after.first
        except Exception:
            pass
        if shadow_tb_after is None:
            shadow_tb_after = _get_first_visible_textbox(re.compile(r"^Shadow VLAN ID\s*\*?$", re.IGNORECASE))
    except Exception:
        pass

    primary_after_val = ""
    shadow_after_val = ""
    try:
        primary_after_val = (primary_tb_after.input_value() or "").strip() if primary_tb_after else ""
    except Exception:
        pass
    try:
        shadow_after_val = (shadow_tb_after.input_value() or "").strip() if shadow_tb_after else ""
    except Exception:
        pass

    needs_retry = False
    if primary_tb_after and primary_after_val != vlan_value:
        needs_retry = True
    if shadow_vlan_required:
        if shadow_tb_after and shadow_after_val != shadow_value:
            needs_retry = True
    else:
        if shadow_tb_after:
            s_norm = shadow_after_val.strip().upper().replace(" ", "")
            if s_norm and s_norm not in ("N/A", "NA"):
                needs_retry = True
    # If VLAN inputs aren't visible after save, skip verification (don't re-open Edit).
    if primary_tb_after is None and shadow_tb_after is None:
        needs_retry = False

    if needs_retry:
        print(f"⚠️ VLAN inputs not correct after save (primary='{primary_after_val}', shadow='{shadow_after_val}'). Re-fill once…")
        # Re-fill (only first visible inputs to avoid multi-node React conflicts).
        if primary_tb_after:
            _fill_vlan_and_verify(primary_tb_after, vlan_value)
        if shadow_tb_after:
            if shadow_vlan_required:
                _fill_vlan_and_verify(shadow_tb_after, shadow_value)
            else:
                _try_set_shadow_vlan_na(page, a_end_card)
                _fill_vlan_and_verify(shadow_tb_after, "N/A")

        # Save again (wait for button)
        save_btn2 = a_end_card.get_by_role("button", name=re.compile(r"^Save details$", re.IGNORECASE)).first
        save_btn2.wait_for(state="visible", timeout=12000)
        save_btn2.scroll_into_view_if_needed(timeout=5000)
        save_btn2.click(timeout=10000)
        page.wait_for_timeout(600)

    print("✅ Saved A-End/VLAN details.")

def _find_po_textbox_within_billing_section(billing_section):
    # Attempt 1: label substring
    try:
        tb = billing_section.get_by_label("PO number", exact=False)
        if tb.count() > 0:
            return tb.first
    except Exception:
        pass

    # Attempt 2: any container with "PO number"
    try:
        block = billing_section.locator("div").filter(has_text=re.compile(r"PO number", re.IGNORECASE)).first
        if block.count() > 0:
            tb2 = block.get_by_role("textbox")
            if tb2.count() > 0:
                return tb2.first
            inp = block.locator("input").first
            if inp.count() > 0:
                return inp
    except Exception:
        pass

    return None

def fill_billing_contact_information_section(page, billing: dict):
    print("🔎 Locating Billing & contact information card...")
    billing_section = page.locator("section").filter(
        has_text=re.compile(r"Billing\s*&\s*contact information", re.IGNORECASE)
    ).first
    safe_wait_visible(billing_section, timeout_ms=20000)
    billing_section.scroll_into_view_if_needed()
    print("✅ Billing & contact information card found.")

    edit_btn = billing_section.get_by_role("button", name=re.compile(r"^Edit", re.IGNORECASE))
    if edit_btn.count() > 0:
        print("🖱 Clicking Billing & contact information Edit...")
        edit_btn.first.click()
        page.wait_for_timeout(250)  # Let form expand

    # Click A-End contact once for each contact subsection.
    # This avoids clicking the wrong button(s) when there are multiple A-End contact controls.
    def _click_a_end_in_subsection(heading_pattern: re.Pattern, label: str) -> None:
        try:
            sub = billing_section.locator("div, section").filter(has_text=heading_pattern).first
            if sub.count() == 0:
                print(f"ℹ️ {label}: subsection not found (skipping).")
                return
            btns = sub.locator("button, a, [role='button']").filter(
                has_text=re.compile(r"A-End contact", re.IGNORECASE)
            )
            if btns.count() == 0:
                print(f"ℹ️ {label}: A-End contact button not found (skipping).")
                return
            btn = btns.first
            btn.scroll_into_view_if_needed(timeout=5000)
            btn.click(timeout=8000)
            page.wait_for_timeout(400)  # let fields populate before continuing
            print(f"✅ {label}: A-End contact applied.")
        except Exception as e:
            print(f"ℹ️ {label}: could not apply A-End contact ({e}).")

    _click_a_end_in_subsection(re.compile(r"^Order Delivery contact$|Order Delivery contact", re.IGNORECASE), "Order Delivery")
    _click_a_end_in_subsection(re.compile(r"^Operational contact$|Operational contact", re.IGNORECASE), "Operational")

    # Fill contact fields directly (reliable even if A-End button population is inconsistent).
    def _fill_if_needed(locator, value: str):
        try:
            current = (locator.input_value() or "").strip()
        except Exception:
            current = ""
        if current == str(value).strip():
            return
        safe_fill_textbox(locator, value, timeout_ms=12000)

    first_name_tbs = billing_section.get_by_role(
        "textbox", name=re.compile(r"^First name \*$", re.IGNORECASE)
    )
    for i in range(first_name_tbs.count()):
        _fill_if_needed(first_name_tbs.nth(i), billing["first_name"])

    surname_tbs = billing_section.get_by_role(
        "textbox", name=re.compile(r"^Surname \*$", re.IGNORECASE)
    )
    for i in range(surname_tbs.count()):
        _fill_if_needed(surname_tbs.nth(i), billing["surname"])

    phone_tbs = billing_section.get_by_role(
        "textbox", name=re.compile(r"^Mobile or landline phone number \*$", re.IGNORECASE)
    )
    for i in range(phone_tbs.count()):
        _fill_if_needed(phone_tbs.nth(i), billing["phone"])

    email_tbs = billing_section.get_by_role(
        "textbox", name=re.compile(r"^Email address \*$", re.IGNORECASE)
    )
    for i in range(email_tbs.count()):
        _fill_if_needed(email_tbs.nth(i), billing["email"])

    print("⌨️ Filling PO number / Ref * ...")
    po_tb = _find_po_textbox_within_billing_section(billing_section)
    if po_tb is None:
        raise RuntimeError("Could not locate PO number / Ref textbox in Billing & contact information card.")
    safe_fill_textbox(po_tb, billing["po_ref"])
    print("✅ PO number / Ref filled.")

    print("🟧 Clicking Save details (Billing & contact information)...")
    save_btn = billing_section.get_by_role("button", name=re.compile(r"^Save details$", re.IGNORECASE)).first
    save_btn.scroll_into_view_if_needed()
    save_btn.click()
    page.wait_for_timeout(600)  # Let save complete + propagate before switching user in Demo 4
    print("✅ Saved Billing & contact information details.")

def _order_ready_for_customer_submit(page) -> bool:
    """
    Demo 4 guardrail: before switching to customer, verify order page is truly ready for
    "Submit for review" (i.e. not still showing incomplete billing bullets / locked section).
    """
    # If internal user sees the expected handoff message, the order is ready for customer submit.
    # Use full body text (not visibility-sensitive locators) because this banner can render with
    # line breaks / different apostrophes and occasionally fails strict get_by_text matching.
    try:
        no_perm_ready = bool(
            page.evaluate(
                """() => {
                    const body = (document.body && document.body.innerText) ? document.body.innerText : '';
                    const t = body.toLowerCase();
                    return (
                        /currently,?\\s*you\\s*(don['’]?t|do\\s*not)\\s*have\\s*permission\\s*to\\s*submit\\s*the\\s*order/.test(t) ||
                        /copy\\s*the\\s*below\\s*link\\s*and\\s*send\\s*it\\s*to\\s*your\\s*approved\\s*purchaser/.test(t) ||
                        (/submit\\s*order\\s*for\\s*review/.test(t) && /link\\s*to\\s*share/.test(t) && /approved\\s*purchaser/.test(t))
                    );
                }"""
            )
        )
        if no_perm_ready:
            return True
    except Exception:
        pass

    try:
        # If the review section still shows a lock icon, required sections are not complete yet.
        review = page.locator("section, div").filter(
            has_text=re.compile(r"Submit order for review", re.IGNORECASE)
        ).first
        if review.count() > 0:
            try:
                lock_in_review = review.locator("[class*='lock'], i.fa-lock, svg[data-icon='lock'], svg[class*='lock']")
                if lock_in_review.count() > 0 and lock_in_review.first.is_visible(timeout=300):
                    return False
            except Exception:
                pass
    except Exception:
        pass

    # Billing card incomplete copy seen in failures.
    for pat in [
        r"Add contact details for operations and order management",
        r"Confirm billing reference",
    ]:
        try:
            t = page.get_by_text(re.compile(pat, re.IGNORECASE))
            if t.count() > 0 and t.first.is_visible(timeout=400):
                return False
        except Exception:
            continue

    return True


def _ensure_internal_order_ready_before_customer_submit(
    page,
    billing: dict,
    b_end_postcode: str | None,
    sc_toggles: dict | None,
    bearer: str,
    bandwidth: str,
) -> bool:
    """
    Demo 4 only: run a quick readiness check before logging out internal user.
    If not ready, re-open/fill Billing & contact once and re-check.
    """
    if _order_ready_for_customer_submit(page):
        return True

    print("⚠️ Order not ready for customer submit (review section still locked/incomplete). Retrying Billing & contact once…")
    try:
        fill_billing_contact_information_section(page, billing)
    except Exception as e:
        print(f"ℹ️ Billing retry step could not re-open/refill ({e}); re-checking readiness anyway.")

    page.wait_for_timeout(500)
    return _order_ready_for_customer_submit(page)


def fill_order_billing_screen(
    page,
    billing: dict,
    ro2_diversity: bool = False,
    b_end_postcode: str | None = None,
    sc_toggles: dict | None = None,
    bearer: str = "",
    bandwidth: str = "",
    submit_for_review: bool = True,
    shadow_vlan_required: bool = True,
):
    print("🧾 On order page. Filling billing blocks...")
    page.wait_for_timeout(90)  # Let order page settle
    # RO2 diversity disabled: always pass False to downstream sections
    fill_b_end_section(page, billing, ro2_diversity=False, b_end_postcode=b_end_postcode, sc_toggles=sc_toggles, bearer=bearer, bandwidth=bandwidth)
    fill_a_end_vlan_section(page, billing, ro2_diversity=False, shadow_vlan_required=shadow_vlan_required)
    fill_billing_contact_information_section(page, billing)
    if submit_for_review:
        submitted = submit_order_for_review(page)
        if submitted:
            print("✅ Preset complete (Submit order for review reached).")
        else:
            print("⚠️ Preset finished billing but customer submit for review did not complete — check the browser/order.")
    else:
        print("✅ Billing filled (submit for review deferred — e.g. customer will submit in Demo 4).")


def _order_review_submit_already_done(page) -> bool:
    """True only when the customer submit step appears finished (not merely the step heading visible)."""
    for pat in [
        r"successfully submitted",
        r"has been submitted for review",
        r"submitted for review successfully",
        r"thank you for (submitting|your order)",
        r"your order has been submitted",
        r"order (has been )?submitted",
        r"awaiting review",
        r"pending review",
    ]:
        try:
            loc = page.get_by_text(re.compile(pat, re.IGNORECASE))
            if loc.count() > 0 and loc.first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


def _terms_agreement_checkbox_tick(page) -> bool:
    """
    Tick the mandatory 'Agree to General terms and Ethernet terms…' checkbox (React-friendly).
    Returns True if any strategy leaves a matching checkbox checked.
    """
    try:
        terms_section = page.get_by_text(re.compile(r"Supplementary Terms|Agree to General terms|Ethernet terms", re.IGNORECASE))
        if terms_section.count() > 0:
            terms_section.first.scroll_into_view_if_needed(timeout=2000)
            page.wait_for_timeout(60)
    except Exception:
        pass

    def _any_terms_checkbox_checked() -> bool:
        try:
            return bool(
                page.evaluate("""() => {
                    const termsRe = /Agree to General terms|Ethernet terms|Supplementary Terms|shall incorporate/i;
                    const cbs = document.querySelectorAll('input[type="checkbox"]');
                    for (const cb of cbs) {
                        let p = cb.parentElement;
                        for (let i = 0; p && i < 14; i++, p = p.parentElement) {
                            const ctx = (p.innerText || '').slice(0, 2500);
                            if (termsRe.test(ctx)) {
                                if (cb.checked) return true;
                                break;
                            }
                        }
                    }
                    const t = document.querySelector('#terms-checkbox');
                    return !!(t && t.checked);
                }""")
            )
        except Exception:
            return False

    def _js_tick_terms_checkbox() -> bool:
        try:
            did = page.evaluate("""() => {
                const fire = (el) => {
                    el.checked = true;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.click();
                };
                let cb = document.querySelector('#terms-checkbox');
                if (cb && !cb.checked) { fire(cb); return true; }
                for (const lab of document.querySelectorAll('label')) {
                    if (/Agree to General terms|Ethernet terms/i.test(lab.innerText || '')) {
                        const inp = lab.querySelector('input[type="checkbox"]');
                        const id = lab.getAttribute('for');
                        const byId = id && document.getElementById(id);
                        const target = inp || (byId && byId.matches && byId.matches('input[type=checkbox]') ? byId : null);
                        if (target && !target.checked) { fire(target); return true; }
                    }
                }
                const termsRe = /Agree to General terms|Ethernet terms|Supplementary Terms|shall incorporate/i;
                for (const el of document.querySelectorAll('input[type="checkbox"]')) {
                    let p = el.parentElement;
                    for (let i = 0; p && i < 14; i++, p = p.parentElement) {
                        if (termsRe.test((p.innerText || '').slice(0, 2500)) && !el.checked) {
                            fire(el);
                            return true;
                        }
                    }
                }
                return false;
            }""")
            page.wait_for_timeout(120)
            return bool(did)
        except Exception:
            return False

    # 0) JS first — fastest for React and avoids slow Playwright retries when #terms-checkbox id differs
    if _js_tick_terms_checkbox() and _any_terms_checkbox_checked():
        return True

    # 1) Playwright locators (id, role, label, form-check, visible text)
    strategies = [
        lambda: page.locator("#terms-checkbox"),
        lambda: page.get_by_role("checkbox", name=re.compile(r"Agree to General terms|Ethernet terms", re.IGNORECASE)),
        lambda: page.get_by_label(re.compile(r"Agree to General terms|Ethernet terms", re.IGNORECASE)),
        lambda: page.locator(".form-check, [class*='form-check']").filter(
            has_text=re.compile(r"Agree to General terms", re.IGNORECASE)
        ).locator("input[type='checkbox']"),
        lambda: page.locator("label").filter(has_text=re.compile(r"Agree to General terms", re.IGNORECASE)),
    ]
    for get_loc in strategies:
        try:
            cb = get_loc()
            if cb.count() == 0:
                continue
            el = cb.first
            el.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(80)
            tag = el.evaluate("n => n.tagName")
            if str(tag).upper() == "LABEL":
                el.click(timeout=4000, force=True)
            else:
                if el.is_checked():
                    return True
                el.check(timeout=5000, force=True)
            page.wait_for_timeout(200)
            if _any_terms_checkbox_checked():
                return True
        except Exception:
            continue

    # 2) Click long label text (portal often binds click to the paragraph, not the input)
    for text_pat in [
        r"Agree to General terms and Ethernet terms",
        r"Agree to General terms",
        r"General terms and Ethernet terms",
        r"Supplementary Terms and Conditions",
    ]:
        try:
            tloc = page.get_by_text(re.compile(text_pat, re.IGNORECASE))
            if tloc.count() > 0:
                tloc.first.scroll_into_view_if_needed(timeout=3000)
                tloc.first.click(timeout=4000, force=True)
                page.wait_for_timeout(200)
                if _any_terms_checkbox_checked():
                    return True
        except Exception:
            continue

    # 3) JS again (after Playwright attempts)
    if _js_tick_terms_checkbox() and _any_terms_checkbox_checked():
        return True

    return _any_terms_checkbox_checked()


def _wait_submit_for_review_enabled(page, timeout_ms: int = 12000) -> bool:
    deadline = time.perf_counter() + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        for loc in [
            page.locator("button.submitOrder--btn"),
            page.get_by_role("button", name=re.compile(r"^Submit for review$", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"Submit for review", re.IGNORECASE)),
        ]:
            try:
                if loc.count() == 0:
                    continue
                b = loc.first
                if not b.is_visible(timeout=350):
                    continue
                if b.is_enabled():
                    return True
            except Exception:
                continue
        page.wait_for_timeout(100)
    return False


def _submit_for_review_button_locators(page):
    return [
        page.locator("button.submitOrder--btn"),
        page.get_by_role("button", name=re.compile(r"^Submit for review$", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"Submit for review", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"Submit order for review", re.IGNORECASE)),
            page.get_by_role("link", name=re.compile(r"Submit for review", re.IGNORECASE)),
            page.get_by_role("link", name=re.compile(r"Submit order for review", re.IGNORECASE)),
        page.locator("button, a, [role='button']").filter(has_text=re.compile(r"^Submit for review$", re.IGNORECASE)),
    ]


def submit_order_for_review(page) -> bool:
    """
    Check terms checkbox, click 'Submit for review', wait for real post-submit UI.
    IMPORTANT: The step title on the order page is also 'Submit order for review' — that is NOT success;
    we must tick terms first or the submit button stays disabled.
    """
    print("🟧 Submitting order for review...")
    page.wait_for_timeout(80)

    if _order_review_submit_already_done(page):
        print("✅ Order already appears submitted for review (success message present).")
        return True

    terms_ok = _terms_agreement_checkbox_tick(page)
    if terms_ok:
        print("✅ Terms agreement checkbox is checked.")
    else:
        print("⚠️ Could not confirm terms checkbox; waiting for Submit to enable anyway…")

    if not _wait_submit_for_review_enabled(page, timeout_ms=10000):
        print("⚠️ 'Submit for review' did not become enabled — terms may not be ticked or UI changed.")
        # One more aggressive pass: re-tick + short wait
        _terms_agreement_checkbox_tick(page)
        page.wait_for_timeout(200)
        if not _wait_submit_for_review_enabled(page, timeout_ms=5000):
            return False

    submit_clicked = False
    try:
        for loc in _submit_for_review_button_locators(page):
            try:
                if loc.count() == 0:
                    continue
                btn = loc.first
                if not btn.is_visible(timeout=1500):
                    continue
                expect(btn).to_be_enabled(timeout=4000)
                btn.scroll_into_view_if_needed()
                btn.click(timeout=8000)
                page.wait_for_timeout(180)
                submit_clicked = True
                break
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️ Could not click Submit for review: {e}")

    if not submit_clicked:
        print("⚠️ Submit for review button not clicked.")
        return bool(_order_review_submit_already_done(page))

    # Real success: confirmation copy and/or submit control gone or disabled after navigation/update
    page.wait_for_timeout(200)
    if _order_review_submit_already_done(page):
        print("✅ Order submitted for review (success text detected).")
        return True

    try:
        page.wait_for_function(
            """() => {
                const body = document.body && document.body.innerText ? document.body.innerText : '';
                if (/successfully submitted|has been submitted for review|thank you for submitting|your order has been submitted|awaiting review|pending review/i.test(body))
                    return true;
                const btns = [...document.querySelectorAll('button')];
                const still = btns.some(b => {
                    const t = (b.innerText || '').trim();
                    if (!/^Submit for review$/i.test(t) && !/Submit for review/i.test(t)) return false;
                    return b.offsetParent !== null && !b.disabled;
                });
                return !still;
            }""",
            timeout=12000,
        )
        print("✅ Order submitted for review (submit control cleared or success text detected).")
        return True
    except Exception:
        pass

    if _order_review_submit_already_done(page):
        return True

    print("⚠️ Submit was clicked but post-submit state was not confirmed within the timeout.")
    page.wait_for_timeout(1200)
    if _order_review_submit_already_done(page):
        print("✅ Order submitted for review (late success text).")
        return True
    return False

# ============================
# Location step: find postcode input (multiple strategies)
# ============================
def find_postcode_input(page):
    """Find the B-End postcode textbox on the location step. Tries label, placeholder, then textbox near Find."""
    for label_pat in [
        re.compile(r"^Postcode\s*\*?$", re.IGNORECASE),
        re.compile(r"Postcode", re.IGNORECASE),
    ]:
        try:
            tb = page.get_by_label(label_pat)
            if tb.count() > 0 and tb.first.is_visible(timeout=2000):
                return tb.first
        except Exception:
            pass
    for ph in ["postcode", "enter postcode", "e.g. SW1A 1AA"]:
        try:
            tb = page.get_by_placeholder(re.compile(re.escape(ph), re.IGNORECASE))
            if tb.count() > 0 and tb.first.is_visible(timeout=1500):
                return tb.first
        except Exception:
            pass
    # Form/section containing Find button
    try:
        container = page.locator("form").filter(has=page.get_by_role("button", name=re.compile(r"^Find$", re.IGNORECASE)))
        if container.count() > 0:
            tb = container.first.get_by_role("textbox").first
            if tb.is_visible(timeout=2000):
                return tb
    except Exception:
        pass
    return page.get_by_role("textbox").first


# ============================
# Product journey start (never use /quotes/new/location = Location journey)
# ============================
def start_product_journey(page, base_url: str):
    """
    Start PRODUCT journey only. Clicks Product's Start a quote, or goes to /quotes/new.
    Never goes to /quotes/new/location (that is the Location journey).
    """
    start_btns = page.get_by_role("button", name=re.compile(r"^Start a quote$", re.IGNORECASE))
    try:
        start_btns.first.wait_for(state="visible", timeout=2500)
        n = min(start_btns.count(), 6)
        # Product = 2nd button (index 1); Location = 1st (index 0). Use Product only.
        order = [1] + [i for i in range(n) if i != 1]
        for i in order:
            if i >= start_btns.count():
                continue
            b = start_btns.nth(i)
            try:
                if b.is_visible():
                    b.scroll_into_view_if_needed(timeout=2000)
                    b.click(timeout=4000)
                    print("✅ Clicked 'Start a quote' on welcome (Product journey).")
                    return
            except Exception:
                continue

        print("ℹ️ 'Start a quote' not clickable — going to /quotes/new (Product journey).")
        page.goto(f"{base_url}/quotes/new", wait_until="domcontentloaded")
    except Exception:
        print("ℹ️ No 'Start a quote' — going to /quotes/new (Product journey).")
        page.goto(f"{base_url}/quotes/new", wait_until="domcontentloaded")

def _extract_basket_id_from_page(page) -> str:
    """Extract Basket Id from current order page (same pattern as run_csv_regression)."""
    try:
        body = page.evaluate("() => document.body ? (document.body.innerText || '') : ''") or ""
        m = re.search(r"Basket\s*I[Dd]:\s*([0-9]+)", body, re.IGNORECASE)
        if not m:
            m = re.search(r"Basket\s*I[Dd]\s*([0-9]+)", body, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _scrape_demo34_order_surface(page, order_id: str, base_url: str) -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
    """Best-effort scrape of order page fields for summary CSV (internal or customer view).

    Returns (order_number, quote_number, quote_url_out, quotation_num, line_id, tcv_total,
             install_price, annual_rental, ftpp_aggregation, add_on, b_end_supplier).
    """
    order_number = ""
    quote_number = ""
    quote_url_out = ""
    quotation_num = ""
    line_id = ""
    tcv_total = ""
    install_price = ""
    annual_rental = ""
    ftpp_aggregation = ""
    add_on = ""
    b_end_supplier = ""
    base = (base_url or "").rstrip("/")
    try:
        page.wait_for_timeout(400)
        quote_link = None
        for _ in range(6):
            for loc in [
                page.locator("#quote-link"),
                page.get_by_role("link", name=re.compile(r"From quote:", re.IGNORECASE)),
                page.get_by_role("link", name=re.compile(r"Q-[a-f0-9-]+", re.IGNORECASE)),
                page.locator("a[href*='/quotes/']").filter(has_text=re.compile(r"Q-|From quote", re.IGNORECASE)),
            ]:
                try:
                    if loc.count() > 0 and loc.first.is_visible(timeout=1500):
                        quote_link = loc.first
                        break
                except Exception:
                    continue
            if quote_link is not None:
                break
            page.wait_for_timeout(2000)
        if quote_link is None and page.locator("#quote-link").count() > 0:
            quote_link = page.locator("#quote-link").first

        body = page.evaluate("() => document.body ? (document.body.innerText || '') : ''") or ""
        body = str(body)
        om = re.search(r"Order\s+(O-[a-f0-9]+)", body, re.IGNORECASE)
        if om:
            order_number = om.group(1).strip()
        elif order_id:
            order_number = "O-" + order_id[:8] if len(order_id) >= 8 else "O-" + order_id

        _money = r"([0-9][0-9,]*(?:\.\d{1,2})?)"
        if not install_price:
            for pat in (
                r"Install(?:\s+price)?\s*£\s*" + _money,
                r"Install[^£]{0,40}£\s*" + _money,
                r"Up[-\s]?front[^£]{0,60}£\s*" + _money,
            ):
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    install_price = m.group(1).replace(",", "")
                    break
        if not annual_rental:
            for pat in (
                r"Annual(?:\s+(?:Charge|charge|Rental|rental))?\s*£\s*" + _money,
                r"Annual[^£]{0,40}£\s*" + _money,
            ):
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    annual_rental = m.group(1).replace(",", "")
                    break
        if not ftpp_aggregation:
            for pat in (
                r"FTTP\s*Aggregation\s*£\s*" + _money,
                r"FTTP[^£]{0,50}£\s*" + _money,
            ):
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    ftpp_aggregation = m.group(1).replace(",", "")
                    break

        b_end_m = re.search(r"B-End\s*\(([^)]+)\)", body, re.IGNORECASE)
        if b_end_m:
            b_end_supplier = b_end_m.group(1).strip()

        if quote_link is not None:
            try:
                link_text = quote_link.inner_text(timeout=2000) or ""
                qm = re.search(r"(Q-[a-f0-9-]+)", link_text, re.IGNORECASE)
                if qm:
                    quote_number = qm.group(1).strip()
                href = quote_link.get_attribute("href")
                if href:
                    quote_url_out = href if href.startswith("http") else (base + href) if href.startswith("/") else ""
                if not quote_number and quote_url_out:
                    qum = re.search(r"/quotes/([^/?#]+)", quote_url_out)
                    if qum:
                        slug = qum.group(1).strip()
                        quote_number = "Q-" + slug[:12] if not slug.upper().startswith("Q-") else slug
            except Exception:
                pass
    except Exception:
        pass
    return (
        order_number,
        quote_number,
        quote_url_out,
        quotation_num,
        line_id,
        tcv_total,
        install_price,
        annual_rental,
        ftpp_aggregation,
        add_on,
        b_end_supplier,
    )


# ============================
# Demo 3 / 4 / 5 runner (internal quote+adjust; customer submit; optional internal place order + Basket ID poll)
# ============================
def run_preset_demo3_demo4(
    preset_path: Path,
    postcode_override: str | None,
    *,
    internal_place_order_after_customer: bool = True,
    capture_basket_id: bool,
    headless: bool = False,
) -> tuple[str, str, str, str, str, str, str, str, str, str, str, str, str, str, str, str]:
    """
    Returns (order_id, quotation_num, line_id, tcv_total, start_supplier, install_price, annual_rental,
             ftpp_aggregation, add_on, order_number, quote_number, order_url, quote_url,
             discount_install, discount_annual, basket_id).
    Uses internal NEOS user to create quote, adjust discounts, then customer to submit for review.
    Demo 4/5: internal logs back in and places order. Demo 5 also polls for Basket ID.
    Demo 3 (short): stops after customer submit (no internal place order / Basket polling).
    """
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    base_url = preset["base_url"].rstrip("/")
    q = preset["quote"].copy()
    billing = preset["billing"]
    if postcode_override:
        q["b_end_postcode"] = postcode_override.strip()
    creds = get_neos_internal_creds() if get_neos_internal_creds else None
    if not creds:
        raise RuntimeError("Demo 3/4/5 require neos_internal credentials in config.json.")

    with sync_playwright() as p:
        _sm_d = os.environ.get("P2NNI_PLAYWRIGHT_SLOW_MO", "").strip()
        slow_mo_d = 0 if headless else (int(_sm_d) if _sm_d.isdigit() else 35)
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo_d)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(5000)

        if not _login_internal_neos(page, base_url, creds):
            context.close()
            browser.close()
            raise RuntimeError("Internal login failed.")

        page.goto(f"{base_url}/welcome", wait_until="domcontentloaded", timeout=60000)
        print("✅ Portal opened (internal).")

        start_product_journey(page, base_url)
        try:
            # Speed: don't block long on networkidle here; product tile can be clickable before full idle.
            page.wait_for_load_state("networkidle", timeout=2500)
        except Exception:
            pass
        page.wait_for_timeout(80)

        tile = page.get_by_text(q["product_tile"])
        tile_visible = tile.count() > 0 and tile.first.is_visible(timeout=2500)
        if not tile_visible:
            page.wait_for_timeout(120)
            tile_visible = tile.count() > 0 and tile.first.is_visible(timeout=1200)
        if tile_visible:
            print(f"🖱 Selecting product: {q['product_tile']}")
            safe_click(tile)
            page.wait_for_timeout(150)
            next_btn = page.get_by_role("button", name=re.compile(r"^Next$", re.IGNORECASE))
            if next_btn.count() > 0 and next_btn.first.is_visible(timeout=2000):
                next_btn.first.click(timeout=5000)
                page.wait_for_timeout(120)
            print("✅ Product selected.")
        else:
            print("ℹ️ Product tile not visible — may already be on location step.")

        find_btn = page.get_by_role("button", name=re.compile(r"^Find$", re.IGNORECASE))
        try:
            find_btn.first.wait_for(state="visible", timeout=35000)
        except Exception:
            try:
                page.get_by_text(re.compile(r"New quote|Location|postcode", re.IGNORECASE)).first.wait_for(state="visible", timeout=15000)
            except Exception:
                pass
        page.wait_for_timeout(200)

        postcode_tb = find_postcode_input(page)
        safe_fill(postcode_tb, q["b_end_postcode"], timeout=25000)
        safe_click(page.get_by_role("button", name=re.compile(r"^Find$", re.IGNORECASE)), timeout=35000)
        page.wait_for_timeout(3000)

        page.set_default_timeout(5000)
        try:
            optional_select_nni_dropdown(page, q.get("select_first_nni", True), b_end_postcode=q.get("b_end_postcode"))
            optional_choose_location_dropdown(page, q.get("select_first_choose_location", False))
            optional_shadow_vlan(page, q.get("shadow_vlan_required", False))
        finally:
            page.set_default_timeout(5000)

        next_btn = page.get_by_role("button", name=re.compile(r"^Next$", re.IGNORECASE))
        if next_btn.count() > 0:
            try:
                click_when_enabled(next_btn, timeout_ms=20000)
            except Exception as e:
                print(f"ℹ️ Next button not enabled in time: {e}")
                page.wait_for_timeout(1800)
                optional_select_nni_dropdown(page, q.get("select_first_nni", True), b_end_postcode=q.get("b_end_postcode"))
                page.wait_for_timeout(1000)
                try:
                    click_when_enabled(next_btn, timeout_ms=15000)
                except Exception as e2:
                    print(f"ℹ️ Next still not enabled after retry: {e2}")
        else:
            print("ℹ️ Next button not visible.")

        bearer_val = (q.get("bearer") or "")
        if isinstance(bearer_val, str):
            bearer_val = bearer_val.strip().replace("\ufeff", "").strip() or None
        select_access_and_configuration(
            page, access_type=q.get("access_type"), bearer=bearer_val, bandwidth=q.get("bandwidth"),
            contract_term=q.get("contract_term"), pause=False,
        )

        # Same as Demo 1/2: wait for pricing UI (in-browser polling).
        bearer_lower = str(q.get("bearer", "") or "").lower().replace(" ", "")
        is_10g = bearer_lower in ("10gbps", "10 gbps")
        timeout_ms = 60000 if is_10g else 20000
        try:
            print("⏳ Waiting for pricing UI…")
            _wait_for_pricing_ui_ready(page, timeout_ms=timeout_ms)
        except Exception as e:
            context.close()
            browser.close()
            raise RuntimeError(
                f"Neither Publish nor Proceed to order appeared. {e}"
            ) from e

        start_supplier = ""
        _KNOWN_PROVIDERS = ["Virgin Media", "Virgin", "Neos Networks via Openreach", "Neos via Openreach", "Neos Networks", "PXC", "Sky via Openreach", "Sky via ITS", "BT Wholesale", "Openreach", "via Openreach", "CityFibre", "Colt", "Vodafone National", "Vorboss"]

        def _extract_provider(txt: str) -> str:
            t = (txt or "").strip()
            for p in _KNOWN_PROVIDERS:
                if p in t:
                    return "Neos via Openreach" if p == "via Openreach" else p
            return ""

        def _supplier_matches(preferred: str, tile_provider: str) -> bool:
            if not preferred or not tile_provider:
                return False
            p, t = preferred.strip().lower(), tile_provider.strip().lower()
            p_compact, t_compact = re.sub(r"\s+", "", p), re.sub(r"\s+", "", t)
            if p_compact == "btws" and "bt" in t_compact and "wholesale" in t:
                return True
            if p == t:
                return True
            if p == "virgin" and t == "virgin media":
                return True
            if p == "virgin media" and t == "virgin":
                return True
            if p in t or t in p:
                return True  # e.g. "neos" in "neos via openreach"
            return False

        try:
            page.get_by_test_id("price-tile").first.wait_for(state="visible", timeout=8000)
            # Very short settle time before Adjust quote (keep total gap < ~3s after supplier click)
            page.wait_for_timeout(300)
            preferred_supplier = (q.get("preferred_supplier") or "").strip()
            if preferred_supplier and preferred_supplier.lower().startswith("no specified"):
                preferred_supplier = ""
            if preferred_supplier:
                try:
                    if preferred_supplier.lower() == "sky via openreach":
                        # Limit carousel scans and waits so selection → Adjust quote stays fast
                        for _ in range(4):
                            tile_with_logo = page.locator("button[data-testid='price-tile']").filter(
                                has=page.locator("img.supplier_image[src*='sky']")
                            )
                            if tile_with_logo.count() > 0:
                                try:
                                    tile_with_logo.first.scroll_into_view_if_needed()
                                    tile_with_logo.first.click(timeout=5000)
                                    page.wait_for_timeout(150)
                                except Exception:
                                    pass
                                start_supplier = "Sky via Openreach"
                                break
                            next_ar = page.locator("button.slick-arrow.slick-next")
                            if next_ar.count() == 0:
                                break
                            try:
                                next_ar.first.click(timeout=1500)
                            except Exception:
                                break
                            page.wait_for_timeout(150)
                    else:
                        # Generic preferred supplier: scan a few pages quickly, minimal waits
                        for _ in range(4):
                            tiles = page.get_by_test_id("price-tile")
                            for j in range(min(tiles.count(), 12)):
                                try:
                                    txt = tiles.nth(j).inner_text(timeout=1500) or ""
                                    prov = _extract_provider(txt)
                                    if prov and _supplier_matches(preferred_supplier, prov):
                                        try:
                                            tiles.nth(j).scroll_into_view_if_needed()
                                            tiles.nth(j).click(timeout=4000)
                                            page.wait_for_timeout(120)
                                        except Exception:
                                            pass
                                        start_supplier = prov
                                        break
                                    if preferred_supplier and txt and preferred_supplier.lower() in txt.lower():
                                        try:
                                            tiles.nth(j).scroll_into_view_if_needed()
                                            tiles.nth(j).click(timeout=4000)
                                            page.wait_for_timeout(150)
                                        except Exception:
                                            pass
                                        start_supplier = prov or preferred_supplier
                                        break
                                except Exception:
                                    continue
                            if start_supplier:
                                break
                            next_ar = page.locator("button.slick-arrow.slick-next")
                            if next_ar.count() == 0:
                                break
                            try:
                                next_ar.first.click(timeout=1500)
                            except Exception:
                                break
                            page.wait_for_timeout(150)
                except Exception:
                    pass
            # Selected (green / aria-selected) tile — do not overwrite preferred_supplier with first carousel tile.
            tiles = page.get_by_test_id("price-tile")
            n = min(tiles.count(), 8)
            for i in range(n):
                t = tiles.nth(i)
                try:
                    has_green = t.evaluate("""el => {
                        const isGreen = (e) => {
                            const s = getComputedStyle(e);
                            for (const prop of ['backgroundColor','borderColor','borderTopColor','outlineColor']) {
                                const v = (s[prop] || '').trim();
                                const rgb = v.match(/rgb\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)\\s*\\)/);
                                if (rgb) {
                                    const r=+rgb[1], g=+rgb[2], b=+rgb[3];
                                    if (g > 70 && g > r && g > b) return true;
                                }
                                if (v.includes('green') || /^#[0-9a-fA-F]{3,8}$/.test(v)) return true;
                            }
                            return false;
                        };
                        if (el.getAttribute('data-selected')==='true' || el.getAttribute('aria-selected')==='true') return true;
                        const cls = (el.className||'') + ' ' + (el.parentElement?.className||'');
                        if (/selected|is-selected|active|highlight/.test(cls)) return true;
                        if (isGreen(el)) return true;
                        for (const k of el.querySelectorAll('*')) { if (isGreen(k)) return true; }
                        return false;
                    }""")
                    if has_green and not start_supplier:
                        txt = t.inner_text(timeout=500) or ""
                        start_supplier = _extract_provider(txt)
                        if start_supplier:
                            break
                except Exception:
                    continue
            if not start_supplier and n >= 1:
                try:
                    start_supplier = _extract_provider(tiles.first.inner_text(timeout=500) or "")
                except Exception:
                    pass
        except Exception:
            pass

        # Gap 1 (Virgin → Adjust quote): overlay gone (max 3s) then minimal scroll/waits
        _wait_for_updating_overlay_gone(page, timeout_ms=3000)
        pay_upfront = q.get("pay_upfront", True)
        upfront_wrapper = "#wrapper-amortise-up-front" if pay_upfront else "#wrapper-amortise-spread-costs"
        try:
            page.locator(upfront_wrapper).first.wait_for(state="attached", timeout=1500)
            page.locator(upfront_wrapper).first.scroll_into_view_if_needed(timeout=800)
            page.wait_for_timeout(50)
        except Exception:
            try:
                up_el = page.get_by_text(re.compile(r"Amounts shown|up-front|circuit charge", re.IGNORECASE))
                if up_el.count() > 0 and up_el.first.is_visible(timeout=800):
                    up_el.first.scroll_into_view_if_needed(timeout=500)
                    page.wait_for_timeout(50)
            except Exception:
                pass
        toggle_upfront_charge(page, pay_upfront)
        page.wait_for_timeout(50)

        # Demo 3/4: Adjust quote (discounts + Recalculate)
        list_install_str, list_annual_str = _scrape_list_prices_from_quote_page(page)
        list_install = _parse_price(q.get("list_install") or list_install_str)
        list_annual = _parse_price(q.get("list_annual") or list_annual_str)
        negotiated_install = _parse_price(q.get("negotiated_install"))
        negotiated_annual = _parse_price(q.get("negotiated_annual"))
        install_discount = max(0.0, list_install - negotiated_install)
        annual_discount = max(0.0, list_annual - negotiated_annual)
        discount_install_str = f"{install_discount:.2f}".rstrip("0").rstrip(".")
        discount_annual_str = f"{annual_discount:.2f}".rstrip("0").rstrip(".")
        adjust_quote_discounts(page, discount_install_str, discount_annual_str)
        page.wait_for_timeout(50)

        # FTTP: use same robust flow as main preset (Demo 1/2) so "Proceed to order" enables reliably
        page.wait_for_timeout(200)  # Let discount recalc settle before FTTP
        apply_fttp_aggregation_with_fallback(page, q.get("fttp_aggregation", False))
        page.wait_for_timeout(300)

        # Gap 2 (FTTP → Publish): wait for overlay gone and allow time for button to enable
        _wait_for_updating_overlay_gone(page, timeout_ms=5000)
        page.wait_for_timeout(1500)  # Let Proceed to order become enabled after FTTP
        publish_and_proceed_to_order(page)

        # Wait for orders URL
        try:
            page.wait_for_url(re.compile(r".*/orders/.*"), timeout=60000)
        except Exception:
            pass

        if not is_on_order_page(page):
            print(f"⚠️ Not confidently detected order page yet. Current URL: {page.url}")
            page.wait_for_timeout(500)

        # Order ID and URL up front (needed for Demo 4 customer → internal flow)
        order_id = ""
        url = page.url or ""
        match = re.search(r"/orders/([^/?]+)", url)
        if match:
            order_id = match.group(1).strip()
        order_url_out = (base_url.rstrip("/") + "/orders/" + order_id) if order_id else (url or "")

        # ---------- Demo 3/4/5: internal fills billing → customer submits → (optional) internal places order + Basket poll ----------
        basket_id = ""
        order_number = ""
        quote_number = ""
        quote_url_out = ""
        quotation_num = ""
        line_id = ""
        tcv_total = ""
        install_price = ""
        annual_rental = ""
        ftpp_aggregation = ""
        add_on = ""

        fill_order_billing_screen(
            page,
            billing,
            ro2_diversity=q.get("ro2_diversity", False),
            b_end_postcode=q.get("b_end_postcode"),
            sc_toggles=preset.get("site_config"),
            bearer=q.get("bearer", ""),
            bandwidth=q.get("bandwidth", ""),
            submit_for_review=False,
            shadow_vlan_required=q.get("shadow_vlan_required", True),
        )
        if not _ensure_internal_order_ready_before_customer_submit(
            page,
            billing,
            q.get("b_end_postcode"),
            preset.get("site_config"),
            q.get("bearer", ""),
            q.get("bandwidth", ""),
        ):
            print(
                "⚠️ Internal readiness check did not confirm submit state; "
                "continuing to customer switch anyway."
            )

        # Change to Customer: true session switch (avoids stale auth.json acting as wrong role).
        print("🔄 Switching to Customer (fresh session) to submit order for review…")
        try:
            context.close()
        except Exception:
            pass

        cust_context = browser.new_context()
        cust_page = cust_context.new_page()
        cust_page.set_default_timeout(10000)
        customer_submitted_ok = False
        try:
            cust_creds = get_customer_creds() if get_customer_creds else None
            cust_page.goto(base_url.rstrip("/") + "/login", wait_until="domcontentloaded", timeout=60000)
            if cust_creds:
                login_ok = _login_customer_page(cust_page, base_url, cust_creds)
                if login_ok:
                    try:
                        cust_context.storage_state(path=str(AUTH_STATE_PATH))
                    except Exception:
                        pass
                else:
                    print("⚠️ Customer auto-login failed; waiting for manual login...")

            if "/login" in (cust_page.url or ""):
                print("⏳ Waiting for manual customer login (leave /login to continue)…")
                for _ in range(150):  # ~5 minutes
                    cust_page.wait_for_timeout(2000)
                    if "/login" not in (cust_page.url or ""):
                        break
                else:
                    print("⚠️ Customer login timed out — cannot submit for review.")

                if "/login" not in (cust_page.url or ""):
                    try:
                        cust_context.storage_state(path=str(AUTH_STATE_PATH))
                    except Exception:
                        pass

            cust_page.goto(order_url_out, wait_until="domcontentloaded", timeout=60000)

            if "/login" not in (cust_page.url or ""):
                ok = submit_order_for_review(cust_page)
                if ok:
                    customer_submitted_ok = True
                    print("✅ Customer submitted order for review.")
                else:
                    print("⚠️ Customer submission for review did not complete (Submit not clicked / success not detected).")
            else:
                print("⚠️ Still on /login; skipping customer submit.")

            if customer_submitted_ok and not internal_place_order_after_customer:
                print("✅ Short demo: stopping after customer submit (no internal place order / Basket ID poll).")
                (
                    order_number,
                    quote_number,
                    quote_url_out,
                    quotation_num,
                    line_id,
                    tcv_total,
                    install_price,
                    annual_rental,
                    ftpp_aggregation,
                    add_on,
                    b_end_supplier,
                ) = _scrape_demo34_order_surface(cust_page, order_id, base_url)
                if b_end_supplier:
                    start_supplier = b_end_supplier
        except Exception as e:
            print(f"⚠️ Customer submit step failed: {e}")
        finally:
            cust_context.close()

        if not customer_submitted_ok:
            msg = "Demo 3/4/5: customer submission for review did not complete."
            if internal_place_order_after_customer:
                msg += " Refusing to place order as internal user."
            raise RuntimeError(msg)

        if internal_place_order_after_customer:
            print("🔄 Switching back to internal user to place order…")
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(5000)
            if not _login_internal_neos(page, base_url, creds):
                context.close()
                browser.close()
                raise RuntimeError("Internal login failed after customer submit (Demo 4/5).")

            page.goto(order_url_out, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                page.wait_for_timeout(800)
            except Exception:
                pass
            try:
                btn = page.locator("button.accept-btn").first
                try:
                    btn.wait_for(state="visible", timeout=60000)
                except Exception:
                    btn = page.get_by_role("button", name=re.compile(r"Place order", re.IGNORECASE)).first
                    btn.wait_for(state="visible", timeout=60000)
                print("🟧 Clicking 'Place order' as internal user…")
                btn.scroll_into_view_if_needed(timeout=5000)
                try:
                    expect(btn).to_be_enabled(timeout=20000)
                except Exception:
                    pass
                btn.click(timeout=30000)
                try:
                    page.get_by_text(re.compile(r"Order Accepted", re.IGNORECASE)).first.wait_for(state="visible", timeout=30000)
                except Exception:
                    pass
                ok_btn = page.get_by_role("button", name=re.compile(r"^OK$", re.IGNORECASE))
                if ok_btn.count() > 0:
                    ok_btn.first.scroll_into_view_if_needed(timeout=5000)
                    ok_btn.first.click(timeout=30000)
                    print("✅ Order Accepted dialog confirmed.")
                page.goto(order_url_out, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"⚠️ Place order / OK failed: {e}")

            if capture_basket_id:
                refresh_interval_ms = 5000
                max_attempts = 18
                print("⏳ Waiting for Basket Id (refreshing every 5s, up to ~90s)…")
                for attempt in range(1, max_attempts + 1):
                    try:
                        if attempt == 1 or attempt % 3 == 0:
                            print(f"  ⏳ BasketId not ready yet (attempt {attempt}/{max_attempts})…")
                        page.goto(order_url_out, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(refresh_interval_ms)
                        basket_id = _extract_basket_id_from_page(page)
                        if basket_id:
                            print(f"✅ BasketId captured: {basket_id}")
                            break
                    except Exception as e:
                        print(f"  ℹ️ Poll attempt {attempt}: {e}")
                        continue
                if not basket_id:
                    print("⚠️ Basket Id not found within timeout.")
            else:
                page.wait_for_timeout(600)

            (
                order_number,
                quote_number,
                quote_url_out,
                quotation_num,
                line_id,
                tcv_total,
                install_price,
                annual_rental,
                ftpp_aggregation,
                add_on,
                b_end_supplier,
            ) = _scrape_demo34_order_surface(page, order_id, base_url)
            if b_end_supplier:
                start_supplier = b_end_supplier

        browser.close()
        return (
            order_id,
            quotation_num,
            line_id,
            tcv_total,
            start_supplier,
            install_price,
            annual_rental,
            ftpp_aggregation,
            add_on,
            order_number,
            quote_number,
            order_url_out,
            quote_url_out,
            discount_install_str,
            discount_annual_str,
            basket_id,
        )


# ============================
# Main preset runner
# ============================
def run_preset(preset_path: Path, postcode_override: str | None = None, headless: bool = False, pause: bool = False):
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    base_url = preset["base_url"]
    q = preset["quote"].copy()
    billing = preset["billing"]
    sc = preset.get("site_config", {})
    # Bearer/bandwidth constraint validation
    try:
        from p2nni_constraints import validate_row
        errs = validate_row(
            bearer=q.get("bearer"),
            bandwidth=q.get("bandwidth"),
            connector_type=sc.get("connector_type"),
            media_type=sc.get("media_type"),
            power_supply=sc.get("power_supply"),
            auto_negotiation="Yes" if sc.get("auto_negotiation") else "No",
            vlan_tagging="Yes" if sc.get("vlan_tagging") else "No",
        )
        if errs:
            raise RuntimeError("Invalid options for Bearer/Bandwidth: " + "; ".join(errs))
    except ImportError:
        pass
    if postcode_override:
        q["b_end_postcode"] = postcode_override.strip()
        print(f"📍 Postcode override: {q['b_end_postcode']}")

    with sync_playwright() as p:
        # slow_mo=0 for headless; light delay when headful (Demo 2 visible) — was 80ms, now ~35ms to cut ~30–40s/run.
        _sm = os.environ.get("P2NNI_PLAYWRIGHT_SLOW_MO", "").strip()
        slow_mo = 0 if headless else (int(_sm) if _sm.isdigit() else 35)
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context_kwargs = {}
        if AUTH_STATE_PATH.exists():
            context_kwargs["storage_state"] = str(AUTH_STATE_PATH)

        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(5000)  # Cap all actions at 5s unless explicit (was 30s)

        # Start from welcome to ensure session is valid
        page.goto(f"{base_url}/welcome", wait_until="domcontentloaded", timeout=60000)
        if "/login" in page.url:
            raise RuntimeError("Redirected to /login. auth.json is stale — run login_once.py again.")
        print("✅ Portal opened.")

        start_product_journey(page, base_url)
        try:
            # Speed: don't block long on networkidle here; product tile can be clickable before full idle.
            page.wait_for_load_state("networkidle", timeout=2500)
        except Exception:
            pass
        page.wait_for_timeout(80)

        # Product tile step: select product then Next → location step (Product journey)
        tile = page.get_by_text(q["product_tile"])
        tile_visible = tile.count() > 0 and tile.first.is_visible(timeout=2500)
        if not tile_visible:
            page.wait_for_timeout(120)
            tile_visible = tile.count() > 0 and tile.first.is_visible(timeout=1200)
        if tile_visible:
            print(f"🖱 Selecting product: {q['product_tile']}")
            safe_click(tile)
            page.wait_for_timeout(150)
            next_btn = page.get_by_role("button", name=re.compile(r"^Next$", re.IGNORECASE))
            if next_btn.count() > 0 and next_btn.first.is_visible(timeout=2000):
                next_btn.first.click(timeout=5000)
                page.wait_for_timeout(120)
            print("✅ Product selected.")
        else:
            print("ℹ️ Product tile not visible — may already be on location step.")

        # Wait for location step (postcode + Find) — do NOT go to /quotes/new/location
        find_btn = page.get_by_role("button", name=re.compile(r"^Find$", re.IGNORECASE))
        try:
            find_btn.first.wait_for(state="visible", timeout=35000)  # Page can load slowly
        except Exception:
            try:
                page.get_by_text(re.compile(r"New quote|Location|postcode", re.IGNORECASE)).first.wait_for(state="visible", timeout=15000)
            except Exception:
                pass
        page.wait_for_timeout(200)

        # B-End postcode + Find
        postcode_tb = find_postcode_input(page)
        safe_fill(postcode_tb, q["b_end_postcode"], timeout=25000)
        safe_click(page.get_by_role("button", name=re.compile(r"^Find$", re.IGNORECASE)), timeout=35000)
        page.wait_for_timeout(1700)  # Let address + NNI load (was 3s; trim for Demo 1/2 speed)

        # Cap at 5s - was 2.5s but NNI click needs more time to be stable
        page.set_default_timeout(5000)
        try:
            # NNI first (primary "Search for NNI and data centre"), then Choose location only when enabled
            optional_select_nni_dropdown(page, q.get("select_first_nni", True), b_end_postcode=q.get("b_end_postcode"))
            optional_choose_location_dropdown(page, q.get("select_first_choose_location", False))
            optional_shadow_vlan(page, q.get("shadow_vlan_required", False))
        finally:
            page.set_default_timeout(5000)

        # Next to config (wait for button to be enabled after location validated)
        next_btn = page.get_by_role("button", name=re.compile(r"^Next$", re.IGNORECASE))
        if next_btn.count() > 0:
            try:
                click_when_enabled(next_btn, timeout_ms=20000)
            except Exception as e:
                print(f"ℹ️ Next button not enabled in time: {e}")
                # Retry: NNI may not have been selected in time; wait and try NNI + Next again
                page.wait_for_timeout(1800)
                optional_select_nni_dropdown(page, q.get("select_first_nni", True), b_end_postcode=q.get("b_end_postcode"))
                page.wait_for_timeout(1000)
                try:
                    click_when_enabled(next_btn, timeout_ms=15000)
                except Exception as e2:
                    print(f"ℹ️ Next still not enabled after retry: {e2}")
        else:
            print("ℹ️ Next button not visible — config may already be on this page.")

        # Select bearer/bandwidth/access and price (--pause will open Inspector at bearer step)
        bearer_val = (q.get("bearer") or "")
        if isinstance(bearer_val, str):
            bearer_val = bearer_val.strip().replace("\ufeff", "").strip() or None
        select_access_and_configuration(
            page,
            access_type=q.get("access_type"),
            bearer=bearer_val,
            bandwidth=q.get("bandwidth"),
            contract_term=q.get("contract_term"),
            pause=pause,
        )

        # Wait for pricing UI (in-browser polling — faster than Python evaluate loops).
        bearer_lower = str(q.get("bearer", "") or "").lower().replace(" ", "")
        is_10g = bearer_lower in ("10gbps", "10 gbps")
        timeout_ms = 60000 if is_10g else 20000
        try:
            print("⏳ Waiting for pricing UI…")
            _wait_for_pricing_ui_ready(page, timeout_ms=timeout_ms)
        except Exception as e:
            raise RuntimeError(
                f"Pricing UI did not become ready within {'60s' if is_10g else '20s'}. "
                f"Bearer/bandwidth selection may have failed, or pricing is slow. Check bearer '{q.get('bearer')}' and postcode '{q.get('b_end_postcode')}'. {e}"
            ) from e

        # RO2 diversity currently disabled in automation (feature temporarily turned off)
        if q.get("ro2_diversity", False):
            print("ℹ️ RO2 diversity option is currently disabled; skipping RO2 flow.")

        # Capture / optionally select Start Supplier from the broadband price tiles
        start_supplier = ""
        _KNOWN_PROVIDERS = ["Virgin Media", "Virgin", "Neos Networks via Openreach", "Neos via Openreach", "Neos Networks", "PXC", "Sky via Openreach", "Sky via ITS", "BT Wholesale", "Openreach", "via Openreach", "CityFibre", "Colt", "Vodafone National", "Vorboss"]

        def _extract_provider_from_text(txt: str) -> str:
            t = (txt or "").strip()
            for p in _KNOWN_PROVIDERS:
                if p in t:
                    if p == "via Openreach":
                        return "Neos via Openreach"
                    return p
            return ""

        def _supplier_matches(preferred: str, tile_provider: str) -> bool:
            if not preferred or not tile_provider:
                return False
            p, t = preferred.strip().lower(), tile_provider.strip().lower()
            p_compact, t_compact = re.sub(r"\s+", "", p), re.sub(r"\s+", "", t)
            if p_compact == "btws" and "bt" in t_compact and "wholesale" in t:
                return True
            if p == t:
                return True
            if p == "virgin" and t == "virgin media":
                return True
            if p == "virgin media" and t == "virgin":
                return True
            if p in t or t in p:
                return True
            return False

        try:
            page.get_by_test_id("price-tile").first.wait_for(state="visible", timeout=8000)
            page.wait_for_timeout(400)

            # If the preset requested a specific supplier, try to select that tile first.
            preferred_supplier = (q.get("preferred_supplier") or "").strip()
            if preferred_supplier and preferred_supplier.lower().startswith("no specified"):
                preferred_supplier = ""
            if preferred_supplier:
                try:
                    matched = False

                    # Special-case handling for Sky via Openreach: use the supplier logo image,
                    # because the visible text on the tile is just "via Openreach".
                    if preferred_supplier.lower() == "sky via openreach":
                        logo_selector = "img.supplier_image[src*='sky']"

                        for _ in range(8):  # up to 8 carousel pages
                            tile_with_logo = page.locator("button[data-testid='price-tile']").filter(
                                has=page.locator(logo_selector)
                            )
                            if tile_with_logo.count() > 0:
                                tile = tile_with_logo.first
                                try:
                                    tile.scroll_into_view_if_needed()
                                except Exception:
                                    pass
                                try:
                                    tile.click(timeout=5000)
                                    page.wait_for_timeout(100)
                                except Exception:
                                    # Even if click fails, let fallback logic run.
                                    pass
                                start_supplier = "Sky via Openreach"
                                matched = True
                                print("✅ Selected preferred supplier tile via logo: Sky via Openreach")
                                break

                            # Advance carousel if possible
                            next_btn = page.locator("button.slick-arrow.slick-next")
                            if next_btn.count() == 0:
                                break
                            try:
                                next_btn.first.scroll_into_view_if_needed()
                            except Exception:
                                pass
                            try:
                                next_btn.first.click(timeout=2000)
                            except Exception:
                                break
                            page.wait_for_timeout(150)

                    else:
                        def _try_match_current_tiles() -> str:
                            tiles_local = page.get_by_test_id("price-tile")
                            n_local = min(tiles_local.count(), 20)
                            for j in range(n_local):
                                tile = tiles_local.nth(j)
                                try:
                                    txt_local = tile.inner_text(timeout=2000) or ""
                                except Exception:
                                    continue
                                prov_local = _extract_provider_from_text(txt_local)
                                if prov_local and _supplier_matches(preferred_supplier, prov_local):
                                    try:
                                        tile.scroll_into_view_if_needed()
                                    except Exception:
                                        pass
                                    try:
                                        tile.click(timeout=5000)
                                        page.wait_for_timeout(100)
                                    except Exception:
                                        # Even if click fails, we still let fallback logic run.
                                        pass
                                    print(f"✅ Selected preferred supplier tile: {prov_local}")
                                    return prov_local
                            return ""

                        # Some suppliers are on later "pages" of the price carousel; click the next-arrow
                        # a few times to cycle through all tiles until we see the requested supplier.
                        for _ in range(8):  # up to 8 carousel pages
                            prov_found = _try_match_current_tiles()
                            if prov_found:
                                start_supplier = prov_found
                                matched = True
                                break
                            # Try to advance the carousel; if no next arrow, stop.
                            next_btn = page.locator("button.slick-arrow.slick-next")
                            if next_btn.count() == 0:
                                break
                            try:
                                next_btn.first.scroll_into_view_if_needed()
                            except Exception:
                                pass
                            try:
                                next_btn.first.click(timeout=2000)
                            except Exception:
                                break
                            page.wait_for_timeout(150)

                    if not matched:
                        print(f"ℹ️ Preferred supplier '{preferred_supplier}' not found in price tiles; using default/cheapest option.")
                except Exception as e:
                    print(f"ℹ️ Error while trying to select preferred supplier '{preferred_supplier}'; falling back to default tile. {e}")

            tiles = page.get_by_test_id("price-tile")
            n = min(tiles.count(), 8)  # speed: limit supplier scan

            for i in range(n):
                t = tiles.nth(i)
                try:
                    has_green = t.evaluate("""el => {
                        const isGreen = (e) => {
                            const s = getComputedStyle(e);
                            for (const prop of ['backgroundColor','borderColor','borderTopColor','outlineColor']) {
                                const v = (s[prop] || '').trim();
                                const rgb = v.match(/rgb\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)\\s*\\)/);
                                if (rgb) {
                                    const r=+rgb[1], g=+rgb[2], b=+rgb[3];
                                    if (g > 70 && g > r && g > b) return true;
                                }
                                if (v.includes('green') || /^#[0-9a-fA-F]{3,8}$/.test(v)) return true;
                            }
                            return false;
                        };
                        if (el.getAttribute('data-selected')==='true' || el.getAttribute('aria-selected')==='true') return true;
                        const cls = (el.className||'') + ' ' + (el.parentElement?.className||'');
                        if (/selected|is-selected|active|highlight/.test(cls)) return true;
                        if (isGreen(el)) return true;
                        for (const k of el.querySelectorAll('*')) { if (isGreen(k)) return true; }
                        return false;
                    }""")
                    if has_green and not start_supplier:
                        txt = t.inner_text(timeout=500) or ""
                        start_supplier = _extract_provider_from_text(txt)
                        if start_supplier:
                            break
                except Exception:
                    continue
            if not start_supplier and n >= 1:
                txt = tiles.first.inner_text(timeout=500) or ""
                start_supplier = _extract_provider_from_text(txt)
        except Exception:
            pass

        # CSV Yes = pay upfront; portal "Pay up-front circuit charge" = pay. If portal shows opposite, invert.
        toggle_upfront_charge(page, q.get("pay_upfront", True))
        page.wait_for_timeout(150)
        _wait_for_updating_overlay_gone(page, timeout_ms=5000)
        page.wait_for_timeout(300)
        apply_fttp_aggregation_with_fallback(page, q.get("fttp_aggregation", False))
        publish_and_proceed_to_order(page)

        # Wait for orders URL
        try:
            page.wait_for_url(re.compile(r".*/orders/.*"), timeout=60000)
        except Exception:
            pass

        if not is_on_order_page(page):
            print(f"⚠️ Not confidently detected order page yet. Current URL: {page.url}")
            page.wait_for_timeout(250)

        fill_order_billing_screen(
            page,
            billing,
            ro2_diversity=q.get("ro2_diversity", False),
            b_end_postcode=q.get("b_end_postcode"),
            sc_toggles=preset.get("site_config"),
            bearer=q.get("bearer", ""),
            bandwidth=q.get("bandwidth", ""),
            shadow_vlan_required=q.get("shadow_vlan_required", True),
        )

        # Order ID from URL (e.g. .../orders/abc-123)
        order_id = None
        url = page.url or ""
        match = re.search(r"/orders/([^/?]+)", url)
        if match:
            order_id = match.group(1).strip()

        # Wait for "From quote: Q-xxx" link to appear (order must be submitted first)
        page.wait_for_timeout(700)  # Let order page update after submit
        quote_link = None
        for wait_attempt in range(6):  # Up to ~18s for link to appear after submit
            for loc in [
                page.locator("#quote-link"),
                page.get_by_role("link", name=re.compile(r"From quote:", re.IGNORECASE)),
                page.get_by_role("link", name=re.compile(r"Q-[a-f0-9-]+", re.IGNORECASE)),
                page.locator("a[href*='/quotes/']").filter(has_text=re.compile(r"Q-|From quote", re.IGNORECASE)),
            ]:
                if loc.count() > 0 and loc.first.is_visible(timeout=2000):
                    quote_link = loc.first
                    break
            if quote_link is not None:
                break
            page.wait_for_timeout(2000)
        if quote_link is None:
            quote_link = page.locator("#quote-link").first if page.locator("#quote-link").count() > 0 else None

        # Capture order/quote refs and scrape pricing + B-End provider from order page (no quote navigation)
        order_number = ""
        quote_number = ""
        order_url = (base_url.rstrip("/") + "/orders/" + order_id) if order_id else (url or "")
        quote_url = ""
        quotation_num = ""
        line_id = ""
        tcv_total = ""
        install_price = ""
        annual_rental = ""
        ftpp_aggregation = ""
        add_on = ""
        try:
            body = page.evaluate("""() => document.body ? (document.body.innerText || '') : ''""")
            body = str(body or "")
            om = re.search(r"Order\s+(O-[a-f0-9]+)", body, re.IGNORECASE)
            if om:
                order_number = om.group(1).strip()
            elif order_id:
                order_number = "O-" + order_id[:8] if len(order_id) >= 8 else "O-" + order_id
            if quote_link and quote_link.count() > 0:
                try:
                    link_text = quote_link.inner_text(timeout=2000) or ""
                    qm = re.search(r"(Q-[a-f0-9]+)", link_text, re.IGNORECASE)
                    if qm:
                        quote_number = qm.group(1).strip()
                    href = quote_link.get_attribute("href")
                    if href:
                        quote_url = href if href.startswith("http") else (base_url.rstrip("/") + href) if href.startswith("/") else ""
                    if not quote_number and quote_url:
                        qum = re.search(r"/quotes/([^/?]+)", quote_url)
                        if qum:
                            quote_number = "Q-" + qum.group(1)[:8] if len(qum.group(1)) >= 8 else "Q-" + qum.group(1)
                except Exception:
                    pass
            # B-End broadband provider: "B-End (Virgin)" -> Virgin
            b_end_m = re.search(r"B-End\s*\(([^)]+)\)", body, re.IGNORECASE)
            if b_end_m:
                start_supplier = b_end_m.group(1).strip()
            # Term & Price on order page: Install £250.00, FTTP Aggregation £0.00, Annual £6,550.58
            install_m = re.search(r"Install\s*£\s*([0-9,]+\.\d{2})", body, re.IGNORECASE)
            if install_m:
                install_price = install_m.group(1).replace(",", "")
            fttp_m = re.search(r"FTTP\s+Aggregation\s*£\s*([0-9,]+\.\d{2})", body, re.IGNORECASE)
            if fttp_m:
                ftpp_aggregation = fttp_m.group(1).replace(",", "")
            annual_m = re.search(r"Annual\s*£\s*([0-9,]+\.\d{2})", body, re.IGNORECASE)
            if annual_m:
                annual_rental = annual_m.group(1).replace(",", "")
        except Exception:
            pass

        print(f"✅ Finished preset: {preset['id']}")
        print(f"📌 Final URL: {page.url}")

        context.close()
        browser.close()
        return (order_id, quotation_num, line_id, tcv_total, start_supplier, install_price, annual_rental, ftpp_aggregation, add_on, order_number, quote_number, order_url, quote_url)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_preset.py <preset_id_or_path> [--postcode \"POSTCODE\"] [--headless] [--pause]")
        print("Example: python3 run_preset.py presets/p2nni/p2nni_10g_10g_36m_upfront_shadowvlan.json")
        print("Example: python3 run_preset.py p2nni/p2nni_10g_10g_36m --postcode \"SP2 8NJ\"")
        print("  --pause   Open Playwright Inspector at config step (Pick locator for bearer, etc.)")
        sys.exit(1)

    args = sys.argv[1:]
    postcode_override = None
    headless = "--headless" in args
    pause = "--pause" in args
    args = [a for a in args if a not in ("--headless", "--pause")]
    if pause:
        headless = False  # Inspector needs visible browser
    if "--postcode" in args:
        idx = args.index("--postcode")
        if idx + 1 < len(args):
            postcode_override = args[idx + 1]
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]
    if not args:
        print("Usage: python3 run_preset.py <preset_id_or_path> [--postcode \"POSTCODE\"]")
        sys.exit(1)

    arg = args[0]
    p = Path(arg)
    if p.exists():
        preset_path = p
    else:
        # allow p2nni/preset_name as well as just preset_name
        if "/" in arg:
            preset_path = Path("presets") / f"{arg}.json"
        else:
            preset_path = Path("presets") / f"{arg}.json"

    if not preset_path.exists():
        raise FileNotFoundError(f"Preset not found: {preset_path}")

    run_preset(preset_path, postcode_override=postcode_override, headless=headless, pause=pause)

if __name__ == "__main__":
    main()

