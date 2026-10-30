"""Unity Gateway migration progress dashboard (prototype).

Builds an AI/BI dashboard on the snapshot tables written by
`ug_migration_account.py --snapshot-table <catalog.schema.prefix>`:
  <prefix>_workspaces  one row per workspace per run
  <prefix>_endpoints   one row per legacy endpoint per run

    python ug_migration_dashboard.py --profile P --warehouse-id W --snapshot-table main.ug.snap \\
        --parent-path /Workspace/Users/me@x.com/ug-migration [--publish] [--dashboard-id ID]

Without --dashboard-id it creates a new dashboard; with it, it updates that one
(so shared links keep working). --json-only writes the dashboard JSON without
deploying. Written by STS as a prototype; not an official Databricks tool.
"""

from __future__ import annotations

import argparse
import json
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.dashboards import Dashboard

THEME = {
    "canvasBackgroundColor": {"light": "#FCFCFC", "dark": "#1F272D"},
    "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#11171C"},
    "widgetBorderColor": {"light": "#FFFFFF", "dark": "#11171C"},
    "fontColor": {"light": "#11171C", "dark": "#E8ECF0"},
    "selectionColor": {"light": "#2272B4", "dark": "#8ACAFF"},
    # Okabe-Ito: color-blind safe. Legacy = vermilion, Unity Gateway = bluish green.
    "visualizationColors": ["#D55E00", "#009E73", "#0072B2", "#E69F00", "#CC79A7", "#56B4E9", "#F0E442"],
    "widgetHeaderAlignment": "LEFT",
}

WAVE_ORDER = "CASE WHEN wave LIKE 'v2%' THEN 0 WHEN wave LIKE '0%' THEN 1 WHEN wave LIKE '1: cleanup%' THEN 2 " \
             "WHEN wave LIKE '1%' THEN 3 ELSE 4 END"


def datasets(prefix_leaf: str) -> list[dict]:
    ws, ep = f"{prefix_leaf}_workspaces", f"{prefix_leaf}_endpoints"
    latest_ws = f"(SELECT max(snapshot_time) FROM {ws})"
    latest_ep = f"(SELECT max(snapshot_time) FROM {ep})"
    return [
        {"name": "ds_trend", "displayName": "Progress over time", "queryLines": [
            "SELECT snapshot_time, ",
            "sum(legacy_requests) AS legacy_requests, sum(v3_requests) AS v3_requests, ",
            "sum(active_legacy_endpoints) AS active_legacy_endpoints, ",
            "count_if(wave LIKE '0%') AS enforce_candidates, count(*) AS workspaces ",
            f"FROM {ws} GROUP BY snapshot_time ORDER BY snapshot_time"]},
        {"name": "ds_kpi", "displayName": "Latest snapshot", "queryLines": [
            "SELECT max(snapshot_time) AS snapshot_time, ",
            "sum(legacy_requests) AS legacy_requests, sum(v3_requests) AS v3_requests, ",
            "try_divide(sum(v3_requests), sum(v3_requests) + sum(legacy_requests)) AS v3_share, ",
            "sum(active_legacy_endpoints) AS active_legacy_endpoints, ",
            "count_if(wave LIKE '0%') AS enforce_candidates, count(*) AS workspaces ",
            f"FROM {ws} WHERE snapshot_time = {latest_ws}"]},
        {"name": "ds_waves", "displayName": "Workspaces by wave", "queryLines": [
            f"SELECT wave, {WAVE_ORDER} AS wave_order, count(*) AS workspaces, sum(legacy_requests) AS legacy_requests ",
            f"FROM {ws} WHERE snapshot_time = {latest_ws} GROUP BY wave ORDER BY wave_order"]},
        {"name": "ds_workspaces", "displayName": "Workspaces (latest)", "queryLines": [
            "SELECT workspace_name, workspace_id, wave, legacy_endpoints, custom_legacy_endpoints, ",
            "active_legacy_endpoints, v1_requests, legacy_requests, legacy_throttled, v2_requests, v3_requests, v3_share ",
            f"FROM {ws} WHERE snapshot_time = {latest_ws} ",
            "ORDER BY legacy_requests DESC, custom_legacy_endpoints DESC"]},
        {"name": "ds_endpoints", "displayName": "Busiest legacy endpoints (latest)", "queryLines": [
            "SELECT workspace_name, endpoint_name, kind, requests, requesters, throttled, last_request ",
            f"FROM {ep} WHERE snapshot_time = {latest_ep} AND requests > 0 AND kind <> 'out_of_scope' ",
            "ORDER BY requests DESC LIMIT 200"]},
    ]


def _counter(name, title, ds, field, fmt=None, x=0, y=0, w=3):
    enc = {"fieldName": field, "displayName": title}
    if fmt:
        enc["format"] = fmt
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
        "datasetName": ds, "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": True}}],
        "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": enc},
                 "frame": {"showTitle": True, "title": title}}},
        "position": {"x": x, "y": y, "width": w, "height": 3}}


def _table(name, title, ds, cols, y, h=7):
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
        "datasetName": ds, "fields": [{"name": c, "expression": f"`{c}`"} for c, _, _ in cols],
        "disaggregated": True}}],
        "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": [
            {"fieldName": c, "displayName": d, **({"format": f} if f else {})} for c, d, f in cols]},
            "frame": {"showTitle": True, "title": title}}},
        "position": {"x": 0, "y": y, "width": 12, "height": h}}


def build(prefix_leaf: str) -> dict:
    compact = {"type": "number-plain", "abbreviation": "compact", "decimalPlaces": {"type": "max", "places": 1}}
    pct = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 0}}
    layout = [
        {"widget": {"name": "title", "multilineTextboxSpec": {"lines": [
            "## Unity Gateway migration progress\n", "\n",
            "Legacy v2 endpoints stop serving first (on **November 30, 2026**) and v1 endpoints stop serving "
            "on **March 30, 2027** (dates from Databricks migration communications as of October 30, 2026; confirm with your "
            "account team). Legacy traffic below counts v1 and v2 requests. Each snapshot adds a point to the trend."]}},
         "position": {"x": 0, "y": 0, "width": 12, "height": 2}},
        _counter("kpi-legacy", "Legacy requests, v1 + v2 (window)", "ds_kpi", "legacy_requests", compact, 0, 2),
        _counter("kpi-share", "Share on Unity Gateway", "ds_kpi", "v3_share", pct, 3, 2),
        _counter("kpi-active", "Active legacy endpoints", "ds_kpi", "active_legacy_endpoints", None, 6, 2),
        _counter("kpi-ready", "Enforce candidates (wave 0)", "ds_kpi", "enforce_candidates", None, 9, 2),
        {"widget": {"name": "trend", "queries": [{"name": "main_query", "query": {
            "datasetName": "ds_trend", "fields": [
                {"name": "snapshot_time", "expression": "`snapshot_time`"},
                {"name": "legacy_requests", "expression": "`legacy_requests`"},
                {"name": "v3_requests", "expression": "`v3_requests`"}], "disaggregated": True}}],
            "spec": {"version": 3, "widgetType": "line", "encodings": {
                "x": {"fieldName": "snapshot_time", "scale": {"type": "temporal"}, "displayName": "Snapshot"},
                "y": {"scale": {"type": "quantitative"}, "fields": [
                    {"fieldName": "legacy_requests", "displayName": "Legacy requests"},
                    {"fieldName": "v3_requests", "displayName": "Unity Gateway requests"}]}},
                "frame": {"showTitle": True, "title": "Legacy vs Unity Gateway traffic"}}},
         "position": {"x": 0, "y": 5, "width": 6, "height": 6}},
        {"widget": {"name": "endpoint-trend", "queries": [{"name": "main_query", "query": {
            "datasetName": "ds_trend", "fields": [
                {"name": "snapshot_time", "expression": "`snapshot_time`"},
                {"name": "active_legacy_endpoints", "expression": "`active_legacy_endpoints`"},
                {"name": "enforce_candidates", "expression": "`enforce_candidates`"}], "disaggregated": True}}],
            "spec": {"version": 3, "widgetType": "line", "encodings": {
                "x": {"fieldName": "snapshot_time", "scale": {"type": "temporal"}, "displayName": "Snapshot"},
                "y": {"scale": {"type": "quantitative"}, "fields": [
                    {"fieldName": "active_legacy_endpoints", "displayName": "Active legacy endpoints"},
                    {"fieldName": "enforce_candidates", "displayName": "Enforce candidates"}]}},
                "frame": {"showTitle": True, "title": "Burn-down: endpoints and ready workspaces"}}},
         "position": {"x": 6, "y": 5, "width": 6, "height": 6}},
        {"widget": {"name": "waves", "queries": [{"name": "main_query", "query": {
            "datasetName": "ds_waves", "fields": [
                {"name": "wave", "expression": "`wave`"},
                {"name": "workspaces", "expression": "`workspaces`"}], "disaggregated": True}}],
            "spec": {"version": 3, "widgetType": "bar", "encodings": {
                "x": {"fieldName": "wave", "scale": {"type": "categorical", "sort": {
                    "by": "custom-order", "orderedValues": ["v2 first", "0: enforce candidate", "1: cleanup",
                                                            "1: small", "2: high volume"]}},
                      "displayName": "Wave"},
                "y": {"fieldName": "workspaces", "scale": {"type": "quantitative"}, "displayName": "Workspaces"}},
                "frame": {"showTitle": True, "title": "Workspaces by migration wave (latest)"}}},
         "position": {"x": 0, "y": 11, "width": 12, "height": 5}},
        _table("workspaces", "Workspaces (latest snapshot, busiest first)", "ds_workspaces", [
            ("workspace_name", "Workspace", None), ("workspace_id", "ID", None), ("wave", "Wave", None),
            ("legacy_endpoints", "Legacy endpoints", None), ("custom_legacy_endpoints", "External/PT", None),
            ("active_legacy_endpoints", "Active", None), ("v1_requests", "v1 requests", compact),
            ("legacy_throttled", "Throttled", compact), ("v2_requests", "v2 requests", compact),
            ("v3_requests", "Unity Gateway requests", compact), ("v3_share", "On Unity Gateway", pct)], 16, 8),
        _table("endpoints", "Busiest legacy v1 endpoints (latest snapshot)", "ds_endpoints", [
            ("workspace_name", "Workspace", None), ("endpoint_name", "Endpoint", None), ("kind", "Kind", None),
            ("requests", "Requests", compact), ("requesters", "Callers", None), ("throttled", "Throttled", compact),
            ("last_request", "Last request", None)], 24, 8),
    ]
    return {"datasets": datasets(prefix_leaf),
            "pages": [{"name": "progress", "displayName": "Progress", "pageType": "PAGE_TYPE_CANVAS",
                       "layoutVersion": "GRID_V1", "layout": layout}],
            "uiSettings": {"theme": THEME}}


def deploy(w: WorkspaceClient, warehouse_id: str, snapshot_table: str, parent_path: str,
           dashboard_id: str | None = None, publish: bool = False,
           display_name: str = "Unity Gateway migration progress") -> str:
    catalog, schema, leaf = snapshot_table.split(".")
    body = Dashboard(display_name=display_name, warehouse_id=warehouse_id, parent_path=parent_path,
                     serialized_dashboard=json.dumps(build(leaf)))
    if dashboard_id:
        d = w.lakeview.update(dashboard_id, Dashboard(display_name=display_name, warehouse_id=warehouse_id,
                                                      serialized_dashboard=body.serialized_dashboard),
                              dataset_catalog=catalog, dataset_schema=schema)
    else:
        w.workspace.mkdirs(parent_path)
        d = w.lakeview.create(body, dataset_catalog=catalog, dataset_schema=schema)
    if publish:
        w.lakeview.publish(d.dashboard_id, warehouse_id=warehouse_id, embed_credentials=False)
    return d.dashboard_id


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help='Databricks CLI profile (default: the CLI default)')
    p.add_argument("--warehouse-id", help='SQL warehouse for the dashboard (and its queries)')
    p.add_argument("--snapshot-table", required=True, help="catalog.schema.prefix used with ug_migration_account")
    p.add_argument("--parent-path", help="Workspace folder for the dashboard")
    p.add_argument("--dashboard-id", help="Update this dashboard instead of creating one")
    p.add_argument("--publish", action="store_true", help='Create or update the dashboard in the workspace (otherwise only writes the JSON)')
    p.add_argument("--json-only", help="Write the dashboard JSON to this file and stop")
    a = p.parse_args(argv)
    if a.json_only:
        with open(a.json_only, "w") as f:
            json.dump(build(a.snapshot_table.split(".")[-1]), f, indent=1)
        print(a.json_only)
        return 0
    if not a.warehouse_id:
        p.error("--warehouse-id is required to deploy")
    if not a.parent_path and not a.dashboard_id:
        p.error("--parent-path is required to create a dashboard")
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    did = deploy(w, a.warehouse_id, a.snapshot_table, a.parent_path, a.dashboard_id, a.publish)
    host = w.config.host.rstrip("/")
    print(json.dumps({"dashboard_id": did, "draft": f"{host}/sql/dashboardsv3/{did}",
                      **({"published": f"{host}/sql/dashboardsv3/{did}/published"} if a.publish else {})}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
