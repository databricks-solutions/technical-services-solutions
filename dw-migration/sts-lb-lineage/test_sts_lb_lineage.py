import csv
import json
from pathlib import Path

import sts_lb_uc
from sts_lb_lineage import Lineage, fix_rel

FIX = Path(__file__).parent / "fixtures"


def load(*names):
    lin = Lineage()
    for n in names:
        lin.add_report(json.loads((FIX / f"{n}.json").read_text()))
    return lin


def edge(lin, src, dst, kind="data"):
    by_name = {n["name"].lower(): nid for nid, n in lin.nodes.items()}
    return lin.edges.get((by_name[src.lower()], by_name[dst.lower()], kind))


def test_sql_statement_lineage_temp_tables_and_roles():
    lin = load("sql_retail")
    e = edge(lin, "raw.orders", "@order_tmp")
    assert e and e["grain"] == "statement" and e["via"] == {"etl/load_orders.sql"}
    assert "temp" in lin.nodes["table:@order_tmp"]["tags"]
    roles = lin.insights()["roles"]
    assert roles["table:raw.orders"] == "source"
    assert roles["table:dw.fact_orders"] == "intermediate"
    assert roles["table:mart.sales_daily"] == "terminal"
    # inventory metadata is attached to the SQL file that the lineage names
    assert lin.programs["etl/build_sales_mart.sql"]["complexity"] == "HIGH"
    assert lin.programs["etl/build_sales_mart.sql"]["drivers"]["loops"] == 2


def test_etl_job_edges_parent_process_and_cycles():
    lin = load("infa_customer")
    assert edge(lin, "SRC_CUSTOMER", "DIM_CUSTOMER")["via"] == {"m_load_customer"}
    assert edge(lin, "s_load_customer", "m_load_customer", "orchestration")
    assert lin.root("m_load_customer") == {"wf_customer"}
    proc = lin.processes()
    assert proc["table:fact_sales"] == "wf_sales"
    ins = lin.insights()
    # DIM_CUSTOMER and CUSTOMER_SCORE cross workflows, so both are shared hubs
    assert {h["id"] for h in ins["hubs"]} >= {
        "table:dim_customer",
        "table:customer_score",
    }
    procs = {p["name"]: p for p in ins["processes"]}
    # wf_customer -> DIM_CUSTOMER -> wf_sales -> CUSTOMER_SCORE -> wf_customer is a cycle
    assert procs["wf_customer"]["cycle"] is not None
    assert procs["wf_customer"]["cycle"] == procs["wf_sales"]["cycle"]
    assert ins["summary"]["cycles"] == 1
    assert lin.programs["m_load_sales"]["drivers"]["transformations"]["Joiner"] == 1


def test_nested_sequences_resolve_to_top_level():
    lin = load("datastage_nested")
    assert lin.root("JOB_EXTRACT_ACCOUNTS") == {"SEQ_MASTER"}
    assert lin.processes()["table:stg_accounts"] == "SEQ_MASTER"


def test_embedded_sql_statement_grain_and_off_schema_level():
    lin = load("sas_programs")
    e = edge(lin, "work.sales", "work.summary")
    assert e["grain"] == "statement" and e["via"] == {"monthly_report.sas"}
    assert not edge(
        lin, "work.sales", "out.monthly_report"
    )  # statements are not cross-joined
    assert lin.insights()["trust"]["offSchemaComplexity"] == 1


def test_ssis_shifted_object_rel_is_repaired():
    assert fix_rel(
        {"action": "src.orders", "count": {"Source": 1}, "object": "Read orders"}
    ) == {
        "object": "src.orders",
        "action": "source",
        "count": 1,
        "task": "Read orders",
    }
    lin = load("ssis_shifted")
    assert edge(lin, "src.orders", "dst.orders")
    assert not any(n["name"].startswith("Read ") for n in lin.nodes.values())


def test_statistics_are_facts_only():
    st = load("sql_retail", "infa_customer").insights()["statistics"]
    assert st["fanIn"][0]["count"] >= 2
    assert {"name": "Expression", "count": 3} in st["transformations"]
    assert st["code"]["lines"] == 220 + 640 + 40 + 90
    assert st["crossProcessLinks"] >= 2
    assert not any("wave" in k or "effort" in k for k in st)


def test_mixed_reports_focus_and_outputs(tmp_path):
    lin = load(
        "sql_retail",
        "infa_customer",
        "datastage_nested",
        "sas_programs",
        "ssis_shifted",
    )
    sub = lin.focus("dw.fact_orders")
    assert "table:mart.sales_daily" in sub.nodes and "table:raw.orders" in sub.nodes
    d = sub.write(tmp_path, {"json", "csv", "mermaid", "html"})
    assert (tmp_path / "lineage.mmd").read_text().startswith("flowchart LR")
    assert json.loads((tmp_path / "lineage.json").read_text())["edges"]
    assert (
        '<script id="lineage-data" type="application/json">{"insights":'
        in (tmp_path / "lineage.html").read_text()
    )
    assert {p["name"] for p in d["insights"]["processes"]} >= {"etl/load_orders.sql"}


def _hostile_report():
    return {
        "runInfo": {"sourceTechnology": "INFA"},
        "inventory": [
            {
                "name": "m_x",
                "objectRel": [
                    {
                        "action": "source",
                        "object": "a</script><img src=x onerror=alert(1)>",
                        "count": 1,
                    },
                    {
                        "action": "target",
                        "object": '=HYPERLINK("http://example.invalid")',
                        "count": 1,
                    },
                ],
            }
        ],
        "subJobInfo": [],
    }


def test_html_embed_cannot_break_out_of_the_script_tag(tmp_path):
    lin = Lineage()
    lin.add_report(_hostile_report())
    lin.write(tmp_path, {"html"})
    html = (tmp_path / "lineage.html").read_text()
    data = html.split('<script id="lineage-data" type="application/json">', 1)[1]
    payload = data.split("</script>", 1)[0]
    assert "<" not in payload  # every "<" is escaped as < inside the JSON
    assert "a\\u003c/script>" in payload
    assert json.loads(payload)["nodes"]


def test_csv_outputs_neutralize_formulas(tmp_path):
    lin = Lineage()
    lin.add_report(_hostile_report())
    lin.write(tmp_path, {"csv"})
    with open(tmp_path / "nodes.csv") as f:
        names = [r["name"] for r in csv.DictReader(f)]
    assert '\'=HYPERLINK("http://example.invalid")' in names
    assert not any(n.startswith("=") for n in names)


def test_uc_mapping_volumes_and_external_lineage(tmp_path):
    d = load("sql_retail").to_dict()
    d = sts_lb_uc.enrich(
        d,
        catalog="main",
        pattern="{catalog}.{layer}_{schema}.{table}",
        volumes={"raw.orders": {"rows": 10, "bytes": 99}, "fact_orders": {"rows": 5}},
    )
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes["table:raw.orders"]["uc"] == {
        "layer": "bronze",
        "target": "main.bronze_raw.orders",
    }
    assert nodes["table:mart.sales_daily"]["uc"]["layer"] == "gold"
    assert "uc" not in nodes["table:@order_tmp"]  # temp tables get no target
    assert nodes["table:raw.orders"]["volume"] == {"rows": 10, "bytes": 99}
    # a bare volume name matches a qualified table, but never across two schemas
    assert nodes["table:dw.fact_orders"]["volume"] == {"rows": 5}
    assert d["insights"]["summary"]["volumes"]["matched"] == 2

    p = sts_lb_uc.payload(d, sts_lb_uc.system_type_for("Teradata", None))
    names = [m["name"] for m in p["external_metadata"]]
    assert len(names) == len(set(names)) and all("." not in n for n in names)
    assert p["external_metadata"][0]["system_type"] == "TERADATA"
    assert len(p["external_lineage"]) == sum(
        1 for e in d["edges"] if e["kind"] == "data"
    )

    sts_lb_uc.write_mapping(d, tmp_path)
    assert "main.bronze_raw.orders" in (tmp_path / "uc_mapping.csv").read_text()


def test_uc_push_refuses_payloads_over_metastore_limits():
    import pytest

    big = {
        "external_metadata": [{}] * (sts_lb_uc.MAX_METADATA + 1),
        "external_lineage": [],
    }
    with pytest.raises(SystemExit):
        sts_lb_uc.push(big, profile="unused", assume_yes=True)


def test_mermaid_labels_cannot_inject_statements(tmp_path):
    lin = Lineage()
    lin.add_report(
        {
            "runInfo": {"sourceTechnology": "INFA"},
            "inventory": [
                {
                    "name": "m_y",
                    "objectRel": [
                        {
                            "action": "source",
                            "object": 'a"]\nclick n0 call evil()',
                            "count": 1,
                        },
                        {"action": "target", "object": "b", "count": 1},
                    ],
                }
            ],
            "subJobInfo": [],
        }
    )
    lin.write(tmp_path, {"mermaid"})
    mmd = (tmp_path / "lineage.mmd").read_text()
    assert not any(line.lstrip().startswith("click") for line in mmd.splitlines())


def _ai_server(d, answers):
    import threading
    from http.server import ThreadingHTTPServer

    import sts_lb_ai

    def fake_ask(msgs):
        answers.append(msgs)
        return "## Summary\n- ok"

    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        sts_lb_ai.make_handler(b"<html>", d, fake_ask, "ep", "host", "T" * 32),
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _req(srv, method, path, body=None, headers=None):
    import http.client

    c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    h = {"Host": f"127.0.0.1:{srv.server_port}", **(headers or {})}
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, r.read()


def test_ai_context_is_bounded_and_grounded():
    import pytest

    import sts_lb_ai

    d = load("sql_retail", "infa_customer").to_dict()
    ctx = sts_lb_ai.impact_context(d, "table:dw.fact_orders", "down")
    names = {o["name"] for o in ctx["objects"]}
    assert {"mart.sales_daily", "v_flag"} <= names and "raw.orders" not in names
    assert ctx["target"]["name"] == "dw.fact_orders"
    up = sts_lb_ai.impact_context(d, "proc:wf_sales", "up")
    assert any(p["name"] == "wf_customer" for p in up["processes"])
    with pytest.raises(ValueError):
        sts_lb_ai.impact_context(d, "table:does_not_exist")


def test_ai_server_guards_and_answers():
    d = load("sql_retail").to_dict()
    sent = []
    srv = _ai_server(d, sent)
    try:
        ok = {"X-STS-Session": "T" * 32, "Content-Type": "application/json"}
        body = json.dumps({"target": "table:dw.fact_orders", "mode": "down"})
        assert _req(srv, "GET", "/")[0] == 200
        assert (
            _req(srv, "GET", "/", headers={"Host": "evil.example:80"})[0] == 403
        )  # DNS rebinding
        assert (
            _req(srv, "POST", "/api/ai", body, {"Content-Type": "application/json"})[0]
            == 403
        )  # no session
        assert (
            _req(srv, "POST", "/api/ai", body, {**ok, "Content-Type": "text/plain"})[0]
            == 415
        )
        assert _req(srv, "POST", "/api/ai", "x" * 9000, ok)[0] == 413
        assert (
            _req(srv, "POST", "/api/ai", json.dumps({"target": "table:nope"}), ok)[0]
            == 400
        )
        status, raw = _req(srv, "POST", "/api/ai", body, ok)
        assert status == 200 and json.loads(raw)["answer"].startswith("## Summary")
        prompt = sent[-1][1][1]
        assert (
            "mart.sales_daily" in prompt and "raw.orders" not in prompt
        )  # only the impact set
        assert (
            json.loads(
                _req(srv, "GET", "/api/ai/status", headers={"X-STS-Session": "T" * 32})[
                    1
                ]
            )["endpoint"]
            == "ep"
        )
    finally:
        srv.shutdown()


def test_ai_server_rejects_malformed_requests():
    d = load("sql_retail").to_dict()
    srv = _ai_server(d, [])
    try:
        ok = {"X-STS-Session": "T" * 32, "Content-Type": "application/json"}
        bad_len = _req(srv, "POST", "/api/ai", "{}", {**ok, "Content-Length": "abc"})[0]
        assert bad_len == 400
        path_int = json.dumps({"target": "table:raw.orders", "mode": "path", "to": 5})
        assert _req(srv, "POST", "/api/ai", path_int, ok)[0] == 400
        nested = "[" * 3000 + "]" * 3000
        assert _req(srv, "POST", "/api/ai", json.dumps({"target": nested}), ok)[0] in (
            400,
            413,
        )
        assert _req(srv, "POST", "/api/ai", "[" * 2000 + "]" * 2000, ok)[0] == 400
        headers = {}
        import http.client

        c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
        c.request("GET", "/", headers={"Host": f"127.0.0.1:{srv.server_port}"})
        r = c.getresponse()
        headers = dict(r.getheaders())
        assert headers["X-Frame-Options"] == "DENY"
    finally:
        srv.shutdown()
