"""Contract test binding the GCP checker to config/permissions/gcp.yaml.

Review finding H11: GCPChecker hard-codes its permission set and never reads
gcp.yaml, so the two could drift (the YAML declaring permissions the checker
never tests) with nothing to catch it. This test makes that drift a test
failure: every IAM permission the YAML declares must be in the set the checker
actually sends to projects.testIamPermissions.
"""

from pathlib import Path

import yaml

from checkers.gcp import GCPChecker

_GCP_YAML = Path(__file__).resolve().parents[1] / "config" / "permissions" / "gcp.yaml"


def _yaml_declared_iam_permissions() -> set:
    """IAM permissions declared across gcp.yaml resources.

    GCP IAM permissions are 'service.resource.verb'. Anything containing ':' or
    '/' (ARNs, URLs) or without a '.' is not a testIamPermissions permission and
    is skipped.
    """
    data = yaml.safe_load(_GCP_YAML.read_text())
    perms = set()
    for resource in (data.get("resources") or {}).values():
        if isinstance(resource, dict):
            for action in resource.get("actions", []) or []:
                if "." in action and ":" not in action and "/" not in action:
                    perms.add(action)
    return perms


def _checker_tested_permissions() -> set:
    """The maximal permission set the checker tests (every scope active)."""
    all_scopes = GCPChecker._scopes_in_effect(psc=True, dns=True, cmek=True)
    perms, _index = GCPChecker._build_permission_request(all_scopes)
    return set(perms)


def test_checker_tests_every_yaml_declared_permission():
    declared = _yaml_declared_iam_permissions()
    tested = _checker_tested_permissions()
    assert declared, "gcp.yaml declared no IAM permissions — did the file move?"
    missing = declared - tested
    assert not missing, (
        "config/permissions/gcp.yaml declares permissions the checker never "
        f"sends to testIamPermissions (drift — see review H11): {sorted(missing)}"
    )
