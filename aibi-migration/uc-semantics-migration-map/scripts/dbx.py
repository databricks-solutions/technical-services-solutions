"""dbx.py — Databricks client for apply.py / author.py, plus an in-memory FakeClient.

DbxClient wraps the Databricks SDK (`databricks-sdk`, preinstalled on Databricks compute):
  * inside Genie Code / a notebook / a job it authenticates ambiently — `DbxClient()` just works;
  * elsewhere pass `profile="<cli profile>"` (or rely on DATABRICKS_HOST/TOKEN env vars).
No tokens are read, logged or stored by this code.

FakeClient mimics exactly the endpoints apply.py uses, so the plan/apply loop (and idempotency) is testable
without a workspace:  python3 -I tests/test_idempotency.py
"""
import re
import urllib.parse


class ApiError(Exception):
    pass


class NotFound(ApiError):
    pass


class Unsupported(ApiError):
    """Endpoint does not exist on this workspace/release (feature not enabled or not rolled out)."""


class Denied(ApiError):
    pass


# ------------------------------------------------------------------ real client
class DbxClient:
    def __init__(self, profile=None, warehouse_id=None):
        try:
            from databricks.sdk import WorkspaceClient
        except ImportError as e:  # pragma: no cover
            raise ApiError("databricks-sdk is not installed — `pip install databricks-sdk` (preinstalled on Databricks compute)") from e
        try:
            self.w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
        except ValueError as e:
            if "CONTEXT_UNAVAILABLE_FOR_REMOTE_CLIENT" in str(e) or "runtime" in str(e):
                raise ApiError(
                    "Databricks notebook credentials are not available to a child process. Run the script IN-PROCESS instead:\n"
                    "    import sys; sys.path.insert(0, '<skill>/scripts'); import ucsm; ucsm.run('<script>.py', ...)\n"
                    "or set DATABRICKS_HOST and DATABRICKS_TOKEN (or pass --profile) for the child process.") from e
            raise ApiError(f"cannot authenticate to Databricks: {str(e)[:300]}") from e
        self.profile = profile
        self._wh = warehouse_id

    # ---- REST
    def _do(self, method, path, params=None, body=None):
        from databricks.sdk import errors as E
        try:
            return self.w.api_client.do(method, path, query=params or None, body=body) or {}
        except E.NotFound as e:
            if re.search(r"No API found|ENDPOINT_NOT_FOUND|no such (api|route)", str(e), re.I):
                raise Unsupported(str(e)) from e
            raise NotFound(str(e)) from e
        except E.PermissionDenied as e:
            raise Denied(str(e)) from e
        except E.DatabricksError as e:
            msg = str(e)
            if re.search(r"No API found|ENDPOINT_NOT_FOUND|Not Found$", msg, re.I) and "RESOURCE_DOES_NOT_EXIST" not in msg:
                raise Unsupported(msg) from e
            if getattr(e, "error_code", "") in ("RESOURCE_DOES_NOT_EXIST", "NOT_FOUND"):
                raise NotFound(msg) from e
            raise ApiError(msg) from e

    def get(self, path, params=None):
        return self._do("GET", path, params)

    def post(self, path, body=None, params=None):
        return self._do("POST", path, params, body)

    def patch(self, path, body=None, params=None):
        return self._do("PATCH", path, params, body)

    def delete(self, path, params=None):
        return self._do("DELETE", path, params)

    # ---- SQL
    @property
    def warehouse_id(self):
        if not self._wh:
            self._wh = self._pick_warehouse()
        return self._wh

    def _pick_warehouse(self):
        try:
            whs = list(self.w.warehouses.list())
        except Exception as e:
            raise ApiError(f"cannot list SQL warehouses: {e}") from e
        if not whs:
            raise ApiError("no SQL warehouse available — create one (DBR 17.3+ for metric views) or set target.warehouse_id")

        def rank(x):
            st = str(getattr(x, "state", "")).upper()
            serverless = bool(getattr(x, "enable_serverless_compute", False))
            return (0 if "RUNNING" in st else 1, 0 if serverless else 1)
        return sorted(whs, key=rank)[0].id

    def sql(self, statement):
        import time
        from databricks.sdk.service.sql import StatementState
        try:
            r = self.w.statement_execution.execute_statement(statement=statement, warehouse_id=self.warehouse_id, wait_timeout="50s")
            while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
                time.sleep(2)
                r = self.w.statement_execution.get_statement(r.statement_id)
        except Exception as e:
            raise ApiError(f"SQL failed: {str(e)[:400]}") from e
        if r.status.state != StatementState.SUCCEEDED:
            err = r.status.error
            raise ApiError(f"SQL {r.status.state}: {(err.message if err else '')[:400]}")
        return (r.result.data_array if r.result and r.result.data_array else [])

    # ---- UC helpers
    def table_columns(self, fqn):
        t = self.w.tables.get(fqn)
        return [(c.name, str(c.type_text or c.type_name)) for c in (t.columns or [])]

    def who(self):
        try:
            return self.w.current_user.me().user_name
        except Exception:
            return "?"

    host = who


# ------------------------------------------------------------------ fake client
class FakeClient:
    """In-memory stand-in for the endpoints apply.py uses. `.writes` records every mutation."""

    def __init__(self, pages=True, wikis=True, tag_policies=True):
        self.domains, self.tags, self.tables, self.pages, self.wikis = {}, {}, {}, {}, {}
        self.caps = dict(pages=pages, wikis=wikis, tag_policies=tag_policies)
        self.writes = []
        self._pid = 0
        self.columns = {}  # fqn -> [(name,type)] for table_columns()

    def _w(self, what):
        self.writes.append(what)

    def who(self):
        return "fake@test"

    host = who

    def table_columns(self, fqn):
        return self.columns.get(fqn, [])

    def _nf(self, p):
        raise NotFound(p)

    # -- GET
    def get(self, path, params=None):
        params = params or {}
        if path == "/api/2.0/domains":
            return dict(domains=list(self.domains.values()))
        m = re.match(r"/api/2\.0/domains/(.+)$", path)
        if m:
            return self.domains[m.group(1)] if m.group(1) in self.domains else self._nf(path)
        if path == "/api/2.1/tag-policies":
            if not self.caps["tag_policies"]:
                raise Unsupported(path)
            return dict(tag_policies=[dict(tag_key=k) for k in self.tags])
        if path.startswith("/api/2.1/unity-catalog/tables/"):
            fq = path.split("/tables/")[-1]
            return self.tables[fq] if fq in self.tables else self._nf(path)
        if path == "/api/2.0/knowledge/pages":
            if not self.caps["pages"]:
                raise Unsupported(path)
            f = params.get("filter") or ""
            dm = re.search(r'domain = "([^"]+)"', f)
            rows = [dict(name=p["name"], domain=p["domain"], display_name=p["display_name"], state=p["state"])
                    for p in self.pages.values() if not dm or p["domain"] == dm.group(1)]
            # behave like the real service: ONE row per response, always with a continuation token until the end
            i = int(params.get("page_token") or 0)
            return dict(pages=rows[i:i + 1], **({"next_page_token": str(i + 1)} if i + 1 < len(rows) else {}))
        m = re.match(r"/api/2\.0/knowledge/pages/(.+)$", path)
        if m:
            return self.pages.get("pages/" + m.group(1)) or self._nf(path)
        m = re.match(r"/api/2\.0/knowledge/tables/(.+)/page$", path)
        if m:
            if not self.caps["wikis"]:
                raise Unsupported(path)
            return self.wikis.get(urllib.parse.unquote(m.group(1))) or self._nf(path)
        raise Unsupported(path)

    # -- POST
    def post(self, path, body=None, params=None):
        params = params or {}
        if path == "/api/2.0/domains":
            if any(d["tag_key"] == body["tag_key"] for d in self.domains.values()):
                raise ApiError("ALREADY_EXISTS domain on tag")
            did = params.get("domain_id") or f"d{len(self.domains) + 1}"
            self.domains[did] = dict(body, domain_id=did, name=f"domains/{did}", effective_draft=body.get("draft", True))
            self._w(f"domain+{did}")
            return self.domains[did]
        if path == "/api/2.1/tag-policies":
            self.tags[body["tag_key"]] = body
            self._w("tag+")
            return body
        if path == "/api/2.0/knowledge/pages":
            rid = params.get("request_id")
            for p in self.pages.values():
                if rid and p.get("_rid") == rid:
                    return p
            self._pid += 1
            nm = f"pages/p{self._pid}"
            self.pages[nm] = dict(body, name=nm, _rid=rid, state=body.get("state", "DRAFT"))
            self._w(f"page+{nm}")
            return self.pages[nm]
        raise Unsupported(path)

    # -- PATCH
    def patch(self, path, body=None, params=None):
        m = re.match(r"/api/2\.0/domains/(.+)$", path)
        if m:
            self.domains[m.group(1)].update(body)
            if "draft" in body:
                self.domains[m.group(1)]["effective_draft"] = body["draft"]
            self._w(f"domain~{m.group(1)}")
            return self.domains[m.group(1)]
        m = re.match(r"/api/2\.0/knowledge/pages/(.+)$", path)
        if m:
            self.pages["pages/" + m.group(1)].update(body)
            self._w(f"page~{m.group(1)}")
            return self.pages["pages/" + m.group(1)]
        m = re.match(r"/api/2\.0/knowledge/tables/(.+)/page$", path)
        if m:
            t = urllib.parse.unquote(m.group(1))
            self.wikis[t] = dict(self.wikis.get(t, dict(state="DRAFT")), **body, name=f"tables/{t}/page")
            self._w(f"wiki~{t}")
            return self.wikis[t]
        raise Unsupported(path)

    def delete(self, path, params=None):
        m = re.match(r"/api/2\.0/domains/(.+)$", path)
        if m:
            self.domains.pop(m.group(1), None)
            self._w(f"domain-{m.group(1)}")
            return {}
        m = re.match(r"/api/2\.0/knowledge/pages/(.+)$", path)
        if m:
            self.pages.pop("pages/" + m.group(1), None)
            self._w(f"page-{m.group(1)}")
            return {}
        m = re.match(r"/api/2\.1/tag-policies/(.+)$", path)
        if m:
            self.tags.pop(urllib.parse.unquote(m.group(1)), None)
            self._w("tag-")
            return {}
        raise Unsupported(path)

    # -- SQL
    def sql(self, st):
        s = " ".join(st.split())
        m = re.match(r"CREATE OR REPLACE VIEW (\S+) WITH METRICS LANGUAGE YAML AS \$\$(.*)\$\$\s*$", st.strip(), re.S)
        if m:
            fq = m.group(1)
            self.tables[fq] = dict(full_name=fq, table_type="METRIC_VIEW", view_definition=m.group(2).strip(), tags=self.tables.get(fq, {}).get("tags", []))
            self._w(f"mv:{fq}")
            return []
        m = re.match(r"SELECT MEASURE\(`([^`]+)`\) FROM (\S+)", s)
        if m:
            if m.group(2) not in self.tables:
                raise ApiError("TABLE_OR_VIEW_NOT_FOUND")
            if "BROKEN" in self.tables[m.group(2)].get("view_definition", ""):
                raise ApiError("UNRESOLVED_COLUMN in measure")
            return [["1"]]
        m = re.match(r"ALTER (?:TABLE|VIEW) (\S+) SET TAGS \('([^']+)'", s)
        if m:
            t = self.tables.setdefault(m.group(1), dict(full_name=m.group(1), tags=[]))
            if m.group(2) not in t["tags"]:
                t["tags"] = t["tags"] + [m.group(2)]
            self._w(f"tag:{m.group(1)}:{m.group(2)}")
            return []
        m = re.match(r"SELECT tag_name FROM (\S+)\.information_schema\.table_tags WHERE .*table_name = '([^']+)'.*schema_name = '([^']+)'", s)
        if m:
            fq = f"{m.group(1)}.{m.group(3)}.{m.group(2)}"
            return [[t] for t in self.tables.get(fq, {}).get("tags", [])]
        m = re.match(r"DROP VIEW IF EXISTS (\S+)", s)
        if m:
            self.tables.pop(m.group(1), None)
            self._w(f"dropmv:{m.group(1)}")
            return []
        raise ApiError(f"FakeClient: unhandled SQL {s[:80]}")
