# Budget Policy Drift Tracker

This solution accelerator helps platform teams monitor serverless budget-policy compliance and detect policy drift over time.

It focuses on:

- Tracking whether serverless usage remains aligned with centrally approved policy tags.
- Classifying usage into compliance buckets (`central_approved`, `central_drifted`, `workspace_created`, `default_no_policy`).
- Surfacing drift signals for dashboards and alerting workflows.

## Objective

Enable serverless usage tracking while preserving a consistent tag model for cost allocation across workloads.

Expected outcome:

- Serverless usage can be validated against required policy tags (`division`, `department`, `environment`, `service_name`).
- Non-compliant or unmanaged usage patterns can be detected and escalated quickly.

## Repository Contents

- `Budget Policy Drift Tracker.ipynb`
  - Production-oriented notebook.
  - Uses `system.billing.usage` for usage classification.
  - Expects a live policy registry table in Unity Catalog.

- `Budget Policy Drift Tracker(with Test Data).ipynb`
  - Demo/testing notebook.
  - Creates dummy policy-live and usage tables for validation.
  - Best option to validate logic before pointing to production system tables.

## What This Accelerator Covers

This repository intentionally focuses on **monitoring and drift detection**.

It includes:

1. Policy drift checks between expected policy tags and live policy tags.
2. Audit-log query patterns for policy changes.
3. Usage classification logic for serverless consumption.



## Prerequisites

- Databricks workspace with Unity Catalog enabled.
- Permissions to create/read tables in a target catalog and schema.
- Access to `system.billing.usage` (for production notebook runs).
- Access to `system.access.audit` (optional but recommended for audit-based drift checks).
- Notebook runtime with Python + Spark SQL support.

If you run the API-based policy extraction cells:

- Account-level API access and a service principal with required account permissions.

## Quick Start

1. Import notebook into your Databricks workspace.
2. Set widget values for:
   - `uc_catalog`
   - `uc_schema`
3. Run cells sequentially.
4. Start with the test notebook first:
   - `Budget Policy Drift Tracker(with Test Data).ipynb`
5. After validation, switch to:
   - `Budget Policy Drift Tracker.ipynb`
   - Update table references if needed for your environment.

## Data Objects Created/Used

Typical tables referenced in the workflow:

- `serverless_policies_registry` (expected/approved policy metadata).
- `serverless_policies_registry_live` (live policy snapshot).
- `serverless_policies_registry_live_dummy` (test notebook only).
- `usage_dummy` (test notebook only).
- `system.billing.usage` (production usage source).

## Core Monitoring Logic

### A) Policy Drift

Compares expected policy tags from `serverless_policies_registry` with live values and flags mismatches for:

- `division`
- `department`
- `environment`
- `service_name`

### B) Usage Classification

Classifies usage rows as:

- `central_approved`: policy exists and tags match.
- `central_drifted`: policy exists but tags do not match.
- `workspace_created`: policy ID not found in central registry.
- `default_no_policy`: usage with no policy ID.

This output can be used directly in dashboards/alerts for governance and chargeback visibility.

## Operationalizing

For production adoption:

- Schedule refresh of live policy data (if using live policy extraction).
- Build dashboards on classification aggregates (workspace, policy, tag dimensions).
- Configure alerts for:
  - any `default_no_policy` usage,
  - any `workspace_created` usage,
  - threshold breaches on `central_drifted`.

## Notes

- Replace placeholder credentials and identifiers before running.
- Keep naming conventions for required tags consistent across policy definitions and usage tagging.
- Test with the dummy-data notebook before enabling production monitoring.
