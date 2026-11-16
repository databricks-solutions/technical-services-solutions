"""Synthetic Lakebridge Analyzer reports for a larger estate (UI and scale tests, demos).

`python tests/estate.py OUT_DIR [--workflows N] [--scripts N] [--seed S]` writes etl.json (Informatica
style: workflows -> sessions -> mappings, shared dimension tables, one cross-workflow cycle) and
sql.json (scripts with temp tables, chained marts). Names are generic and synthetic.
"""

import argparse
import json
import random
from pathlib import Path

LEVELS = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
DOMAINS = [
    "customer",
    "sales",
    "product",
    "finance",
    "inventory",
    "hr",
    "supplier",
    "marketing",
]


def etl_report(workflows: int, rng: random.Random) -> dict:
    inventory, sub = [], []
    dims = [f"dw.dim_{d}" for d in DOMAINS]
    for w in range(workflows):
        dom = DOMAINS[w % len(DOMAINS)]
        wf = f"wf_{dom}_{w:02d}"
        prev = f"raw.{dom}_{w:02d}"
        for m in range(rng.randint(2, 5)):
            mp, ss = f"m_{dom}_{w:02d}_{m}", f"s_m_{dom}_{w:02d}_{m}"
            out = f"stg.{dom}_{w:02d}_{m}" if m < 2 else f"dw.fact_{dom}_{w:02d}"
            rel = [
                {"action": "source", "object": prev, "count": 1},
                {"action": "target", "object": out, "count": 1},
            ]
            if rng.random() < 0.6:
                rel.append({"action": "lookup", "object": rng.choice(dims), "count": 1})
            if m == 1 and rng.random() < 0.4:
                rel.append({"action": "target", "object": f"dw.dim_{dom}", "count": 1})
            inventory.append(
                {
                    "name": mp,
                    "type": "Mapping",
                    "complexityLevel": rng.choice(LEVELS),
                    "objectRel": rel,
                    "nodes": {
                        "Expression": rng.randint(1, 6),
                        "Lookup": rng.randint(0, 3),
                        "Aggregator": rng.randint(0, 2),
                    },
                    "jobParameters": [{"name": "$$LOAD_DATE"}] * rng.randint(0, 3),
                    "dynamicStatements": [{}] * (1 if rng.random() < 0.15 else 0),
                }
            )
            sub += [
                {
                    "parent": wf,
                    "parentType": "Workflow",
                    "child": ss,
                    "childType": "Session",
                    "count": 1,
                },
                {
                    "parent": ss,
                    "parentType": "Session",
                    "child": mp,
                    "childType": "Mapping",
                    "count": 1,
                },
            ]
            prev = out
    # one cycle: the last workflow's fact feeds the first workflow
    inventory[0]["objectRel"].append({"action": "lookup", "object": prev, "count": 1})
    return {
        "runInfo": {"sourceTechnology": "INFA"},
        "inventory": inventory,
        "subJobInfo": sub,
    }


def sql_report(scripts: int, workflows: int, rng: random.Random) -> dict:
    inventory, lineage = [], {}

    def write(target, file, sources):
        lineage.setdefault(target, {"target": target, "writes": [], "reads": []})[
            "writes"
        ].append({"file": file, "sources": sources})
        for s in sources:
            lineage.setdefault(s, {"target": s, "writes": [], "reads": []})[
                "reads"
            ].append(file)

    for i in range(scripts):
        dom = DOMAINS[i % len(DOMAINS)]
        f = f"sql/{dom}/build_{dom}_mart_{i:02d}.sql"
        facts = [
            f"dw.fact_{DOMAINS[k % len(DOMAINS)]}_{k:02d}"
            for k in rng.sample(range(workflows), k=min(2, workflows))
        ]
        tmp = f"#{dom}_{i:02d}_work"
        write(tmp, f, facts + [f"dw.dim_{dom}"])
        write(f"mart.{dom}_summary_{i:02d}", f, [tmp])
        if i and rng.random() < 0.5:
            write(
                f"mart.{dom}_summary_{i:02d}",
                f,
                [f"mart.{DOMAINS[(i - 1) % len(DOMAINS)]}_summary_{i - 1:02d}"],
            )
        inventory.append(
            {
                "sourceFile": f,
                "name": f,
                "complexityLevel": rng.choice(LEVELS),
                "lineCount": rng.randint(40, 900),
                "statementCount": rng.randint(3, 40),
                "dynamicStatements": [{}] * rng.randint(0, 2),
                "loopsAndCursors": [{}] * rng.randint(0, 2),
            }
        )
    return {
        "runInfo": {"sourceTechnology": "SQL"},
        "inventory": inventory,
        "object_lineage": list(lineage.values()),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("out", type=Path)
    ap.add_argument("--workflows", type=int, default=24)
    ap.add_argument("--scripts", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "etl.json").write_text(json.dumps(etl_report(a.workflows, rng), indent=1))
    (a.out / "sql.json").write_text(
        json.dumps(sql_report(a.scripts, a.workflows, rng), indent=1)
    )


if __name__ == "__main__":
    main()
