"""Offline tests for the installer's pure helpers.

The helpers live between the HELPERS-BEGIN / HELPERS-END markers in installer/install_template.py (the rest of the
notebook needs dbutils and a workspace). This file runs that block on its own and tests it.
"""

import pathlib
import re

import pytest
from databricks.sdk.service import apps, jobs

TEMPLATE = pathlib.Path(__file__).parent / "installer" / "install_template.py"


def _helpers() -> dict:
    text = TEMPLATE.read_text()
    block = re.search(r"# HELPERS-BEGIN\n(.*?)# HELPERS-END", text, re.S).group(1)
    ns: dict = {}
    exec(compile(block, str(TEMPLATE), "exec"), ns)
    return ns


H = _helpers()


# Folders

@pytest.mark.parametrize("path", [
    "/Workspace/Users/someone@example.com/unity-gateway-migration-toolkit",
    "/Workspace/Shared/ug toolkit",
])
def test_valid_folder(path):
    assert H["valid_folder"](path) is None


@pytest.mark.parametrize("path", [
    "/Users/someone/x",                           # not under /Workspace
    "/Workspace/Repos/x",                         # other top-level folder
    "/Workspace/Users/someone/../../Shared",      # traversal
    "/Workspace/Users/someone/./x",               # dot segment
    "/Workspace/Users/.hidden",                   # first segment starts with a dot
    "/Workspace/Users//x",                        # empty segment
    "/Workspace/Users/",                          # nothing after Users/
])
def test_invalid_folder(path):
    assert H["valid_folder"](path) is not None


def test_folder_default_keeps_legacy_path_for_default_app():
    assert H["folder_for"]("", "a@b.c", "unity-gateway-migration") == "/Workspace/Users/a@b.c/unity-gateway-migration-toolkit"
    assert H["folder_for"]("/Workspace/Shared/x/", "a@b.c", "app") == "/Workspace/Shared/x"


def test_results_schema_default_keeps_legacy_schema_and_follows_app_name():
    assert H["results_schema_for"]("", "unity-gateway-migration") == "ug_migration"
    assert H["results_schema_for"]("", "ug-migration-bundle") == "ug_migration_bundle"
    assert H["results_schema_for"]("my_schema", "ug-migration-bundle") == "my_schema"


# Identity and versions

def test_service_principal_detection():
    assert H["is_service_principal"]("0b1f7c2e-1234-4abc-9def-0123456789ab")
    assert not H["is_service_principal"]("someone@example.com")
    assert not H["is_service_principal"]("")


def test_downgrade_needs_widget():
    assert H["downgrade_problem"]("0.8.0", "0.7.0", allow=False) is not None
    assert H["downgrade_problem"]("0.8.0", "0.7.0", allow=True) is None
    assert H["downgrade_problem"]("0.7.0", "0.8.0", allow=False) is None
    assert H["downgrade_problem"]("", "0.8.0", allow=False) is None  # unknown previous version
    assert H["downgrade_problem"]("0.8.0", "0.8.0", allow=False) is None
    assert H["downgrade_problem"]("0.10.0", "0.9.0", allow=False) is not None  # numeric, not string, compare


def test_marker_json_and_legacy_text():
    text = H["marker_text"]("unity-gateway-migration", "0.8.0", "main.ug_migration", "/Workspace/Users/a/x", "a")
    d = H["parse_marker"](text)
    assert d["version"] == "0.8.0" and d["app"] == "unity-gateway-migration"
    assert H["parse_marker"]("Unity Gateway migration toolkit\n") == {}  # 0.7 and 0.8 markers: no version


# Apps and jobs

def test_toolkit_app_marker():
    assert H["is_toolkit_app"]("Unity Gateway Migration Toolkit: account overview")
    assert not H["is_toolkit_app"]("my own app")
    assert not H["is_toolkit_app"](None)


def test_app_from_job_uses_tag_then_name():
    assert H["app_from_job"]("[ug-migration] Unity Gateway migration apply", {"app": ""}) == "ug-migration"
    assert H["app_from_job"]("whatever", {"app": "unity-gateway-migration"}) == "unity-gateway-migration"
    assert H["app_from_job"]("[dev a] Unity Gateway migration scan", {}) == "dev a"


def test_secret_schemas():
    assert H["parse_secret_schemas"]("") == ([], None)
    assert H["parse_secret_schemas"]("main.sec, main.sec ,other.s") == (["main.sec", "other.s"], None)
    _, problem = H["parse_secret_schemas"]("main")
    assert problem and "catalog.schema" in problem


def test_shared_state_finds_results_and_folder_clashes():
    others = [
        {"app": "ug-migration", "results": "MAIN.ug_migration", "folder": "/Workspace/Users/a/ug-migration-toolkit"},
        {"app": "other", "results": "main.other", "folder": "/Workspace/Users/a/ug-migration-toolkit/sub"},
        {"app": "clean", "results": "main.clean", "folder": "/Workspace/Users/a/clean"},
    ]
    clash = H["shared_state"](others, "main.ug_migration", "/Workspace/Users/a/ug-migration-toolkit")
    assert {"kind": "results", "app": "ug-migration"} in clash
    assert {"kind": "folder", "app": "ug-migration"} in clash
    assert {"kind": "folder", "app": "other"} in clash
    assert not any(c["app"] == "clean" for c in clash)


def test_job_specs_names_tags_and_parameters():
    specs = H["job_specs"]("ug-migration-bundle", "/Workspace/Users/a/x", "main.ug_migration", "wh1", ["main.s"], True)
    assert set(specs) == {"snapshot", "scan", "apply"}
    titles = {"snapshot": "snapshot", "scan": "workspace scan", "apply": "apply"}
    notebooks = {"snapshot": "run_account", "scan": "run_scan", "apply": "run_apply"}
    for role, spec in specs.items():
        assert spec.name == f"[ug-migration-bundle] Unity Gateway migration {titles[role]}"
        assert spec.tags == {"tool": "ug-migration-toolkit", "Project": "unity-gateway-migration-toolkit",
                             "app": "ug-migration-bundle", "role": role}
        assert spec.tasks[0].notebook_task.notebook_path == f"/Workspace/Users/a/x/files/notebook/{notebooks[role]}"
    params = {p.name: p.default for p in specs["apply"].parameters}
    assert params["secret_schemas"] == "main.s"
    assert params["allow_secret_read_enabled"] == "true"
    assert params["ack_guardrails"] == "false"
    snap = {p.name: p.default for p in specs["snapshot"].parameters}
    assert snap["deep_warehouse_id"] == "wh1"
    assert specs["snapshot"].schedule.pause_status == jobs.PauseStatus.PAUSED


def test_job_specs_secret_read_default_off():
    specs = H["job_specs"]("unity-gateway-migration", "/Workspace/Users/a/x", "main.ug_migration", "wh1", [], False)
    params = {p.name: p.default for p in specs["apply"].parameters}
    assert params["allow_secret_read_enabled"] == "false" and params["secret_schemas"] == ""


def test_app_update_keeps_fields_the_installer_does_not_set():
    existing = apps.App(name="unity-gateway-migration", description="Unity Gateway Migration Toolkit: x",
                        budget_policy_id="bp-1", usage_policy_id="up-1", compute_size=apps.ComputeSize.MEDIUM,
                        compute_min_instances=1, compute_max_instances=3, space="team-space",
                        forward_user_access_token=True, url="https://example/app", id="app-id",
                        active_deployment=apps.AppDeployment(deployment_id="d1"),
                        resources=[], user_api_scopes=["sql"])
    spec = H["app_update_spec"](existing, name="unity-gateway-migration", description="new", resources=[],
                                user_api_scopes=["sql"])
    assert spec.budget_policy_id == "bp-1" and spec.usage_policy_id == "up-1"
    assert spec.compute_size == apps.ComputeSize.MEDIUM and spec.compute_min_instances == 1
    assert spec.compute_max_instances == 3 and spec.space == "team-space" and spec.forward_user_access_token is True
    assert spec.description == "new"
    # Output-only fields are not sent back
    assert spec.url is None and spec.id is None and spec.active_deployment is None


def test_app_env_and_resources():
    env = {e.name: e for e in H["app_env"]("main.ug_migration", ["a@x.com"], "0.8.0", ["main.s"], False)}
    assert env["UGMIG_VERSION"].value == "0.8.0"
    assert env["UGMIG_SECRET_SCHEMAS"].value == "main.s"
    assert env["UGMIG_ALLOW_SECRET_READ"].value == "false"
    assert env["UGMIG_MAX_SCAN_AGE_DAYS"].value == "14"
    assert env["OPERATORS"].value == "a@x.com"
    res = H["app_resources"]("wh1", {"snapshot": 1, "scan": 2, "apply": 3})
    assert {r.name for r in res} == {"sql-warehouse", "snapshot-job", "scan-job", "apply-job"}


def test_uninstall_summary_lists_choices_and_warns_about_orphans():
    pending = [{"apply_id": "a", "created": 2}, {"apply_id": "b", "created": 1}]
    remove, keep = H["uninstall_summary"](False, False, False, pending, True, "c.s", "/Workspace/Users/me/t")
    assert any("3 object(s)" in k and "roll back" in k for k in keep)
    assert any("results tables in c.s" in k for k in keep) and any("apply_logs" in k for k in keep)
    remove, keep = H["uninstall_summary"](True, True, True, pending, True, "c.s", "/Workspace/Users/me/t")
    assert remove[0].startswith("Unity Gateway services") and any("schema" in r for r in remove)
    assert any("apply_logs" in r for r in remove) and not any("WARNING" in k for k in keep)
    remove, keep = H["uninstall_summary"](False, True, False, pending, True, "c.s", "/Workspace/Users/me/t")
    assert any(k.startswith("WARNING") for k in keep)
    remove, keep = H["uninstall_summary"](False, False, False, [], False, "c.s", "/Workspace/Users/me/t")
    assert any("no Unity Gateway services" in k for k in keep) and not any("apply_logs" in x for x in remove + keep)


def test_default_app_name_keeps_short_schema_and_folder():
    assert H["DEFAULT_APP"] == "ug-migration-toolkit" and len(H["DEFAULT_APP"]) <= 30
    assert H["results_schema_for"]("", "ug-migration-toolkit") == "ug_migration"
    assert H["folder_for"]("", "a@b.c", "ug-migration-toolkit") == "/Workspace/Users/a@b.c/ug-migration-toolkit"
    assert H["folder_for"]("", "a@b.c", "unity-gateway-migration") == "/Workspace/Users/a@b.c/unity-gateway-migration-toolkit"
    assert H["folder_for"]("", "a@b.c", "team-a") == "/Workspace/Users/a@b.c/team-a-toolkit"
