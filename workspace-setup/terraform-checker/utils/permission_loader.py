"""
Permission loader for Databricks Terraform Pre-Check.

Loads permission definitions from YAML files, making it easy to update
permissions when Databricks documentation changes.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

import yaml


# Default config directory
CONFIG_DIR = Path(__file__).parent.parent / "config" / "permissions"


@dataclass
class ResourcePermission:
    """Represents a Terraform resource and its required permissions."""
    name: str
    terraform_type: str
    description: str
    actions: List[str] = field(default_factory=list)
    deployment_modes: List[str] = field(default_factory=lambda: ["standard"])
    optional: bool = False


@dataclass
class DeploymentProfile:
    """Represents a deployment profile with its required resources."""
    name: str
    description: str
    resources: List[str] = field(default_factory=list)
    additional_resources: List[str] = field(default_factory=list)
    inherits: Optional[str] = None


class PermissionLoader:
    """Loads and manages permission definitions from YAML files."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or CONFIG_DIR
        self._cache: Dict[str, Dict] = {}
    
    def _load_yaml(self, cloud: str) -> Dict[str, Any]:
        """Load YAML file for a cloud provider."""
        if cloud in self._cache:
            return self._cache[cloud]
        
        yaml_path = self.config_dir / f"{cloud}.yaml"
        
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Permission file not found: {yaml_path}\n"
                f"Please ensure {cloud}.yaml exists in {self.config_dir}"
            )
        
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        
        self._cache[cloud] = data
        return data
    
    def get_resource_permissions(
        self, 
        cloud: str, 
        resource_name: str
    ) -> Optional[ResourcePermission]:
        """Get permissions for a specific resource."""
        data = self._load_yaml(cloud)
        resources = data.get('resources', {})
        
        if resource_name not in resources:
            return None
        
        res = resources[resource_name]
        return ResourcePermission(
            name=res.get('name', resource_name),
            terraform_type=res.get('terraform_type', ''),
            description=res.get('description', ''),
            actions=res.get('actions', []),
            deployment_modes=res.get('deployment_modes', ['standard']),
            optional=res.get('optional', False),
        )
    
    def get_all_resources(self, cloud: str) -> Dict[str, ResourcePermission]:
        """Get all resource permissions for a cloud."""
        data = self._load_yaml(cloud)
        resources = data.get('resources', {})
        
        result = {}
        for name, res in resources.items():
            result[name] = ResourcePermission(
                name=res.get('name', name),
                terraform_type=res.get('terraform_type', ''),
                description=res.get('description', ''),
                actions=res.get('actions', []),
                deployment_modes=res.get('deployment_modes', ['standard']),
                optional=res.get('optional', False),
            )
        
        return result
    
    def get_deployment_profile(
        self, 
        cloud: str, 
        profile_name: str
    ) -> Optional[DeploymentProfile]:
        """Get a deployment profile."""
        data = self._load_yaml(cloud)
        profiles = data.get('deployment_profiles', {})
        
        if profile_name not in profiles:
            return None
        
        prof = profiles[profile_name]
        return DeploymentProfile(
            name=profile_name,
            description=prof.get('description', ''),
            resources=prof.get('resources', []),
            additional_resources=prof.get('additional_resources', []),
            inherits=prof.get('inherits'),
        )
    
    def get_actions_for_profile(
        self, 
        cloud: str, 
        profile_name: str
    ) -> List[str]:
        """Get all actions required for a deployment profile."""
        profile = self.get_deployment_profile(cloud, profile_name)
        if not profile:
            return []
        
        all_resources = set(profile.resources)
        
        # Handle inheritance
        if profile.inherits:
            parent = self.get_deployment_profile(cloud, profile.inherits)
            if parent:
                all_resources.update(parent.resources)
        
        # Add additional resources
        all_resources.update(profile.additional_resources)
        
        # Collect all actions
        actions = set()
        for resource_name in all_resources:
            resource = self.get_resource_permissions(cloud, resource_name)
            if resource:
                actions.update(resource.actions)
        
        return sorted(list(actions))
    
    def get_vpc_type_actions(self, cloud: str, vpc_type: str) -> List[str]:
        """Get EC2 actions for a specific VPC type (AWS only)."""
        if cloud != 'aws':
            return []
        
        data = self._load_yaml(cloud)
        vpc_types = data.get('vpc_types', {})
        
        if vpc_type not in vpc_types:
            return []
        
        vpc_config = vpc_types[vpc_type]
        actions = vpc_config.get('ec2_actions', [])
        
        # Add common IAM actions
        common = data.get('common_iam_actions', [])
        
        return actions + common
    
    def get_required_providers(self, cloud: str) -> List[Dict[str, str]]:
        """Get required resource providers (Azure) or APIs (GCP)."""
        data = self._load_yaml(cloud)
        
        if cloud == 'azure':
            providers = data.get('resource_providers', {}).get('required', [])
            return providers
        elif cloud == 'gcp':
            apis = data.get('required_apis', [])
            return apis
        
        return []
    
    def get_private_dns_zones(self, cloud: str) -> List[str]:
        """Get required private DNS zones (Azure)."""
        if cloud != 'azure':
            return []
        
        data = self._load_yaml(cloud)
        zones = data.get('private_dns_zones', {})
        
        return [z.get('zone') for z in zones.values() if z.get('zone')]
    
    def get_quotas(self, cloud: str) -> Dict[str, Dict]:
        """Get quota definitions for a cloud."""
        data = self._load_yaml(cloud)
        return data.get('quotas', {})
    
    def get_unity_catalog_roles(self, cloud: str) -> Dict[str, Dict]:
        """Get Unity Catalog RBAC roles (Azure)."""
        if cloud != 'azure':
            return {}
        
        data = self._load_yaml(cloud)
        return data.get('unity_catalog_roles', {})


# Global loader instance
_loader: Optional[PermissionLoader] = None


def get_permission_loader(config_dir: Optional[Path] = None) -> PermissionLoader:
    """Get the global permission loader instance."""
    global _loader
    if _loader is None or config_dir is not None:
        _loader = PermissionLoader(config_dir)
    return _loader


def get_actions_for_deployment(
    cloud: str,
    deployment_mode: str,
    vpc_type: Optional[str] = None
) -> List[str]:
    """
    Convenience function to get all required actions for a deployment.
    
    Args:
        cloud: Cloud provider ('aws', 'azure', 'gcp')
        deployment_mode: Deployment mode ('standard', 'privatelink', 'unity', 'full')
        vpc_type: VPC type for AWS ('databricks_managed', 'customer_managed_default', etc.)
    
    Returns:
        List of required IAM/RBAC actions
    """
    loader = get_permission_loader()
    
    actions = set()
    
    # Get profile actions
    profile_actions = loader.get_actions_for_profile(cloud, deployment_mode)
    actions.update(profile_actions)
    
    # Add VPC type actions for AWS
    if cloud == 'aws' and vpc_type:
        vpc_actions = loader.get_vpc_type_actions(cloud, vpc_type)
        actions.update(vpc_actions)
    
    return sorted(list(actions))

