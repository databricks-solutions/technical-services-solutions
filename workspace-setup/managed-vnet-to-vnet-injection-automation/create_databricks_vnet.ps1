<#
.SYNOPSIS
    Creates an Azure VNet prepared for Azure Databricks VNet injection.

.DESCRIPTION
    This script creates a resource group if needed, then creates a VNet with public and private subnets.
    Both subnets are associated with Network Security Groups and delegated to Microsoft.Databricks/workspaces.
    Created resources are tagged with owner=<current Azure CLI user>.

    If CIDR values are not supplied, these defaults are used:
      VNet:           10.0.0.0/16
      Public subnet:  10.0.1.0/24
      Private subnet: 10.0.2.0/24

.EXAMPLE
    ./create_databricks_vnet.ps1 -ResourceGroupName "rg-databricks-network" -Location "eastus"

.EXAMPLE
    ./create_databricks_vnet.ps1 -ResourceGroupName "rg-databricks-network" -Location "eastus" -VNetName "adb-vnet" -VNetCidr "10.20.0.0/16" -PublicSubnetCidr "10.20.1.0/24" -PrivateSubnetCidr "10.20.2.0/24"
#>

param(
    [Parameter(Mandatory = $false, HelpMessage = "Resource group where the VNet will be created")]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $false, HelpMessage = "Azure region for the resource group and VNet")]
    [Alias("Region")]
    [string]$Location,

    [Parameter(Mandatory = $false, HelpMessage = "Name of the VNet to create")]
    [string]$VNetName,

    [Parameter(Mandatory = $false, HelpMessage = "Address space for the VNet")]
    [string]$VNetCidr,

    [Parameter(Mandatory = $false, HelpMessage = "Name of the public subnet")]
    [string]$PublicSubnetName,

    [Parameter(Mandatory = $false, HelpMessage = "Address range for the public subnet")]
    [string]$PublicSubnetCidr,

    [Parameter(Mandatory = $false, HelpMessage = "Name of the private subnet")]
    [string]$PrivateSubnetName,

    [Parameter(Mandatory = $false, HelpMessage = "Address range for the private subnet")]
    [string]$PrivateSubnetCidr
)

$ErrorActionPreference = "Stop"

$DefaultVNetName = "databricks-vnet"
$DefaultPublicSubnetName = "public-subnet"
$DefaultPrivateSubnetName = "private-subnet"
$DefaultVNetCidr = "10.0.0.0/16"
$DefaultPublicSubnetCidr = "10.0.1.0/24"
$DefaultPrivateSubnetCidr = "10.0.2.0/24"

function Read-RequiredValue {
    param(
        [string]$Prompt,
        [string]$CurrentValue
    )

    if (-not [string]::IsNullOrWhiteSpace($CurrentValue)) {
        return $CurrentValue
    }

    do {
        $value = Read-Host $Prompt
        if ([string]::IsNullOrWhiteSpace($value)) {
            Write-Warning "A value is required."
        }
    } while ([string]::IsNullOrWhiteSpace($value))

    return $value
}

function Read-ValueWithDefault {
    param(
        [string]$Prompt,
        [string]$CurrentValue,
        [string]$DefaultValue
    )

    if (-not [string]::IsNullOrWhiteSpace($CurrentValue)) {
        return $CurrentValue
    }

    $value = Read-Host "$Prompt [$DefaultValue]"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $DefaultValue
    }

    return $value
}

function Assert-LastCommandSucceeded {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        Write-Error $Message
        exit 1
    }
}

function Test-AzCliResourceExists {
    param([scriptblock]$Command)

    & $Command *> $null
    return ($LASTEXITCODE -eq 0)
}

function Set-OwnerTag {
    param(
        [string]$ResourceId,
        [string]$Owner
    )

    az tag update --resource-id $ResourceId --operation Merge --tags owner=$Owner --output none
    Assert-LastCommandSucceeded "Failed to set owner tag on '$ResourceId'."
}

if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI ('az') is not installed or not in the path."
    exit 1
}

$account = az account show --output json | ConvertFrom-Json
Assert-LastCommandSucceeded "Azure CLI is not logged in. Run 'az login' before using this script."

$OwnerTagValue = $account.user.name
if ([string]::IsNullOrWhiteSpace($OwnerTagValue)) {
    $OwnerTagValue = $account.name
}

if ([string]::IsNullOrWhiteSpace($OwnerTagValue)) {
    Write-Error "Unable to determine the current Azure CLI user for the owner tag."
    exit 1
}

$ResourceGroupName = Read-RequiredValue -Prompt "Resource group name" -CurrentValue $ResourceGroupName
$Location = Read-RequiredValue -Prompt "Azure region, for example eastus" -CurrentValue $Location
$VNetName = Read-ValueWithDefault -Prompt "VNet name" -CurrentValue $VNetName -DefaultValue $DefaultVNetName
$VNetCidr = Read-ValueWithDefault -Prompt "VNet CIDR" -CurrentValue $VNetCidr -DefaultValue $DefaultVNetCidr
$PublicSubnetName = Read-ValueWithDefault -Prompt "Public subnet name" -CurrentValue $PublicSubnetName -DefaultValue $DefaultPublicSubnetName
$PublicSubnetCidr = Read-ValueWithDefault -Prompt "Public subnet CIDR" -CurrentValue $PublicSubnetCidr -DefaultValue $DefaultPublicSubnetCidr
$PrivateSubnetName = Read-ValueWithDefault -Prompt "Private subnet name" -CurrentValue $PrivateSubnetName -DefaultValue $DefaultPrivateSubnetName
$PrivateSubnetCidr = Read-ValueWithDefault -Prompt "Private subnet CIDR" -CurrentValue $PrivateSubnetCidr -DefaultValue $DefaultPrivateSubnetCidr

if ($PublicSubnetName -eq $PrivateSubnetName) {
    Write-Error "PublicSubnetName and PrivateSubnetName must be different."
    exit 1
}

if ($PublicSubnetCidr -eq $PrivateSubnetCidr) {
    Write-Error "PublicSubnetCidr and PrivateSubnetCidr must be different."
    exit 1
}

$PublicNsgName = "$VNetName-public-nsg"
$PrivateNsgName = "$VNetName-private-nsg"

Write-Host "Checking resource group..." -ForegroundColor Cyan
$rgExists = az group exists --name $ResourceGroupName --output tsv
Assert-LastCommandSucceeded "Failed to check whether resource group '$ResourceGroupName' exists."

if ($rgExists -ne "true") {
    Write-Host "Creating resource group '$ResourceGroupName' in '$Location'..." -ForegroundColor Cyan
    az group create --name $ResourceGroupName --location $Location --tags owner=$OwnerTagValue --output none
    Assert-LastCommandSucceeded "Failed to create resource group '$ResourceGroupName'."
} else {
    Write-Host "Resource group '$ResourceGroupName' already exists." -ForegroundColor DarkGray
    $resourceGroup = az group show --name $ResourceGroupName --output json | ConvertFrom-Json
    Assert-LastCommandSucceeded "Failed to read resource group '$ResourceGroupName'."
    Set-OwnerTag -ResourceId $resourceGroup.id -Owner $OwnerTagValue
}

if (Test-AzCliResourceExists { az network vnet show --resource-group $ResourceGroupName --name $VNetName --output none }) {
    Write-Error "VNet '$VNetName' already exists in resource group '$ResourceGroupName'. Choose a different VNetName or delete the existing VNet."
    exit 1
}

Write-Host "Creating NSGs..." -ForegroundColor Cyan
if (-not (Test-AzCliResourceExists { az network nsg show --resource-group $ResourceGroupName --name $PublicNsgName --output none })) {
    az network nsg create --resource-group $ResourceGroupName --name $PublicNsgName --location $Location --tags owner=$OwnerTagValue --output none
    Assert-LastCommandSucceeded "Failed to create NSG '$PublicNsgName'."
} else {
    $publicNsg = az network nsg show --resource-group $ResourceGroupName --name $PublicNsgName --output json | ConvertFrom-Json
    Assert-LastCommandSucceeded "Failed to read NSG '$PublicNsgName'."
    Set-OwnerTag -ResourceId $publicNsg.id -Owner $OwnerTagValue
}

if (-not (Test-AzCliResourceExists { az network nsg show --resource-group $ResourceGroupName --name $PrivateNsgName --output none })) {
    az network nsg create --resource-group $ResourceGroupName --name $PrivateNsgName --location $Location --tags owner=$OwnerTagValue --output none
    Assert-LastCommandSucceeded "Failed to create NSG '$PrivateNsgName'."
} else {
    $privateNsg = az network nsg show --resource-group $ResourceGroupName --name $PrivateNsgName --output json | ConvertFrom-Json
    Assert-LastCommandSucceeded "Failed to read NSG '$PrivateNsgName'."
    Set-OwnerTag -ResourceId $privateNsg.id -Owner $OwnerTagValue
}

Write-Host "Creating VNet '$VNetName' with public subnet '$PublicSubnetName'..." -ForegroundColor Cyan
az network vnet create `
    --resource-group $ResourceGroupName `
    --name $VNetName `
    --location $Location `
    --address-prefixes $VNetCidr `
    --subnet-name $PublicSubnetName `
    --subnet-prefixes $PublicSubnetCidr `
    --network-security-group $PublicNsgName `
    --tags owner=$OwnerTagValue `
    --output none
Assert-LastCommandSucceeded "Failed to create VNet '$VNetName'."

Write-Host "Delegating public subnet to Microsoft.Databricks/workspaces..." -ForegroundColor Cyan
az network vnet subnet update `
    --resource-group $ResourceGroupName `
    --vnet-name $VNetName `
    --name $PublicSubnetName `
    --delegations Microsoft.Databricks/workspaces `
    --output none
Assert-LastCommandSucceeded "Failed to delegate public subnet '$PublicSubnetName'."

Write-Host "Creating private subnet '$PrivateSubnetName'..." -ForegroundColor Cyan
az network vnet subnet create `
    --resource-group $ResourceGroupName `
    --vnet-name $VNetName `
    --name $PrivateSubnetName `
    --address-prefixes $PrivateSubnetCidr `
    --network-security-group $PrivateNsgName `
    --delegations Microsoft.Databricks/workspaces `
    --output none
Assert-LastCommandSucceeded "Failed to create private subnet '$PrivateSubnetName'."

$vnet = az network vnet show --resource-group $ResourceGroupName --name $VNetName --output json | ConvertFrom-Json
Assert-LastCommandSucceeded "Failed to read VNet '$VNetName' after creation."

Write-Host ""
Write-Host "Databricks-ready VNet created successfully." -ForegroundColor Green
Write-Host "VNet ID: $($vnet.id)"
Write-Host "Public subnet: $PublicSubnetName ($PublicSubnetCidr)"
Write-Host "Private subnet: $PrivateSubnetName ($PrivateSubnetCidr)"
Write-Host ""
Write-Host "Use this with update_databricks_vnet.ps1:" -ForegroundColor Cyan
Write-Host "./update_databricks_vnet.ps1 -WorkspaceId `"<workspace-resource-id>`" -VNetId `"$($vnet.id)`" -PublicSubnetName `"$PublicSubnetName`" -PrivateSubnetName `"$PrivateSubnetName`""
