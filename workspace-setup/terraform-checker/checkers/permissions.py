"""
Permission definitions loaded from external YAML files.

This module provides the same interface as databricks_actions.py but loads
permission definitions from config/permissions/*.yaml files.

This allows non-developers to update permissions by editing YAML files
instead of Python code.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any
import logging

from utils.permission_loader import get_permission_loader, PermissionLoader


logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS (These stay in Python as they define behavior, not just data)
# =============================================================================

class DeploymentMode(Enum):
    """Databricks deployment modes."""
    STANDARD = "standard"
    PRIVATE_LINK = "privatelink"
    CUSTOMER_MANAGED_VPC = "customer_managed_vpc"
    UNITY_CATALOG = "unity"
    FULL = "full"


class VPCType(Enum):
    """VPC deployment types for Databricks (AWS)."""
    DATABRICKS_MANAGED = "databricks_managed"
    CUSTOMER_MANAGED_DEFAULT = "customer_managed_default"
    CUSTOMER_MANAGED_CUSTOM = "customer_managed_custom"


# =============================================================================
# PERMISSION LOADER WRAPPER
# =============================================================================

class PermissionRegistry:
    """
    Central registry for cloud permissions.
    
    Loads permissions from YAML files and provides convenient access methods.
    This is the PRIMARY source of truth for permissions.
    """
    
    _instance: Optional['PermissionRegistry'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._loader = get_permission_loader()
        self._cache: Dict[str, Any] = {}
        self._initialized = True
        logger.debug("PermissionRegistry initialized with YAML loader")
    
    # =========================================================================
    # AWS Permissions
    # =========================================================================
    
    def get_aws_vpc_type_actions(self, vpc_type: VPCType) -> List[str]:
        """Get EC2 actions required for a VPC type."""
        type_map = {
            VPCType.DATABRICKS_MANAGED: "databricks_managed",
            VPCType.CUSTOMER_MANAGED_DEFAULT: "customer_managed_default",
            VPCType.CUSTOMER_MANAGED_CUSTOM: "customer_managed_default",  # Same as default
        }
        yaml_type = type_map.get(vpc_type, "customer_managed_default")
        
        actions = self._loader.get_vpc_type_actions("aws", yaml_type)
        logger.debug("Loaded %d AWS VPC actions for type %s", len(actions), yaml_type)
        return actions
    
    def get_aws_resource_actions(self, resource_name: str) -> List[str]:
        """Get actions required for a specific AWS resource."""
        resource = self._loader.get_resource_permissions("aws", resource_name)
        if resource:
            return resource.actions
        return []
    
    def get_aws_deployment_actions(self, mode: DeploymentMode) -> List[str]:
        """Get all actions required for an AWS deployment mode."""
        mode_map = {
            DeploymentMode.STANDARD: "standard",
            DeploymentMode.PRIVATE_LINK: "privatelink",
            DeploymentMode.UNITY_CATALOG: "unity_catalog",
            DeploymentMode.FULL: "full",
        }
        profile_name = mode_map.get(mode, "standard")
        
        actions = self._loader.get_actions_for_profile("aws", profile_name)
        logger.debug("Loaded %d AWS actions for mode %s", len(actions), profile_name)
        return actions
    
    def get_aws_cross_account_actions(self, vpc_type: VPCType) -> List[str]:
        """Get cross-account IAM actions for Databricks."""
        return self.get_aws_vpc_type_actions(vpc_type)
    
    def get_aws_unity_catalog_actions(self) -> List[str]:
        """Get actions for Unity Catalog storage credentials."""
        cache_key = "aws_unity_catalog"
        if cache_key not in self._cache:
            # Load from YAML unity_catalog section
            try:
                data = self._loader._load_yaml("aws")
                unity = data.get("unity_catalog", {})
                storage = unity.get("storage_credential", {}).get("actions", [])
                self._cache[cache_key] = storage
            except Exception:
                self._cache[cache_key] = []
        return self._cache[cache_key]
    
    # =========================================================================
    # Azure Permissions
    # =========================================================================
    
    def get_azure_required_providers(self) -> List[Dict[str, str]]:
        """Get required Azure resource providers."""
        return self._loader.get_required_providers("azure")
    
    def get_azure_private_dns_zones(self) -> List[str]:
        """Get required Azure private DNS zones."""
        return self._loader.get_private_dns_zones("azure")
    
    def get_azure_resource_actions(self, resource_name: str) -> List[str]:
        """Get actions required for a specific Azure resource."""
        resource = self._loader.get_resource_permissions("azure", resource_name)
        if resource:
            return resource.actions
        return []
    
    def get_azure_deployment_actions(self, mode: str) -> List[str]:
        """Get all actions required for an Azure deployment mode."""
        return self._loader.get_actions_for_profile("azure", mode)
    
    def get_azure_unity_catalog_roles(self) -> Dict[str, Dict]:
        """Get Unity Catalog RBAC role requirements."""
        return self._loader.get_unity_catalog_roles("azure")
    
    # =========================================================================
    # GCP Permissions
    # =========================================================================
    
    def get_gcp_required_apis(self) -> List[Dict[str, str]]:
        """Get required GCP APIs."""
        return self._loader.get_required_providers("gcp")
    
    def get_gcp_resource_actions(self, resource_name: str) -> List[str]:
        """Get actions required for a specific GCP resource."""
        resource = self._loader.get_resource_permissions("gcp", resource_name)
        if resource:
            return resource.actions
        return []
    
    def get_gcp_deployment_actions(self, mode: str) -> List[str]:
        """Get all actions required for a GCP deployment mode."""
        return self._loader.get_actions_for_profile("gcp", mode)
    
    # =========================================================================
    # Generic Methods
    # =========================================================================
    
    def get_all_resources(self, cloud: str) -> Dict[str, Any]:
        """Get all resource definitions for a cloud."""
        return self._loader.get_all_resources(cloud)
    
    def get_quotas(self, cloud: str) -> Dict[str, Dict]:
        """Get quota definitions for a cloud."""
        return self._loader.get_quotas(cloud)


# =============================================================================
# CONVENIENCE FUNCTIONS (Backward compatible with databricks_actions.py)
# =============================================================================

_registry: Optional[PermissionRegistry] = None


def get_registry() -> PermissionRegistry:
    """Get the global permission registry."""
    global _registry
    if _registry is None:
        _registry = PermissionRegistry()
    return _registry


def get_cross_account_actions(vpc_type: VPCType) -> List[str]:
    """Get cross-account IAM actions for a VPC type."""
    return get_registry().get_aws_cross_account_actions(vpc_type)


def get_aws_deployment_profile_actions(mode: DeploymentMode) -> List[str]:
    """Get all actions for an AWS deployment profile."""
    return get_registry().get_aws_deployment_actions(mode)


# =============================================================================
# BACKWARD COMPATIBILITY - Lists that can be imported directly
# =============================================================================

# These are populated at import time from YAML
def _load_vpc_actions() -> Dict[str, List[str]]:
    """Load VPC actions from YAML."""
    registry = get_registry()
    return {
        "databricks_managed": registry.get_aws_vpc_type_actions(VPCType.DATABRICKS_MANAGED),
        "customer_managed_default": registry.get_aws_vpc_type_actions(VPCType.CUSTOMER_MANAGED_DEFAULT),
        "customer_managed_custom": registry.get_aws_vpc_type_actions(VPCType.CUSTOMER_MANAGED_CUSTOM),
    }


# Lazy loading to avoid circular imports
_vpc_actions_cache: Optional[Dict[str, List[str]]] = None


def _get_vpc_actions() -> Dict[str, List[str]]:
    global _vpc_actions_cache
    if _vpc_actions_cache is None:
        _vpc_actions_cache = _load_vpc_actions()
    return _vpc_actions_cache


# For backward compatibility, these can be imported
# but they now load from YAML
@property
def DATABRICKS_MANAGED_VPC_ACTIONS() -> List[str]:
    return _get_vpc_actions().get("databricks_managed", [])


@property  
def CUSTOMER_MANAGED_VPC_DEFAULT_ACTIONS() -> List[str]:
    return _get_vpc_actions().get("customer_managed_default", [])


# =============================================================================
# LOGGING
# =============================================================================

def log_permission_source():
    """Log where permissions are being loaded from."""
    loader = get_permission_loader()
    logger.info(
        "Permissions loaded from YAML files in: %s",
        loader.config_dir
    )

