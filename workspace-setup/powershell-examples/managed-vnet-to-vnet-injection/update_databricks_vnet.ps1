<#
.SYNOPSIS
    Updates an Azure Databricks workspace to use VNet Injection (or updates its VNet config) using Azure CLI and PowerShell.
    Can be run from Azure Cloud Shell (PowerShell).

.DESCRIPTION
    This script exports the current ARM template of a Databricks workspace, modifies it to include VNet injection parameters,
    removes legacy parameters, and redeploys it. Aligns with Microsoft Learn:
    https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces

    Before running: terminate all clusters and jobs; confirm the workspace is not on Azure Load Balancer (see documentation).

.EXAMPLE
    ./update_databricks_vnet.ps1 -WorkspaceId "/subscriptions/.../workspaces/my-ws" -VNetId "/subscriptions/.../virtualNetworks/my-vnet" -PublicSubnetName "pub-subnet" -PrivateSubnetName "priv-subnet"

    If PublicSubnetName and/or PrivateSubnetName are omitted, the script lists the target VNet subnets and prompts for the missing values.
#>

param(
    [Parameter(Mandatory = $true, HelpMessage = "Resource ID of the Databricks Workspace")]
    [string]$WorkspaceId,

    [Parameter(Mandatory = $true, HelpMessage = "Resource ID of the target Virtual Network")]
    [string]$VNetId,

    [Parameter(Mandatory = $false, HelpMessage = "Name of the Public Subnet")]
    [string]$PublicSubnetName,

    [Parameter(Mandatory = $false, HelpMessage = "Name of the Private Subnet")]
    [string]$PrivateSubnetName
)

$ErrorActionPreference = "Stop"

Write-Warning @"
Pre-flight (per Microsoft documentation): terminate all running clusters and jobs in the workspace; restart after the update completes.
If the workspace uses Azure Load Balancer, contact your account team before migrating.
"@

# Check for Azure CLI
if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI ('az') is not installed or not in the path."
    exit 1
}

function Get-ResourceIdSubscriptionId {
    param([string]$ResourceId)

    if ($ResourceId -match "^/?subscriptions/(?<subId>[^/]+)/") {
        return $Matches['subId']
    }

    return $null
}

Write-Host "Parsing Workspace ID..." -ForegroundColor Cyan
# Regex to extract components from Resource ID
if ($WorkspaceId -match "^/?subscriptions/(?<subId>[^/]+)/resourceGroups/(?<rgName>[^/]+)/.+/workspaces/(?<wsName>[^/]+)$") {
    $SubscriptionId = $Matches['subId']
    $ResourceGroup = $Matches['rgName']
    $WorkspaceName = $Matches['wsName']
} else {
    Write-Error "Invalid Workspace ID format."
    exit 1
}

Write-Host "Subscription: $SubscriptionId"
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Workspace: $WorkspaceName"

# Set Subscription
Write-Host "Setting active subscription..." -ForegroundColor Cyan
az account set --subscription $SubscriptionId

# Get Workspace Location for validation
Write-Host "Getting Workspace details..." -ForegroundColor Cyan
$wsDetails = az resource show --ids $WorkspaceId --output json | ConvertFrom-Json
$wsLocation = $wsDetails.location

function Test-WorkspaceUsesManagedVNet {
    param([object]$WorkspaceResource)
    $params = $WorkspaceResource.properties.parameters
    if ($null -eq $params) { return $true }
    $cvnProp = $params.PSObject.Properties['customVirtualNetworkId']
    if ($null -eq $cvnProp) { return $true }
    $valObj = $cvnProp.Value
    if ($null -eq $valObj) { return $true }
    $val = $valObj.value
    return [string]::IsNullOrWhiteSpace([string]$val)
}

function Get-ManagedResourceGroupVnetPeerings {
    param(
        [string]$ManagedResourceGroupId,
        [string]$SubscriptionId
    )
    $result = [System.Collections.Generic.List[object]]::new()
    if ([string]::IsNullOrWhiteSpace($ManagedResourceGroupId)) { return $result }
    if ($ManagedResourceGroupId -notmatch '/resourceGroups/([^/]+)$') { return $result }
    $managedRg = $Matches[1]

    $vnetJson = az network vnet list -g $managedRg --subscription $SubscriptionId -o json 2>$null
    if ([string]::IsNullOrWhiteSpace($vnetJson)) { return $result }
    $vnets = $vnetJson | ConvertFrom-Json
    foreach ($v in @($vnets)) {
        $peerJson = az network vnet peering list -g $managedRg --vnet-name $v.name --subscription $SubscriptionId -o json 2>$null
        if ([string]::IsNullOrWhiteSpace($peerJson)) { continue }
        $peers = $peerJson | ConvertFrom-Json
        foreach ($p in @($peers)) {
            $remoteId = $null
            if ($p.remoteVirtualNetwork -and $p.remoteVirtualNetwork.id) {
                $remoteId = $p.remoteVirtualNetwork.id
            } elseif ($p.properties -and $p.properties.remoteVirtualNetwork -and $p.properties.remoteVirtualNetwork.id) {
                $remoteId = $p.properties.remoteVirtualNetwork.id
            }
            $result.Add([PSCustomObject]@{
                VNetName               = $v.name
                PeeringName            = $p.name
                RemoteVirtualNetworkId = $remoteId
            })
        }
    }
    return $result
}

Write-Host "Checking managed VNet / VNet peerings..." -ForegroundColor Cyan
if (Test-WorkspaceUsesManagedVNet -WorkspaceResource $wsDetails) {
    $mrgid = $wsDetails.properties.managedResourceGroupId
    $peerings = Get-ManagedResourceGroupVnetPeerings -ManagedResourceGroupId $mrgid -SubscriptionId $SubscriptionId
    if ($peerings.Count -gt 0) {
        Write-Warning @"
Found $($peerings.Count) VNet peering connection(s) on the workspace managed resource group VNet(s). Remove these managed VNet connections before migrating the workspace to VNet injection, then recreate the required connectivity on the target VNet after migration. See: https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/update-workspaces
"@
        $peerings | Format-Table -AutoSize | Out-String | Write-Host
        Write-Error "Managed VNet peering connections must be removed before this migration can continue."
        exit 1
    } else {
        Write-Host "No VNet peerings found on VNet(s) in the managed resource group (or no VNet listed there)." -ForegroundColor DarkGray
    }
} else {
    Write-Host "Workspace already has customVirtualNetworkId set (VNet-injected). Skipping managed-VNet peering scan; if you are moving to another VNet, review peerings on your current VNet." -ForegroundColor DarkGray
}

# Validate VNet existence and Region
Write-Host "Validating VNet existence and configuration..." -ForegroundColor Cyan
$vnetValid = $false
while (-not $vnetValid) {
    $vnetSubscriptionId = Get-ResourceIdSubscriptionId -ResourceId $VNetId
    if ([string]::IsNullOrWhiteSpace($vnetSubscriptionId)) {
        Write-Warning "VNet ID '$VNetId' is not a valid Azure resource ID."
        $VNetId = Read-Host "Please re-enter the valid VNet Resource ID"
        continue
    }

    if ($vnetSubscriptionId -ne $SubscriptionId) {
        Write-Warning "VNet subscription '$vnetSubscriptionId' does not match Workspace subscription '$SubscriptionId'."
        $VNetId = Read-Host "Please re-enter a VNet Resource ID from the Workspace subscription"
        continue
    }

    $vnetInfo = az network vnet show --ids $VNetId --output json 2>$null | ConvertFrom-Json
    if (-not $vnetInfo) {
        Write-Warning "VNet with ID '$VNetId' not found."
        $VNetId = Read-Host "Please re-enter the valid VNet Resource ID"
        continue
    }
    
    # Check Region
    if ($vnetInfo.location -ne $wsLocation) {
        Write-Error "VNet region ($($vnetInfo.location)) does not match Workspace region ($wsLocation). VNet injection requires them to be in the same region."
        exit 1
    }

    $vnetValid = $true
}

# Extract VNet name and Resource Group for subnet validation
if ($VNetId -match "^/?subscriptions/[^/]+/resourceGroups/(?<rg>[^/]+)/.+/virtualNetworks/(?<name>[^/]+)$") {
    $VNetRG = $Matches['rg']
    $VNetName = $Matches['name']
} else {
    Write-Error "Invalid VNet ID format."
    exit 1
}

# Helper function to prompt for a subnet when a subnet name was omitted
function Select-SubnetName {
    param (
        [object[]]$Subnets,
        [string]$Role,
        [string]$ExcludedSubnetName
    )

    if (-not $Subnets -or $Subnets.Count -eq 0) {
        Write-Error "No subnets found in the selected VNet."
        exit 1
    }

    Write-Host ""
    Write-Host "Available subnets for $Role subnet selection:" -ForegroundColor Cyan
    for ($i = 0; $i -lt $Subnets.Count; $i++) {
        $subnet = $Subnets[$i]
        $delegations = @($subnet.delegations) | ForEach-Object {
            if ($_.serviceName) { $_.serviceName }
            elseif ($_.properties -and $_.properties.serviceName) { $_.properties.serviceName }
        }
        $delegationText = if ($delegations -and $delegations.Count -gt 0) { $delegations -join ", " } else { "None" }
        $nsgText = if ($subnet.networkSecurityGroup -and $subnet.networkSecurityGroup.id) { "Yes" } else { "No" }
        Write-Host ("[{0}] {1} | Prefix: {2} | Databricks delegation/other: {3} | NSG: {4}" -f ($i + 1), $subnet.name, $subnet.addressPrefix, $delegationText, $nsgText)
    }

    while ($true) {
        $selection = Read-Host "Enter the number or name for the $Role subnet"
        if ([string]::IsNullOrWhiteSpace($selection)) {
            Write-Warning "A subnet selection is required."
            continue
        }

        $selectedName = $null
        $selectionNumber = 0
        if ([int]::TryParse($selection, [ref]$selectionNumber)) {
            if ($selectionNumber -ge 1 -and $selectionNumber -le $Subnets.Count) {
                $selectedName = $Subnets[$selectionNumber - 1].name
            }
        } else {
            $match = @($Subnets | Where-Object { $_.name -eq $selection })
            if ($match.Count -eq 1) {
                $selectedName = $match[0].name
            }
        }

        if ([string]::IsNullOrWhiteSpace($selectedName)) {
            Write-Warning "Invalid subnet selection '$selection'."
            continue
        }

        if (-not [string]::IsNullOrWhiteSpace($ExcludedSubnetName) -and $selectedName -eq $ExcludedSubnetName) {
            Write-Warning "The $Role subnet cannot be the same as '$ExcludedSubnetName'. Choose a different subnet."
            continue
        }

        return $selectedName
    }
}

# Helper function for subnet validation
function Validate-Subnet {
    param (
        [string]$SubnetName,
        [string]$VNetRG,
        [string]$VNetName,
        [string]$Role
    )
    
    $subnetInfo = az network vnet subnet show --resource-group $VNetRG --vnet-name $VNetName --name $SubnetName --output json 2>$null | ConvertFrom-Json
    
    if (-not $subnetInfo) {
        Write-Warning "$Role Subnet '$SubnetName' not found in VNet '$VNetName'."
        return $null
    }

    # Check Delegation
    $hasDelegation = $false
    
    # Ensure delegations is treated as an array even if single object
    $delegations = @($subnetInfo.delegations)
    
    if ($delegations -and $delegations.Count -gt 0) {
        foreach ($del in $delegations) {
            # Try various property paths to find serviceName
            $serviceName = $null
            
            if ($del.properties -and $del.properties.serviceName) {
                $serviceName = $del.properties.serviceName
            } elseif ($del.serviceName) {
                $serviceName = $del.serviceName
            } elseif ($del.PSObject.Properties['properties'] -and $del.PSObject.Properties['properties'].Value.serviceName) {
                $serviceName = $del.PSObject.Properties['properties'].Value.serviceName
            }
            
            if ($serviceName -eq "Microsoft.Databricks/workspaces") {
                $hasDelegation = $true
                break
            }
        }
    }

    if (-not $hasDelegation) {
        $found = if ($subnetInfo.delegations) { 
             $subnetInfo.delegations | ForEach-Object { 
                if ($_.properties.serviceName) { $_.properties.serviceName } 
                elseif ($_.PSObject.Properties['properties'].Value.serviceName) { $_.PSObject.Properties['properties'].Value.serviceName }
             }
        } else { "None" }
        Write-Error "Subnet '$SubnetName' is missing the required delegation to 'Microsoft.Databricks/workspaces'. Found: $($found -join ', ')"
        exit 1
    }

    # Check NSG Association
    if (-not $subnetInfo.networkSecurityGroup.id) {
        Write-Error "Subnet '$SubnetName' does not have a Network Security Group (NSG) associated. A security group is required."
        exit 1
    }

    return $subnetInfo
}

Write-Host "Loading target VNet subnets..." -ForegroundColor Cyan
$subnetsJson = az network vnet subnet list --resource-group $VNetRG --vnet-name $VNetName --output json
$subnets = @($subnetsJson | ConvertFrom-Json)

if ([string]::IsNullOrWhiteSpace($PublicSubnetName)) {
    $PublicSubnetName = Select-SubnetName -Subnets $subnets -Role "Public" -ExcludedSubnetName $PrivateSubnetName
}

if ([string]::IsNullOrWhiteSpace($PrivateSubnetName)) {
    $PrivateSubnetName = Select-SubnetName -Subnets $subnets -Role "Private" -ExcludedSubnetName $PublicSubnetName
}

if ($PublicSubnetName -eq $PrivateSubnetName) {
    Write-Error "PublicSubnetName and PrivateSubnetName must be different subnets."
    exit 1
}

# Validate Public Subnet
Write-Host "Validating Public Subnet..." -ForegroundColor Cyan
while (-not (Validate-Subnet -SubnetName $PublicSubnetName -VNetRG $VNetRG -VNetName $VNetName -Role "Public")) {
    $PublicSubnetName = Read-Host "Please re-enter the valid Public Subnet Name"
    if ($PublicSubnetName -eq $PrivateSubnetName) {
        Write-Error "PublicSubnetName and PrivateSubnetName must be different subnets."
        exit 1
    }
}

# Validate Private Subnet
Write-Host "Validating Private Subnet..." -ForegroundColor Cyan
while (-not (Validate-Subnet -SubnetName $PrivateSubnetName -VNetRG $VNetRG -VNetName $VNetName -Role "Private")) {
    $PrivateSubnetName = Read-Host "Please re-enter the valid Private Subnet Name"
    if ($PublicSubnetName -eq $PrivateSubnetName) {
        Write-Error "PublicSubnetName and PrivateSubnetName must be different subnets."
        exit 1
    }
}

# Export Template
Write-Host "Exporting current ARM template..." -ForegroundColor Cyan
$TemplateFile = "exported_template.json"
$ModifiedFile = "modified_template.json"
$ExportErrorFile = "export_errors.txt"

if (Test-Path $ExportErrorFile) {
    Remove-Item -Path $ExportErrorFile -Force
}

az group export --resource-group $ResourceGroup --resource-ids $WorkspaceId --output json 1> $TemplateFile 2> $ExportErrorFile
$exportExitCode = $LASTEXITCODE

$exportErrors = ""
if (Test-Path $ExportErrorFile) {
    $exportErrors = Get-Content -Path $ExportErrorFile -Raw
}

$privateEndpointExportWarning = "Could not get resources of the type 'Microsoft.Databricks/workspaces/privateEndpointConnections'"
$nonIgnoredExportErrors = @()
if (-not [string]::IsNullOrWhiteSpace($exportErrors)) {
    $nonIgnoredExportErrors = @($exportErrors -split "`r?`n" | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and
        $_ -notmatch [regex]::Escape($privateEndpointExportWarning) -and
        $_ -notmatch "Resources of this type will not be exported"
    })
}
$hasPrivateEndpointExportWarning = (-not [string]::IsNullOrWhiteSpace($exportErrors)) -and ($exportErrors -match [regex]::Escape($privateEndpointExportWarning))

if ($exportExitCode -ne 0 -and $nonIgnoredExportErrors.Count -gt 0) {
    Write-Error "Failed to export template. Azure CLI error: $exportErrors"
    exit 1
}

if ($hasPrivateEndpointExportWarning) {
    Write-Host "Ignoring Azure export warning for Databricks privateEndpointConnections; those child resources are not needed for this migration." -ForegroundColor DarkGray
}

if (Test-Path $ExportErrorFile) {
    Remove-Item -Path $ExportErrorFile -Force
}

if (-not (Test-Path $TemplateFile) -or (Get-Item $TemplateFile).Length -eq 0) {
    Write-Error "Failed to export template."
    exit 1
}

# Modify JSON using PowerShell
Write-Host "Modifying template for VNet injection..." -ForegroundColor Cyan

try {
    $json = Get-Content -Path $TemplateFile -Raw | ConvertFrom-Json

    # Locate the Databricks workspace resource
    $resources = $json.resources
    $json.resources = @($resources | Where-Object { $_.type -ne "Microsoft.Databricks/workspaces/privateEndpointConnections" })
    $resources = $json.resources
    $found = $false

    foreach ($res in $resources) {
        if ($res.type -eq "Microsoft.Databricks/workspaces") {
            $found = $true
            
            # API version required for this migration path (Microsoft Learn: Update workspace network configuration)
            $res.apiVersion = "2026-01-01"

            # Remove legacy parameters from properties.parameters if they exist (per Microsoft documentation)
            $legacyProps = @("vnetAddressPrefix", "natGatewayName", "publicIpName")
            if ($res.properties.parameters) {
                foreach ($prop in $legacyProps) {
                    if ($res.properties.parameters.PSObject.Properties.Match($prop)) {
                        $res.properties.parameters.PSObject.Properties.Remove($prop)
                    }
                }
            }

            # Remove read-only provisioningState
            if ($res.properties.PSObject.Properties.Match("provisioningState")) {
                $res.properties.PSObject.Properties.Remove("provisioningState")
            }

            # Ensure parameters object exists
            if (-not $res.properties.parameters) {
                $res.properties | Add-Member -MemberType NoteProperty -Name "parameters" -Value ([PSCustomObject]@{})
            }

            # Add/Update VNet Injection parameters
            # Note: We use Add-Member -Force to overwrite if exists or just standard assignment
            # Using a helper object to construct the parameter structure expected by ARM: { "value": "..." }
            
            $res.properties.parameters | Add-Member -MemberType NoteProperty -Name "customVirtualNetworkId" -Value ([PSCustomObject]@{ value = $VNetId }) -Force
            $res.properties.parameters | Add-Member -MemberType NoteProperty -Name "customPublicSubnetName" -Value ([PSCustomObject]@{ value = $PublicSubnetName }) -Force
            $res.properties.parameters | Add-Member -MemberType NoteProperty -Name "customPrivateSubnetName" -Value ([PSCustomObject]@{ value = $PrivateSubnetName }) -Force
        }
    }

    if (-not $found) {
        Write-Error "Could not find Microsoft.Databricks/workspaces resource in the exported template."
        exit 1
    }

    # Save modified JSON
    $json | ConvertTo-Json -Depth 100 | Set-Content -Path $ModifiedFile
}
catch {
    Write-Error "Error processing JSON: $_"
    exit 1
}

# Parameters Handling
# When exporting, some parameters might be parameterized in the ARM template but not have default values in the 'parameters' section.
# We need to ensure we pass the workspace name if it was parameterized.

$deploymentParams = @()
if ($json.parameters -and $json.parameters.PSObject.Properties.Match("workspaceName")) {
   # Check if it lacks a default value
   if (-not $json.parameters.workspaceName.defaultValue) {
       $deploymentParams += "--parameters workspaceName=$WorkspaceName"
   }
}
# Also check for any other parameters that look like the workspace name parameter that the user mentioned
# The export command often auto-generates parameter names like "workspaces_name_name"

# To be safe, we can try to detect parameters that don't have default values and see if we can fill them, 
# but for now, let's just use the --parameters argument if we detect the standard pattern or pass the template as-is 
# and let the user interact if needed. But since this is a script, we should try to automate.

# BETTER APPROACH:
# We will inspect the 'parameters' section of the exported JSON.
# Any parameter that does NOT have a 'defaultValue' needs to be supplied.
# We know 'workspaceName' is likely one of them.

$paramsToPass = @{}

if ($json.parameters) {
    foreach ($paramName in $json.parameters.PSObject.Properties.Name) {
        $paramObj = $json.parameters.$paramName
        if (-not $paramObj.defaultValue) {
            # Try to guess the value based on name
            if ($paramName -like "*workspace*" -or $paramName -like "*name*") {
                $paramsToPass[$paramName] = $WorkspaceName
            }
        }
    }
}

$paramArgs = @()
foreach ($key in $paramsToPass.Keys) {
    $paramArgs += "--parameters"
    $paramArgs += "$key=$($paramsToPass[$key])"
}

# Deploy
Write-Host "Deploying updated template..." -ForegroundColor Cyan
az deployment group create `
    --resource-group $ResourceGroup `
    --name "vnet-update-deployment-$(Get-Date -Format 'yyyyMMddHHmm')" `
    --template-file $ModifiedFile `
    --mode Incremental `
    @paramArgs

Write-Host "Deployment initiated successfully." -ForegroundColor Green

