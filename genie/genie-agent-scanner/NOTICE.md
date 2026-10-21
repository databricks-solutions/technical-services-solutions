## Attribution

This project is a **derivative work**. It ports and adapts the deterministic
"IQ Scan" scoring rubric, the maturity-tier mapping, and the Genie Space
Optimizer (GSO) scan-check → lever mapping from the public Databricks
**Genie Workbench** open-source accelerator:

- **databricks-solutions/databricks-genie-workbench**
- https://github.com/databricks-solutions/databricks-genie-workbench

Specifically, portions of the scoring logic under `scripts/genie_space_iq/`
(notably `checks.py`, `scoring.py`, and `levers.py`) are reimplemented from that
repository's `genie-space-optimizer` package —
`packages/genie-space-optimizer/src/genie_space_optimizer/iq_scan/scoring.py`
(`calculate_score`, `get_maturity_label`, `CONFIG_CHECK_COUNT`) and the GSO lever
configuration. Those files have been **rewritten and condensed** for a single
Genie space and are **modified derivative works**, marked as such in their module
headers.

The upstream project is provided under the **Databricks License** (see the
repository-root [`LICENSE.md`](../../LICENSE.md)), and this derivative work is
distributed under the same license.

## Not an official Databricks product

This is an unofficial, community port for use with Databricks Genie. It is **not**
an official Databricks product, feature, certification, or quality guarantee, and
the "IQ score" it produces is a convenience metric, not a Databricks SLA.

## Support

Databricks does not offer official support for Databricks Solutions or its
repositories, and this derivative is likewise **unsupported**. For issues with
this project, open a GitHub issue; the maintainers will look on a best-effort
basis.
