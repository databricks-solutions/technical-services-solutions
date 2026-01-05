"""Tests for the permissions module integration with YAML files."""

import pytest

from checkers.permissions import (
    get_registry,
    DeploymentMode,
    VPCType,
    get_cross_account_actions,
    get_aws_deployment_profile_actions,
)


class TestPermissionRegistry:
    """Tests for the PermissionRegistry class."""
    
    @pytest.fixture
    def registry(self):
        """Get the permission registry."""
        return get_registry()
    
    def test_registry_singleton(self):
        """Test that registry is a singleton."""
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2
    
    def test_aws_vpc_type_actions_databricks_managed(self, registry):
        """Test loading Databricks-managed VPC actions from YAML."""
        actions = registry.get_aws_vpc_type_actions(VPCType.DATABRICKS_MANAGED)
        
        assert len(actions) > 0
        # These actions should be in databricks_managed VPC type
        assert "ec2:CreateVpc" in actions
        assert "ec2:CreateSubnet" in actions
        assert "ec2:CreateInternetGateway" in actions
    
    def test_aws_vpc_type_actions_customer_managed(self, registry):
        """Test loading customer-managed VPC actions from YAML."""
        actions = registry.get_aws_vpc_type_actions(VPCType.CUSTOMER_MANAGED_DEFAULT)
        
        assert len(actions) > 0
        # Customer-managed should NOT have CreateVpc (Databricks doesn't create VPC)
        # But should have other compute actions
        assert "ec2:CreateSecurityGroup" in actions
        assert "ec2:RunInstances" in actions
    
    def test_aws_resource_actions(self, registry):
        """Test loading specific resource actions from YAML."""
        s3_actions = registry.get_aws_resource_actions("s3_root_bucket")
        
        assert len(s3_actions) > 0
        assert "s3:CreateBucket" in s3_actions
        assert "s3:PutBucketPolicy" in s3_actions
    
    def test_aws_deployment_actions_standard(self, registry):
        """Test loading standard deployment actions from YAML."""
        actions = registry.get_aws_deployment_actions(DeploymentMode.STANDARD)
        
        assert len(actions) > 0
        # Standard should have S3 and IAM actions
        assert any("s3:" in a for a in actions)
        assert any("iam:" in a for a in actions)
    
    def test_aws_deployment_actions_full(self, registry):
        """Test loading full deployment actions from YAML."""
        actions = registry.get_aws_deployment_actions(DeploymentMode.FULL)
        
        assert len(actions) > 0
        # Full should have everything including KMS
        assert any("kms:" in a for a in actions)
    
    def test_azure_required_providers(self, registry):
        """Test loading Azure required providers from YAML."""
        providers = registry.get_azure_required_providers()
        
        assert len(providers) > 0
        namespaces = [p.get("namespace") for p in providers]
        assert "Microsoft.Databricks" in namespaces
        assert "Microsoft.Network" in namespaces
        assert "Microsoft.Storage" in namespaces
    
    def test_azure_private_dns_zones(self, registry):
        """Test loading Azure private DNS zones from YAML."""
        zones = registry.get_azure_private_dns_zones()
        
        assert len(zones) > 0
        assert "privatelink.azuredatabricks.net" in zones
        assert "privatelink.blob.core.windows.net" in zones
    
    def test_azure_resource_actions(self, registry):
        """Test loading specific Azure resource actions from YAML."""
        vnet_actions = registry.get_azure_resource_actions("virtual_network")
        
        assert len(vnet_actions) > 0
        assert "Microsoft.Network/virtualNetworks/write" in vnet_actions
    
    def test_gcp_required_apis(self, registry):
        """Test loading GCP required APIs from YAML."""
        apis = registry.get_gcp_required_apis()
        
        assert len(apis) > 0
        api_names = [a.get("api") for a in apis]
        assert "compute.googleapis.com" in api_names
        assert "storage.googleapis.com" in api_names
    
    def test_gcp_resource_actions(self, registry):
        """Test loading specific GCP resource actions from YAML."""
        vpc_actions = registry.get_gcp_resource_actions("vpc_network")
        
        assert len(vpc_actions) > 0
        assert "compute.networks.create" in vpc_actions
    
    def test_get_all_resources(self, registry):
        """Test getting all resources for a cloud."""
        aws_resources = registry.get_all_resources("aws")
        azure_resources = registry.get_all_resources("azure")
        gcp_resources = registry.get_all_resources("gcp")
        
        assert len(aws_resources) > 0
        assert len(azure_resources) > 0
        assert len(gcp_resources) > 0


class TestBackwardCompatibility:
    """Tests for backward compatibility functions."""
    
    def test_get_cross_account_actions(self):
        """Test backward-compatible get_cross_account_actions function."""
        actions = get_cross_account_actions(VPCType.DATABRICKS_MANAGED)
        
        assert len(actions) > 0
        assert isinstance(actions, list)
        assert all(isinstance(a, str) for a in actions)
    
    def test_get_aws_deployment_profile_actions(self):
        """Test backward-compatible deployment profile function."""
        actions = get_aws_deployment_profile_actions(DeploymentMode.STANDARD)
        
        assert len(actions) > 0
        assert isinstance(actions, list)


class TestYAMLSourceOfTruth:
    """Tests to verify YAML is the source of truth."""
    
    def test_yaml_files_exist(self):
        """Verify YAML permission files exist."""
        from pathlib import Path
        
        config_dir = Path(__file__).parent.parent / "config" / "permissions"
        
        assert (config_dir / "aws.yaml").exists()
        assert (config_dir / "azure.yaml").exists()
        assert (config_dir / "gcp.yaml").exists()
    
    def test_permissions_load_from_yaml(self):
        """Verify that permissions are actually loaded from YAML."""
        from utils.permission_loader import get_permission_loader
        
        loader = get_permission_loader()
        
        # Load directly from YAML
        aws_resources = loader.get_all_resources("aws")
        
        # Verify we got data
        assert "s3_root_bucket" in aws_resources
        assert aws_resources["s3_root_bucket"].actions
        
        # Now verify registry uses the same data
        registry = get_registry()
        registry_actions = registry.get_aws_resource_actions("s3_root_bucket")
        
        assert registry_actions == aws_resources["s3_root_bucket"].actions

