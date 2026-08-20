"""Tests for permission loader utility."""

import pytest
from pathlib import Path

from utils.permission_loader import (
    PermissionLoader,
    get_permission_loader,
    get_actions_for_deployment,
    ResourcePermission,
)


class TestPermissionLoader:
    """Tests for PermissionLoader class."""
    
    @pytest.fixture
    def loader(self):
        """Create a permission loader instance."""
        return PermissionLoader()
    
    def test_load_aws_permissions(self, loader):
        """Test loading AWS permission YAML."""
        resources = loader.get_all_resources('aws')
        
        assert len(resources) > 0
        assert 's3_root_bucket' in resources
        assert 'vpc' in resources
        assert 'security_group' in resources
    
    def test_load_azure_permissions(self, loader):
        """Test loading Azure permission YAML."""
        resources = loader.get_all_resources('azure')
        
        assert len(resources) > 0
        assert 'resource_group' in resources
        assert 'virtual_network' in resources
        assert 'storage_account' in resources
    
    def test_load_gcp_permissions(self, loader):
        """Test loading GCP permission YAML."""
        resources = loader.get_all_resources('gcp')
        
        assert len(resources) > 0
        assert 'vpc_network' in resources
        assert 'subnetwork' in resources
        assert 'storage_bucket' in resources
    
    def test_get_resource_permissions(self, loader):
        """Test getting permissions for a specific resource."""
        s3_bucket = loader.get_resource_permissions('aws', 's3_root_bucket')
        
        assert s3_bucket is not None
        assert s3_bucket.name == "S3 Root Bucket (DBFS)"
        assert 's3:CreateBucket' in s3_bucket.actions
        assert 's3:DeleteBucket' in s3_bucket.actions
    
    def test_get_deployment_profile(self, loader):
        """Test getting deployment profiles."""
        profile = loader.get_deployment_profile('aws', 'standard')
        
        assert profile is not None
        assert profile.name == 'standard'
        assert 's3_root_bucket' in profile.resources
        assert 'vpc' in profile.resources
    
    def test_get_actions_for_profile(self, loader):
        """Test getting all actions for a profile."""
        actions = loader.get_actions_for_profile('aws', 'standard')
        
        assert len(actions) > 0
        assert 's3:CreateBucket' in actions
        assert 'ec2:CreateVpc' in actions
    
    def test_get_vpc_type_actions(self, loader):
        """Test getting VPC type actions for AWS customer-managed VPC."""
        actions = loader.get_vpc_type_actions('aws', 'customer_managed_default')
        
        assert len(actions) > 0
        assert 'ec2:CreateSecurityGroup' in actions
        assert 'ec2:RunInstances' in actions
    
    def test_get_required_providers_azure(self, loader):
        """Test getting required providers for Azure."""
        providers = loader.get_required_providers('azure')
        
        assert len(providers) > 0
        namespaces = [p['namespace'] for p in providers]
        assert 'Microsoft.Databricks' in namespaces
        assert 'Microsoft.Network' in namespaces
    
    def test_get_required_apis_gcp(self, loader):
        """Test getting required APIs for GCP."""
        apis = loader.get_required_providers('gcp')
        
        assert len(apis) > 0
        api_names = [a['api'] for a in apis]
        assert 'compute.googleapis.com' in api_names
        assert 'storage.googleapis.com' in api_names
    
    def test_get_private_dns_zones(self, loader):
        """Test getting private DNS zones for Azure."""
        zones = loader.get_private_dns_zones('azure')
        
        assert len(zones) > 0
        assert 'privatelink.azuredatabricks.net' in zones
        assert 'privatelink.blob.core.windows.net' in zones
    
    def test_invalid_cloud(self, loader):
        """Test handling invalid cloud provider."""
        with pytest.raises(FileNotFoundError):
            loader.get_all_resources('invalid_cloud')
    
    def test_invalid_resource(self, loader):
        """Test handling invalid resource name."""
        result = loader.get_resource_permissions('aws', 'nonexistent_resource')
        assert result is None
    
    def test_invalid_profile(self, loader):
        """Test handling invalid profile name."""
        result = loader.get_deployment_profile('aws', 'nonexistent_profile')
        assert result is None


class TestGetActionsForDeployment:
    """Tests for the convenience function."""
    
    def test_aws_standard(self):
        """Test getting actions for AWS standard deployment."""
        actions = get_actions_for_deployment('aws', 'standard')
        
        assert len(actions) > 0
        assert 's3:CreateBucket' in actions
    
    def test_aws_with_vpc_type(self):
        """Test getting actions for AWS with customer-managed VPC type."""
        actions = get_actions_for_deployment(
            'aws', 
            'standard', 
            vpc_type='customer_managed_default'
        )
        
        assert len(actions) > 0
        assert 'ec2:CreateSecurityGroup' in actions
    
    def test_azure_full(self):
        """Test getting actions for Azure full deployment."""
        actions = get_actions_for_deployment('azure', 'full')
        
        assert len(actions) > 0
        assert 'Microsoft.Network/virtualNetworks/write' in actions

