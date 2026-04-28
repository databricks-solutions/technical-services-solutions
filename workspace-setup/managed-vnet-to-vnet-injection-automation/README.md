# Azure Databricks VNet Injection Updater

This project provides PowerShell scripts to automate the process of updating an Azure Databricks workspace to use VNet Injection (or updating its VNet configuration), as described in the [Microsoft documentation](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces).

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

These scripts are ideal for running in the **Azure Cloud Shell** (PowerShell mode).

### Optional: Create a Databricks-ready VNet

`create_databricks_vnet.ps1` is optional. Use it when you do not already have a target VNet prepared for Databricks VNet injection.

The script creates everything needed for the workspace upgrade to complete without the common VNet validation failures:

- A resource group if it does not already exist.
- A VNet in the requested region.
- Public and private subnets.
- NSGs associated to both subnets.
- `Microsoft.Databricks/workspaces` delegation on both subnets.
- An `owner` tag using the Azure CLI user running the script.

If CIDR ranges are not provided, it uses:

- VNet: `10.0.0.0/16`
- Public subnet: `10.0.1.0/24`
- Private subnet: `10.0.2.0/24`

```powershell
./create_databricks_vnet.ps1 `
  -ResourceGroupName "<network-rg-name>" `
  -Location "<azure-region>"
```

After it finishes, the script prints the `VNetId`, public subnet name, and private subnet name to use with the workspace update script.

### Update the Databricks workspace

```powershell
./update_databricks_vnet.ps1 `
  -WorkspaceId "/subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.Databricks/workspaces/<workspace-name>" `
  -VNetId "/subscriptions/<sub-id>/resourceGroups/<rg-name>/providers/Microsoft.Network/virtualNetworks/<vnet-name>" `
  -PublicSubnetName "my-public-subnet" `
  -PrivateSubnetName "my-private-subnet"
```

### Script Features

1. **Validation**: Checks if the provided VNet and Subnets exist.
   - **Subscription Check**: Ensures the VNet is in the same subscription as the Workspace.
   - **Region Check**: Ensures the VNet is in the same region as the Workspace.
   - **Delegation Check**: Ensures subnets are delegated to `Microsoft.Databricks/workspaces`.
   - **NSG Check**: Ensures subnets have a Network Security Group associated (consistent with the NSG + quickstart VNet steps in the documentation).
2. **Subnet selection**: If public or private subnet names are omitted, the script lists the target VNet subnets and prompts you to choose them.
3. **Managed VNet peerings**: If the workspace uses a **managed** VNet (`customVirtualNetworkId` not set on the workspace resource), the script checks VNet peerings on any virtual network in the workspace **managed resource group**. Existing managed VNet peerings must be removed before the migration continues.
4. **Export**: Exports the current ARM template of the specified Databricks Workspace and ignores the known `Microsoft.Databricks/workspaces/privateEndpointConnections` export limitation for managed VNet workspaces.
5. **Modification** (aligned with [Step 3 in Microsoft Learn](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces)):
   - Sets the workspace resource `apiVersion` to **`2026-01-01`**.
   - Removes legacy parameters from `properties.parameters` when present: `vnetAddressPrefix`, `natGatewayName`, `publicIpName`.
   - Sets VNet injection parameters: `customVirtualNetworkId`, `customPublicSubnetName`, `customPrivateSubnetName`.
   - Strips read-only `provisioningState` from the exported resource when present.
   - Fills missing template parameter defaults for workspace name–like parameters when possible.
6. **Deployment**: Redeploys the updated template with incremental mode.

## Notes

- Ensure the new VNet and subnets have the correct delegations (`Microsoft.Databricks/workspaces`) before running `update_databricks_vnet.ps1`, or use the optional VNet creation script to create a compliant network first.
- The script uses the current Azure CLI session. Run `az login` first if running locally.
- Microsoft documents that **Terraform is not supported** for this workspace network update path; this script uses ARM export and `az deployment group create` instead.
