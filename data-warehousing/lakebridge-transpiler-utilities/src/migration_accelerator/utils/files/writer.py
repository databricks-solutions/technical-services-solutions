"""
File writing utilities for Migration Accelerator

This module provides functions to write various file formats including
JSON, XML, YAML, configuration files, and environment files.
"""

import configparser
import json
import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Union

from migration_accelerator.utils.logger import get_logger

log = get_logger()


def write_json(
    data: Dict[str, Any],
    file_path: Union[str, Path],
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    """
    Write dictionary to JSON file.

    Args:
        data: Dictionary to write
        file_path: Path to the JSON file
        indent: Number of spaces for indentation
        ensure_ascii: If True, escape non-ASCII characters

    Raises:
        TypeError: If data is not JSON serializable
        OSError: If file cannot be written
    """
    path = Path(file_path)
    log.info(f"Writing JSON file: {path}")

    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=indent, ensure_ascii=ensure_ascii)
        log.info(f"Successfully wrote JSON file with {len(data)} keys")
    except TypeError as e:
        log.error(f"Data not JSON serializable: {e}")
        raise
    except Exception as e:
        log.error(f"Error writing JSON file {path}: {e}")
        raise


def write_xml(
    data: Dict[str, Any],
    file_path: Union[str, Path],
    root_name: str = "root",
    pretty_print: bool = True,
) -> None:
    """
    Write dictionary to XML file.

    Args:
        data: Dictionary to write
        file_path: Path to the XML file
        root_name: Name of the root XML element
        pretty_print: If True, format XML with proper indentation

    Raises:
        OSError: If file cannot be written
    """
    path = Path(file_path)
    log.info(f"Writing XML file: {path}")

    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        root = ET.Element(root_name)
        _dict_to_xml(data, root)

        if pretty_print:
            # Use minidom for pretty printing
            rough_string = ET.tostring(root, encoding="unicode")
            reparsed = xml.dom.minidom.parseString(rough_string)
            pretty_xml = reparsed.toprettyxml(indent="  ")
            # Remove empty lines
            pretty_lines = [line for line in pretty_xml.split("\n") if line.strip()]
            xml_content = "\n".join(pretty_lines)
        else:
            xml_content = ET.tostring(root, encoding="unicode")

        with path.open("w", encoding="utf-8") as file:
            file.write(xml_content)

        log.info(f"Successfully wrote XML file with root element: {root_name}")
    except Exception as e:
        log.error(f"Error writing XML file {path}: {e}")
        raise


def _dict_to_xml(data: Any, parent: ET.Element) -> None:
    """
    Convert dictionary to XML elements.

    Args:
        data: Data to convert
        parent: Parent XML element
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key.startswith("@"):
                # Handle attributes
                continue
            elif key == "#text":
                parent.text = str(value)
            else:
                child = ET.SubElement(parent, str(key))
                _dict_to_xml(value, child)
    elif isinstance(data, list):
        for item in data:
            child = ET.SubElement(parent, "item")
            _dict_to_xml(item, child)
    else:
        parent.text = str(data)


def write_yaml(
    data: Dict[str, Any], file_path: Union[str, Path], default_flow_style: bool = False
) -> None:
    """
    Write dictionary to YAML file.

    Args:
        data: Dictionary to write
        file_path: Path to the YAML file
        default_flow_style: If True, use flow style (compact) format

    Raises:
        ImportError: If PyYAML is not installed
        OSError: If file cannot be written
    """
    path = Path(file_path)
    log.info(f"Writing YAML file: {path}")

    try:
        import yaml  # type: ignore
    except ImportError:
        raise ImportError(
            "PyYAML is required to write YAML files. "
            "Install with: pip install PyYAML"
        )

    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(
                data,
                file,
                default_flow_style=default_flow_style,
                allow_unicode=True,
                indent=2,
            )
        log.info(f"Successfully wrote YAML file with {len(data)} keys")
    except Exception as e:
        log.error(f"Error writing YAML file {path}: {e}")
        raise


def write_config(
    data: Dict[str, Dict[str, Union[str, int, float, bool]]],
    file_path: Union[str, Path],
) -> None:
    """
    Write dictionary to configuration file (.cfg, .ini).

    Args:
        data: Dictionary with sections and key-value pairs
        file_path: Path to the configuration file

    Raises:
        OSError: If file cannot be written
        ValueError: If data structure is invalid for config format
    """
    path = Path(file_path)
    log.info(f"Writing config file: {path}")

    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        config = configparser.ConfigParser()

        for section_name, section_data in data.items():
            if not isinstance(section_data, dict):
                raise ValueError(f"Section '{section_name}' must be a dictionary")

            config.add_section(section_name)
            for key, value in section_data.items():
                config.set(section_name, key, str(value))

        with path.open("w", encoding="utf-8") as file:
            config.write(file)

        log.info(f"Successfully wrote config file with {len(data)} sections")
    except Exception as e:
        log.error(f"Error writing config file {path}: {e}")
        raise


def write_env(
    data: Dict[str, Union[str, int, float, bool]],
    file_path: Union[str, Path],
    quote_values: bool = True,
) -> None:
    """
    Write dictionary to environment file (.env).

    Args:
        data: Dictionary with environment variables
        file_path: Path to the environment file
        quote_values: If True, quote string values

    Raises:
        OSError: If file cannot be written
    """
    path = Path(file_path)
    log.info(f"Writing env file: {path}")

    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("w", encoding="utf-8") as file:
            file.write("# Environment variables\n")
            file.write("# Generated by Migration Accelerator\n\n")

            for key, value in data.items():
                # Convert value to string
                str_value = str(value)

                # Quote string values if requested
                if quote_values and isinstance(value, str):
                    if " " in str_value or '"' in str_value or "'" in str_value:
                        # Use single quotes to avoid escaping issues
                        str_value = "'" + str_value.replace("'", "''") + "'"

                file.write(f"{key}={str_value}\n")

        log.info(f"Successfully wrote env file with {len(data)} variables")
    except Exception as e:
        log.error(f"Error writing env file {path}: {e}")
        raise


def write_file_by_extension(
    data: Dict[str, Any], file_path: Union[str, Path], **kwargs: Any
) -> None:
    """
    Write data to file based on its extension.

    Args:
        data: Data to write
        file_path: Path to the file
        **kwargs: Additional arguments for specific file formats

    Raises:
        ValueError: If file extension is not supported
        OSError: If file cannot be written
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    log.info(f"Auto-detecting file type for: {path} (extension: {extension})")

    if extension == ".json":
        write_json(data, path, **kwargs)
    elif extension == ".xml":
        write_xml(data, path, **kwargs)
    elif extension in [".yaml", ".yml"]:
        write_yaml(data, path, **kwargs)
    elif extension in [".cfg", ".ini"]:
        write_config(data, path, **kwargs)  # type: ignore
    elif extension == ".env":
        write_env(data, path, **kwargs)  # type: ignore
    else:
        raise ValueError(f"Unsupported file extension: {extension}")


def backup_file(file_path: Union[str, Path], backup_suffix: str = ".bak") -> Path:
    """
    Create a backup of an existing file before writing.

    Args:
        file_path: Path to the file to backup
        backup_suffix: Suffix to add to backup file

    Returns:
        Path: Path to the backup file

    Raises:
        FileNotFoundError: If original file doesn't exist
        OSError: If backup cannot be created
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Cannot backup non-existent file: {path}")

    backup_path = path.with_suffix(path.suffix + backup_suffix)

    try:
        # Copy file content
        backup_path.write_bytes(path.read_bytes())
        log.info(f"Created backup: {backup_path}")
        return backup_path
    except Exception as e:
        log.error(f"Error creating backup {backup_path}: {e}")
        raise
