"""AI-assisted impact analysis for sts-lb-lineage through a Databricks serving endpoint.

`sts-lb-lineage ... --serve --profile P --endpoint E` serves the viewer on 127.0.0.1 and
answers the viewer's "Explain impact" / "Ask" requests. The server builds the context from the
lineage itself (the browser only names a target), calls the endpoint with the Databricks CLI
profile, and never sends the Databricks credential to the browser.
"""

import json
import secrets
import sys
import threading
import webbrowser
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 24_000  # bytes per request from the viewer (question plus short history)
MAX_QUESTION = 1_000  # characters
MAX_HISTORY = 3  # earlier question/answer turns kept per request
MAX_ANSWER = 4_000  # characters kept from each earlier answer
MAX_OBJECTS = 300  # objects sent to the endpoint per request
SESSION_TAG = '<meta name="sts-ai-session" content="__AI_SESSION__">'

SYSTEM_PROMPT = """You are a data migration analyst. You explain lineage impact for a legacy \
SQL/ETL estate that is being migrated to Databricks.

Rules:
- Use only the JSON context you are given. If something is not in it, say it is not in the scan.
- Never invent tables, jobs, processes, numbers, effort estimates, or schedules.
- Name objects and processes exactly as they appear in the context.
- Write short Markdown: headings with ##, bullet lists with -, no tables, no HTML."""

EXPLAIN_PROMPT = """Explain the impact for the target in the context. Use these sections:
## Summary
Two or three sentences: what the target is and how far its impact reaches.
## What is affected
The affected processes and the most important objects, grouped by process.
## Risk flags
Only risks that the context shows: shared tables, dependency cycles, job-grain (approximate) \
edges, dynamic SQL, loops, high analyzer complexity, terminal outputs that may feed consumers \
outside the scan. Say "None in the scan" when there are none.
## What to check first
Three to five concrete checks, each tied to a named object or process."""


def _index(d: dict):
    nodes = {n["id"]: n for n in d["nodes"]}
    down, up = defaultdict(list), defaultdict(list)
    for e in d["edges"]:
        down[e["from"]].append(e)
        up[e["to"]].append(e)
    procs = {p["name"]: p for p in d["insights"]["processes"]}
    hubs = {h["id"]: h for h in d["insights"]["hubs"]}
    progs = {p["name"]: p for p in d["programs"]}
    return nodes, down, up, procs, hubs, progs


def _start(target: str, side: str, nodes, procs, hubs) -> list[str]:
    if target.startswith("proc:"):
        p = procs.get(target[5:])
        if not p:
            return []
        own = [
            h
            for h, v in hubs.items()
            if target[5:] in (v["writers"] if side == "down" else v["readers"])
        ]
        return list(p["objects"]) + own
    return [target] if target in nodes else []


def _walk(start: list[str], side: str, down, up) -> dict[str, int]:
    seen = {s: 0 for s in start}
    q = deque(start)
    while q:
        v = q.popleft()
        for e in (down if side == "down" else up)[v]:
            o = e["to"] if side == "down" else e["from"]
            if o not in seen:
                seen[o] = seen[v] + 1
                q.append(o)
    return seen


def impact_context(
    d: dict, target: str, mode: str = "down", to: str | None = None
) -> dict:
    """Compact, bounded impact context for one target (node id or "proc:<name>")."""
    nodes, down, up, procs, hubs, progs = _index(d)
    if mode == "path":
        a = _walk(_start(target, "down", nodes, procs, hubs), "down", down, up)
        b = _walk(_start(to or "", "up", nodes, procs, hubs), "up", down, up)
        hops = {k: v for k, v in a.items() if k in b}
    else:
        hops = _walk(_start(target, mode, nodes, procs, hubs), mode, down, up)
    if not hops:
        raise ValueError("unknown target or no lineage in this direction")
    ids = sorted(hops, key=lambda i: (hops[i], i))
    truncated = len(ids) > MAX_OBJECTS
    ids = ids[:MAX_OBJECTS]
    keep = set(ids)
    via = defaultdict(set)
    grain = defaultdict(int)
    for i in ids:
        for e in down[i]:
            if e["to"] in keep and e["kind"] == "data":
                grain[e["grain"]] += 1
                via[i].update(e["via"])
    involved = {p for i in ids for p in via[i]}
    objects = []
    for i in ids:
        n = nodes[i]
        o = {
            "name": n["name"],
            "kind": n["kind"],
            "role": n.get("role"),
            "process": n.get("process"),
            "hops": hops[i],
        }
        if i in hubs:
            o["shared_by"] = hubs[i]["processCount"]
        objects.append(o)
    affected = sorted({n.get("process") for n in (nodes[i] for i in ids)} - {None})
    proc_info = []
    for name in affected:
        p = procs.get(name)
        if p:
            proc_info.append(
                {
                    "name": name,
                    "tech": p["tech"],
                    "max_complexity": p["maxComplexity"],
                    "in_cycle": p["cycle"] is not None,
                }
            )
    programs = []
    for name in sorted(involved):
        p = progs.get(name) or {}
        dr = p.get("drivers") or {}
        flags = {k: dr[k] for k in ("dynamicSql", "loops", "embeddedSql") if dr.get(k)}
        programs.append(
            {
                "name": name,
                "tech": p.get("tech"),
                "complexity": p.get("complexity"),
                **flags,
            }
        )
    label = (
        target[5:]
        if target.startswith("proc:")
        else nodes.get(target, {}).get("name", target)
    )
    return {
        "target": {
            "name": label,
            "kind": "process"
            if target.startswith("proc:")
            else nodes.get(target, {}).get("kind"),
        },
        "direction": {
            "down": "downstream impact",
            "up": "upstream dependencies",
            "path": "path between two objects",
        }[mode],
        "path_end": (
            to[5:]
            if to and to.startswith("proc:")
            else nodes.get(to or "", {}).get("name")
        )
        if mode == "path"
        else None,
        "objects": objects,
        "objects_truncated": truncated,
        "processes": proc_info,
        "programs": programs[:100],
        "edge_grain": dict(grain),
    }


def clean_history(raw) -> list[tuple[str, str]]:
    """Earlier turns from the browser: a list of {q, a} strings, capped and truncated."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError("bad history")
    out = []
    for t in raw[-MAX_HISTORY:]:
        if not isinstance(t, dict) or not all(isinstance(t.get(k), str) for k in "qa"):
            raise TypeError("bad history turn")
        out.append((t["q"][:MAX_QUESTION], t["a"][:MAX_ANSWER]))
    return out


def messages_for(
    ctx: dict, question: str | None, history: list[tuple[str, str]] = ()
) -> list[tuple[str, str]]:
    task = (
        EXPLAIN_PROMPT
        if not question
        else f"Answer this question about the context:\n{question}"
    )
    context = f"Context (JSON):\n{json.dumps(ctx, separators=(',', ':'))}"
    if not history:
        return [("system", SYSTEM_PROMPT), ("user", f"{task}\n\n{context}")]
    msgs = [("system", SYSTEM_PROMPT)]
    for i, (q, a) in enumerate(history):
        msgs += [("user", f"{q}\n\n{context}" if i == 0 else q), ("assistant", a)]
    return msgs + [("user", task)]


def sdk_caller(profile: str, endpoint: str):
    """Returns (host, ask) where ask(messages) -> text, using the Databricks CLI profile."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    w = WorkspaceClient(profile=profile)
    w.serving_endpoints.get(endpoint)  # fail fast on a wrong name or missing access

    def ask(msgs: list[tuple[str, str]]) -> str:
        r = w.serving_endpoints.query(
            name=endpoint,
            messages=[
                ChatMessage(role=ChatMessageRole(role), content=content)
                for role, content in msgs
            ],
            max_tokens=1200,
            usage_context={"client": "sts-lb-lineage"},
        )
        choice = (r.choices or [None])[0]
        return (
            choice.message.content if choice and choice.message else None
        ) or "The endpoint returned no text."

    return w.config.host, ask


def make_handler(html: bytes, d: dict, ask, endpoint: str, host: str, token: str):

    calls = threading.BoundedSemaphore(2)  # at most two endpoint calls at once

    def has_token(h) -> bool:
        return secrets.compare_digest(h.headers.get("X-STS-Session") or "", token)

    class Handler(BaseHTTPRequestHandler):
        timeout = 15  # seconds; a stalled client cannot pin a thread

        def log_message(self, *args):  # keep customer names out of the terminal log
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj).encode())

        def _guard(self) -> bool:
            port = self.server.server_port
            if self.headers.get("Host") not in (
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            ):  # blocks DNS rebinding
                self._json(403, {"error": "forbidden host"})
                return False
            return True

        def do_GET(self):
            if not self._guard():
                return
            if self.path in ("/", "/index.html"):
                return self._send(200, html, "text/html; charset=utf-8")
            if self.path == "/api/ai/status":
                if not has_token(self):
                    return self._json(403, {"error": "missing session"})
                return self._json(200, {"endpoint": endpoint, "host": host})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            if self.path != "/api/ai":
                return self._json(404, {"error": "not found"})
            if not has_token(self):  # custom header: cross-site pages cannot send it
                return self._json(403, {"error": "missing session"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json(415, {"error": "json only"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "bad content length"})
            if n <= 0 or n > MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                req = json.loads(self.rfile.read(n))
                target = str(req["target"])
                mode = req.get("mode", "down")
                if mode not in ("down", "up", "path"):
                    raise ValueError("bad mode")
                to = req.get("to")
                if to is not None and not isinstance(to, str):
                    raise ValueError("bad path end")
                question = req.get("question")
                if question is not None:
                    question = str(question).strip()[:MAX_QUESTION] or None
                history = clean_history(req.get("history")) if question else []
                ctx = impact_context(d, target, mode, to)
            except (
                KeyError,
                ValueError,
                TypeError,
                AttributeError,
                RecursionError,
            ) as e:
                return self._json(400, {"error": f"bad request: {type(e).__name__}"})
            if not calls.acquire(blocking=False):
                return self._json(
                    429, {"error": "another request is running; try again"}
                )
            try:
                answer = ask(messages_for(ctx, question, history))
            except Exception as e:  # noqa: BLE001 - keep SDK details (host, config) out of the browser
                print(f"endpoint call failed: {type(e).__name__}: {e}", file=sys.stderr)
                return self._json(
                    502,
                    {
                        "error": f"the endpoint call failed ({type(e).__name__}); see the terminal"
                    },
                )
            finally:
                calls.release()
            self._json(
                200,
                {
                    "answer": answer,
                    "objects": len(ctx["objects"]),
                    "truncated": ctx["objects_truncated"],
                },
            )

    return Handler


def serve(
    html_path: Path,
    d: dict,
    profile: str,
    endpoint: str,
    port: int = 8765,
    open_browser: bool = True,
    ask=None,
):
    """Serve the viewer with AI on 127.0.0.1 until Ctrl+C."""
    if ask is None:
        try:
            host, ask = sdk_caller(profile, endpoint)
        except Exception as e:  # noqa: BLE001
            sys.exit(
                f"Cannot use endpoint '{endpoint}' with profile '{profile}': {type(e).__name__}: {e}"
            )
    else:
        host = "test"
    token = secrets.token_urlsafe(24)
    page = html_path.read_text(encoding="utf-8")
    if SESSION_TAG not in page:
        sys.exit(f"{html_path} has no AI session tag; rebuild the viewer")
    html = page.replace(
        SESSION_TAG, SESSION_TAG.replace("__AI_SESSION__", token), 1
    ).encode()
    try:
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", port), make_handler(html, d, ask, endpoint, host, token)
        )
    except OSError as e:
        sys.exit(
            f"Cannot listen on 127.0.0.1:{port} ({e.strerror}). Pick another port with --port."
        )
    url = f"http://127.0.0.1:{httpd.server_port}/"
    print(
        f"Serving the viewer with AI at {url} (endpoint {endpoint} on {host}). Press Ctrl+C to stop.",
        file=sys.stderr,
    )
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
