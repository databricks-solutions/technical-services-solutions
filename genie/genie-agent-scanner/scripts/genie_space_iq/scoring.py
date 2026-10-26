"""IQ score (0-12) and 3-tier maturity mapping.

Ported from the public Databricks Genie Workbench accelerator
(databricks-solutions/databricks-genie-workbench),
``packages/genie-space-optimizer/.../iq_scan/scoring.py`` (see NOTICE.md):

* ``score = sum(1 for c in checks if c["passed"])`` out of 12 (no weights).
* Maturity tiers (``get_maturity_label``)::

      all 12 checks pass          -> "Trusted"            # 12/12
      config checks (1-10) pass   -> "Ready to Optimize"
      otherwise                   -> "Not Ready"
"""

from __future__ import annotations

from typing import Any

TOTAL_CHECKS = 12
CONFIG_CHECK_COUNT = 10

TIER_TRUSTED = "Trusted"
TIER_READY = "Ready to Optimize"
TIER_NOT_READY = "Not Ready"


def calculate_score(checks: list[dict[str, Any]]) -> int:
    """Number of passing checks (each check is worth one point)."""
    return sum(1 for c in checks if c.get("passed"))


def get_maturity_label(checks: list[dict[str, Any]]) -> str:
    """Map the check results onto the 3-tier maturity ladder."""
    ordered = sorted(checks, key=lambda c: c.get("id", 0))
    if ordered and all(c.get("passed") for c in ordered):
        return TIER_TRUSTED
    config = ordered[:CONFIG_CHECK_COUNT]
    if config and all(c.get("passed") for c in config):
        return TIER_READY
    return TIER_NOT_READY
