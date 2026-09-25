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
