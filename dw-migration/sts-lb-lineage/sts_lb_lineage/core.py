"""Build table-level lineage from BladeBridge analyzer (bladespector) JSON output.

sts-lb-lineage report.json [more.json ...] -o lineage/ --open
sts-lb-lineage --run ./src --platform Oracle -o lineage/
sts-lb-lineage report.json --focus dw.fact_orders -o lineage/
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ETL_IN = {"source", "lookup", "read"}
ETL_OUT = {"target", "write", "create"}
ETL_EXEC = {"execute"}
DDL_TAGS = {"create", "drop", "truncate", "delete"}
SHARED = "(shared by several processes)"
NO_PROCESS = "(no process)"
LEVELS = [
    "LOW",
    "MEDIUM",
    "HIGH",
    "COMPLEX",
    "VERY_HIGH",
]  # COMPLEX: SAS emits it off-schema


def item_meta(item: dict, root: str | None = None) -> dict:
    """Complexity and its drivers for one analyzer inventory item (SQL script or ETL job)."""

    def n(k):
        return len(item.get(k) or [])

    drivers = {
        "transformations": item.get("nodes") or {},
        "functions": item.get("functionCall") or {},
        "parameters": n("jobParameters"),
        "embeddedSql": n("sqlStatements"),
        "dynamicSql": n("dynamicStatements"),
        "loops": n("loopsAndCursors"),
        "conditionals": n("conditionalStatements"),
        "lines": item.get("lineCount"),
        "statements": item.get("statementCount"),
        "categories": item.get("scriptCategories") or [],
    }
    return {
        "complexity": item.get("complexityLevel") or "UNKNOWN",
        "type": item.get("type") or item.get("scriptType"),
        "folder": local(item.get("folder"), root),
        "drivers": {k: v for k, v in drivers.items() if v not in (None, 0, {}, [])},
    }


VIEWER = Path(__file__).with_name(
    "lineage_viewer.html"
)  # built by viewer/ (npm run build)
PLACEHOLDER = "__LINEAGE_JSON__"
DATA_TAG = f'<script id="lineage-data" type="application/json">{PLACEHOLDER}</script>'


def clean(name: str) -> str:
    return ".".join(p.strip("[]\"`' ") for p in name.strip().split("."))


def local(path, root: str | None):
    """Analyzer paths can be absolute on the scanning machine. Keep them relative to the scanned
    folder (or the file name only) so outputs carry no local paths."""
    if not path:
        return path
    s, r = str(path).replace("\\", "/"), (root or "").replace("\\", "/").rstrip("/")
    if r and (s == r or s.startswith(r + "/")):
        return s[len(r) + 1 :] or "."
    if s.startswith("/") or re.match(r"^[A-Za-z]:/", s):
        return s.rsplit("/", 1)[-1]
    return path


def fix_rel(r: dict) -> dict:
    # Analyzer bug (SSIS, 0.3.1): {"object": task, "action": table, "count": {"Source": 1}}
    if isinstance(r.get("count"), dict) and r["count"]:
        direction, n = next(iter(r["count"].items()))
        return {
            "object": r["action"],
            "action": direction.lower(),
            "count": n,
            "task": r["object"],
        }
    return r


class Lineage:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple, dict] = {}
        self.programs: dict[str, dict] = {}
        self.parents: dict[str, set] = defaultdict(set)
        self.post = None  # optional hook: dict -> dict, applied before writing
        self.input_dir: str | None = (
            None  # analyzer inputFolder of the report being read
        )
        self.statements: list[dict] = []  # embedded ETL SQL text, for column lineage

    def node(self, kind: str, name: str, tech: str | None = None) -> str:
        name = clean(name)
        nid = f"{kind}:{name.lower()}"
        n = self.nodes.setdefault(
            nid, {"id": nid, "name": name, "kind": kind, "tags": set()}
        )
        if kind == "table" and name[:1] in "@#":
            n["tags"].add("temp")
        if tech:
            n["tags"].add(tech)
        return nid

    def edge(self, src: str, dst: str, kind: str, via: str, grain: str, tech: str):
        e = self.edges.setdefault(
            (src, dst, kind),
            {
                "from": src,
                "to": dst,
                "kind": kind,
                "via": set(),
                "grain": grain,
                "tech": tech,
            },
        )
        e["via"].add(via)

    def program(self, name: str, tech: str, reads=(), writes=()):
        p = self.programs.setdefault(
            name, {"name": name, "tech": tech, "reads": set(), "writes": set()}
        )
        p["reads"].update(reads)
        p["writes"].update(writes)

    def add_report(self, data: dict):
        run = data.get("runInfo") or {}
        tech = run.get("sourceTechnology") or "unknown"
        self.input_dir = run.get("inputFolder")
        if "object_lineage" in data or tech == "SQL":
            self._add_sql(data, tech)
        else:
            self._add_etl(data, tech)

    def _add_sql(self, data: dict, tech: str):
        for item in data.get("inventory") or []:
            name = local(item.get("sourceFile") or item["name"], self.input_dir)
            self.program(name, tech)
            self.programs[name].update(item_meta(item, self.input_dir))
        for entry in data.get("object_lineage") or []:
            dst = self.node("table", entry["target"])
            for w in entry.get("writes") or []:
                srcs = [self.node("table", s) for s in w["sources"]]
                f = local(w["file"], self.input_dir)
                for src in srcs:
                    self.edge(src, dst, "data", f, "statement", tech)
                self.program(f, tech, srcs, [dst])
            for f in entry.get("reads") or []:
                self.program(local(f, self.input_dir), tech, reads=[dst])

    def _add_etl(self, data: dict, tech: str):
        for item in data.get("inventory") or []:
            job = local(item["name"], self.input_dir)
            # statement-level first so shared edges keep the finer grain
            for st in item.get("sqlStatements") or []:
                self._link(st.get("objectRel"), job, "statement", tech)
                if st.get("sql"):
                    self.statements.append({"job": job, "tech": tech, "sql": st["sql"]})
            # inputs x outputs per job over-links multi-flow mappings; the analyzer's `nodes` holds
            # transformation counts only (no flow graph), so job grain is the finest available here
            self._link(item.get("objectRel"), job, "job", tech)
            self.programs[job].update(item_meta(item, self.input_dir))
        subs = data.get("subJobInfo") or []
        known = {s["parent"] for s in subs}
        for s in subs:
            child = s["child"]
            # Oozie (0.3.1) qualifies parents (workflow.wf.action) but not children (action)
            scope = s["parent"].rpartition(".")[0]
            if (
                child not in known
                and "." not in child
                and scope
                and f"{scope}.{child}" in known
            ):
                child = f"{scope}.{child}"
            p, c = (
                self.node("job", s["parent"], s.get("parentType")),
                self.node("job", child, s.get("childType")),
            )
            self.edge(p, c, "orchestration", s["parent"], "job", tech)
            self.parents[child.lower()].add(s["parent"])

    def _link(self, rels, job: str, grain: str, tech: str):
        rels = [fix_rel(r) for r in rels or []]
        ins = [self.node("table", r["object"]) for r in rels if r["action"] in ETL_IN]
        outs = [self.node("table", r["object"]) for r in rels if r["action"] in ETL_OUT]
        for r in rels:
            if r["action"] in DDL_TAGS:
                self.nodes[self.node("table", r["object"])]["tags"].add(r["action"])
            if r["action"] in ETL_EXEC:
                self.edge(
                    self.node("job", job),
                    self.node("job", r["object"]),
                    "orchestration",
                    job,
                    "job",
                    tech,
                )
                self.parents[r["object"].lower()].add(job)
        for src in ins:
            for dst in outs:
                if src != dst:
                    self.edge(src, dst, "data", job, grain, tech)
        self.program(job, tech, ins, outs)

    def focus(self, name: str) -> "Lineage":
        start = next(
            (nid for nid in self.nodes if nid.split(":", 1)[1] == clean(name).lower()),
            None,
        )
        if not start:
            sys.exit(f"--focus: '{name}' not found")
        down, up = defaultdict(set), defaultdict(set)
        for s, d, _ in self.edges:
            down[s].add(d)
            up[d].add(s)
        keep = {start}
        for adj in (down, up):
            stack = [start]
            while stack:
                for nxt in adj[stack.pop()] - keep:
                    keep.add(nxt)
                    stack.append(nxt)
        sub = Lineage()
        sub.nodes = {k: v for k, v in self.nodes.items() if k in keep}
        sub.edges = {
            k: v for k, v in self.edges.items() if k[0] in keep and k[1] in keep
        }
        vias = {v for e in sub.edges.values() for v in e["via"]}
        sub.programs = {k: v for k, v in self.programs.items() if k in vias}
        sub.parents = self.parents
        return sub

    def root(self, name: str, seen: frozenset = frozenset()) -> set[str]:
        """Top-level process(es) of a program: walk subJobInfo/execute parents up."""
        ups = {
            p for p in self.parents.get(name.lower(), ()) if p.lower() != name.lower()
        } - seen
        if not ups:
            return {name}
        return set().union(*(self.root(p, seen | {name}) for p in ups))

    def processes(self) -> dict[str, str]:
        """Node id -> parent process. A table belongs to the one process that writes or
        reads it; a table touched by several processes is a shared hub (SHARED), because
        it is the contract between them."""
        roots = {name: self.root(name) for name in self.programs}
        writers, readers = defaultdict(set), defaultdict(set)
        for name, p in self.programs.items():
            for nid in p["writes"]:
                writers[nid] |= roots[name]
            for nid in p["reads"]:
                readers[nid] |= roots[name]
        out = {}
        for nid, n in self.nodes.items():
            if n["kind"] == "job":
                procs = self.root(n["name"])
            else:
                procs = writers[nid] | readers[nid]
            out[nid] = (
                next(iter(procs))
                if len(procs) == 1
                else SHARED
                if procs
                else NO_PROCESS
            )
        return out

    def insights(self) -> dict:
        """Migration intelligence: object roles, process graph, shared hubs, cycles, statistics, trust."""
        proc = self.processes()
        prog_proc = {name: min(self.root(name)) for name in self.programs}
        writers, readers = defaultdict(set), defaultdict(set)  # table -> processes
        written, read = set(), set()
        for name, p in self.programs.items():
            for nid in p["writes"]:
                writers[nid].add(prog_proc[name])
                written.add(nid)
            for nid in p["reads"]:
                readers[nid].add(prog_proc[name])
                read.add(nid)

        roles = {}
        for nid, n in self.nodes.items():
            if n["kind"] == "job":
                roles[nid] = "job"
            else:
                w, r = nid in written, nid in read
                roles[nid] = (
                    "intermediate"
                    if w and r
                    else "source"
                    if r
                    else "terminal"
                    if w
                    else "orphan"
                )

        names = sorted(
            ({prog_proc[p] for p in self.programs} | set(proc.values()))
            - {SHARED, NO_PROCESS}
        )
        pedges = defaultdict(set)  # (writer process, reader process) -> tables
        for nid in self.nodes:
            for w in writers[nid]:
                for r in readers[nid] - {w}:
                    pedges[(w, r)].add(nid)
        succ = defaultdict(set)
        for a, b in pedges:
            succ[a].add(b)

        comp = scc(names, succ)
        sizes = defaultdict(int)
        for n_ in names:
            sizes[comp[n_]] += 1
        by_proc = defaultdict(list)
        for prog, pr in prog_proc.items():
            by_proc[pr].append(prog)
        objs = defaultdict(list)
        for nid, pr in proc.items():
            objs[pr].append(nid)
        up, down = defaultdict(set), defaultdict(set)
        for a, b in pedges:
            down[a].add(b)
            up[b].add(a)

        processes = []
        for name in names:
            progs = sorted(by_proc[name])
            counts = defaultdict(int)
            for prog in progs:
                counts[self.programs[prog].get("complexity", "UNKNOWN")] += 1
            ranked = [lv for lv in LEVELS if counts.get(lv)]
            processes.append(
                {
                    "name": name,
                    "tech": sorted({self.programs[prog]["tech"] for prog in progs}),
                    "programs": progs,
                    "objects": sorted(objs[name]),
                    "complexity": dict(counts),
                    "maxComplexity": ranked[-1] if ranked else "UNKNOWN",
                    "cycle": comp[name] if sizes[comp[name]] > 1 else None,
                    "upstream": sorted(up[name]),
                    "downstream": sorted(down[name]),
                }
            )

        hubs = sorted(
            (
                {
                    "id": nid,
                    "writers": sorted(writers[nid]),
                    "readers": sorted(readers[nid]),
                    "processCount": len(writers[nid] | readers[nid]),
                }
                for nid in self.nodes
                if proc[nid] == SHARED
            ),
            key=lambda h: (-h["processCount"], h["id"]),
        )
        tables = [nid for nid, n in self.nodes.items() if n["kind"] == "table"]
        grain = defaultdict(int)
        for e in self.edges.values():
            if e["kind"] == "data":
                grain[e["grain"]] += 1
        progs = self.programs.values()
        return {
            "summary": {
                "processes": len(names),
                "programs": len(self.programs),
                "tables": len(tables),
                "edges": len(self.edges),
                "cycles": len(
                    {p["cycle"] for p in processes if p["cycle"] is not None}
                ),
                "hubs": len(hubs),
                "roles": {
                    r: sum(1 for t in tables if roles[t] == r)
                    for r in ("source", "intermediate", "terminal", "orphan")
                },
                "complexity": {
                    lv: sum(1 for p in progs if p.get("complexity", "UNKNOWN") == lv)
                    for lv in LEVELS + ["UNKNOWN"]
                },
                "technologies": {
                    t: sum(1 for p in progs if p["tech"] == t)
                    for t in sorted({p["tech"] for p in progs})
                },
            },
            "statistics": statistics(self, processes, pedges, hubs),
            "processes": processes,
            "processEdges": [
                {"from": a, "to": b, "tables": sorted(t)}
                for (a, b), t in sorted(pedges.items())
            ],
            "hubs": hubs,
            "roles": roles,
            "trust": {
                "statementGrainEdges": grain["statement"],
                "jobGrainEdges": grain["job"],
                "tempTables": sum(1 for t in tables if "temp" in self.nodes[t]["tags"]),
                "unqualifiedTables": sum(
                    1 for t in tables if "." not in self.nodes[t]["name"]
                ),
                "programsWithoutLineage": sum(
                    1 for p in progs if not p["reads"] and not p["writes"]
                ),
                "offSchemaComplexity": sum(
                    1 for p in progs if p.get("complexity") == "COMPLEX"
                ),
            },
        }

    def to_dict(self) -> dict:
        def s(x):
            return sorted(x) if isinstance(x, set) else x

        proc = self.processes()
        ins = self.insights()
        roles = ins.pop("roles")
        return {
            "insights": ins,
            "nodes": [
                {
                    **{k: s(v) for k, v in n.items()},
                    "process": proc[n["id"]],
                    "role": roles[n["id"]],
                }
                for n in self.nodes.values()
            ],
            "edges": [{k: s(v) for k, v in e.items()} for e in self.edges.values()],
            "programs": [
                {k: s(v) for k, v in p.items()} for p in self.programs.values()
            ],
        }

    def to_mermaid(self) -> str:
        ids = {nid: f"n{i}" for i, nid in enumerate(self.nodes)}
        out = ["flowchart LR"]
        groups = defaultdict(list)
        for nid, proc in self.processes().items():
            groups[proc].append(nid)
        for gi, (proc, members) in enumerate(sorted(groups.items())):
            out.append(f'  subgraph p{gi}["{mermaid_text(Path(proc).name)}"]')
            for nid in members:
                n = self.nodes[nid]
                label = mermaid_text(n["name"])
                o, c = ("[[", "]]") if n["kind"] == "job" else ("[", "]")
                out.append(f'    {ids[nid]}{o}"{label}"{c}')
            out.append("  end")
        for nid, n in self.nodes.items():
            if "temp" in n["tags"]:
                out.append(f"  style {ids[nid]} stroke-dasharray: 5 5")
        for (s, d, kind), e in self.edges.items():
            via = mermaid_text(", ".join(sorted(Path(v).name for v in e["via"])))
            via = via if len(via) <= 60 else via[:57] + "..."
            arrow = "-.->" if kind == "orchestration" else "-->"
            out.append(
                f'  {ids[s]} {arrow}|"{via.replace(chr(34), chr(39))}"| {ids[d]}'
            )
        return "\n".join(out) + "\n"

    def write(self, out: Path, formats: set[str]) -> dict:
        out.mkdir(parents=True, exist_ok=True)
        d = self.to_dict()
        if self.post:
            d = self.post(d)
        if "json" in formats:
            (out / "lineage.json").write_text(json.dumps(d, indent=2))
        if "csv" in formats:
            with open(out / "edges.csv", "w", newline="") as f:
                w = safe_writer(f)
                w.writerow(["from", "to", "kind", "via", "grain", "tech"])
                for e in d["edges"]:
                    w.writerow(
                        [
                            self.nodes[e["from"]]["name"],
                            self.nodes[e["to"]]["name"],
                            e["kind"],
                            "|".join(e["via"]),
                            e["grain"],
                            e["tech"],
                        ]
                    )
            with open(out / "nodes.csv", "w", newline="") as f:
                w = safe_writer(f)
                w.writerow(["id", "name", "kind", "process", "role", "tags"])
                for n in d["nodes"]:
                    w.writerow(
                        [
                            n["id"],
                            n["name"],
                            n["kind"],
                            n["process"],
                            n["role"],
                            "|".join(n["tags"]),
                        ]
                    )
            ins = d["insights"]
            with open(out / "processes.csv", "w", newline="") as f:
                w = safe_writer(f)
                w.writerow(
                    [
                        "process",
                        "tech",
                        "cycle",
                        "programs",
                        "objects",
                        "max_complexity",
                    ]
                    + LEVELS
                    + ["upstream", "downstream"]
                )
                for p in sorted(ins["processes"], key=lambda p: p["name"]):
                    w.writerow(
                        [
                            p["name"],
                            "|".join(p["tech"]),
                            "" if p["cycle"] is None else p["cycle"],
                            len(p["programs"]),
                            len(p["objects"]),
                            p["maxComplexity"],
                        ]
                        + [p["complexity"].get(lv, 0) for lv in LEVELS]
                        + ["|".join(p["upstream"]), "|".join(p["downstream"])]
                    )
            with open(out / "hubs.csv", "w", newline="") as f:
                w = safe_writer(f)
                w.writerow(["table", "process_count", "writers", "readers"])
                for h in ins["hubs"]:
                    w.writerow(
                        [
                            self.nodes[h["id"]]["name"],
                            h["processCount"],
                            "|".join(h["writers"]),
                            "|".join(h["readers"]),
                        ]
                    )
        if "mermaid" in formats:
            (out / "lineage.mmd").write_text(self.to_mermaid())
        if "html" in formats:
            payload = json.dumps(d, separators=(",", ":")).replace("<", "\\u003c")
            html = VIEWER.read_text(encoding="utf-8")
            if DATA_TAG not in html:
                sys.exit(
                    f"{VIEWER} has no data placeholder; rebuild it with `npm run build` in viewer/"
                )
            html = html.replace(DATA_TAG, DATA_TAG.replace(PLACEHOLDER, payload), 1)
            (out / "lineage.html").write_text(html, encoding="utf-8")
        return d


def mermaid_text(s: str) -> str:
    """Make a name safe inside a quoted Mermaid label: no quotes, line breaks, or brackets."""
    return re.sub(r'["\r\n\[\]{}()<>|]', " ", s).strip()


class safe_writer:
    """csv.writer that neutralizes spreadsheet formulas in text cells (CSV injection):
    customer object names that start with = + - @ open as formulas in Excel otherwise."""

    def __init__(self, f):
        self.w = csv.writer(f)

    def writerow(self, row):
        self.w.writerow(
            [
                "'" + v
                if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r")
                else v
                for v in row
            ]
        )


def statistics(lin: "Lineage", processes: list, pedges: dict, hubs: list) -> dict:
    """Descriptive statistics of the scanned estate (facts only, no estimates)."""
    tables = {nid for nid, n in lin.nodes.items() if n["kind"] == "table"}
    fan_in, fan_out = defaultdict(set), defaultdict(set)
    for a, b, kind in lin.edges:
        if kind == "data":
            fan_out[a].add(b)
            fan_in[b].add(a)

    def top(m, n=10):
        ranked = sorted(
            ((len(v), k) for k, v in m.items() if k in tables), reverse=True
        )[:n]
        return [{"id": k, "count": c} for c, k in ranked]

    def summed(key, n=15):
        total = defaultdict(int)
        for p in lin.programs.values():
            for k, v in ((p.get("drivers") or {}).get(key) or {}).items():
                total[k] += v
        return [
            {"name": k, "count": v}
            for k, v in sorted(total.items(), key=lambda kv: -kv[1])[:n]
        ]

    code = defaultdict(int)
    for p in lin.programs.values():
        for k in (
            "lines",
            "statements",
            "embeddedSql",
            "dynamicSql",
            "loops",
            "conditionals",
            "parameters",
        ):
            code[k] += (p.get("drivers") or {}).get(k) or 0
    sizes = sorted(len(p["objects"]) for p in processes if p["objects"])
    schemas = defaultdict(int)
    for t in tables:
        name = lin.nodes[t]["name"]
        schemas[name.rsplit(".", 1)[0] if "." in name else "(no schema)"] += 1
    types = defaultdict(int)
    for p in lin.programs.values():
        types[p.get("type") or "(unknown)"] += 1
    hub_procs = {x for h in hubs for x in h["writers"] + h["readers"]}
    return {
        "fanIn": top(fan_in),
        "fanOut": top(fan_out),
        "transformations": summed("transformations"),
        "functions": summed("functions"),
        "code": dict(code),
        "programTypes": dict(sorted(types.items(), key=lambda kv: -kv[1])),
        "schemas": [
            {"name": k, "count": v}
            for k, v in sorted(schemas.items(), key=lambda kv: -kv[1])[:15]
        ],
        "processSize": {
            "min": sizes[0] if sizes else 0,
            "median": sizes[len(sizes) // 2] if sizes else 0,
            "max": sizes[-1] if sizes else 0,
        },
        "crossProcessLinks": len(pedges),
        "selfContainedProcesses": sum(
            1 for p in processes if p["objects"] and p["name"] not in hub_procs
        ),
    }


def scc(nodes: list[str], succ: dict[str, set]) -> dict[str, int]:
    """Tarjan, iterative: node -> component id. Processes in a cycle migrate together."""
    index, low, comp, stack, on = {}, {}, {}, [], set()
    counter, cid = 0, 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        work = [(root, iter(sorted(succ.get(root, ()))))]
        while work:
            v, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(succ.get(nxt, ())))))
                elif nxt in on:
                    low[v] = min(low[v], index[nxt])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp[w] = cid
                    if w == v:
                        break
                cid += 1
    return comp


def run_analyzer(
    src: Path, platform: str, out: Path, extension: str | None = None
) -> Path:
    from databricks.labs.bladespector.analyzer import Analyzer

    out.mkdir(parents=True, exist_ok=True)
    xlsx = out / "analyzer.xlsx"
    report = xlsx.with_suffix(".json")
    if extension:
        return _run_with_extension(Analyzer, src, platform, xlsx, report, extension)
    try:
        Analyzer.analyze(src, xlsx, platform, json_result=report)
    except RuntimeError as e:
        # bladespector rejects schema-invalid JSON after writing it; fix_rel() repairs known shapes
        if not report.exists():
            raise
        print(
            f"warning: analyzer JSON failed schema check ({e.__cause__}); using it anyway",
            file=sys.stderr,
        )
    return report


def _run_with_extension(Analyzer, src, platform, xlsx, report, extension) -> Path:
    """The analyzer wrapper (0.3.x) cannot pass the binary's -E (file extension) option, which
    some sources need (for example DataStage .dsx). Run the bundled binary with it directly."""
    import os
    import subprocess

    from databricks.labs.bladespector import analyzer as bb

    tech = bb._PLATFORM_TO_SOURCE_TECHNOLOGY.get(platform)
    if not tech:
        sys.exit(f"--platform: unsupported '{platform}'")
    ext = extension.lstrip(".")
    if not re.fullmatch(r"[A-Za-z0-9]{1,10}", ext):
        sys.exit("--extension: letters and digits only, for example dsx")
    args = [str(Analyzer()._binary), "-d", str(src), "-r", str(xlsx), "-t", tech]
    args += ["-E", ext, "-j", str(report)]
    rc = subprocess.run(
        args, env={**os.environ, "UTF8_NOT_SUPPORTED": "1"}, check=False
    ).returncode
    if rc or not report.exists():
        sys.exit(f"Lakebridge Analyzer failed (exit {rc}) for {platform} with -E {ext}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("reports", nargs="*", type=Path, help="analyzer JSON files")
    ap.add_argument(
        "--run", type=Path, metavar="SRC_DIR", help="run the analyzer on SRC_DIR first"
    )
    ap.add_argument(
        "--platform",
        help="analyzer platform for --run, e.g. 'Oracle', 'Informatica - PC'",
    )
    ap.add_argument(
        "--extension",
        help="source file extension for --run when the Lakebridge Analyzer needs one, e.g. dsx",
    )
    ap.add_argument("-o", "--out", type=Path, default=Path("lineage"))
    ap.add_argument("--format", default="json,csv,mermaid,html")
    ap.add_argument(
        "--focus", help="keep only upstream + downstream of this table or job"
    )
    ap.add_argument(
        "--open", action="store_true", help="open lineage.html in the browser when done"
    )
    nm = ap.add_argument_group("Lineage accuracy (optional)")
    nm.add_argument(
        "--search-path",
        help="comma-separated schemas used to qualify unqualified table names, e.g. dbo,dw",
    )
    nm.add_argument(
        "--collapse-instances",
        action="store_true",
        help="fold ETL instance names (SQ_X, LKP_X, X_1) into table X",
    )
    nm.add_argument(
        "--columns",
        action="store_true",
        help="column-level lineage from embedded ETL SQL (needs sqlglot)",
    )
    nm.add_argument(
        "--compare",
        type=Path,
        metavar="OLD_LINEAGE_JSON",
        help="show changes since a previous lineage.json",
    )
    nm.add_argument(
        "--profiler",
        type=Path,
        metavar="EXTRACT_DB",
        help="read table volumes from a Lakebridge Profiler DuckDB extract",
    )
    ai = ap.add_argument_group("AI-assisted impact analysis (optional)")
    ai.add_argument(
        "--serve",
        action="store_true",
        help="serve the viewer on 127.0.0.1 with AI impact analysis",
    )
    ai.add_argument("--profile", help="Databricks CLI profile for --serve")
    ai.add_argument(
        "--endpoint",
        help="chat serving endpoint (for example behind Unity AI Gateway) for --serve",
    )
    ai.add_argument(
        "--port", type=int, default=8765, help="local port for --serve (default 8765)"
    )
    uc = ap.add_argument_group("Unity Catalog")
    uc.add_argument(
        "--uc-catalog", default="", help="target catalog for suggested UC names"
    )
    uc.add_argument(
        "--uc-pattern",
        default="{catalog}.{schema}.{table}",
        help="suggested target name; fields {catalog} {layer} {schema} {table}",
    )
    uc.add_argument(
        "--volumes",
        type=Path,
        help="CSV with table,rows,bytes to size processes",
    )
    uc.add_argument(
        "--source-system",
        help="UC system_type for external lineage (default from --platform, else OTHER)",
    )
    uc.add_argument(
        "--uc-prefix",
        default="legacy",
        help="name prefix for UC external metadata objects",
    )
    uc.add_argument(
        "--uc-push",
        metavar="PROFILE",
        help="create the external lineage in this workspace profile",
    )
    uc.add_argument(
        "--uc-link",
        action="store_true",
        help="with --uc-push: link legacy tables to their suggested UC tables that exist",
    )
    uc.add_argument(
        "--uc-remove",
        metavar="PROFILE",
        help="delete the external lineage named <uc-prefix>__* in this workspace",
    )
    uc.add_argument(
        "--uc-export",
        metavar="CATALOG.SCHEMA",
        help="export lineage and insights to Delta tables (needs --profile, --warehouse)",
    )
    uc.add_argument("--warehouse", help="SQL warehouse id for --uc-export")
    uc.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt for --uc-push, --uc-remove, --uc-export",
    )
    a = ap.parse_args(argv)

    reports = list(a.reports)
    if a.run:
        if not a.platform:
            ap.error("--run needs --platform")
        reports.append(run_analyzer(a.run, a.platform, a.out, a.extension))
    if a.uc_remove:
        from . import uc as sts_lb_uc

        sts_lb_uc.remove(a.uc_remove, a.uc_prefix, a.yes)
        if not reports:
            return
    if not reports:
        ap.error("give analyzer JSON files or --run")

    lin = Lineage()
    for r in reports:
        lin.add_report(json.loads(r.read_text(encoding="utf-8")))
    from . import normalize

    merged = {}
    if a.search_path:
        paths = [x.strip() for x in a.search_path.split(",") if x.strip()]
        merged["searchPath"] = normalize.merge(
            lin, normalize.search_path_aliases(lin, paths)
        )
    if a.collapse_instances:
        merged["instances"] = normalize.merge(lin, normalize.instance_aliases(lin))
    if a.focus:
        lin = lin.focus(a.focus)
    from . import uc as sts_lb_uc

    formats = {f.strip() for f in a.format.split(",")}
    volumes = sts_lb_uc.load_volumes(a.volumes) if a.volumes else None
    if a.profiler:
        from .profiler import load_profiler

        found, used = load_profiler(a.profiler)
        print(f"profiler: {len(found)} table volumes from {used}")
        volumes = {**found, **(volumes or {})}
    col_edges, col_stats = [], None
    if a.columns:
        from .columns import column_edges

        col_edges, col_stats = column_edges(lin.statements)

    def post(d: dict) -> dict:
        d = sts_lb_uc.enrich(d, a.uc_catalog, a.uc_pattern, volumes)
        if n := d["insights"]["trust"]["ucTargetCollisions"]:
            print(
                f"warning: {n} suggested UC targets are shared by several legacy tables; "
                "see uc_mapping.csv (shared_with) or change --uc-pattern",
                file=sys.stderr,
            )
        if a.columns:
            d["columns"] = col_edges
            d["insights"]["trust"]["columnStatements"] = col_stats["parsed"]
            d["insights"]["trust"]["columnStatementsSkipped"] = col_stats["skipped"]
        for k, v in merged.items():
            d["insights"]["trust"][f"merged_{k}"] = v
        if a.compare:
            from .diff import compare

            d["diff"] = compare(a.compare, d)
        return d

    lin.post = post
    d = lin.write(a.out, formats)
    if "csv" in formats:
        sts_lb_uc.write_mapping(d, a.out)
    p = sts_lb_uc.payload(
        d, sts_lb_uc.system_type_for(a.platform, a.source_system), a.uc_prefix
    )
    sts_lb_uc.write_payload(p, a.out)
    if volumes:
        v = d["insights"]["summary"]["volumes"]
        print(f"volumes: matched {v['matched']} of {v['provided']} rows in {a.volumes}")
    if a.uc_push:
        sts_lb_uc.push(p, a.uc_push, a.yes, link=a.uc_link, prefix=a.uc_prefix)
    if a.uc_export:
        if not (a.profile and a.warehouse):
            ap.error("--uc-export needs --profile and --warehouse")
        from .export import export

        export(d, a.uc_export, a.profile, a.warehouse, a.yes)
    print(
        f"{len(lin.nodes)} nodes, {len(lin.edges)} edges, {len(lin.programs)} programs -> {a.out}"
    )
    html = a.out / "lineage.html"
    if a.serve:
        if not (a.profile and a.endpoint):
            ap.error("--serve needs --profile and --endpoint")
        if not html.exists():
            ap.error("--serve needs the html format")
        from . import ai as sts_lb_ai

        sts_lb_ai.serve(html, d, a.profile, a.endpoint, a.port)
        return
    if a.open and html.exists():
        import webbrowser

        webbrowser.open(html.resolve().as_uri())


if __name__ == "__main__":
    main()
