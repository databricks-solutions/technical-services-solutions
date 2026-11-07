"""Migration slices: one CSV per top-level process with every table it touches, how it uses it,
whether the table is a shared contract with other processes, and its suggested UC target.
slices/index.csv lists the processes with their dependencies."""

import hashlib
import re
from pathlib import Path

HEADER = [
    "table",
    "access",
    "role",
    "shared",
    "shared_with",
    "suggested_target",
    "layer",
    "rows",
    "bytes",
    "programs",
    "tags",
]


def file_name(process: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", process).strip("._")[:80] or "process"
    name = (
        base
        if base.lower() not in used
        else f"{base}_{hashlib.sha1(process.encode()).hexdigest()[:6]}"
    )
    used.add(name.lower())
    return f"{name}.csv"


def slice_rows(d: dict) -> dict[str, list[list]]:
    """Process name -> rows (in HEADER order)."""
    nodes = {n["id"]: n for n in d["nodes"]}
    progs = {p["name"]: p for p in d["programs"]}
    hubs = {h["id"]: h for h in d["insights"]["hubs"]}
    out = {}
    for proc in d["insights"]["processes"]:
        use: dict[str, dict] = {}
        for prog in proc["programs"]:
            p = progs.get(prog) or {}
            for side in ("reads", "writes"):
                for t in p.get(side, []):
                    if t in nodes and nodes[t]["kind"] == "table":
                        u = use.setdefault(
                            t, {"reads": False, "writes": False, "programs": set()}
                        )
                        u[side] = True
                        u["programs"].add(prog)
        rows = []
        for t, u in sorted(use.items(), key=lambda x: nodes[x[0]]["name"].lower()):
            n, h = nodes[t], hubs.get(t)
            uc, vol = n.get("uc") or {}, n.get("volume") or {}
            others = (
                sorted((set(h["writers"]) | set(h["readers"])) - {proc["name"]})
                if h
                else []
            )
            rows.append(
                [
                    n["name"],
                    "reads and writes"
                    if u["reads"] and u["writes"]
                    else "writes"
                    if u["writes"]
                    else "reads",
                    n.get("role", ""),
                    "yes" if h else "no",
                    "|".join(others),
                    uc.get("target", ""),
                    uc.get("layer", ""),
                    vol.get("rows", ""),
                    vol.get("bytes", ""),
                    "|".join(sorted(u["programs"])),
                    "|".join(
                        sorted(
                            x
                            for x in n.get("tags", [])
                            if x in ("temp", "cte", "maybe-cte", "merged")
                        )
                    ),
                ]
            )
        out[proc["name"]] = rows
    return out


def write_slices(d: dict, out: Path) -> Path:
    from .core import safe_writer

    folder = out / "slices"
    folder.mkdir(parents=True, exist_ok=True)
    rows = slice_rows(d)
    used: set[str] = set()
    procs = {p["name"]: p for p in d["insights"]["processes"]}
    with open(folder / "index.csv", "w", newline="", encoding="utf-8") as idx:
        iw = safe_writer(idx)
        iw.writerow(
            [
                "process",
                "file",
                "technology",
                "programs",
                "tables",
                "shared_tables",
                "depends_on",
                "feeds",
                "in_cycle",
                "max_complexity",
            ]
        )
        for name, r in rows.items():
            f = file_name(name, used)
            with open(folder / f, "w", newline="", encoding="utf-8") as fh:
                w = safe_writer(fh)
                w.writerow(HEADER)
                for row in r:
                    w.writerow(row)
            p = procs[name]
            iw.writerow(
                [
                    name,
                    f,
                    "|".join(p["tech"]),
                    len(p["programs"]),
                    len(r),
                    sum(1 for x in r if x[3] == "yes"),
                    "|".join(p["upstream"]),
                    "|".join(p["downstream"]),
                    "yes" if p["cycle"] is not None else "no",
                    p["maxComplexity"],
                ]
            )
    return folder
