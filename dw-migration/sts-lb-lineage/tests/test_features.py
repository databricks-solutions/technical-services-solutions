import json
from types import SimpleNamespace

import pytest
from test_lineage import FIX, load

from sts_lb_lineage import export, normalize
from sts_lb_lineage import uc as sts_lb_uc
from sts_lb_lineage.core import Lineage, main
from sts_lb_lineage.diff import compare


def tiny(*rels):
    lin = Lineage()
    for i, (src, dst) in enumerate(rels):
        a, b = lin.node("table", src), lin.node("table", dst)
        lin.edge(a, b, "data", f"job{i}", "job", "INFA")
        lin.program(f"job{i}", "INFA", reads=[a], writes=[b])
    return lin


def test_search_path_qualifies_only_unambiguous_names():
    lin = tiny(("orders", "dw.fact"), ("dbo.orders", "dw.fact"), ("cust", "dw.dim"))
    lin.node("table", "dbo.cust")
    lin.node("table", "stage.cust")
    alias = normalize.search_path_aliases(lin, ["dbo", "stage"])
    assert alias == {"table:orders": "table:dbo.orders"}  # cust is ambiguous
    assert normalize.merge(lin, alias) == 1
    assert "table:orders" not in lin.nodes
    assert lin.edges[("table:dbo.orders", "table:dw.fact", "data")]["via"] == {
        "job0",
        "job1",
    }
    assert "merged" in lin.nodes["table:dbo.orders"]["tags"]
    assert lin.programs["job0"]["reads"] == {"table:dbo.orders"}


def test_instance_names_fold_into_base_table():
    lin = tiny(("SQ_CUSTOMER", "DIM_CUSTOMER_1"), ("CUSTOMER", "DIM_CUSTOMER"))
    alias = normalize.instance_aliases(lin)
    assert alias == {
        "table:sq_customer": "table:customer",
        "table:dim_customer_1": "table:dim_customer",
    }
    normalize.merge(lin, alias)
    assert set(lin.edges) == {("table:customer", "table:dim_customer", "data")}


def test_column_lineage_from_embedded_sql():
    pytest.importorskip("sqlglot")
    from sts_lb_lineage.columns import column_edges

    lin = load("sas_programs")
    edges, stats = column_edges(lin.statements + [{"job": "x", "sql": "not sql ((("}])
    pairs = {(e["from"].lower(), e["to"].lower()) for e in edges}
    assert ("work.regions.region_name", "work.summary.region") in pairs
    assert ("work.sales.amount", "work.summary.total") in pairs
    assert ("work.summary.total", "out.monthly_report.total") in pairs
    assert stats == {"statements": 3, "parsed": 2, "skipped": 1}


def test_profiler_reads_volumes_from_a_duckdb_extract(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from sts_lb_lineage.profiler import load_profiler

    db = tmp_path / "extract.db"
    con = duckdb.connect(str(db))
    con.execute("create table notes (name varchar)")
    con.execute(
        "create table table_stats (schema_name varchar, table_name varchar, row_count bigint, size_bytes bigint)"
    )
    con.execute(
        "insert into table_stats values ('RAW', 'ORDERS', 10, 99), ('DW', 'X', NULL, 5)"
    )
    con.close()
    vols, used = load_profiler(db)
    assert vols == {"raw.orders": {"rows": 10, "bytes": 99}, "dw.x": {"bytes": 5}}
    assert "table_stats" in used


def test_compare_reports_added_removed_and_moved(tmp_path):
    old = load("sql_retail").to_dict()
    new = load("sql_retail", "sas_programs").to_dict()
    (tmp_path / "old.json").write_text(json.dumps(old))
    diff = compare(tmp_path / "old.json", new)
    assert "table:work.summary" in diff["addedObjects"]
    assert not diff["removedObjects"] and not diff["removedEdges"]
    assert diff["addedProcesses"]


def test_export_rows_and_identifier_validation():
    d = sts_lb_uc.enrich(load("infa_customer").to_dict(), "main")
    r = export.rows(d)
    assert len(r["nodes"]) == len(d["nodes"]) and r["processes"]
    assert json.loads(r["summary"][0]["insights_json"])["trust"]
    for bad in ("main", "a.b.c", "main.x;drop", "main.`x`", "1a.b", "main.x\n"):
        with pytest.raises(SystemExit):
            export.export(d, bad, "unused", "wh", assume_yes=True)


class FakeWS:
    """Records external lineage calls; enough of WorkspaceClient for push/remove."""

    def __init__(self, existing=(), rels=None, tables=()):
        self.created, self.deleted_rels, self.deleted_meta = [], [], []
        names = list(existing)
        self.config = SimpleNamespace(host="https://example.invalid")
        self.tables = SimpleNamespace(
            exists=lambda n: SimpleNamespace(table_exists=n in tables)
        )
        self.external_metadata = SimpleNamespace(
            list_external_metadata=lambda: [SimpleNamespace(name=n) for n in names],
            create_external_metadata=lambda m: names.append(m.name),
            delete_external_metadata=self.deleted_meta.append,
        )
        self.external_lineage = SimpleNamespace(
            create_external_lineage_relationship=self.created.append,
            list_external_lineage_relationships=lambda object_info, lineage_direction: (
                rels or {}
            ).get((object_info.external_metadata.name, lineage_direction.value), []),
            delete_external_lineage_relationship=self.deleted_rels.append,
        )


def test_push_links_existing_uc_tables_and_skips_existing_metadata(monkeypatch):
    pytest.importorskip("databricks.sdk")
    d = sts_lb_uc.enrich(
        load("sql_retail").to_dict(), "main", "{catalog}.{layer}.{table}"
    )
    p = sts_lb_uc.payload(d, prefix="t")
    first = p["external_metadata"][0]["name"]
    target = p["table_links"][0]["table"]
    ws = FakeWS(existing=[first], tables={target})
    monkeypatch.setattr(sts_lb_uc, "_client", lambda profile: ws)
    out = sts_lb_uc.push(p, "unused", assume_yes=True, link=True, prefix="t")
    assert out == {"metadata_created": len(p["external_metadata"]) - 1, "links": 1}
    assert len(ws.created) == len(p["external_lineage"]) + 1
    assert ws.created[-1].target.table.name == target
    assert all(x["table"].count(".") == 2 for x in p["table_links"])


def test_remove_only_touches_prefixed_metadata(monkeypatch):
    pytest.importorskip("databricks.sdk")
    rels = {
        ("t__a", "DOWNSTREAM"): [
            SimpleNamespace(
                external_metadata_info=SimpleNamespace(name="t__b"), table_info=None
            ),
            SimpleNamespace(
                external_metadata_info=None,
                table_info=SimpleNamespace(
                    catalog_name="main", schema_name="s", name="a"
                ),
            ),
        ]
    }
    ws = FakeWS(existing=["t__a", "t__b", "other__c"], rels=rels)
    monkeypatch.setattr(sts_lb_uc, "_client", lambda profile: ws)
    assert sts_lb_uc.remove("unused", "t", assume_yes=True) == 2
    assert sorted(ws.deleted_meta) == ["t__a", "t__b"]
    assert ws.deleted_rels[1].target.table.name == "main.s.a"
    with pytest.raises(SystemExit):
        sts_lb_uc.remove("unused", "bad prefix;", assume_yes=True)


def test_cli_accuracy_flags_end_to_end(tmp_path):
    pytest.importorskip("sqlglot")
    out1, out2 = tmp_path / "a", tmp_path / "b"
    main([str(FIX / "sql_retail.json"), "-o", str(out1)])
    main(
        [
            str(FIX / "sql_retail.json"),
            str(FIX / "sas_programs.json"),
            "-o",
            str(out2),
            "--columns",
            "--collapse-instances",
            "--search-path",
            "dbo",
            "--compare",
            str(out1 / "lineage.json"),
        ]
    )
    d = json.loads((out2 / "lineage.json").read_text())
    assert d["columns"] and d["insights"]["trust"]["columnStatements"] == 2
    assert d["diff"]["addedObjects"]


def test_ai_history_is_validated_and_capped():
    from sts_lb_lineage import ai

    hist = ai.clean_history([{"q": f"q{i}", "a": "x" * 9_000} for i in range(5)])
    assert [q for q, _ in hist] == ["q2", "q3", "q4"]
    assert all(len(a) == ai.MAX_ANSWER for _, a in hist)
    for bad in ("text", [{"q": 1, "a": "x"}], [["q", "a"]]):
        with pytest.raises(TypeError):
            ai.clean_history(bad)
    msgs = ai.messages_for({"objects": []}, "and then?", hist)
    assert [r for r, _ in msgs] == ["system"] + ["user", "assistant"] * 3 + ["user"]
    assert "Context (JSON)" in msgs[1][1] and msgs[-1][1].endswith("and then?")


def test_column_lineage_skips_oversized_sql():
    pytest.importorskip("sqlglot")
    from sts_lb_lineage.columns import MAX_SQL, column_edges

    huge = "INSERT INTO t SELECT a FROM s WHERE a IN (" + "1," * MAX_SQL + "1)"
    assert column_edges([{"job": "j", "sql": huge}])[1]["skipped"] == 1


def test_shared_uc_targets_are_flagged(tmp_path):
    d = load("sql_retail", "ssis_shifted").to_dict()
    d = sts_lb_uc.enrich(d, "main", "{catalog}.bronze.{table}")
    shared = {
        n["name"]: n["uc"]["sharedWith"]
        for n in d["nodes"]
        if "sharedWith" in n.get("uc", {})
    }
    assert shared["raw.orders"] == ["dst.orders", "src.orders"]
    assert d["insights"]["trust"]["ucTargetCollisions"] == 1
    sts_lb_uc.write_mapping(d, tmp_path)
    assert "dst.orders|src.orders" in (tmp_path / "uc_mapping.csv").read_text()
    clean = sts_lb_uc.enrich(load("sql_retail").to_dict(), "main")
    assert clean["insights"]["trust"]["ucTargetCollisions"] == 0
