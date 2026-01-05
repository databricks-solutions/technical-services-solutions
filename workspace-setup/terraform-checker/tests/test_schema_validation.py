"""Tests for YAML schema validation."""

import pytest
import tempfile
from pathlib import Path

from config.schema import (
    validate_yaml_schema,
    validate_resource,
    validate_deployment_profile,
    validate_all_configs,
    validate_and_raise,
    SchemaValidationError,
    ValidationResult,
)


class TestValidateResource:
    """Tests for resource validation."""
    
    def test_valid_resource(self):
        """Test validation of a valid resource."""
        resource = {
            "name": "S3 Bucket",
            "terraform_type": "aws_s3_bucket",
            "description": "S3 bucket for storage",
            "actions": ["s3:CreateBucket", "s3:DeleteBucket"],
        }
        errors = validate_resource("s3_bucket", resource, "aws")
        assert len(errors) == 0
    
    def test_missing_required_keys(self):
        """Test validation fails with missing keys."""
        resource = {
            "name": "S3 Bucket",
            # Missing terraform_type, description, actions
        }
        errors = validate_resource("s3_bucket", resource, "aws")
        # 3 missing keys + 1 "empty actions" = 4 errors
        assert len(errors) >= 3
        assert any("terraform_type" in e for e in errors)
        assert any("description" in e for e in errors)
        assert any("actions" in e for e in errors)
    
    def test_empty_actions(self):
        """Test validation fails with empty actions list."""
        resource = {
            "name": "S3 Bucket",
            "terraform_type": "aws_s3_bucket",
            "description": "S3 bucket",
            "actions": [],
        }
        errors = validate_resource("s3_bucket", resource, "aws")
        assert len(errors) == 1
        assert "empty actions" in errors[0]
    
    def test_invalid_deployment_modes(self):
        """Test validation fails with invalid deployment modes."""
        resource = {
            "name": "VPC",
            "terraform_type": "aws_vpc",
            "description": "VPC",
            "actions": ["ec2:CreateVpc"],
            "deployment_modes": ["invalid_mode", "standard"],
        }
        errors = validate_resource("vpc", resource, "aws")
        assert len(errors) == 1
        assert "invalid_mode" in errors[0]


class TestValidateDeploymentProfile:
    """Tests for deployment profile validation."""
    
    def test_valid_profile(self):
        """Test validation of a valid profile."""
        profile = {
            "description": "Standard deployment",
            "resources": ["vpc", "s3_bucket"],
        }
        errors = validate_deployment_profile(
            "standard", profile, {"vpc", "s3_bucket", "iam_role"}
        )
        assert len(errors) == 0
    
    def test_missing_description(self):
        """Test validation fails without description."""
        profile = {
            "resources": ["vpc"],
        }
        errors = validate_deployment_profile("standard", profile, {"vpc"})
        assert len(errors) == 1
        assert "description" in errors[0]
    
    def test_unknown_resource_reference(self):
        """Test validation fails with unknown resource."""
        profile = {
            "description": "Test profile",
            "resources": ["vpc", "unknown_resource"],
        }
        errors = validate_deployment_profile("test", profile, {"vpc"})
        assert len(errors) == 1
        assert "unknown_resource" in errors[0]


class TestValidateYamlSchema:
    """Tests for full YAML schema validation."""
    
    def test_valid_aws_yaml(self):
        """Test validation of the actual AWS config."""
        config_path = Path(__file__).parent.parent / "config" / "permissions" / "aws.yaml"
        if config_path.exists():
            result = validate_yaml_schema(config_path, "aws")
            assert result.valid, f"Errors: {result.errors}"
    
    def test_valid_azure_yaml(self):
        """Test validation of the actual Azure config."""
        config_path = Path(__file__).parent.parent / "config" / "permissions" / "azure.yaml"
        if config_path.exists():
            result = validate_yaml_schema(config_path, "azure")
            assert result.valid, f"Errors: {result.errors}"
    
    def test_valid_gcp_yaml(self):
        """Test validation of the actual GCP config."""
        config_path = Path(__file__).parent.parent / "config" / "permissions" / "gcp.yaml"
        if config_path.exists():
            result = validate_yaml_schema(config_path, "gcp")
            assert result.valid, f"Errors: {result.errors}"
    
    def test_nonexistent_file(self):
        """Test validation of nonexistent file."""
        result = validate_yaml_schema(Path("/nonexistent/file.yaml"), "aws")
        assert not result.valid
        assert any("not found" in e.lower() for e in result.errors)
    
    def test_empty_yaml(self):
        """Test validation of empty YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("")
            f.flush()
            result = validate_yaml_schema(Path(f.name), "aws")
            assert not result.valid
            assert any("empty" in e.lower() for e in result.errors)
    
    def test_invalid_yaml_syntax(self):
        """Test validation of invalid YAML syntax."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            f.flush()
            result = validate_yaml_schema(Path(f.name), "aws")
            assert not result.valid
            assert any("parse error" in e.lower() for e in result.errors)


class TestValidateAllConfigs:
    """Tests for validating all config files."""
    
    def test_validate_all(self):
        """Test validating all configs in directory."""
        config_dir = Path(__file__).parent.parent / "config" / "permissions"
        if config_dir.exists():
            results = validate_all_configs(config_dir)
            
            assert "aws" in results
            assert "azure" in results
            assert "gcp" in results


class TestValidateAndRaise:
    """Tests for validate_and_raise function."""
    
    def test_valid_configs_no_exception(self):
        """Test that valid configs don't raise."""
        config_dir = Path(__file__).parent.parent / "config" / "permissions"
        if config_dir.exists():
            # Should not raise
            validate_and_raise(config_dir)
    
    def test_invalid_config_raises(self):
        """Test that invalid configs raise SchemaValidationError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an invalid config
            invalid_path = Path(tmpdir) / "aws.yaml"
            with open(invalid_path, 'w') as f:
                f.write("resources: {}")
            
            with pytest.raises(SchemaValidationError):
                validate_and_raise(Path(tmpdir))

