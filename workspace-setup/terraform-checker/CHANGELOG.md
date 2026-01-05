# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

