# Databricks Terraform Deployment Examples

## Overview

This repository contains practical, ready-to-deploy Terraform configurations for Databricks, curated by the **Databricks Shared Technical Services Team** based on real customer-facing experiences.

Unlike highly modularized Terraform examples, these scenarios are designed to be **self-contained and immediately deployable**, making them ideal for customers who are deploying Databricks with Terraform for the first time.

## Philosophy

Our approach prioritizes **practicality over abstraction**:

- **Scenario-based**: Each deployment represents a complete, real-world use case
- **Minimal modularization**: Code is intentionally kept in a single place to make it easier to understand and customize
- **Production-ready**: Configurations reflect best practices learned from actual customer deployments
- **Quick start**: You should be able to choose a scenario and deploy it with minimal modifications

## Repository Structure

```
terraform-examples/
├── aws/           # AWS deployment scenarios
├── azure/         # Azure deployment scenarios
└── gcp/           # GCP deployment scenarios
```

Each cloud provider directory contains multiple deployment scenarios. Browse the folders to find the scenario that best matches your requirements.

## Getting Started

1. **Choose your cloud provider**: Navigate to the `aws/`, `azure/`, or `gcp/` directory
2. **Select a scenario**: Browse the available scenarios and select one that matches your deployment requirements
3. **Follow the README**: Each scenario contains its own `README.md` with:
   - Detailed description of what gets deployed
   - Prerequisites and required permissions
   - Step-by-step deployment instructions
   - Configuration variables and customization options
   - Clean-up instructions

## Scenario Naming Convention

Scenario folders follow a clear naming pattern that describes the deployment configuration:

```
{cloud}-{network-type}-{security-features}
```

**Examples:**
- `aws-byovpc-cmk` - AWS deployment with Bring Your Own VPC and Customer-Managed Keys
- `azure-vnet-injection-privatelink` - Azure deployment with VNet injection and Private Link
- `gcp-byovpc-default-encryption` - GCP deployment with custom VPC and default encryption

This naming helps you quickly identify the right scenario for your needs.

## Available Scenarios

### AWS
*Scenarios coming soon*

### Azure
*Scenarios coming soon*

### GCP
*Scenarios coming soon*

## Prerequisites

Before using any scenario, ensure you have:

- Terraform installed (version 1.0 or later recommended)
- Cloud provider CLI configured with appropriate credentials
- Required permissions to create resources in your cloud account
- Databricks account admin access (for account-level resources)

Specific prerequisites for each scenario are documented in their respective READMEs.

## Contributing New Scenarios

When adding a new deployment scenario, please follow these guidelines:

### 1. Directory Structure
Place your scenario in the appropriate cloud provider directory:
```
terraform-examples/{cloud}/scenario-name/
```

### 2. Naming Convention
Use descriptive folder names that clearly indicate the deployment characteristics:
- Start with the cloud provider prefix (`aws-`, `azure-`, `gcp-`)
- Include key networking configuration (e.g., `byovpc`, `vnet-injection`)
- Add security features if applicable (e.g., `cmk`, `privatelink`)

**Good examples:**
- `aws-byovpc-cmk-privatelink`
- `azure-standard-deployment`
- `gcp-shared-vpc-cmek`

**Avoid:**
- Generic names like `scenario1`, `example`
- Overly technical abbreviations without context

### 3. Required Files
Each scenario directory must include:

#### `README.md`
A comprehensive guide containing:
- **Overview**: What this scenario deploys and when to use it
- **Architecture**: Brief description of the resources created
- **Prerequisites**: Required tools, permissions, and pre-existing resources
- **Configuration**: Variables that need to be set
- **Deployment Steps**: Clear, numbered steps to deploy
- **Validation**: How to verify the deployment succeeded
- **Clean-up**: How to destroy resources
- **Troubleshooting**: Common issues and solutions

#### Terraform Files
- `main.tf` - Primary resource definitions
- `variables.tf` - Input variable declarations
- `outputs.tf` - Output values
- `versions.tf` - Terraform and provider version constraints
- `terraform.tfvars.example` - Example variable values (no sensitive data)

### 4. Code Style
- Keep code self-contained in a single directory
- Avoid complex module abstractions
- Include inline comments explaining key decisions
- Use descriptive resource names
- Follow Terraform best practices for the provider

### 5. Documentation Standards
- Write clear, customer-friendly documentation
- Assume the reader is new to Databricks and Terraform
- Include actual command examples
- Document any cloud-specific configurations
- Explain security implications of choices made

## Support and Feedback

These examples are maintained by the Databricks Shared Technical Services Team. If you encounter issues or have suggestions:

1. Check the scenario-specific README for troubleshooting tips
2. Review Databricks documentation for your cloud provider
3. Contact your Databricks representative for assistance

## License

See the [LICENSE.md](../../LICENSE.md) file in the root of this repository.

---

**Note**: These examples are provided as starting points. Always review and customize them according to your organization's security policies, compliance requirements, and operational standards before deploying to production environments.

