"""
Configuration file loader for Databricks Terraform Pre-Check.

Supports YAML configuration files for recurring settings.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

import yaml


@dataclass
class CloudConfig:
    """Configuration for a single cloud provider."""
    enabled: bool = True
    region: Optional[str] = None
    profile: Optional[str] = None  # AWS
    subscription_id: Optional[str] = None  # Azure
    resource_group: Optional[str] = None  # Azure
    project: Optional[str] = None  # GCP
    credentials_file: Optional[str] = None  # GCP


@dataclass
class PreCheckConfig:
    """Main configuration for the pre-check tool."""
    # General settings
    output_file: Optional[str] = None
    log_file: Optional[str] = None
    log_level: str = "info"
    verbose: bool = False
    
    # Cloud configurations
    aws: CloudConfig = field(default_factory=CloudConfig)
    azure: CloudConfig = field(default_factory=CloudConfig)
    gcp: CloudConfig = field(default_factory=CloudConfig)
    
    # Check settings
    skip_cleanup: bool = False
    dry_run: bool = False
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PreCheckConfig':
        """Create config from a dictionary."""
        config = cls()
        
        # General settings
        config.output_file = data.get('output_file')
        config.log_file = data.get('log_file')
        config.log_level = data.get('log_level', 'info')
        config.verbose = data.get('verbose', False)
        config.skip_cleanup = data.get('skip_cleanup', False)
        config.dry_run = data.get('dry_run', False)
        
        if 'aws' in data:
            aws = data['aws']
            config.aws = CloudConfig(
                enabled=aws.get('enabled', True),
                region=aws.get('region'),
                profile=aws.get('profile'),
            )
        
        if 'azure' in data:
            az = data['azure']
            config.azure = CloudConfig(
                enabled=az.get('enabled', True),
                region=az.get('region'),
                subscription_id=az.get('subscription_id'),
                resource_group=az.get('resource_group'),
            )
        
        if 'gcp' in data:
            gcp = data['gcp']
            config.gcp = CloudConfig(
                enabled=gcp.get('enabled', True),
                region=gcp.get('region'),
                project=gcp.get('project'),
                credentials_file=gcp.get('credentials_file'),
            )
        
        return config


def load_config(config_path: Optional[str] = None) -> Optional[PreCheckConfig]:
    """
    Load configuration from a YAML file.
    
    Args:
        config_path: Path to config file. If None, searches for:
            1. ./precheck.yaml
            2. ./precheck.yml
            3. ~/.databricks/precheck.yaml
    
    Returns:
        PreCheckConfig if file found, None otherwise
    """
    search_paths = []
    
    if config_path:
        search_paths.append(Path(config_path))
    else:
        # Current directory
        search_paths.append(Path.cwd() / 'precheck.yaml')
        search_paths.append(Path.cwd() / 'precheck.yml')
        search_paths.append(Path.cwd() / '.precheck.yaml')
        
        # Home directory
        home = Path.home()
        search_paths.append(home / '.databricks' / 'precheck.yaml')
        search_paths.append(home / '.precheck.yaml')
    
    for path in search_paths:
        if path.exists():
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
            return PreCheckConfig.from_dict(data or {})
    
    return None


def generate_sample_config() -> str:
    """Generate a sample configuration file."""
    return """# Databricks Terraform Pre-Check Configuration
# Save as precheck.yaml in your project directory

# General settings
output_file: precheck-report.txt
log_file: precheck.log
log_level: info  # debug, info, warning, error
verbose: false
dry_run: false

# AWS Configuration
aws:
  enabled: true
  region: us-east-1
  profile: default  # AWS CLI profile name

# Azure Configuration
azure:
  enabled: true
  region: eastus
  subscription_id: null  # Set your subscription ID or leave null for auto-detect
  resource_group: null  # Optional: specify an existing resource group

# GCP Configuration
gcp:
  enabled: false
  region: us-central1
  project: null  # Your GCP project ID
  credentials_file: null  # Path to service account JSON key
"""


def save_sample_config(path: str = 'precheck.yaml') -> str:
    """Save a sample configuration file."""
    content = generate_sample_config()
    with open(path, 'w') as f:
        f.write(content)
    return path

