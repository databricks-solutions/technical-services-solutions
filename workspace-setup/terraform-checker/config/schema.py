"""
YAML Schema Validation for Permission Configuration Files.

Validates that permission YAML files conform to the expected schema.
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
import yaml


class SchemaValidationError(Exception):
    """Raised when YAML schema validation fails."""
    pass


@dataclass
class ValidationResult:
    """Result of schema validation."""
    valid: bool
    errors: List[str]
    warnings: List[str]
    
    def __bool__(self) -> bool:
        return self.valid


# Required top-level keys per cloud
REQUIRED_KEYS: Dict[str, Set[str]] = {
    "aws": {"vpc_types", "resources", "deployment_profiles"},
    "azure": {"resource_providers", "resources", "deployment_profiles"},
    "gcp": {"required_apis", "resources", "deployment_profiles"},
}

# Required keys for each resource definition
RESOURCE_REQUIRED_KEYS = {"name", "terraform_type", "description", "actions"}

# Valid deployment modes
VALID_DEPLOYMENT_MODES = {"standard", "privatelink", "unity", "vnet", "full"}


def validate_resource(
    resource_name: str,
    resource_data: Dict[str, Any],
    cloud: str
) -> List[str]:
    """Validate a single resource definition."""
    errors = []
    
    if not isinstance(resource_data, dict):
        errors.append(f"Resource '{resource_name}' must be a dictionary")
        return errors
    
    # Check required keys
    for key in RESOURCE_REQUIRED_KEYS:
        if key not in resource_data:
            errors.append(f"Resource '{resource_name}' missing required key: {key}")
    
    # Validate actions is a list
    actions = resource_data.get("actions", [])
    if not isinstance(actions, list):
        errors.append(f"Resource '{resource_name}' actions must be a list")
    elif not actions:
        errors.append(f"Resource '{resource_name}' has empty actions list")
    
    # Validate deployment_modes if present
    modes = resource_data.get("deployment_modes", [])
    if modes and not isinstance(modes, list):
        errors.append(f"Resource '{resource_name}' deployment_modes must be a list")
    elif modes:
        invalid = set(modes) - VALID_DEPLOYMENT_MODES
        if invalid:
            errors.append(
                f"Resource '{resource_name}' has invalid deployment_modes: {invalid}"
            )
    
    return errors


def validate_deployment_profile(
    profile_name: str,
    profile_data: Dict[str, Any],
    available_resources: Set[str]
) -> List[str]:
    """Validate a deployment profile definition."""
    errors = []
    
    if not isinstance(profile_data, dict):
        errors.append(f"Profile '{profile_name}' must be a dictionary")
        return errors
    
    # Check required keys
    if "description" not in profile_data:
        errors.append(f"Profile '{profile_name}' missing 'description'")
    
    # Validate resources reference existing resources
    resources = profile_data.get("resources", [])
    if resources:
        for res in resources:
            if res not in available_resources:
                errors.append(
                    f"Profile '{profile_name}' references unknown resource: {res}"
                )
    
    # Validate inherits reference
    inherits = profile_data.get("inherits")
    if inherits and not isinstance(inherits, str):
        errors.append(f"Profile '{profile_name}' inherits must be a string")
    
    return errors


def validate_yaml_schema(filepath: Path, cloud: str) -> ValidationResult:
    """
    Validate a permission YAML file against the schema.
    
    Args:
        filepath: Path to the YAML file
        cloud: Cloud provider name (aws, azure, gcp)
    
    Returns:
        ValidationResult with errors and warnings
    """
    errors: List[str] = []
    warnings: List[str] = []
    
    # Load YAML
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML parse error: {e}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)
    except FileNotFoundError:
        errors.append(f"File not found: {filepath}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)
    
    if data is None:
        errors.append("YAML file is empty")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)
    
    # Check required top-level keys
    required = REQUIRED_KEYS.get(cloud, set())
    for key in required:
        if key not in data:
            errors.append(f"Missing required top-level key: {key}")
    
    # Check for unknown top-level keys (warning only)
    known_keys = {
        "vpc_types", "common_iam_actions", "resources", "deployment_profiles",
        "quotas", "unity_catalog", "resource_providers", "private_dns_zones",
        "required_apis", "predefined_roles", "minimum_iam", "minimum_rbac",
        "unity_catalog_roles", "privatelink_additional"
    }
    for key in data.keys():
        if key not in known_keys:
            warnings.append(f"Unknown top-level key: {key}")
    
    # Validate resources section
    resources = data.get("resources", {})
    resource_names = set(resources.keys())
    
    for name, res_data in resources.items():
        res_errors = validate_resource(name, res_data, cloud)
        errors.extend(res_errors)
    
    # Validate deployment profiles
    profiles = data.get("deployment_profiles", {})
    for name, prof_data in profiles.items():
        prof_errors = validate_deployment_profile(name, prof_data, resource_names)
        errors.extend(prof_errors)
    
    # Check for duplicate actions across resources (warning)
    all_actions: Dict[str, List[str]] = {}
    for name, res_data in resources.items():
        if isinstance(res_data, dict):
            for action in res_data.get("actions", []):
                if action not in all_actions:
                    all_actions[action] = []
                all_actions[action].append(name)
    
    # Not flagging duplicates as they may be intentional
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def validate_all_configs(config_dir: Path) -> Dict[str, ValidationResult]:
    """Validate all permission YAML files in a directory."""
    results = {}
    
    for cloud in ["aws", "azure", "gcp"]:
        filepath = config_dir / f"{cloud}.yaml"
        if filepath.exists():
            results[cloud] = validate_yaml_schema(filepath, cloud)
        else:
            results[cloud] = ValidationResult(
                valid=False,
                errors=[f"Missing config file: {filepath}"],
                warnings=[]
            )
    
    return results


def validate_and_raise(config_dir: Path) -> None:
    """Validate all configs and raise if any are invalid."""
    results = validate_all_configs(config_dir)
    
    all_errors = []
    for cloud, result in results.items():
        for error in result.errors:
            all_errors.append(f"[{cloud}] {error}")
    
    if all_errors:
        raise SchemaValidationError(
            "Permission configuration validation failed:\n" +
            "\n".join(f"  - {e}" for e in all_errors)
        )

