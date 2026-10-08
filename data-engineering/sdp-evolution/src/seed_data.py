"""Seed order data into the landing volume for the SDP schema-evolution demo.

Runs as a serverless job task so end users trigger a job, never a notebook.

  --version v1  lands the clean baseline batch (step 1).
  --version v2  lands the drifted batch: rename + type change + new column (step 3).

Schema and volume are created by the Databricks Asset Bundle on deploy.
This job only writes JSON into the existing volume.

Same-directory import of `generate_data` works because Python puts the running
script's own directory on sys.path.
"""

import argparse

from generate_data import v1_records, v2_records, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--volume", default="landing")
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    args = parser.parse_args()

    landing_dir = f"/Volumes/{args.catalog}/{args.schema}/{args.volume}/orders"
    if args.version == "v1":
        records, filename = v1_records(), "orders_v1.json"
    else:
        records, filename = v2_records(), "orders_v2.json"

    path = write_json(records, landing_dir, filename)
    print(f"wrote {len(records)} {args.version} records to {path}")


if __name__ == "__main__":
    main()
