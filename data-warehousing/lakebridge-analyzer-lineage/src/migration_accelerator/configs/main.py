from typing import Any, Dict

from migration_accelerator.configs.modules import CONFIG_REGISTRY
from migration_accelerator.exceptions import MigrationAcceleratorConfigurationException
from migration_accelerator.utils.environment import get_config_directory
from migration_accelerator.utils.files import read_json, write_json
from migration_accelerator.utils.logger import get_logger

log = get_logger()


def get_config(config_name: str) -> Any:
    """
    Get the said configuration for the migration accelerator.
    """
    config_dir = get_config_directory()

    log.info(f"Getting configuration: {config_name}")
    if config_name not in CONFIG_REGISTRY:
        raise MigrationAcceleratorConfigurationException(
            f"Configuration {config_name} not found"
        )

    try:
        config_class = CONFIG_REGISTRY[config_name]
        config_file_name = config_class.__name__.lower() + ".json"
        config_file_path = config_dir / config_file_name
        config_dict = read_json(config_file_path)
        log.info(f"Successfully read configuration: {config_name}")
        return config_class.from_dict(config_dict)
    except Exception as e:
        log.error(f"Error reading configuration {config_name}: {e}")
        raise MigrationAcceleratorConfigurationException(
            f"Error reading configuration {config_name}"
        ) from e


def set_config(config_name: str, kwargs: Dict[str, Any]) -> Any:
    """
    Sets the said configuration for the migration accelerator and returns the
    instance of the configuration.
    """
    log.info(f"Setting configuration: {config_name}")
    if config_name not in CONFIG_REGISTRY:
        raise MigrationAcceleratorConfigurationException(
            f"Configuration {config_name} not found"
        )

    try:
        config_class = CONFIG_REGISTRY[config_name]
        config_instance = config_class.from_dict(kwargs)
        config_dict = config_instance.to_dict()
        config_file_name = config_class.__name__.lower() + ".json"
        config_dir = get_config_directory()
        config_file_path = config_dir / config_file_name
        write_json(config_dict, config_file_path)
        log.info(f"Successfully set configuration: {config_name} to {config_file_path}")
        return config_instance
    except Exception as e:
        log.error(f"Error setting configuration {config_name}: {e}")
        raise MigrationAcceleratorConfigurationException(
            f"Error setting configuration {config_name}"
        ) from e
