# Preset naming – site config (billing details)

Quote prefix: `p2nni_{bearer}_{bandwidth}_{contract}m` e.g. `p2nni_1g_500m_36m`, `p2nni_100m_100m_36m`.
Bearers: `10g`, `1g`, `100m`. Bandwidths: `10g`, `1g`, `500m`, `200m`, `100m`.

After product/quote options (e.g. `p2nni_10g_10g_48m_upfront_shadowvlan_LC_AC_LR`), site config tags:

| Tag | Meaning |
|-----|---------|
| **VlanNo** | VLAN tagging: No |
| **VlanYes** | VLAN tagging: Yes |
| **0-48h** | Access notice: 0–48 hours |
| **48h+** | Access notice: Over 48 hours |
| **MultiTenant** | More than one tenant on-site |
| **RJ45** | Connector type: RJ45 (vs LC/SC) |
| **TX** | Media type: TX (vs LR/SR) |
| **AutoNegYes** | Auto Negotiation: Yes (1 Gbps only) |
| **AutoNegNo** | Auto Negotiation: No (1 Gbps only) |
| **Pre2000** | Building built prior to year 2000 |
| **AsbestosNo** | Asbestos register: No (when Pre2000) |
| **AsbestosYes** | Asbestos register: Yes (when Pre2000) |
| **Hazards** | Hazards on site – generic description |
| **Wayleave** | Land owner permission (Wayleave) required |
