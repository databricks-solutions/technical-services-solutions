"""Azure checker for Databricks Terraform Pre-Check."""

import uuid
import time
import logging
from enum import Enum
from typing import Optional, List, Dict, Any

from .base import (
    BaseChecker,
    CheckCategory,
    CheckResult,
    CheckStatus,
    CheckReport,
)

# Import permission data from YAML-backed module
from .permissions import get_registry


logger = logging.getLogger(__name__)


# Prefix for temporary test resources
TEST_RESOURCE_PREFIX = "dbxprecheck"


class AzureDeploymentMode(Enum):
    """Azure Databricks deployment modes."""
    STANDARD = "standard"           # Databricks-managed VNet (no custom VNet)
    VNET_INJECTION = "vnet"         # Customer-managed VNet (VNet injection)
    UNITY_CATALOG = "unity"         # With Unity Catalog (needs ADLS Gen2)
    PRIVATELINK = "privatelink"     # With Private Link + SCC + NAT Gateway
    FULL = "full"                   # All features: VNet + Unity + Private Link


class AzureChecker(BaseChecker):
    """
    Checker for Azure resources and permissions for Databricks deployment.
    
    Azure Databricks Deployment Model:
    ==================================
    
    STANDARD (Databricks-managed VNet):
    - Databricks creates everything in a Managed Resource Group
    - You only provide: managed_resource_group_name
    - Databricks creates: VNet, Subnets, NSG, Storage Account (DBFS)
    - YOU NEED: Contributor/Owner role on subscription
    
    VNET_INJECTION (Customer-managed VNet):
    - You create: VNet, 2 subnets (public/private), NSG
    - You delegate subnets to Microsoft.Databricks/workspaces
    - Databricks still creates Storage Account in Managed RG
    - YOU NEED: Network Contributor + Contributor
    
    UNITY_CATALOG:
    - You create: Storage Account (ADLS Gen2) for Unity metastore
    - You create: Container for data
    - You create: Access Connector for Azure Databricks
    - YOU NEED: Storage Account Contributor + Managed Identity Operator
    
    PRIVATELINK (Secure Cluster Connectivity):
    - You create: Private Endpoints (frontend + backend)
    - You create: Private DNS Zones
    - You create: NAT Gateway with Public IP (required for SCC)
    - YOU NEED: Network Contributor + Private DNS Zone Contributor
    """
    
    # Required resource providers for Databricks
    REQUIRED_PROVIDERS = [
        "Microsoft.Databricks",
        "Microsoft.Network",
        "Microsoft.Storage",
        "Microsoft.Compute",
        "Microsoft.KeyVault",
        "Microsoft.ManagedIdentity",
        "Microsoft.Authorization",
    ]
    
    # Additional providers for Private Link
    PRIVATELINK_PROVIDERS = [
        "Microsoft.Network",  # Private Endpoints
    ]
    
    # Private DNS zones for Databricks Private Link
    PRIVATE_DNS_ZONES = [
        "privatelink.azuredatabricks.net",
        "privatelink.blob.core.windows.net",
        "privatelink.dfs.core.windows.net",
    ]
    
    def __init__(
        self, 
        region: str = None, 
        subscription_id: str = None,
        resource_group: str = None,
        tenant_id: str = None,
        client_id: str = None,
        client_secret: str = None,
        deployment_mode: AzureDeploymentMode = AzureDeploymentMode.STANDARD,
    ):
        super().__init__(region)
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.deployment_mode = deployment_mode
        self._credential = None
        self._subscription_info = None
        self._test_id = str(uuid.uuid4())[:8]
        self._cleanup_tasks = []
    
    @property
    def cloud_name(self) -> str:
        return "Azure"
    
    def _get_credential(self):
        """Get Azure credential object."""
        if self._credential is None:
            try:
                from azure.identity import (
                    DefaultAzureCredential,
                    ClientSecretCredential,
                )
                
                if self.tenant_id and self.client_id and self.client_secret:
                    self._credential = ClientSecretCredential(
                        tenant_id=self.tenant_id,
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                    )
                else:
                    self._credential = DefaultAzureCredential()
                    
            except ImportError:
                raise ImportError(
                    "azure-identity is required for Azure checks. "
                    "Install with: pip install azure-identity"
                )
        return self._credential
    
    def _get_subscription_client(self):
        """Get subscription client."""
        from azure.mgmt.resource import SubscriptionClient
        return SubscriptionClient(self._get_credential())
    
    def _get_resource_client(self):
        """Get resource management client."""
        from azure.mgmt.resource import ResourceManagementClient
        return ResourceManagementClient(
            self._get_credential(),
            self.subscription_id
        )
    
    def _get_network_client(self):
        """Get network management client."""
        from azure.mgmt.network import NetworkManagementClient
        return NetworkManagementClient(
            self._get_credential(),
            self.subscription_id
        )
    
    def _get_storage_client(self):
        """Get storage management client."""
        from azure.mgmt.storage import StorageManagementClient
        return StorageManagementClient(
            self._get_credential(),
            self.subscription_id
        )
    
    def _get_authorization_client(self):
        """Get authorization client for RBAC."""
        from azure.mgmt.authorization import AuthorizationManagementClient
        return AuthorizationManagementClient(
            self._get_credential(),
            self.subscription_id
        )
    
    def _cleanup_test_resources(self):
        """Clean up any temporary resources created during testing."""
        for cleanup_func, resource_name in reversed(self._cleanup_tasks):
            try:
                cleanup_func()
            except Exception:
                pass  # Best effort cleanup
        self._cleanup_tasks = []
    
    # =========================================================================
    # REAL RESOURCE TESTING
    # =========================================================================
    
    def _test_resource_group_permissions(self) -> List[CheckResult]:
        """Test Resource Group permissions by creating a real RG."""
        results = []
        resource_client = self._get_resource_client()
        rg_name = f"{TEST_RESOURCE_PREFIX}-rg-{self._test_id}"
        rg_created = False
        
        # Show what we're creating
        results.append(CheckResult(
            name="  📁 Creating test Resource Group",
            status=CheckStatus.OK,
            message=rg_name
        ))
        
        try:
            # Create Resource Group
            resource_client.resource_groups.create_or_update(
                rg_name,
                {"location": self.region or "eastus"}
            )
            rg_created = True
            results.append(CheckResult(
                name="  Microsoft.Resources/resourceGroups/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {rg_name}"
            ))
            
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error or "does not have authorization" in error:
                results.append(CheckResult(
                    name="  Microsoft.Resources/resourceGroups/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:100]}"
                ))
            else:
                results.append(CheckResult(
                    name="  Microsoft.Resources/resourceGroups/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:100]}"
                ))
            return results
        
        if not rg_created:
            return results
        
        # Test read
        try:
            resource_client.resource_groups.get(rg_name)
            results.append(CheckResult(
                name="  Microsoft.Resources/resourceGroups/read",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            results.append(CheckResult(
                name="  Microsoft.Resources/resourceGroups/read",
                status=CheckStatus.NOT_OK,
                message=f"DENIED: {str(e)[:50]}"
            ))
        
        # CLEANUP: Delete the test resource group
        try:
            # Start deletion (async)
            delete_operation = resource_client.resource_groups.begin_delete(rg_name)
            results.append(CheckResult(
                name="  🗑️  Microsoft.Resources/resourceGroups/delete",
                status=CheckStatus.OK,
                message=f"✓ DELETING: {rg_name} (async)"
            ))
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                results.append(CheckResult(
                    name="  🗑️  Microsoft.Resources/resourceGroups/delete",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:50]}"
                ))
            else:
                results.append(CheckResult(
                    name="  🗑️  Microsoft.Resources/resourceGroups/delete",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {rg_name}"
                ))
        
        return results
    
    def _test_network_permissions(self, test_rg: str = None) -> List[CheckResult]:
        """Test VNet/Subnet permissions by creating real resources."""
        results = []
        network_client = self._get_network_client()
        
        # Use existing resource group or create test one
        rg_name = test_rg or self.resource_group
        if not rg_name:
            results.append(CheckResult(
                name="  Network Tests",
                status=CheckStatus.WARNING,
                message="No resource group - skipping network creation tests"
            ))
            return results
        
        vnet_name = f"{TEST_RESOURCE_PREFIX}-vnet-{self._test_id}"
        nsg_name = f"{TEST_RESOURCE_PREFIX}-nsg-{self._test_id}"
        vnet_created = False
        nsg_created = False
        
        # Show what we're creating
        results.append(CheckResult(
            name="  🌐 Creating test VNet",
            status=CheckStatus.OK,
            message=f"{vnet_name} in {rg_name}"
        ))
        
        # Test NSG creation first
        try:
            nsg_params = {
                "location": self.region or "eastus",
                "tags": {"PreCheck": "Temporary"}
            }
            nsg_operation = network_client.network_security_groups.begin_create_or_update(
                rg_name, nsg_name, nsg_params
            )
            nsg_operation.result()  # Wait for completion
            nsg_created = True
            results.append(CheckResult(
                name="  Microsoft.Network/networkSecurityGroups/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {nsg_name}"
            ))
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                results.append(CheckResult(
                    name="  Microsoft.Network/networkSecurityGroups/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            else:
                results.append(CheckResult(
                    name="  Microsoft.Network/networkSecurityGroups/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
        
        # Test VNet creation
        try:
            vnet_params = {
                "location": self.region or "eastus",
                "address_space": {"address_prefixes": ["10.255.0.0/16"]},
                "subnets": [
                    {
                        "name": "public-subnet",
                        "address_prefix": "10.255.1.0/24",
                        "delegations": [{
                            "name": "databricks-del-public",
                            "service_name": "Microsoft.Databricks/workspaces"
                        }]
                    },
                    {
                        "name": "private-subnet", 
                        "address_prefix": "10.255.2.0/24",
                        "delegations": [{
                            "name": "databricks-del-private",
                            "service_name": "Microsoft.Databricks/workspaces"
                        }]
                    }
                ],
                "tags": {"PreCheck": "Temporary"}
            }
            
            vnet_operation = network_client.virtual_networks.begin_create_or_update(
                rg_name, vnet_name, vnet_params
            )
            vnet_operation.result()  # Wait for completion
            vnet_created = True
            
            results.append(CheckResult(
                name="  Microsoft.Network/virtualNetworks/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {vnet_name}"
            ))
            results.append(CheckResult(
                name="  Microsoft.Network/virtualNetworks/subnets/write",
                status=CheckStatus.OK,
                message="✓ CREATED: public-subnet, private-subnet"
            ))
            results.append(CheckResult(
                name="  Subnet Delegation (Databricks)",
                status=CheckStatus.OK,
                message="✓ Delegated to Microsoft.Databricks/workspaces"
            ))
            
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                results.append(CheckResult(
                    name="  Microsoft.Network/virtualNetworks/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            else:
                results.append(CheckResult(
                    name="  Microsoft.Network/virtualNetworks/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
        
        # CLEANUP
        if vnet_created:
            try:
                network_client.virtual_networks.begin_delete(rg_name, vnet_name)
                results.append(CheckResult(
                    name="  🗑️  Microsoft.Network/virtualNetworks/delete",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {vnet_name}"
                ))
            except Exception as e:
                results.append(CheckResult(
                    name="  🗑️  VNet Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {vnet_name}"
                ))
        
        if nsg_created:
            try:
                network_client.network_security_groups.begin_delete(rg_name, nsg_name)
                results.append(CheckResult(
                    name="  🗑️  Microsoft.Network/networkSecurityGroups/delete",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {nsg_name}"
                ))
            except Exception as e:
                results.append(CheckResult(
                    name="  🗑️  NSG Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {nsg_name}"
                ))
        
        return results
    
    def _test_storage_permissions(self, test_rg: str = None) -> List[CheckResult]:
        """Test Storage Account permissions by creating real resources."""
        results = []
        storage_client = self._get_storage_client()
        
        rg_name = test_rg or self.resource_group
        if not rg_name:
            results.append(CheckResult(
                name="  Storage Tests",
                status=CheckStatus.WARNING,
                message="No resource group - skipping storage creation tests"
            ))
            return results
        
        # Storage account names must be 3-24 lowercase alphanumeric
        storage_name = f"{TEST_RESOURCE_PREFIX}{self._test_id}"[:24].lower()
        storage_created = False
        
        # Show what we're creating
        results.append(CheckResult(
            name="  📦 Creating test Storage Account (ADLS Gen2)",
            status=CheckStatus.OK,
            message=storage_name
        ))
        
        # Check name availability
        try:
            check_result = storage_client.storage_accounts.check_name_availability({
                "name": storage_name,
                "type": "Microsoft.Storage/storageAccounts"
            })
            
            if not check_result.name_available:
                results.append(CheckResult(
                    name="  Storage Name Check",
                    status=CheckStatus.WARNING,
                    message=f"Name not available: {check_result.reason}"
                ))
                return results
        except Exception as e:
            results.append(CheckResult(
                name="  Storage Name Check",
                status=CheckStatus.WARNING,
                message=f"Could not check: {str(e)[:50]}"
            ))
        
        # Create Storage Account with ADLS Gen2 (HNS)
        try:
            storage_params = {
                "location": self.region or "eastus",
                "sku": {"name": "Standard_LRS"},
                "kind": "StorageV2",
                "is_hns_enabled": True,  # ADLS Gen2
                "tags": {"PreCheck": "Temporary"}
            }
            
            storage_operation = storage_client.storage_accounts.begin_create(
                rg_name, storage_name, storage_params
            )
            storage_operation.result()  # Wait for completion
            storage_created = True
            
            results.append(CheckResult(
                name="  Microsoft.Storage/storageAccounts/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {storage_name} (ADLS Gen2)"
            ))
            
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                results.append(CheckResult(
                    name="  Microsoft.Storage/storageAccounts/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            else:
                results.append(CheckResult(
                    name="  Microsoft.Storage/storageAccounts/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
            return results
        
        if storage_created:
            # Test list keys
            try:
                keys = storage_client.storage_accounts.list_keys(rg_name, storage_name)
                results.append(CheckResult(
                    name="  Microsoft.Storage/storageAccounts/listKeys",
                    status=CheckStatus.OK,
                    message="VERIFIED - Can access storage keys"
                ))
            except Exception as e:
                if "AuthorizationFailed" in str(e):
                    results.append(CheckResult(
                        name="  Microsoft.Storage/storageAccounts/listKeys",
                        status=CheckStatus.NOT_OK,
                        message=f"DENIED: {str(e)[:50]}"
                    ))
            
            # CLEANUP
            try:
                storage_client.storage_accounts.delete(rg_name, storage_name)
                results.append(CheckResult(
                    name="  🗑️  Microsoft.Storage/storageAccounts/delete",
                    status=CheckStatus.OK,
                    message=f"✓ DELETED: {storage_name}"
                ))
            except Exception as e:
                results.append(CheckResult(
                    name="  🗑️  Storage Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {storage_name}"
                ))
        
        return results
    
    def _test_access_connector_permissions(self, test_rg: str) -> List[CheckResult]:
        """
        Test Access Connector for Azure Databricks permissions.
        Required for Unity Catalog to access storage with managed identity.
        
        Per Microsoft docs: https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/azure-managed-identities
        """
        results = []
        resource_client = self._get_resource_client()
        
        connector_name = f"{TEST_RESOURCE_PREFIX}-connector-{self._test_id}"
        connector_created = False
        
        results.append(CheckResult(
            name="  🔗 Creating Access Connector for Databricks",
            status=CheckStatus.OK,
            message=connector_name
        ))
        
        # Create Access Connector for Azure Databricks
        try:
            # The Access Connector is a Microsoft.Databricks/accessConnectors resource
            connector_params = {
                "location": self.region or "eastus",
                "identity": {
                    "type": "SystemAssigned"
                },
                "tags": {"PreCheck": "Temporary"}
            }
            
            # Use generic resource creation
            poller = resource_client.resources.begin_create_or_update(
                resource_group_name=test_rg,
                resource_provider_namespace="Microsoft.Databricks",
                parent_resource_path="",
                resource_type="accessConnectors",
                resource_name=connector_name,
                api_version="2024-05-01",
                parameters=connector_params
            )
            connector_result = poller.result()
            connector_created = True
            
            results.append(CheckResult(
                name="  Microsoft.Databricks/accessConnectors/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {connector_name}"
            ))
            
            # Check if managed identity was created
            if hasattr(connector_result, 'identity') and connector_result.identity:
                principal_id = getattr(connector_result.identity, 'principal_id', None)
                if principal_id:
                    results.append(CheckResult(
                        name="  System-Assigned Managed Identity",
                        status=CheckStatus.OK,
                        message=f"✓ Created with principal: {principal_id[:20]}..."
                    ))
            
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                results.append(CheckResult(
                    name="  Microsoft.Databricks/accessConnectors/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            elif "ResourceProviderNotRegistered" in error:
                results.append(CheckResult(
                    name="  Microsoft.Databricks/accessConnectors/write",
                    status=CheckStatus.NOT_OK,
                    message="Microsoft.Databricks provider not registered"
                ))
            else:
                results.append(CheckResult(
                    name="  Microsoft.Databricks/accessConnectors/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
        
        # Check role assignment permissions (needed to grant Storage Blob Data Contributor)
        try:
            auth_client = self._get_authorization_client()
            
            # Try to list role definitions (indicates authorization read access)
            roles = list(auth_client.role_definitions.list(
                scope=f"/subscriptions/{self.subscription_id}",
                filter="roleName eq 'Storage Blob Data Contributor'"
            ))
            
            if roles:
                results.append(CheckResult(
                    name="  Storage Blob Data Contributor role",
                    status=CheckStatus.OK,
                    message="Role exists - can be assigned to Access Connector"
                ))
            
            # Check if we can create role assignments
            # We can't actually test this without a real target, but we can check the permission
            results.append(CheckResult(
                name="  Microsoft.Authorization/roleAssignments",
                status=CheckStatus.WARNING,
                message="Cannot verify - needs Owner/User Access Admin on Storage"
            ))
            
        except Exception as e:
            results.append(CheckResult(
                name="  Role Assignment Check",
                status=CheckStatus.WARNING,
                message=f"Could not verify: {str(e)[:50]}"
            ))
        
        # Required roles for Unity Catalog (informational)
        results.append(CheckResult(
            name="  ── Required RBAC Roles (on Storage Account) ──",
            status=CheckStatus.OK,
            message=""
        ))
        results.append(CheckResult(
            name="  • Storage Blob Data Contributor",
            status=CheckStatus.OK,
            message="Read/write data in blob containers"
        ))
        results.append(CheckResult(
            name="  • Storage Queue Data Contributor",
            status=CheckStatus.OK,
            message="For file events (optional)"
        ))
        results.append(CheckResult(
            name="  ── Required RBAC Roles (on Resource Group) ──",
            status=CheckStatus.OK,
            message=""
        ))
        results.append(CheckResult(
            name="  • EventGrid EventSubscription Contributor",
            status=CheckStatus.OK,
            message="For auto file events (optional)"
        ))
        
        # CLEANUP
        if connector_created:
            try:
                resource_client.resources.begin_delete(
                    resource_group_name=test_rg,
                    resource_provider_namespace="Microsoft.Databricks",
                    parent_resource_path="",
                    resource_type="accessConnectors",
                    resource_name=connector_name,
                    api_version="2024-05-01"
                )
                results.append(CheckResult(
                    name="  🗑️  Deleting Access Connector",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {connector_name}"
                ))
            except Exception as e:
                results.append(CheckResult(
                    name="  🗑️  Access Connector Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {connector_name}"
                ))
        
        return results
    
    # =========================================================================
    # CHECK METHODS
    # =========================================================================
    
    def check_credentials(self) -> CheckCategory:
        """Check Azure credentials validity."""
        category = CheckCategory(name="CREDENTIALS")
        
        # Show how to authenticate
        category.add_result(CheckResult(
            name="Auth Method",
            status=CheckStatus.OK,
            message="Using Azure CLI (az login) or environment variables"
        ))
        
        try:
            sub_client = self._get_subscription_client()
            
            if self.subscription_id:
                try:
                    sub = sub_client.subscriptions.get(self.subscription_id)
                    self._subscription_info = {
                        "id": sub.subscription_id,
                        "name": sub.display_name,
                        "state": str(sub.state),
                    }
                    
                    category.add_result(CheckResult(
                        name="Azure Credentials",
                        status=CheckStatus.OK,
                        message="Authenticated successfully"
                    ))
                    
                    category.add_result(CheckResult(
                        name="Subscription",
                        status=CheckStatus.OK,
                        message=f"{sub.display_name}"
                    ))
                    
                    category.add_result(CheckResult(
                        name="Subscription ID",
                        status=CheckStatus.OK,
                        message=sub.subscription_id
                    ))
                    
                    if str(sub.state) != "SubscriptionState.ENABLED":
                        category.add_result(CheckResult(
                            name="Subscription State",
                            status=CheckStatus.WARNING,
                            message=f"State is {sub.state}"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name="Subscription State",
                            status=CheckStatus.OK,
                            message="Enabled"
                        ))
                        
                except Exception as e:
                    category.add_result(CheckResult(
                        name="Subscription Access",
                        status=CheckStatus.NOT_OK,
                        message=f"Cannot access subscription: {str(e)[:50]}"
                    ))
            else:
                # Auto-detect subscription from az login
                subs = list(sub_client.subscriptions.list())
                if subs:
                    category.add_result(CheckResult(
                        name="Azure Credentials",
                        status=CheckStatus.OK,
                        message="Authenticated via az login"
                    ))
                    
                    # Use first subscription automatically
                    self.subscription_id = subs[0].subscription_id
                    self._subscription_info = {
                        "id": subs[0].subscription_id,
                        "name": subs[0].display_name,
                        "state": str(subs[0].state),
                    }
                    
                    category.add_result(CheckResult(
                        name="Subscription (auto-detected)",
                        status=CheckStatus.OK,
                        message=f"{subs[0].display_name}"
                    ))
                    
                    category.add_result(CheckResult(
                        name="Subscription ID",
                        status=CheckStatus.OK,
                        message=subs[0].subscription_id
                    ))
                    
                    if len(subs) > 1:
                        category.add_result(CheckResult(
                            name="Note",
                            status=CheckStatus.WARNING,
                            message=f"Found {len(subs)} subscriptions - using first. Use --subscription-id to specify."
                        ))
                else:
                    category.add_result(CheckResult(
                        name="Subscription Access",
                        status=CheckStatus.NOT_OK,
                        message="No subscriptions accessible - run: az login"
                    ))
            
            # Check region/location
            if self.region:
                category.add_result(CheckResult(
                    name="Region",
                    status=CheckStatus.OK,
                    message=self.region
                ))
            else:
                category.add_result(CheckResult(
                    name="Region",
                    status=CheckStatus.WARNING,
                    message="No region specified, will use eastus"
                ))
                self.region = "eastus"
            
            # Check resource group if specified
            if self.resource_group:
                try:
                    resource_client = self._get_resource_client()
                    rg = resource_client.resource_groups.get(self.resource_group)
                    category.add_result(CheckResult(
                        name="Resource Group",
                        status=CheckStatus.OK,
                        message=f"{self.resource_group} ({rg.location})"
                    ))
                except Exception as e:
                    category.add_result(CheckResult(
                        name="Resource Group",
                        status=CheckStatus.NOT_OK,
                        message=f"Cannot access: {str(e)[:40]}"
                    ))
                    
        except ImportError as e:
            category.add_result(CheckResult(
                name="Azure SDK",
                status=CheckStatus.NOT_OK,
                message="Run: pip install azure-identity azure-mgmt-resource azure-mgmt-network azure-mgmt-storage"
            ))
        except Exception as e:
            error_msg = str(e)
            if "AADSTS" in error_msg:
                message = "Azure AD authentication failed - run: az login"
            elif "EnvironmentCredential" in error_msg or "DefaultAzureCredential" in error_msg:
                message = "No Azure credentials - run: az login"
            elif "Invalid client secret" in error_msg:
                message = "Invalid client secret"
            elif "AZURE_" in error_msg:
                message = "Missing environment variables - run: az login"
            else:
                message = f"Auth failed: {error_msg[:80]} - try: az login"
            
            category.add_result(CheckResult(
                name="Azure Credentials",
                status=CheckStatus.NOT_OK,
                message=message
            ))
        
        return category
    
    def check_resource_providers(self) -> CheckCategory:
        """Check if required resource providers are registered."""
        category = CheckCategory(name="STEP 1: RESOURCE PROVIDERS")
        
        try:
            resource_client = self._get_resource_client()
            providers = {p.namespace: p for p in resource_client.providers.list()}
            
            for provider_name in self.REQUIRED_PROVIDERS:
                if provider_name in providers:
                    provider = providers[provider_name]
                    if provider.registration_state == "Registered":
                        category.add_result(CheckResult(
                            name=f"  {provider_name}",
                            status=CheckStatus.OK,
                            message="Registered"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name=f"  {provider_name}",
                            status=CheckStatus.WARNING,
                            message=f"State: {provider.registration_state} - may need to register"
                        ))
                else:
                    category.add_result(CheckResult(
                        name=f"  {provider_name}",
                        status=CheckStatus.NOT_OK,
                        message="Not registered - run: az provider register --namespace " + provider_name
                    ))
                    
        except Exception as e:
            category.add_result(CheckResult(
                name="Resource Provider Check",
                status=CheckStatus.WARNING,
                message=f"Could not check: {str(e)[:40]}"
            ))
        
        return category
    
    def run_full_resource_test(self) -> tuple:
        """
        Create a temporary Resource Group and test ALL resources inside it.
        Returns tuple of (rg_category, network_category, storage_category)
        """
        resource_client = self._get_resource_client()
        rg_name = f"{TEST_RESOURCE_PREFIX}-rg-{self._test_id}"
        rg_created = False
        
        # Category for Resource Group
        rg_category = CheckCategory(name="STEP 2: RESOURCE GROUP (REAL TEST)")
        rg_category.add_result(CheckResult(
            name="Test Method",
            status=CheckStatus.OK,
            message="Creating temporary RG, then VNet + Storage inside it..."
        ))
        
        # Create Resource Group first
        rg_category.add_result(CheckResult(
            name="  📁 Creating test Resource Group",
            status=CheckStatus.OK,
            message=rg_name
        ))
        
        try:
            resource_client.resource_groups.create_or_update(
                rg_name,
                {"location": self.region or "eastus", "tags": {"PreCheck": "Temporary"}}
            )
            rg_created = True
            rg_category.add_result(CheckResult(
                name="  Microsoft.Resources/resourceGroups/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {rg_name}"
            ))
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                rg_category.add_result(CheckResult(
                    name="  Microsoft.Resources/resourceGroups/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            else:
                rg_category.add_result(CheckResult(
                    name="  Microsoft.Resources/resourceGroups/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
            
            # Can't continue without RG
            network_category = CheckCategory(name="STEP 3: NETWORK - VNet Injection (REAL TEST)")
            network_category.add_result(CheckResult(
                name="All checks",
                status=CheckStatus.SKIPPED,
                message="Skipped - Resource Group creation failed"
            ))
            
            storage_category = CheckCategory(name="STEP 4: STORAGE - ADLS Gen2 (REAL TEST)")
            storage_category.add_result(CheckResult(
                name="All checks",
                status=CheckStatus.SKIPPED,
                message="Skipped - Resource Group creation failed"
            ))
            
            cleanup_category = CheckCategory(name="CLEANUP")
            cleanup_category.add_result(CheckResult(
                name="Cleanup",
                status=CheckStatus.OK,
                message="No resources created, nothing to clean up"
            ))
            
            return rg_category, network_category, storage_category, cleanup_category
        
        # =========================================================================
        # STEP 3: Create VNet and NSG inside the temporary RG
        # =========================================================================
        network_category = CheckCategory(name="STEP 3: NETWORK - VNet Injection (REAL TEST)")
        network_category.add_result(CheckResult(
            name="Test Method",
            status=CheckStatus.OK,
            message=f"Creating VNet + NSG inside {rg_name}..."
        ))
        
        network_results = self._test_network_permissions(rg_name)
        for result in network_results:
            network_category.add_result(result)
        
        # =========================================================================
        # STEP 4: Create Storage Account inside the temporary RG
        # =========================================================================
        storage_category = CheckCategory(name="STEP 4: STORAGE - ADLS Gen2 (REAL TEST)")
        storage_category.add_result(CheckResult(
            name="Test Method",
            status=CheckStatus.OK,
            message=f"Creating Storage Account (ADLS Gen2) inside {rg_name}..."
        ))
        
        storage_results = self._test_storage_permissions(rg_name)
        for result in storage_results:
            storage_category.add_result(result)
        
        # =========================================================================
        # FINAL CLEANUP: Delete the temporary Resource Group (deletes everything inside)
        # This happens AFTER all tests complete
        # =========================================================================
        cleanup_category = CheckCategory(name="CLEANUP")
        if rg_created:
            try:
                # Start async deletion of RG (this deletes all resources inside)
                resource_client.resource_groups.begin_delete(rg_name)
                cleanup_category.add_result(CheckResult(
                    name="  🗑️  Deleting Resource Group (and all contents)",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {rg_name} (async - includes VNet, NSG, Storage)"
                ))
            except Exception as e:
                cleanup_category.add_result(CheckResult(
                    name="  🗑️  Resource Group Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {rg_name}"
                ))
        
        return rg_category, network_category, storage_category, cleanup_category
    
    def check_databricks_permissions(self) -> CheckCategory:
        """Check Databricks-specific permissions."""
        category = CheckCategory(name="STEP 5: DATABRICKS WORKSPACE PERMISSIONS")
        
        try:
            auth_client = self._get_authorization_client()
            
            # Get role assignments
            scope = f"/subscriptions/{self.subscription_id}"
            if self.resource_group:
                scope += f"/resourceGroups/{self.resource_group}"
            
            try:
                role_assignments = list(auth_client.role_assignments.list_for_scope(scope))
                
                if role_assignments:
                    category.add_result(CheckResult(
                        name="  Role Assignments",
                        status=CheckStatus.OK,
                        message=f"Found {len(role_assignments)} role assignment(s)"
                    ))
                    
                    # Check for Contributor or Owner
                    role_definitions = {}
                    for ra in role_assignments[:10]:
                        try:
                            role_def = auth_client.role_definitions.get_by_id(
                                ra.role_definition_id
                            )
                            role_name = role_def.role_name
                            role_definitions[ra.role_definition_id] = role_name
                        except Exception:
                            pass
                    
                    has_contributor = any(
                        "Contributor" in r or "Owner" in r 
                        for r in role_definitions.values()
                    )
                    
                    if has_contributor:
                        category.add_result(CheckResult(
                            name="  Role Level",
                            status=CheckStatus.OK,
                            message="Has Contributor or Owner role - can create Databricks workspace"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name="  Role Level",
                            status=CheckStatus.WARNING,
                            message="No Contributor/Owner - may need custom role with Microsoft.Databricks/*"
                        ))
                else:
                    category.add_result(CheckResult(
                        name="  Role Assignments",
                        status=CheckStatus.WARNING,
                        message="No direct role assignments found"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="  Role Assignment Check",
                    status=CheckStatus.WARNING,
                    message=f"Could not verify: {str(e)[:40]}"
                ))
            
            # Check Databricks provider
            try:
                resource_client = self._get_resource_client()
                providers = {p.namespace: p for p in resource_client.providers.list()}
                
                if "Microsoft.Databricks" in providers:
                    if providers["Microsoft.Databricks"].registration_state == "Registered":
                        category.add_result(CheckResult(
                            name="  Microsoft.Databricks provider",
                            status=CheckStatus.OK,
                            message="Registered"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name="  Microsoft.Databricks provider",
                            status=CheckStatus.NOT_OK,
                            message="Not registered - run: az provider register --namespace Microsoft.Databricks"
                        ))
                else:
                    category.add_result(CheckResult(
                        name="  Microsoft.Databricks provider",
                        status=CheckStatus.NOT_OK,
                        message="Not found"
                    ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  Databricks Provider",
                    status=CheckStatus.WARNING,
                    message=str(e)[:50]
                ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="Databricks Permissions Check",
                status=CheckStatus.WARNING,
                message=str(e)[:50]
            ))
        
        return category
    
    def check_quotas(self) -> CheckCategory:
        """Check Azure resource quotas."""
        category = CheckCategory(name="QUOTAS & LIMITS")
        
        try:
            network_client = self._get_network_client()
            
            # Check network quotas
            try:
                usages = list(network_client.usages.list(self.region or "eastus"))
                
                critical_quotas = [
                    "VirtualNetworks",
                    "NetworkSecurityGroups",
                    "PublicIPAddresses",
                    "NetworkInterfaces",
                    "PrivateEndpoints",
                ]
                
                for usage in usages:
                    if usage.name.value in critical_quotas:
                        current = usage.current_value
                        limit = usage.limit
                        percentage = (current / limit * 100) if limit > 0 else 0
                        
                        if percentage >= 90:
                            status = CheckStatus.NOT_OK
                            message = f"{current}/{limit} - AT LIMIT!"
                        elif percentage >= 75:
                            status = CheckStatus.WARNING
                            message = f"{current}/{limit} ({percentage:.0f}%) - approaching limit"
                        else:
                            status = CheckStatus.OK
                            message = f"{current}/{limit} ({percentage:.0f}%)"
                        
                        category.add_result(CheckResult(
                            name=f"  {usage.name.localized_value}",
                            status=status,
                            message=message
                        ))
                        
            except Exception as e:
                category.add_result(CheckResult(
                    name="Network Quotas",
                    status=CheckStatus.WARNING,
                    message=f"Could not check: {str(e)[:40]}"
                ))
            
            # Check compute quotas
            try:
                from azure.mgmt.compute import ComputeManagementClient
                compute_client = ComputeManagementClient(
                    self._get_credential(),
                    self.subscription_id
                )
                
                usages = list(compute_client.usage.list(self.region or "eastus"))
                
                for usage in usages:
                    if "Total Regional vCPUs" in usage.name.localized_value:
                        current = usage.current_value
                        limit = usage.limit
                        percentage = (current / limit * 100) if limit > 0 else 0
                        
                        if percentage >= 90:
                            status = CheckStatus.NOT_OK
                        elif percentage >= 75:
                            status = CheckStatus.WARNING
                        else:
                            status = CheckStatus.OK
                        
                        category.add_result(CheckResult(
                            name=f"  {usage.name.localized_value}",
                            status=status,
                            message=f"{current}/{limit} ({percentage:.0f}%)"
                        ))
                        break
                        
            except ImportError:
                category.add_result(CheckResult(
                    name="Compute Quotas",
                    status=CheckStatus.WARNING,
                    message="azure-mgmt-compute not installed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="Compute Quotas",
                    status=CheckStatus.WARNING,
                    message=f"Could not check: {str(e)[:40]}"
                ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="Quota Check",
                status=CheckStatus.WARNING,
                message=f"Could not check quotas: {str(e)[:40]}"
            ))
        
        return category
    
    def check_privatelink_permissions(self, test_rg: str) -> CheckCategory:
        """Check Private Link permissions (NAT Gateway, Private Endpoints)."""
        category = CheckCategory(name="STEP 5: PRIVATE LINK + SCC (REAL TEST)")
        
        network_client = self._get_network_client()
        nat_gw_name = f"{TEST_RESOURCE_PREFIX}-natgw-{self._test_id}"
        public_ip_name = f"{TEST_RESOURCE_PREFIX}-pip-{self._test_id}"
        nat_gw_created = False
        public_ip_created = False
        
        category.add_result(CheckResult(
            name="Test Method",
            status=CheckStatus.OK,
            message=f"Testing NAT Gateway + Private Endpoints in {test_rg}..."
        ))
        
        # Test Public IP creation (required for NAT Gateway)
        category.add_result(CheckResult(
            name="  🌐 Creating Public IP for NAT Gateway",
            status=CheckStatus.OK,
            message=public_ip_name
        ))
        
        try:
            public_ip_params = {
                "location": self.region or "eastus",
                "sku": {"name": "Standard"},
                "public_ip_allocation_method": "Static",
                "tags": {"PreCheck": "Temporary"}
            }
            
            pip_operation = network_client.public_ip_addresses.begin_create_or_update(
                test_rg, public_ip_name, public_ip_params
            )
            pip_result = pip_operation.result()
            public_ip_created = True
            
            category.add_result(CheckResult(
                name="  Microsoft.Network/publicIPAddresses/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {public_ip_name}"
            ))
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                category.add_result(CheckResult(
                    name="  Microsoft.Network/publicIPAddresses/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            else:
                category.add_result(CheckResult(
                    name="  Microsoft.Network/publicIPAddresses/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
        
        # Test NAT Gateway creation
        if public_ip_created:
            category.add_result(CheckResult(
                name="  🌐 Creating NAT Gateway (required for SCC)",
                status=CheckStatus.OK,
                message=nat_gw_name
            ))
            
            try:
                nat_gw_params = {
                    "location": self.region or "eastus",
                    "sku": {"name": "Standard"},
                    "public_ip_addresses": [{
                        "id": f"/subscriptions/{self.subscription_id}/resourceGroups/{test_rg}/providers/Microsoft.Network/publicIPAddresses/{public_ip_name}"
                    }],
                    "tags": {"PreCheck": "Temporary"}
                }
                
                nat_operation = network_client.nat_gateways.begin_create_or_update(
                    test_rg, nat_gw_name, nat_gw_params
                )
                nat_operation.result()
                nat_gw_created = True
                
                category.add_result(CheckResult(
                    name="  Microsoft.Network/natGateways/write",
                    status=CheckStatus.OK,
                    message=f"✓ CREATED: {nat_gw_name}"
                ))
                category.add_result(CheckResult(
                    name="  SCC (Secure Cluster Connectivity)",
                    status=CheckStatus.OK,
                    message="NAT Gateway enables clusters without public IPs"
                ))
            except Exception as e:
                error = str(e)
                if "AuthorizationFailed" in error:
                    category.add_result(CheckResult(
                        name="  Microsoft.Network/natGateways/write",
                        status=CheckStatus.NOT_OK,
                        message=f"DENIED: {error[:80]}"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="  Microsoft.Network/natGateways/write",
                        status=CheckStatus.WARNING,
                        message=f"Error: {error[:80]}"
                    ))
        
        # Check Private DNS Zone permissions (read-only check)
        try:
            from azure.mgmt.privatedns import PrivateDnsManagementClient
            dns_client = PrivateDnsManagementClient(
                self._get_credential(),
                self.subscription_id
            )
            
            zones = list(dns_client.private_zones.list())
            category.add_result(CheckResult(
                name="  Microsoft.Network/privateDnsZones/read",
                status=CheckStatus.OK,
                message=f"Found {len(zones)} private DNS zones"
            ))
            
            # Check for required zones
            existing_zones = [z.name for z in zones]
            for zone in self.PRIVATE_DNS_ZONES:
                if zone in existing_zones:
                    category.add_result(CheckResult(
                        name=f"  Private DNS: {zone}",
                        status=CheckStatus.OK,
                        message="EXISTS"
                    ))
                else:
                    category.add_result(CheckResult(
                        name=f"  Private DNS: {zone}",
                        status=CheckStatus.WARNING,
                        message="NOT FOUND - will need to create"
                    ))
        except ImportError:
            category.add_result(CheckResult(
                name="  Private DNS Zones",
                status=CheckStatus.WARNING,
                message="azure-mgmt-privatedns not installed"
            ))
        except Exception as e:
            category.add_result(CheckResult(
                name="  Private DNS Zones",
                status=CheckStatus.WARNING,
                message=f"Could not check: {str(e)[:50]}"
            ))
        
        # CLEANUP
        if nat_gw_created:
            try:
                network_client.nat_gateways.begin_delete(test_rg, nat_gw_name)
                category.add_result(CheckResult(
                    name="  🗑️  Deleting NAT Gateway",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {nat_gw_name}"
                ))
            except Exception:
                category.add_result(CheckResult(
                    name="  🗑️  NAT Gateway Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {nat_gw_name}"
                ))
        
        if public_ip_created:
            try:
                # Wait a bit for NAT Gateway deletion
                time.sleep(2)
                network_client.public_ip_addresses.begin_delete(test_rg, public_ip_name)
                category.add_result(CheckResult(
                    name="  🗑️  Deleting Public IP",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {public_ip_name}"
                ))
            except Exception:
                category.add_result(CheckResult(
                    name="  🗑️  Public IP Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {public_ip_name}"
                ))
        
        return category
    
    def run_all_checks(self) -> CheckReport:
        """Run all Azure checks for Databricks deployment."""
        self._report = CheckReport(
            cloud=self.cloud_name,
            region=self.region or "default"
        )
        
        # Run credentials check first
        cred_category = self.check_credentials()
        self._report.add_category(cred_category)
        
        # Update region in report
        self._report.region = self.region or "eastus"
        
        # Set account info
        if self._subscription_info:
            self._report.account_info = (
                f"Subscription: {self._subscription_info['name']} "
                f"({self._subscription_info['id']})"
            )
        
        # Check if credentials failed
        credentials_ok = all(
            r.status in (CheckStatus.OK, CheckStatus.WARNING) 
            for r in cred_category.results
        )
        
        if not credentials_ok:
            for check_name in [
                "STEP 1: RESOURCE PROVIDERS",
                "STEP 2: RESOURCE GROUP",
                "STEP 3: NETWORK",
                "STEP 4: STORAGE",
                "STEP 5: DATABRICKS WORKSPACE",
                "QUOTAS & LIMITS"
            ]:
                category = CheckCategory(name=check_name)
                category.add_result(CheckResult(
                    name="All checks",
                    status=CheckStatus.SKIPPED,
                    message="Skipped due to credential failure"
                ))
                self._report.add_category(category)
            return self._report
        
        # Step 1: Resource Providers
        self._report.add_category(self.check_resource_providers())
        
        # Determine what to test based on deployment mode
        mode = self.deployment_mode
        needs_vnet_test = mode in (
            AzureDeploymentMode.VNET_INJECTION,
            AzureDeploymentMode.PRIVATELINK,
            AzureDeploymentMode.FULL
        )
        needs_storage_test = mode in (
            AzureDeploymentMode.UNITY_CATALOG,
            AzureDeploymentMode.FULL
        )
        needs_privatelink_test = mode in (
            AzureDeploymentMode.PRIVATELINK,
            AzureDeploymentMode.FULL
        )
        
        # Show deployment mode explanation
        mode_cat = CheckCategory(name="DEPLOYMENT MODE ANALYSIS")
        mode_cat.add_result(CheckResult(
            name="Mode",
            status=CheckStatus.OK,
            message=f"{mode.value.upper()}"
        ))
        
        if mode == AzureDeploymentMode.STANDARD:
            mode_cat.add_result(CheckResult(
                name="  VNet",
                status=CheckStatus.OK,
                message="Databricks-managed (no VNet creation needed)"
            ))
            mode_cat.add_result(CheckResult(
                name="  Storage (DBFS)",
                status=CheckStatus.OK,
                message="Databricks-managed (created in Managed RG)"
            ))
            mode_cat.add_result(CheckResult(
                name="  You provide",
                status=CheckStatus.OK,
                message="Only managed_resource_group_name"
            ))
        elif mode == AzureDeploymentMode.VNET_INJECTION:
            mode_cat.add_result(CheckResult(
                name="  VNet",
                status=CheckStatus.OK,
                message="Customer-managed (you create VNet + Subnets)"
            ))
            mode_cat.add_result(CheckResult(
                name="  Storage (DBFS)",
                status=CheckStatus.OK,
                message="Databricks-managed (created in Managed RG)"
            ))
        elif mode == AzureDeploymentMode.UNITY_CATALOG:
            mode_cat.add_result(CheckResult(
                name="  VNet",
                status=CheckStatus.OK,
                message="Databricks-managed"
            ))
            mode_cat.add_result(CheckResult(
                name="  Unity Catalog Storage",
                status=CheckStatus.OK,
                message="You create ADLS Gen2 + Container + Access Connector"
            ))
        elif mode == AzureDeploymentMode.PRIVATELINK:
            mode_cat.add_result(CheckResult(
                name="  VNet",
                status=CheckStatus.OK,
                message="Customer-managed (required for Private Link)"
            ))
            mode_cat.add_result(CheckResult(
                name="  NAT Gateway",
                status=CheckStatus.OK,
                message="REQUIRED for Secure Cluster Connectivity (SCC)"
            ))
            mode_cat.add_result(CheckResult(
                name="  Private Endpoints",
                status=CheckStatus.OK,
                message="Frontend + Backend connections"
            ))
        elif mode == AzureDeploymentMode.FULL:
            mode_cat.add_result(CheckResult(
                name="  All Features",
                status=CheckStatus.OK,
                message="VNet Injection + Unity Catalog + Private Link"
            ))
        
        self._report.add_category(mode_cat)
        
        # Create temporary RG for testing (needed for any mode except standard)
        resource_client = self._get_resource_client()
        test_rg = f"{TEST_RESOURCE_PREFIX}-rg-{self._test_id}"
        rg_created = False
        
        # Step 2: Resource Group (always test this)
        rg_category = CheckCategory(name="STEP 2: RESOURCE GROUP (REAL TEST)")
        rg_category.add_result(CheckResult(
            name="Test Method",
            status=CheckStatus.OK,
            message="Creating temporary RG for permission tests..."
        ))
        rg_category.add_result(CheckResult(
            name="  📁 Creating test Resource Group",
            status=CheckStatus.OK,
            message=test_rg
        ))
        
        try:
            resource_client.resource_groups.create_or_update(
                test_rg,
                {"location": self.region or "eastus", "tags": {"PreCheck": "Temporary"}}
            )
            rg_created = True
            rg_category.add_result(CheckResult(
                name="  Microsoft.Resources/resourceGroups/write",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {test_rg}"
            ))
        except Exception as e:
            error = str(e)
            if "AuthorizationFailed" in error:
                rg_category.add_result(CheckResult(
                    name="  Microsoft.Resources/resourceGroups/write",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error[:80]}"
                ))
            else:
                rg_category.add_result(CheckResult(
                    name="  Microsoft.Resources/resourceGroups/write",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error[:80]}"
                ))
        
        self._report.add_category(rg_category)
        
        if rg_created:
            # Step 3: Network (VNet Injection)
            if needs_vnet_test:
                network_category = CheckCategory(name="STEP 3: NETWORK - VNet Injection (REAL TEST)")
                network_category.add_result(CheckResult(
                    name="Test Method",
                    status=CheckStatus.OK,
                    message=f"Creating VNet + Subnets + NSG in {test_rg}..."
                ))
                
                network_results = self._test_network_permissions(test_rg)
                for result in network_results:
                    network_category.add_result(result)
                
                self._report.add_category(network_category)
            else:
                skip_cat = CheckCategory(name="STEP 3: NETWORK")
                skip_cat.add_result(CheckResult(
                    name="VNet Creation",
                    status=CheckStatus.OK,
                    message="Skipped (Databricks-managed VNet in this mode)"
                ))
                self._report.add_category(skip_cat)
            
            # Step 4: Storage (Unity Catalog)
            if needs_storage_test:
                storage_category = CheckCategory(name="STEP 4: STORAGE - Unity Catalog ADLS Gen2 (REAL TEST)")
                storage_category.add_result(CheckResult(
                    name="Test Method",
                    status=CheckStatus.OK,
                    message=f"Creating Storage Account (ADLS Gen2) in {test_rg}..."
                ))
                
                storage_results = self._test_storage_permissions(test_rg)
                for result in storage_results:
                    storage_category.add_result(result)
                
                self._report.add_category(storage_category)
                
                # Step 4b: Access Connector for Unity Catalog
                connector_category = CheckCategory(name="STEP 4b: ACCESS CONNECTOR FOR DATABRICKS (REAL TEST)")
                connector_category.add_result(CheckResult(
                    name="Test Method",
                    status=CheckStatus.OK,
                    message=f"Creating Access Connector for Unity Catalog in {test_rg}..."
                ))
                connector_category.add_result(CheckResult(
                    name="Reference",
                    status=CheckStatus.OK,
                    message="Per: learn.microsoft.com/azure/databricks/.../azure-managed-identities"
                ))
                
                connector_results = self._test_access_connector_permissions(test_rg)
                for result in connector_results:
                    connector_category.add_result(result)
                
                self._report.add_category(connector_category)
            else:
                skip_cat = CheckCategory(name="STEP 4: STORAGE")
                skip_cat.add_result(CheckResult(
                    name="Storage Creation",
                    status=CheckStatus.OK,
                    message="Skipped (DBFS storage is Databricks-managed in this mode)"
                ))
                self._report.add_category(skip_cat)
            
            # Step 5: Private Link + SCC
            if needs_privatelink_test:
                self._report.add_category(self.check_privatelink_permissions(test_rg))
            else:
                skip_cat = CheckCategory(name="STEP 5: PRIVATE LINK")
                skip_cat.add_result(CheckResult(
                    name="Private Link",
                    status=CheckStatus.OK,
                    message="Skipped (not required in this mode)"
                ))
                self._report.add_category(skip_cat)
        else:
            # Can't continue without RG
            for check_name in ["STEP 3: NETWORK", "STEP 4: STORAGE", "STEP 5: PRIVATE LINK"]:
                category = CheckCategory(name=check_name)
                category.add_result(CheckResult(
                    name="All checks",
                    status=CheckStatus.SKIPPED,
                    message="Skipped - Resource Group creation failed"
                ))
                self._report.add_category(category)
        
        # Databricks workspace permissions
        self._report.add_category(self.check_databricks_permissions())
        
        # Quotas
        self._report.add_category(self.check_quotas())
        
        # Final cleanup
        if rg_created:
            cleanup_category = CheckCategory(name="CLEANUP")
            try:
                resource_client.resource_groups.begin_delete(test_rg)
                cleanup_category.add_result(CheckResult(
                    name="  🗑️  Deleting Resource Group (and all contents)",
                    status=CheckStatus.OK,
                    message=f"✓ DELETING: {test_rg} (async - all temp resources)"
                ))
            except Exception as e:
                cleanup_category.add_result(CheckResult(
                    name="  🗑️  Resource Group Cleanup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {test_rg}"
                ))
            self._report.add_category(cleanup_category)
        
        self._cleanup_test_resources()
        
        return self._report
