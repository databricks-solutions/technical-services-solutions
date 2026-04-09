import pulumi
import pulumi_azure_native as azure_native

config = pulumi.Config()
location = config.get("location") or "eastus"
resource_group_name = config.get("resourceGroupName") or "rg-databricks"
workspace_name = config.get("workspaceName") or "databricks-workspace"
pricing_tier = config.get("pricingTier") or "premium"  # Options: standard, premium, trial

client_config = azure_native.authorization.get_client_config()

resource_group = azure_native.resources.ResourceGroup(
    "databricks-rg",
    resource_group_name=resource_group_name,
    location=location,
    tags={
        "Environment": "Development",
        "ManagedBy": "Pulumi"
    }
)

managed_resource_group_id = pulumi.Output.concat(
    "/subscriptions/",
    client_config.subscription_id,
    "/resourceGroups/",
    f"databricks-rg-{workspace_name}"
)

# Create Azure Databricks Workspace
databricks_workspace = azure_native.databricks.Workspace(
    "databricks-workspace",
    resource_group_name=resource_group.name,
    workspace_name=workspace_name,
    location=location,
    sku={
        "name": pricing_tier,
    },
    managed_resource_group_id=managed_resource_group_id,
    parameters={
        "enableNoPublicIp": {
            "value": True,
        },
    },
    compute_mode="Hybrid",
    tags={
        "Environment": "Development",
        "ManagedBy": "Pulumi"
    }
)

pulumi.export("resource_group_name", resource_group.name)
pulumi.export("workspace_id", databricks_workspace.id)
pulumi.export("workspace_url", databricks_workspace.workspace_url)
pulumi.export("workspace_name", databricks_workspace.name)
pulumi.export("location", databricks_workspace.location)
