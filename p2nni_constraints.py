#!/usr/bin/env python3
"""
P2NNI Bearer/Bandwidth constraints.

Valid options for Connector Type, Media Type, Power Supply, Auto Negotiation,
and VLAN Tagging depend on the Bearer and Bandwidth combination.

Rules (from portal behaviour):
- 10/10: Connector LC,SC | Media LR | Power AC,DC | AutoNeg No (fixed) | VLAN Yes,No
- 10/1:  Connector LC,SC | Media LR | Power AC,DC | AutoNeg No (fixed) | VLAN Yes,No
- 1/1:   Connector LC,SC,RJ45 | Media LX,SX,TX | Power AC,DC | AutoNeg Yes,No | VLAN Yes,No
- 1/500, 1/200, 1/100: Connector LC,SC,RJ45 | Media TX | Power AC,DC | AutoNeg Yes,No | VLAN Yes,No
- 100/100: Connector RJ45 | Media TX only (portal hides Single/Multi Mode on many journeys) | Power AC,DC | AutoNeg Yes,No | VLAN Yes,No

CSV/preset values: Connector (LC,SC,RJ45), Media (LR,SR,TX), Power (AC,DC), AutoNeg (Yes,No), VLAN (Yes,No).
Portal mapping: LR→LX for 1G/100M single mode; SR→SX for multi mode.
"""

from typing import Optional

# Bandwidth options per Bearer: 10G→10 or 1; 1G→1,500,200,100; 100M→100
BANDWIDTH_BY_BEARER = {
    10000: [10000, 1000],
    1000: [1000, 500, 200, 100],
    100: [100],
}

# Bearer/Bandwidth keys: (bearer_mbps, bandwidth_mbps)
# Bearer: 100, 1000, 10000
# Bandwidth: 100, 200, 500, 1000, 10000

_CONSTRAINTS = {
    # 10 Gbps bearer
    (10000, 10000): {
        "connector_type": ["LC", "SC"],
        "media_type": ["LR"],  # Portal shows LR for 10G
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["No"],  # Fixed
        "vlan_tagging": ["Yes", "No"],
    },
    (10000, 1000): {
        "connector_type": ["LC", "SC"],
        "media_type": ["LR"],
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["No"],
        "vlan_tagging": ["Yes", "No"],
    },
    # 1 Gbps bearer
    (1000, 1000): {
        "connector_type": ["LC", "SC", "RJ45"],
        "media_type": ["LR", "SR", "TX"],  # CSV LR→LX, SR→SX, TX→TX in portal
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["Yes", "No"],
        "vlan_tagging": ["Yes", "No"],
    },
    (1000, 500): {
        "connector_type": ["LC", "SC", "RJ45"],
        "media_type": ["TX"],
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["Yes", "No"],
        "vlan_tagging": ["Yes", "No"],
    },
    (1000, 200): {
        "connector_type": ["LC", "SC", "RJ45"],
        "media_type": ["TX"],
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["Yes", "No"],
        "vlan_tagging": ["Yes", "No"],
    },
    (1000, 100): {
        "connector_type": ["LC", "SC", "RJ45"],
        "media_type": ["TX"],
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["Yes", "No"],
        "vlan_tagging": ["Yes", "No"],
    },
    # 100 Mbps bearer
    (100, 100): {
        "connector_type": ["RJ45"],
        "media_type": ["TX"],
        "power_supply": ["AC", "DC"],
        "auto_negotiation": ["Yes", "No"],
        "vlan_tagging": ["Yes", "No"],
    },
}


def _parse_mbps(val) -> Optional[int]:
    """Convert bearer/bandwidth string to Mbps (e.g. '1 Gbps'->1000, '1000'->1000)."""
    if val is None:
        return None
    s = str(val).strip().lower().replace(" ", "")
    if not s:
        return None
    if s in ("1g", "1gbps", "1000"):
        return 1000
    if s in ("10g", "10gbps", "10000"):
        return 10000
    if s in ("100m", "100mbps", "100"):
        return 100
    if s.isdigit():
        return int(s)
    if "gbps" in s:
        try:
            return int("".join(c for c in s if c.isdigit())) * 1000
        except ValueError:
            pass
    if "mbps" in s:
        try:
            return int("".join(c for c in s if c.isdigit()))
        except ValueError:
            pass
    return None


def _resolve_config(bearer_mbps: int, bandwidth_mbps: int) -> dict:
    """Get constraint config for bearer/bandwidth. Falls back to nearest if exact match missing."""
    key = (bearer_mbps, bandwidth_mbps)
    if key in _CONSTRAINTS:
        return _CONSTRAINTS[key]
    # Fallback: 10G bearer -> 10/10 or 10/1 rules
    if bearer_mbps >= 10000:
        if bandwidth_mbps >= 10000:
            return _CONSTRAINTS[(10000, 10000)]
        return _CONSTRAINTS[(10000, 1000)]
    # 1G bearer
    if bearer_mbps >= 1000:
        if bandwidth_mbps >= 1000:
            return _CONSTRAINTS[(1000, 1000)]
        if bandwidth_mbps >= 500:
            return _CONSTRAINTS[(1000, 500)]
        if bandwidth_mbps >= 200:
            return _CONSTRAINTS[(1000, 200)]
        return _CONSTRAINTS[(1000, 100)]
    # 100M bearer
    return _CONSTRAINTS[(100, 100)]


BANDWIDTH_BY_BEARER = {
    10000: [10000, 1000],
    1000: [1000, 500, 200, 100],
    100: [100],
}


def get_allowed_bandwidths(bearer) -> list[int]:
    """Return allowed bandwidth values (Mbps) for the given bearer."""
    b = _parse_mbps(bearer)
    if b is None:
        return [1000, 500, 200, 100]
    return BANDWIDTH_BY_BEARER.get(b, [1000, 500, 200, 100]).copy()


def get_allowed_options(bearer, bandwidth) -> dict:
    """
    Return allowed options for connector_type, media_type, power_supply, auto_negotiation, vlan_tagging.
    bearer, bandwidth: strings like "1 Gbps", "1000", or ints.
    """
    b = _parse_mbps(bearer) or 1000
    w = _parse_mbps(bandwidth) or 1000
    return _resolve_config(b, w).copy()


def validate_row(bearer, bandwidth, connector_type=None, media_type=None,
                 power_supply=None, auto_negotiation=None, vlan_tagging=None) -> list[str]:
    """
    Validate a row's options against bearer/bandwidth constraints.
    Returns list of error messages (empty if valid).
    """
    errors = []
    b = _parse_mbps(bearer)
    w = _parse_mbps(bandwidth)
    if b is not None and b >= 100000:
        errors.append("100 Gbps bearer is not supported. Supported bearers: 10 Gbps, 1 Gbps, 100 Mbps.")
        return errors
    # Validate bearer/bandwidth combination
    if b is not None and w is not None:
        allowed_bw = get_allowed_bandwidths(bearer)
        if allowed_bw and w not in allowed_bw:
            errors.append(
                f"Bandwidth '{bandwidth}' not allowed for bearer '{bearer}'. "
                f"Allowed: {', '.join(str(x) for x in allowed_bw)}"
            )
    opts = get_allowed_options(bearer, bandwidth)

    def _norm_yn(val):
        if val is None:
            return ""
        s = str(val).strip().lower()
        if s in ("yes", "y", "1", "true"):
            return "Yes"
        if s in ("no", "n", "0", "false"):
            return "No"
        return str(val).strip()

    def _check(field: str, value, label: str):
        if value is None or str(value).strip() == "":
            return
        allowed = opts.get(field, [])
        if not allowed:
            return
        v = str(value).strip()
        if field in ("auto_negotiation", "vlan_tagging"):
            v = _norm_yn(value)
        else:
            v = v.upper()
        allowed_upper = [str(x).upper() for x in allowed]
        allowed_yn = [str(x) for x in allowed]
        ok = (v in allowed_yn) if field in ("auto_negotiation", "vlan_tagging") else (v in allowed_upper)
        if not ok:
            errors.append(f"{label}: '{value}' not allowed for {bearer}/{bandwidth}. Allowed: {', '.join(allowed)}")

    _check("connector_type", connector_type, "Connector Type")
    _check("media_type", media_type, "Media Type")
    _check("power_supply", power_supply, "Power Supply")
    _check("auto_negotiation", auto_negotiation, "Auto Negotiation")
    _check("vlan_tagging", vlan_tagging, "VLAN Tagging")
    return errors


def format_auto_neg(val) -> str:
    """Normalise auto_negotiation to Yes/No for constraint check."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("yes", "y", "1", "true"):
        return "Yes"
    if s in ("no", "n", "0", "false"):
        return "No"
    return str(val)


def format_vlan(val) -> str:
    """Normalise vlan_tagging to Yes/No for constraint check."""
    return format_auto_neg(val)
