# Databricks Pulumi Deployment Examples

## What is Pulumi?

[Pulumi](https://www.pulumi.com/) is an infrastructure-as-code tool that lets you define and deploy cloud resources using familiar programming languages like Python, TypeScript, and Go — instead of writing HCL or YAML. If you've used Terraform before, Pulumi does the same thing but you write real code.

## What's in here?

Ready-to-deploy Pulumi projects that create Databricks workspaces. Each folder is self-contained — pick a scenario, follow its README, and deploy.

### Azure

| Scenario | Description |
|----------|-------------|
| [azure-hybrid](./azure/azure-hybrid/) | Databricks workspace with Hybrid compute (serverless + classic) and No Public IP |

## Prerequisites

- [Pulumi CLI](https://www.pulumi.com/docs/get-started/install/) — install instructions for macOS, Linux, and Windows
- Cloud provider CLI for your target cloud (e.g. [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli))
- Python 3.10+

## Project Support

These examples are provided AS-IS for exploration and are not formally supported by Databricks with SLAs. Do not submit support tickets for issues arising from their use.
