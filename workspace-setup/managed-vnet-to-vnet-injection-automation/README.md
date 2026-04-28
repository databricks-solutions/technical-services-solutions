# Azure Databricks VNet Injection Updater

This project provides a PowerShell script to automate the process of updating an Azure Databricks workspace to use VNet Injection (or updating its VNet configuration), as described in the [Microsoft documentation](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces).

## Prerequisites

- **Azure CLI (`az`)**: Installed and logged in.
- **PowerShell**: Required to run the script (available in Azure Cloud Shell).
- **Before you begin** (per [Microsoft Learn](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces)): confirm the workspace is **not** configured with Azure Load Balancer (otherwise contact your account team); **terminate all running clusters and jobs** to avoid disruption during the update.
- **Virtual Network (VNet) Configuration**:
  - Must be in the **same region** as the Databricks Workspace.
  - **Subnets**: Requires two subnets (public and private).
  - **Delegation**: Each subnet must be delegated to `Microsoft.Databricks/workspaces`.
  - **Network Security Group (NSG)**: Each subnet must have an NSG associated (typically an empty one).
  - **Outbound Connectivity**: If using No Public IP (NPIP) / Secure Cluster Connectivity, an explicit outbound method (NAT Gateway, Firewall, or Load Balancer) must be configured on the subnets.

## Usage

This script is ideal for running in the **Azure Cloud Shell** (PowerShell mode).

```powershell
./update_databricks_vnet.ps1 `
  -WorkspaceId "/subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.Databricks/workspaces/<workspace-name>" `
  -VNetId "/subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.Network/virtualNetworks/<vnet-name>" `
  -PublicSubnetName "my-public-subnet" `
  -PrivateSubnetName "my-private-subnet"
```

### Script Features

1. **Validation**: Checks if the provided VNet and Subnets exist.
   - **Region Check**: Ensures the VNet is in the same region as the Workspace.
   - **Delegation Check**: Ensures subnets are delegated to `Microsoft.Databricks/workspaces`.
   - **NSG Check**: Ensures subnets have a Network Security Group associated (consistent with the NSG + quickstart VNet steps in the documentation).
2. **Managed VNet peerings**: If the workspace uses a **managed** VNet (`customVirtualNetworkId` not set on the workspace resource), the script lists VNet peerings on any virtual network in the workspace **managed resource group** and warns that they do not move to your new VNet (you must recreate peerings—or Private Link—on the target VNet after migration, similar to the documentation’s note for back-end Private Link).
3. **Export**: Exports the current ARM template of the specified Databricks Workspace.
4. **Modification** (aligned with [Step 3 in Microsoft Learn](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces)):
   - Sets the workspace resource `apiVersion` to **`2026-01-01`**.
   - Removes legacy parameters from `properties.parameters` when present: `vnetAddressPrefix`, `natGatewayName`, `publicIpName`.
   - Sets VNet injection parameters: `customVirtualNetworkId`, `customPublicSubnetName`, `customPrivateSubnetName`.
   - Strips read-only `provisioningState` from the exported resource when present.
   - Fills missing template parameter defaults for workspace name–like parameters when possible.
5. **Deployment**: Redeploys the updated template with incremental mode.

## Notes

- Ensure the new VNet and subnets have the correct delegations (`Microsoft.Databricks/workspaces`) before running this script.
- The script uses the current Azure CLI session. Run `az login` first if running locally.
- Microsoft documents that **Terraform is not supported** for this workspace network update path; this script uses ARM export and `az deployment group create` instead.
