# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-06-16

### Added

- **Mode-agnostic checking** — the tool now runs every permission area
  unconditionally and reports a **Deployment Compatibility matrix** (tri-state:
  SUPPORTED / NOT SUPPORTED / NOT VERIFIED) for Standard, PrivateLink, Unity
  Catalog, Full, and Azure VNet Injection — instead of requiring the user to
  pick a mode up front.
- **`--verify-only`** read-only mode (no resource creation) for environments
  where resource creation requires approval.
- **CMK / KMS check** (`check_kms`) — verifies the KMS permissions that are
  always-on in the Databricks SRA.
- **STS regional endpoint check** — flags a blocker if STS is deactivated for
  the workspace region.
- **`--vpc-id`** — scopes BYO-network validation to a specific VPC
  (subnets / AZ / size / egress + NAT for non-PrivateLink deployments).
- **`--sg-id`** — validates an existing security group's rules.
- **`--vnet-id`** (Azure) — validates an existing VNet for VNet injection
  (delegation / NSG / sizing), including cross-subscription targets.
- **`--databricks-account-id`** — validates the cross-account role trust
  content (Databricks signing principal + ExternalId).
- **Interface VPC endpoint probes** (STS, Kinesis) in addition to the S3
  gateway endpoint, matching what the SRA actually creates.
- **`--strict`** — exit non-zero on warnings / NOT-VERIFIED items too, for
  strict CI gating.
- **Customer-friendly Markdown report** (`--format markdown`) with a
  plain-language verdict, remediation, and a collapsible detail section.
- **"NOT VALIDATED" section** — explicitly states what a cloud-credential
  pre-check cannot prove (`databricks_mws_*` registration, policy content).
- **`REVIEW` compatibility state** — the matrix now distinguishes "verified, but
  has an actionable advisory (no blocker)" from "could not confirm" (NOT
  VERIFIED), and the per-mode detail names the ACTUAL area/reason instead of a
  generic catch-all.
- **GCP rewritten** to drive checks from the full SRA permission set
  (`testIamPermissions`, deploy-blocking subsets, API-enablement, impersonation,
  PSC/DNS), replacing the previous best-effort listing heuristics.
- **Object-level Unity Catalog S3 verification** — when IAM simulation is
  unavailable, the reused temporary bucket is exercised with real
  PutObject/GetObject/DeleteObject/ListBucket/GetBucketLocation calls.

### Changed

- **Databricks-managed VPC sunset (AWS, 2025)** — removed
  `--vpc-type` / `VPCType.DATABRICKS_MANAGED`; only customer-managed VPC
  options remain for new deployments.
- Removed the up-front `--mode` flag (superseded by the compatibility matrix).
- Dependencies **pinned with upper bounds** (supply-chain hardening for a
  high-privilege tool) and modern SPDX license metadata.
- Added an explicit `setuptools` packaging block so `pip install .` and the
  `dbx-precheck` console script work on the flat layout.

### Fixed

- **Broken packaged entry point** (`main:cli` → `main:main`).
- **Broken `check_kms`** — previously returned nothing (no results) when IAM
  simulation was available, so a run could pass without ever testing KMS.
- **Fail-open denial handling** — every denial now routes through
  `is_access_denied()` (SCP / explicit-deny / `UnauthorizedOperation` no longer
  misread as benign), replacing raw `"AccessDenied" in str(error)` matching.
- **IAM `SimulatePrincipalPolicy` throttling** — retries with exponential
  backoff instead of smearing a whole batch to an error/warning.
- **Fail-closed cleanup** — every created resource (bucket, role, policy,
  security group; Azure resource group) is registered for teardown at creation,
  so a mid-run exception cannot leak resources; versioned temp-bucket teardown.
- **Azure `--cleanup-orphans`** is no longer a no-op that printed success.
- **Azure SDK compatibility** — recent `azure-mgmt-resource` builds no longer
  ship `SubscriptionClient`; the checker (and the orphan sweep) used to crash on
  import and skip every Azure check. It now degrades gracefully, validating the
  subscription through the resource client when given `--subscription-id`.
- **Lossless JSON report** for CI / audit consumers — progress/status messages
  now go to stderr, so `--json` stdout is pure parseable JSON and the Markdown
  report has no progress lines prepended.

### Testing

- Expanded to **161 unit tests** — added AWS-check, denial-classification,
  Markdown-reporter, CLI-smoke, and GCP-check suites.

## [1.0.0] - 2025-01-05

### Added

- **Core Functionality**
  - AWS permission checking with real resource creation/deletion tests
  - Azure permission checking with temporary Resource Group testing
  - GCP permission checking (read-only mode)
  - Support for multiple deployment modes: standard, privatelink, unity, full

- **Permission Configuration (YAML)**
  - External YAML files for permission definitions (`config/permissions/`)
  - Schema validation for YAML files
  - Easy updates without code changes

- **CLI Features**
  - `--cloud` flag for selecting cloud provider (aws, azure, gcp)
  - `--mode` flag for deployment mode selection
  - `--vpc-type` flag for AWS VPC configuration
  - `--dry-run` to preview what would be tested
  - `--cleanup-orphans` to remove leftover test resources
  - `--output` to save report to file
  - `--json` for machine-readable output (CI/CD)
  - `--log-level` and `--log-file` for debugging

- **Reporting**
  - TXT report with detailed results
  - JSON report for CI/CD integration
  - Suggested IAM policy generation for AWS
  - Clear pass/fail/warning status

- **Documentation**
  - README.md (English)
  - README_PORTUGUESE.md (Portuguese)
  - CONTRIBUTING.md
  - SECURITY.md
  - Inline help with examples

- **Testing**
  - 69 unit tests
  - Schema validation tests
  - Error handling tests
  - Reporter tests

- **Code Quality**
  - Type hints throughout
  - Pre-commit hooks (ruff, black, mypy)
  - GitHub Actions CI pipeline
  - Proper Python packaging (pyproject.toml)

### Security

- No credentials stored in logs or files
- Immediate cleanup of temporary resources
- Unique resource naming with UUID

## [1.1.0] - 2026-01-21

### Added

- **Verify-Only Mode (`--verify-only`)**
  - New CLI flag for read-only permission checks without creating temporary resources
  - Useful for environments where resource creation requires approval
  - Uses IAM policy simulation (AWS) and read-only API calls
  - Falls back to warnings when write permissions cannot be verified

- **AWS Deployment Mode Documentation**
  - Added detailed deployment modes table (standard, privatelink, unity, full)
  - Added VPC types table (databricks, customer, custom)
  - Added Unity Catalog requirements section

- **GCP Deployment Mode Documentation**
  - Added deployment configurations table
  - Added VPC configuration options
  - Added Unity Catalog requirements for GCP
  - Added Private Connectivity requirements

### Changed

- AWS, Azure, and GCP checkers now accept `verify_only` parameter
- CLI help text updated with verify-only mode explanation
- README.md expanded with comprehensive mode documentation for all clouds

## [1.2.0] - 2026-02-23

### Changed

- **Removed `--mode` CLI option** - The checker now runs all permission checks
  automatically and produces a Deployment Compatibility matrix showing which
  deployment types (Standard, PrivateLink, Unity Catalog, Full) are supported
  based on the detected permissions.

- **Removed `--vpc-type` CLI option** - Databricks Managed VPC has been sunset
  for AWS. Only customer-managed VPC options are available for new deployments.
  The checker now always validates against customer-managed VPC requirements.

- **Removed `VPCType.DATABRICKS_MANAGED`** - Removed from enums, permission
  definitions (YAML), and all code paths that handled Databricks-managed VPC
  since this deployment model is no longer available for new setups.

- **Simplified AWSChecker** - No longer requires `deployment_mode` or `vpc_type`
  parameters. Always runs all checks (storage, network, cross-account role,
  PrivateLink, Unity Catalog, quotas) and reports compatibility.

- **Simplified AzureChecker** - No longer requires `deployment_mode` parameter.
  Removed `AzureDeploymentMode` enum. Always runs all checks (resource providers,
  resource group, network, storage ADLS Gen2, Access Connector, Private Link,
  workspace permissions, quotas) unconditionally and reports compatibility.

- **AWS: Temp bucket reused for Unity Catalog** - The temporary S3 bucket created
  during Storage Configuration is now kept alive and reused for Unity Catalog
  object-level tests (PutObject, GetObject, DeleteObject, ListBucket,
  GetBucketLocation) before being deleted. Eliminates "Cannot test without
  target bucket" warnings.

- **New Deployment Compatibility section** - Added to both AWS and Azure TXT and
  JSON reports. Shows at-a-glance which deployment types the user's permissions
  support.

- **Simplified configuration** - Removed `deployment_mode` and `vpc_type` from
  `precheck.yaml` configuration file and `CloudConfig` dataclass.

- **Removed STEP labels** - Category names in Azure no longer use "STEP X:"
  prefixes for cleaner output.

### Removed

- `--mode` / `-m` CLI flag
- `--vpc-type` CLI flag
- `DATABRICKS_MANAGED_VPC_ACTIONS` permission list
- `VPCType.DATABRICKS_MANAGED` enum value
- `AzureDeploymentMode` enum
- `databricks_managed` section from `config/permissions/aws.yaml`
- `get_deployment_mode()` and `get_vpc_type()` helper functions
- `run_full_resource_test()` dead code from Azure checker

## [Unreleased]

### Planned

- GCP real resource testing (parity with AWS/Azure)
- HTML report output
- Databricks workspace API checks
- Terraform state comparison mode
- Docker image distribution

---

## Version Guidelines

- **MAJOR** (1.x.x → 2.x.x): Breaking changes to CLI, config format, or output
- **MINOR** (1.0.x → 1.1.x): New features, new permissions, new checks
- **PATCH** (1.0.0 → 1.0.1): Bug fixes, documentation, minor improvements

