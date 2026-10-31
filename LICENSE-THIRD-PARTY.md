# Third-Party Software Notices and Licenses

The original source code in this repository is licensed under the Databricks
License — see [LICENSE.md](./LICENSE.md).

The projects in this repository build on third-party open-source software. That
software is **not** covered by the Databricks License; each component remains the
property of its respective authors and is distributed under its own license,
acknowledged below. Where a project bundles or references additional dependencies,
its own `requirements.txt` / `pyproject.toml` (or equivalent manifest) is the
authoritative, version-pinned list.

This file is organized by project. Add a new section when a project introduces
third-party dependencies.

---

## workspace-setup/terraform-checker

Direct runtime dependencies (declared in
[`requirements.txt`](./workspace-setup/terraform-checker/requirements.txt) and
[`pyproject.toml`](./workspace-setup/terraform-checker/pyproject.toml)):

| Dependency | Purpose | License |
|------------|---------|---------|
| [boto3](https://github.com/boto/boto3) | AWS SDK for Python | Apache-2.0 |
| [azure-identity](https://github.com/Azure/azure-sdk-for-python) | Azure authentication | MIT |
| [azure-mgmt-resource](https://github.com/Azure/azure-sdk-for-python) | Azure Resource Management SDK | MIT |
| [azure-mgmt-network](https://github.com/Azure/azure-sdk-for-python) | Azure Network Management SDK | MIT |
| [azure-mgmt-storage](https://github.com/Azure/azure-sdk-for-python) | Azure Storage Management SDK | MIT |
| [azure-mgmt-keyvault](https://github.com/Azure/azure-sdk-for-python) | Azure Key Vault Management SDK | MIT |
| [azure-mgmt-authorization](https://github.com/Azure/azure-sdk-for-python) | Azure Authorization (RBAC) SDK | MIT |
| [azure-mgmt-privatedns](https://github.com/Azure/azure-sdk-for-python) | Azure Private DNS Management SDK | MIT |
| [azure-mgmt-compute](https://github.com/Azure/azure-sdk-for-python) | Azure Compute Management SDK | MIT |
| [google-cloud-storage](https://github.com/googleapis/python-storage) | GCP Cloud Storage client | Apache-2.0 |
| [google-cloud-compute](https://github.com/googleapis/google-cloud-python) | GCP Compute Engine client | Apache-2.0 |
| [google-cloud-resource-manager](https://github.com/googleapis/google-cloud-python) | GCP Resource Manager client | Apache-2.0 |
| [google-cloud-kms](https://github.com/googleapis/google-cloud-python) | GCP Cloud KMS client | Apache-2.0 |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | Google API client library | Apache-2.0 |
| [Click](https://github.com/pallets/click) | Command-line interface framework | BSD-3-Clause |
| [Rich](https://github.com/Textualize/rich) | Rich terminal rendering | MIT |
| [PyYAML](https://github.com/yaml/pyyaml) | YAML parser (permission-set config) | MIT |

Development-only dependencies (not shipped at runtime): `pytest`, `pytest-cov`,
`pytest-mock` (MIT); `mypy` (MIT); `ruff` (MIT); `black` (MIT); `pre-commit` (MIT);
`types-PyYAML` (Apache-2.0).

Each dependency may in turn pull in its own transitive dependencies; those are
governed by their respective licenses as resolved at install time.

### License texts

- **Apache License 2.0** — https://www.apache.org/licenses/LICENSE-2.0
- **MIT License** — https://opensource.org/license/mit
- **BSD 3-Clause License** — https://opensource.org/license/bsd-3-clause

---

## aibi-migration/aibi-migration-map

Direct runtime dependencies (declared in
[`requirements.txt`](./aibi-migration/aibi-migration-map/requirements.txt)):

| Dependency | Purpose | License |
|------------|---------|---------|
| [PyYAML](https://github.com/yaml/pyyaml) | Read/write the `mapping.yaml` migration model | MIT |

Parsing otherwise uses only the Python standard library (`zipfile`, `xml.etree`,
`csv`, `json`) — no other third-party dependencies.

### License texts

- **MIT License** — https://opensource.org/license/mit

---

## genie/genie-agent-scanner

Direct runtime dependencies (declared in
[`scripts/requirements.txt`](./genie/genie-agent-scanner/scripts/requirements.txt)):

| Dependency | Purpose | License |
|------------|---------|---------|
| [databricks-sdk](https://github.com/databricks/databricks-sdk-py) | Genie Spaces REST access + Unity Catalog metadata (imported lazily; needed only for live `--space-id` scans and `--apply`) | Apache-2.0 |

The deterministic scorer and fully offline scans
(`--serialized-space-file`) use only the Python standard library — no
third-party runtime dependency at all.

Development-only dependencies (not shipped in the installed skill): `pytest`,
`ruff` (MIT).

Each dependency may in turn pull in its own transitive dependencies; those are
governed by their respective licenses as resolved at install time.

### License texts

- **Apache License 2.0** — https://www.apache.org/licenses/LICENSE-2.0
- **MIT License** — https://opensource.org/license/mit

---

## dw-migration/source-extracts/snowflake

Direct runtime dependencies (declared in
[`requirements.txt`](./dw-migration/source-extracts/snowflake/requirements.txt)):

| Dependency | Purpose | License |
|------------|---------|---------|
| [snowflake-connector-python](https://github.com/snowflakedb/snowflake-connector-python) | Connect to Snowflake and run `SHOW` / `GET_DDL` | Apache-2.0 |

The connector may pull in its own transitive dependencies; those are governed by their respective licenses as resolved at install time.

### License texts

- **Apache License 2.0** — https://www.apache.org/licenses/LICENSE-2.0

---

## unified-governance/unity-gateway-migration-toolkit

Python runtime dependencies (declared in
[`app/requirements.txt`](./unified-governance/unity-gateway-migration-toolkit/app/requirements.txt); the job notebooks install
`databricks-sdk` themselves):

| Dependency | Purpose | License |
|------------|---------|---------|
| [Databricks SDK for Python](https://github.com/databricks/databricks-sdk-py) | Databricks REST APIs | Apache-2.0 |
| [FastAPI](https://github.com/fastapi/fastapi) | App backend | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI server for the app | BSD-3-Clause |
| [Requests](https://github.com/psf/requests) | HTTP client for the command-line scripts | Apache-2.0 |

Frontend dependencies (declared in
[`app/frontend/package.json`](./unified-governance/unity-gateway-migration-toolkit/app/frontend/package.json); the built
bundle in `app/frontend/static` includes React):

| Dependency | Purpose | License |
|------------|---------|---------|
| [React](https://github.com/facebook/react) and React DOM | UI library | MIT |
| [Vite](https://github.com/vitejs/vite) and @vitejs/plugin-react | Build tool (development only) | MIT |
| [TypeScript](https://github.com/microsoft/TypeScript) | Type checking (development only) | Apache-2.0 |

