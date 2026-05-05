# Lakebridge utilities

Scripts and config samples to help you move **SSIS**, **IBM DataStage**, **Informatica**, and **T-SQL / SQL Server** workloads to Databricks using [Lakebridge](https://databrickslabs.github.io/lakebridge) (BladeBridge plus Switch).

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) must be installed (`databricks labs install lakebridge`), with the Databricks CLI configured for your workspace. For Python, Java, networking, and profile setup, follow the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). You do **not** need to run `databricks labs lakebridge install-transpile` yourself first: each pipeline script installs or refreshes the **BladeBridge** and **Switch** transpilers when you confirm the first-run prompts (or pass the skip flags on later runs once tools are already installed).

These scripts are example automation for efficient Lakebridge usage and are intended as reference. Do not run them in production without custom tuning for your environment.

**Switch prompts:** Each runnable pipeline includes default `*.yml` prompt files for the LLM pass. Treat them as templates and **tune them for your workload** (legacy patterns, naming, and quality bars vary by source and team).
---


## Contents

| Folder | What it is for |
| --- | --- |
| [bladebridge-overrides](./bladebridge-overrides/) | Ready-made **BladeBridge override JSON** samples (by source: SSIS, Informatica, DataStage). Use them to adjust how legacy components map to PySpark or job structure, then point your pipeline at a copy you edited. Not a runnable pipeline by itself. |
| [ssis-to-databricks-pipelines](./ssis-to-databricks-pipelines/) | **SQL Server Integration Services** (`.dtsx` or projects): BladeBridge turns packages into PySpark; Switch improves or reshapes them. Typical end states are **Lakeflow** pipeline code in Databricks or, in an alternate path, **Spark SQL** files orchestrated with a SQL Warehouse job. |
| [tsql-to-databricks-pipeline](./tsql-to-databricks-pipeline/) | **T-SQL** (`.sql` files such as procedures and functions): BladeBridge and Switch convert them for Databricks. You can target **Lakeflow**-style SQL pipelines or **warehouse SQL** jobs, depending on the options described in that folder’s README. |
| [informatica-to-databricks-jobs-pipeline](./informatica-to-databricks-jobs-pipeline/) | **Informatica PowerCenter** exports: BladeBridge and Switch produce **notebooks** and **Databricks job** definitions (including supplemental Python where needed). Optional table mapping helps align names with **Unity Catalog**. |
| [datastage-to-databricks-jobs-pipeline](./datastage-to-databricks-jobs-pipeline/) | **IBM DataStage** XML exports: same two-step transpile, plus helpers that clean up **job JSON**, optional **Unity Catalog** name mapping, and pre-Switch notebook fixes. Delivers notebooks and **Databricks jobs** you can run and refine. |

Each folder’s **README** is the full runbook (`run.sh`, prompts, overrides, and what you may customize).

Several runnable pipelines also ship **`run.txt`**: the same script as `run.sh`, saved with a `.txt` extension so you can obtain it when downloads block `.sh` files. After you copy it to a machine where you run Lakebridge, rename it to `run.sh`, make it executable (`chmod +x run.sh`), and run as usual—or invoke it as `bash run.txt` without renaming.





