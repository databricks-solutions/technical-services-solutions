"""Compare two scans: what was added, removed, or rewired since a previous lineage.json."""

import json
from pathlib import Path


def compare(old_path: Path, new: dict) -> dict:
    old = json.loads(Path(old_path).read_text(encoding="utf-8"))
    on, nn = {n["id"]: n for n in old["nodes"]}, {n["id"]: n for n in new["nodes"]}
    ekey = lambda e: f"{e['from']}|{e['to']}|{e['kind']}"
    oe, ne = {ekey(e): e for e in old["edges"]}, {ekey(e): e for e in new["edges"]}
    op = {p["name"] for p in old["insights"]["processes"]}
    np_ = {p["name"] for p in new["insights"]["processes"]}
    moved = [
        {"id": i, "from": on[i].get("process"), "to": nn[i].get("process")}
        for i in sorted(set(on) & set(nn))
        if on[i].get("process") != nn[i].get("process")
    ]
    return {
        "previous": Path(
            old_path
        ).name,  # file name only; no local paths in shared output
        "addedObjects": sorted(set(nn) - set(on)),
        "removedObjects": [
            {"id": i, "name": on[i]["name"], "kind": on[i]["kind"]}
            for i in sorted(set(on) - set(nn))
        ],
        "addedEdges": [
            {"from": ne[k]["from"], "to": ne[k]["to"], "kind": ne[k]["kind"]}
            for k in sorted(set(ne) - set(oe))
        ],
        "removedEdges": [
            {"from": oe[k]["from"], "to": oe[k]["to"], "kind": oe[k]["kind"]}
            for k in sorted(set(oe) - set(ne))
        ],
        "addedProcesses": sorted(np_ - op),
        "removedProcesses": sorted(op - np_),
        "movedObjects": moved,
    }
