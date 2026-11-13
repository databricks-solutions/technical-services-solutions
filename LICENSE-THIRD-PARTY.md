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

---

## dw-migration/semantics-builder

Direct runtime dependencies (declared in
[`package.json`](./dw-migration/semantics-builder/package.json), versions pinned in
[`pnpm-lock.yaml`](./dw-migration/semantics-builder/pnpm-lock.yaml)):

| Dependency | Purpose | License |
|------------|---------|---------|
| [@databricks/appkit](https://github.com/databricks/appkit) | Databricks Apps server framework (OBO auth, SQL warehouse, Lakebase) | Apache-2.0 |
| [@databricks/appkit-ui](https://github.com/databricks/appkit) | Databricks Apps UI integration | Apache-2.0 |
| [@databricks/design-system](https://github.com/databricks) | Du Bois UI components | ISC |
| [@databricks/sdk-experimental](https://github.com/databricks/databricks-sdk-js) | Databricks REST APIs (Unity Catalog, Genie) | Apache-2.0 |
| [@emotion/react](https://github.com/emotion-js/emotion) | CSS-in-JS used by the design system | MIT |
| [@xyflow/react](https://github.com/xyflow/xyflow) (React Flow, by webkid GmbH) | Interactive lineage canvas: pan, zoom, minimap | MIT |
| [moment](https://github.com/moment/moment) | Dates for the design system | MIT |
| [react](https://github.com/facebook/react), [react-dom](https://github.com/facebook/react) | UI rendering | MIT |
| [react-router](https://github.com/remix-run/react-router) | Client routes | MIT |
| [read-excel-file](https://gitlab.com/catamphetamine/read-excel-file) | Read dictionary uploads (.xlsx) | MIT |
| [write-excel-file](https://gitlab.com/catamphetamine/write-excel-file) | Write the dictionary template (.xlsx) | MIT |
| [yaml](https://github.com/eemeli/yaml) | Parse and render metric view YAML | ISC |
| [zod](https://github.com/colinhacks/zod) | Validate request bodies and model output | MIT |

React Flow is Copyright (c) 2019-2025 webkid GmbH, used under the MIT License. Its own
runtime dependencies (`@xyflow/system`, `classcat`, `zustand`) are MIT.

Development-only dependencies (not shipped at runtime) include TypeScript, Vite, Vitest,
ESLint, Prettier and Playwright (Apache-2.0 or MIT); see `devDependencies` in `package.json`.

Each dependency may in turn pull in its own transitive dependencies; those are
governed by their respective licenses as resolved at install time.

### License texts

- **Apache License 2.0** — https://www.apache.org/licenses/LICENSE-2.0
- **MIT License** — https://opensource.org/license/mit
- **ISC License** — https://opensource.org/license/isc-license-txt
