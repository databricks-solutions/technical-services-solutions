"""Create or delete throwaway legacy objects to exercise the planner live.

Everything is prefixed ugmig_test_. External model endpoints use fake keys and
are never queried.

    python test_fixtures.py --profile DEFAULT setup --warehouse-id <id>
    python test_fixtures.py --profile DEFAULT teardown
"""

import argparse
import os
import base64
import time

from databricks.sdk import WorkspaceClient

SCOPE = "ugmig_test_scope"
# The catalog must exist; the group must exist in the workspace (it gets a CAN_QUERY grant to migrate).
CATALOG = os.environ.get("UGMIG_TEST_CATALOG", "main")
SCHEMA = "ugmig_test"
TEST_GROUP = os.environ.get("UGMIG_TEST_GROUP", "ugmig_test_group")
OPENAI_EP, ANTHROPIC_EP = "ugmig_test_openai", "ugmig_test_anthropic"
NOTEBOOK_DIR = "ugmig_test"
QUERY_NAME = "ugmig_test_legacy_ai_query"
VS_ENDPOINT = "ugmig_test_vs"
DOCS_TABLE = f"{CATALOG}.{SCHEMA}.docs"
VS_INDEX_LEGACY = f"{CATALOG}.{SCHEMA}.docs_idx_legacy"
VS_INDEX_UG = f"{CATALOG}.{SCHEMA}.docs_idx_system_ai"
APP_NAME = "ugmig-test-app"
JOB_NAME = "ugmig_test_job"

NOTEBOOK = """# Databricks notebook source
from openai import OpenAI
client = OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")
resp = client.chat.completions.create(model="ugmig_test_openai", messages=[{"role": "user", "content": "hi"}])

# COMMAND ----------
import requests
requests.post(f"{host}/serving-endpoints/ugmig_test_anthropic/invocations", json={})

# COMMAND ----------
from databricks_langchain import ChatDatabricks
llm = ChatDatabricks(endpoint="databricks-claude-sonnet-4-6")
judge_uri = "endpoints:/databricks-gpt-oss-120b"

# COMMAND ----------
# MAGIC %sql
# MAGIC SELECT ai_query('databricks-meta-llama-3-3-70b-instruct', 'Summarize: ' || text) FROM t;
# MAGIC SELECT ai_query('system.ai.claude-sonnet-4-6', 'already migrated') FROM t;
# MAGIC SELECT ai_query('risk-sk-scoring-v2', 'name that looks like a key prefix') FROM t;

# COMMAND ----------
# Literal fake credentials (never valid): the scan must store these lines with the values hidden.
legacy = OpenAI(api_key="sk-ugmigfake0123456789abcdef", base_url=f"{host}/serving-endpoints")
requests.post(f"{host}/serving-endpoints/ugmig_test_openai/invocations", headers={"Authorization": "Bearer ugmig-fake-bearer-token-not-real"}, json={})
"""

QUERY = ("SELECT ai_query('ugmig_test_openai', 'Classify: ' || body) AS label,\n"
         "       ai_query('databricks-gpt-oss-120b', 'Summarize: ' || body) AS summary\n"
         "FROM samples.bakehouse.media_customer_reviews LIMIT 10")


def _external(name, provider, model, cfg):
    return {"name": name, "external_model": {"name": model, "provider": provider, "task": "llm/v1/chat", **cfg}}


def setup(w: WorkspaceClient, warehouse_id: str) -> None:
    me = w.current_user.me().user_name
    if SCOPE not in [s.name for s in w.secrets.list_scopes()]:
        w.secrets.create_scope(SCOPE)
    w.secrets.put_secret(SCOPE, "openai", string_value="sk-fake-not-a-real-key")
    w.secrets.put_secret(SCOPE, "anthropic", string_value="sk-ant-fake-not-a-real-key")
    try:
        w.schemas.create(name=SCHEMA, catalog_name=CATALOG, comment="ugmig planner test, safe to delete")
    except Exception as e:
        print("schema:", e)

    openai_cfg = {"openai_config": {"openai_api_key": f"{{{{secrets/{SCOPE}/openai}}}}"}}
    endpoints = {
        OPENAI_EP: {
            "served_entities": [_external("primary", "openai", "gpt-5", openai_cfg),
                                _external("backup", "openai", "gpt-5-mini", openai_cfg)],
            "traffic_config": {"routes": [{"served_model_name": "primary", "traffic_percentage": 100},
                                          {"served_model_name": "backup", "traffic_percentage": 0}]},
        },
        ANTHROPIC_EP: {
            "served_entities": [_external("claude", "anthropic", "claude-sonnet-4-6",
                                          {"anthropic_config": {"anthropic_api_key": f"{{{{secrets/{SCOPE}/anthropic}}}}"}})],
        },
    }
    for name, config in endpoints.items():
        try:
            w.api_client.do("POST", "/api/2.0/serving-endpoints", body={"name": name, "config": config,
                                                                        "tags": [{"key": "team", "value": "ugmig-test"}]})
            print("created", name)
        except Exception as e:
            print(name, e)
    for _ in range(30):
        states = [w.api_client.do("GET", f"/api/2.0/serving-endpoints/{n}").get("state", {}).get("config_update")
                  for n in endpoints]
        if all(s != "IN_PROGRESS" for s in states):
            break
        time.sleep(10)

    gateway = {
        "usage_tracking_config": {"enabled": True},
        "rate_limits": [
            {"key": "endpoint", "calls": 100, "renewal_period": "minute"},
            {"key": "user", "calls": 10, "renewal_period": "minute"},
            {"key": "user_group", "principal": TEST_GROUP, "tokens": 5000, "renewal_period": "minute"},
        ],
        "guardrails": {"input": {"pii": {"behavior": "BLOCK"}}},
        "inference_table_config": {"catalog_name": CATALOG, "schema_name": SCHEMA,
                                   "table_name_prefix": OPENAI_EP, "enabled": True},
        "fallback_config": {"enabled": True},
    }
    for name, body in [(OPENAI_EP, gateway), (ANTHROPIC_EP, {"usage_tracking_config": {"enabled": True},
                                                            "rate_limits": [{"key": "user", "principal": me,
                                                                             "calls": 5, "renewal_period": "minute"}]})]:
        try:
            w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{name}/ai-gateway", body=body)
            print("gateway set on", name)
        except Exception as e:
            print("gateway", name, e)
    ep_id = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{OPENAI_EP}")["id"]
    w.api_client.do("PATCH", f"/api/2.0/permissions/serving-endpoints/{ep_id}", body={
        "access_control_list": [{"group_name": TEST_GROUP, "permission_level": "CAN_QUERY"}]})

    path = f"/Users/{me}/{NOTEBOOK_DIR}/legacy_calls"
    w.workspace.mkdirs(f"/Users/{me}/{NOTEBOOK_DIR}")
    w.api_client.do("POST", "/api/2.0/workspace/import", body={
        "path": path, "format": "SOURCE", "language": "PYTHON", "overwrite": True,
        "content": base64.b64encode(NOTEBOOK.encode()).decode()})
    q = w.api_client.do("POST", "/api/2.0/sql/queries", body={"query": {
        "display_name": QUERY_NAME, "warehouse_id": warehouse_id, "query_text": QUERY}})
    print("query", q.get("id"))
    if not os.environ.get("UGMIG_SKIP_EXTRA"):
        setup_extra(w, warehouse_id)


def _sql(w, warehouse_id, statement):
    from databricks.sdk.service.sql import StatementState
    r = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=statement, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state)


def setup_extra(w: WorkspaceClient, warehouse_id: str) -> None:
    """Vector Search endpoint and indexes, an app with a serving-endpoint resource, and a job."""
    _sql(w, warehouse_id, f"CREATE TABLE IF NOT EXISTS {DOCS_TABLE} (id STRING, content STRING) "
                          "TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    _sql(w, warehouse_id, f"INSERT OVERWRITE {DOCS_TABLE} VALUES ('1', 'Unity Gateway governs model access'), "
                          "('2', 'Legacy serving endpoints retire in March 2027'), ('3', 'Re-embed indexes before enforcing')")
    try:
        w.api_client.do("POST", "/api/2.0/vector-search/endpoints", body={"name": VS_ENDPOINT, "endpoint_type": "STANDARD"})
        print("creating VS endpoint")
    except Exception as e:
        print("vs endpoint:", e)
    for _ in range(90):
        st = w.vector_search_endpoints.get_endpoint(VS_ENDPOINT).endpoint_status
        if st and st.state and st.state.value == "ONLINE":
            break
        time.sleep(20)
    print("VS endpoint state:", w.vector_search_endpoints.get_endpoint(VS_ENDPOINT).endpoint_status.state)
    for index, model in [(VS_INDEX_LEGACY, "databricks-gte-large-en"), (VS_INDEX_UG, "system.ai.gte-large-en")]:
        try:
            w.api_client.do("POST", "/api/2.0/vector-search/indexes", body={
                "name": index, "endpoint_name": VS_ENDPOINT, "primary_key": "id", "index_type": "DELTA_SYNC",
                "delta_sync_index_spec": {"source_table": DOCS_TABLE, "pipeline_type": "TRIGGERED",
                                          "embedding_source_columns": [{"name": "content",
                                                                        "embedding_model_endpoint_name": model}]}})
            print("created index", index, "on", model)
        except Exception as e:
            print("index", index, "on", model, "->", str(e)[:300])

    try:
        w.api_client.do("POST", "/api/2.0/apps", query={"no_compute": "true"}, body={
            "name": APP_NAME, "description": "ugmig planner test, safe to delete",
            "resources": [{"name": "llm", "serving_endpoint": {"name": OPENAI_EP, "permission": "CAN_QUERY"}}]})
        print("created app", APP_NAME)
    except Exception as e:
        print("app:", str(e)[:300])

    me = w.current_user.me().user_name
    try:
        j = w.api_client.do("POST", "/api/2.1/jobs/create", body={
            "name": JOB_NAME,
            "tasks": [{"task_key": "score", "notebook_task": {
                "notebook_path": f"/Users/{me}/{NOTEBOOK_DIR}/legacy_calls",
                "base_parameters": {"endpoint": ANTHROPIC_EP, "embedding_endpoint": "databricks-bge-large-en"}}}]})
        print("created job", j.get("job_id"))
    except Exception as e:
        print("job:", str(e)[:300])


def teardown_extra(w: WorkspaceClient) -> None:
    for index in (VS_INDEX_LEGACY, VS_INDEX_UG):
        try:
            w.vector_search_indexes.delete_index(index)
            print("deleted index", index)
        except Exception as e:
            print("index", index, str(e)[:120])
    try:
        w.vector_search_endpoints.delete_endpoint(VS_ENDPOINT)
        print("deleted VS endpoint")
    except Exception as e:
        print("vs endpoint", str(e)[:120])
    try:
        w.apps.delete(APP_NAME)
        print("deleted app")
    except Exception as e:
        print("app", str(e)[:120])
    for j in w.jobs.list(name=JOB_NAME):
        w.jobs.delete(j.job_id)
        print("deleted job", j.job_id)


def teardown(w: WorkspaceClient) -> None:
    if not os.environ.get("UGMIG_SKIP_EXTRA"):
        teardown_extra(w)
    me = w.current_user.me().user_name
    for name in (OPENAI_EP, ANTHROPIC_EP):
        try:
            w.serving_endpoints.delete(name)
            print("deleted", name)
        except Exception as e:
            print(name, e)
    page = w.api_client.do("GET", "/api/2.0/sql/queries", query={"page_size": 100})
    for q in page.get("results", []):
        if q.get("display_name") == QUERY_NAME:
            w.api_client.do("DELETE", f"/api/2.0/sql/queries/{q['id']}")
            print("deleted query", q["id"])
    try:
        w.workspace.delete(f"/Users/{me}/{NOTEBOOK_DIR}", recursive=True)
        print("deleted notebook dir")
    except Exception as e:
        print("notebook", e)
    try:
        w.schemas.delete(f"{CATALOG}.{SCHEMA}", force=True)
        print("deleted schema")
    except Exception as e:
        print("schema", e)
    try:
        w.secrets.delete_scope(SCOPE)
        print("deleted scope")
    except Exception as e:
        print("scope", e)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--profile")
    p.add_argument("action", choices=["setup", "teardown"])
    p.add_argument("--warehouse-id")
    a = p.parse_args()
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    setup(w, a.warehouse_id) if a.action == "setup" else teardown(w)
