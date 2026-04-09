# Databricks Pulumi Deployment Examples

## Overview

This directory contains practical, ready-to-deploy Pulumi configurations for Databricks, curated by the **Databricks Shared Technical Services Team** based on real customer-facing experiences.

These scenarios follow the same philosophy as the [Terraform examples](../terraform-examples/README.md): **self-contained, immediately deployable**, and ideal for customers deploying Databricks with Pulumi for the first time.

## Project Support

Please note that this project is provided for your exploration only and is not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS, and we do not make any guarantees. Please do not submit a support ticket relating to any issues arising from the use of this project.

## Repository Structure

```
pulumi-examples/
├── azure/           # Azure deployment scenarios
```

## Available Scenarios

### Azure

| Scenario | Description |
|----------|-------------|
| [azure-hybrid](./azure/azure-hybrid/) | Deploy a Databricks workspace with Hybrid compute mode (serverless + classic) and No Public IP using Pulumi and Python. |

## Getting Started

1. **Choose your cloud provider**: Navigate to the `azure/` directory
2. **Select a scenario**: Browse the available scenarios
3. **Follow the README**: Each scenario contains its own `README.md` with prerequisites, deployment steps, and clean-up instructions

## Scenario Naming Convention

Scenario folders follow the same pattern as Terraform examples:

```
{cloud}-{compute-or-network-type}
```

**Examples:**
- `azure-hybrid` — Azure workspace with Hybrid compute mode
- `azure-vnet-injection` — Azure workspace with custom VNet

## Prerequisites

- [Pulumi CLI](https://www.pulumi.com/docs/get-started/install/) installed
- Cloud provider CLI configured with appropriate credentials
- Python 3.7+ for Python-based scenarios
- Required permissions to create resources in your cloud account

## License

See the [LICENSE.md](../../LICENSE.md) file in the root of this repository.
