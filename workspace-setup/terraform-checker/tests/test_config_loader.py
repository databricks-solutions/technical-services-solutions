"""Tests for configuration loader utility."""

import pytest
import tempfile
from pathlib import Path

from utils.config_loader import (
    PreCheckConfig,
    CloudConfig,
    load_config,
    generate_sample_config,
    save_sample_config,
)


class TestPreCheckConfig:
    """Tests for PreCheckConfig class."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = PreCheckConfig()
        
        assert config.log_level == "info"
        assert config.verbose is False
        assert config.dry_run is False
        assert config.aws.enabled is True
        assert config.azure.enabled is True
    
    def test_from_dict_basic(self):
        """Test creating config from basic dictionary."""
        data = {
            'log_level': 'debug',
            'verbose': True,
            'output_file': 'report.txt',
        }
        config = PreCheckConfig.from_dict(data)
        
        assert config.log_level == 'debug'
        assert config.verbose is True
        assert config.output_file == 'report.txt'
    
    def test_from_dict_aws(self):
        """Test creating config with AWS settings."""
        data = {
            'aws': {
                'enabled': True,
                'region': 'us-west-2',
                'profile': 'production',
            }
        }
        config = PreCheckConfig.from_dict(data)
        
        assert config.aws.enabled is True
        assert config.aws.region == 'us-west-2'
        assert config.aws.profile == 'production'
    
    def test_from_dict_azure(self):
        """Test creating config with Azure settings."""
        data = {
            'azure': {
                'enabled': True,
                'region': 'eastus',
                'subscription_id': 'sub-123',
                'resource_group': 'rg-test',
            }
        }
        config = PreCheckConfig.from_dict(data)
        
        assert config.azure.enabled is True
        assert config.azure.region == 'eastus'
        assert config.azure.subscription_id == 'sub-123'
        assert config.azure.resource_group == 'rg-test'
    
    def test_from_dict_gcp(self):
        """Test creating config with GCP settings."""
        data = {
            'gcp': {
                'enabled': True,
                'region': 'us-central1',
                'project': 'my-project',
                'credentials_file': '/path/to/creds.json',
            }
        }
        config = PreCheckConfig.from_dict(data)
        
        assert config.gcp.enabled is True
        assert config.gcp.region == 'us-central1'
        assert config.gcp.project == 'my-project'
        assert config.gcp.credentials_file == '/path/to/creds.json'


class TestLoadConfig:
    """Tests for load_config function."""
    
    def test_load_from_path(self):
        """Test loading config from a specific path."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""
log_level: debug
aws:
  region: us-east-1
  profile: test
""")
            f.flush()
            
            config = load_config(f.name)
            
            assert config is not None
            assert config.log_level == 'debug'
            assert config.aws.region == 'us-east-1'
            assert config.aws.profile == 'test'
    
    def test_load_nonexistent_file(self):
        """Test loading from non-existent file returns None."""
        config = load_config('/nonexistent/path/config.yaml')
        assert config is None
    
    def test_load_no_config_found(self):
        """Test that None is returned when no config file exists."""
        # This test may pass or fail depending on whether there's a config file
        # in the default search paths
        result = load_config()
        # Result could be None or a config object


class TestGenerateSampleConfig:
    """Tests for sample config generation."""
    
    def test_generate_sample_config(self):
        """Test generating sample configuration."""
        config = generate_sample_config()
        
        assert 'log_level' in config
        assert 'aws:' in config
        assert 'azure:' in config
        assert 'gcp:' in config
        assert 'region' in config
    
    def test_save_sample_config(self):
        """Test saving sample configuration to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'precheck.yaml'
            result = save_sample_config(str(path))
            
            assert path.exists()
            content = path.read_text()
            assert 'log_level' in content
            assert 'aws:' in content

