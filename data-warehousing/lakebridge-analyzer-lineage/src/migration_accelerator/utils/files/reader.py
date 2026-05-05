"""
File reading utilities for Migration Accelerator

This module provides functions to read various file formats including
JSON, XML, YAML, Excel, configuration files, and environment files.
"""

import configparser
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from migration_accelerator.utils.logger import get_logger

log = get_logger()


def read_json(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Read JSON file and return as dictionary.

    Args:
        file_path: Path to the JSON file

    Returns:
        Dict[str, Any]: Parsed JSON data

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    path = Path(file_path)
    log.info(f"Reading JSON file: {path}")

    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data: Dict[str, Any] = json.load(file)
            log.info(f"Successfully read JSON file with {len(data)} keys")
            return data
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in file {path}: {e}")
        raise
    except Exception as e:
        log.error(f"Error reading JSON file {path}: {e}")
        raise


def read_xml(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Read XML file and return as dictionary.

    Args:
        file_path: Path to the XML file

    Returns:
        Dict[str, Any]: Parsed XML data as dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        ET.ParseError: If file contains invalid XML
    """
    path = Path(file_path)
    log.info(f"Reading XML file: {path}")

    if not path.exists():
        raise FileNotFoundError(f"XML file not found: {path}")

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        data = _xml_to_dict(root)
        log.info(f"Successfully read XML file with root element: {root.tag}")
        return data
    except ET.ParseError as e:
        log.error(f"Invalid XML in file {path}: {e}")
        raise
    except Exception as e:
        log.error(f"Error reading XML file {path}: {e}")
        raise


def _xml_to_dict(element: ET.Element) -> Dict[str, Any]:
    """
    Convert XML element to dictionary.

    Args:
        element: XML element to convert

    Returns:
        Dict[str, Any]: Dictionary representation of XML element
    """
    result: Dict[str, Any] = {}

    # Add attributes
    if element.attrib:
        result["@attributes"] = element.attrib

    # Add text content
    if element.text and element.text.strip():
        if len(element) == 0:
            # Return a dictionary with the text content for leaf elements
            return {"#text": element.text.strip()}
        result["#text"] = element.text.strip()

    # Add child elements
    for child in element:
        child_data = _xml_to_dict(child)
        if child.tag in result:
            # Convert to list if multiple elements with same tag
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(child_data)
        else:
            result[child.tag] = child_data

    return result


def read_yaml(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Read YAML file and return as dictionary.

    Args:
        file_path: Path to the YAML file

    Returns:
        Dict[str, Any]: Parsed YAML data

    Raises:
        FileNotFoundError: If file doesn't exist
        ImportError: If PyYAML is not installed
        yaml.YAMLError: If file contains invalid YAML
    """
    path = Path(file_path)
    log.info(f"Reading YAML file: {path}")

    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    try:
        import yaml  # type: ignore
    except ImportError:
        raise ImportError(
            "PyYAML is required to read YAML files. " "Install with: pip install PyYAML"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            data: Dict[str, Any] = yaml.safe_load(file) or {}
            log.info(f"Successfully read YAML file with {len(data)} keys")
            return data
    except yaml.YAMLError as e:
        log.error(f"Invalid YAML in file {path}: {e}")
        raise
    except Exception as e:
        log.error(f"Error reading YAML file {path}: {e}")
        raise


def read_config(file_path: Union[str, Path]) -> Dict[str, Dict[str, str]]:
    """
    Read configuration file (.cfg, .ini) and return as dictionary.

    Args:
        file_path: Path to the configuration file

    Returns:
        Dict[str, Dict[str, str]]: Parsed configuration data

    Raises:
        FileNotFoundError: If file doesn't exist
        configparser.Error: If file contains invalid configuration
    """
    path = Path(file_path)
    log.info(f"Reading config file: {path}")

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        config = configparser.ConfigParser()
        config.read(str(path), encoding="utf-8")

        # Convert to dictionary
        data: Dict[str, Dict[str, str]] = {}
        for section_name in config.sections():
            data[section_name] = dict(config[section_name])

        log.info(f"Successfully read config file with {len(data)} sections")
        return data
    except configparser.Error as e:
        log.error(f"Invalid configuration in file {path}: {e}")
        raise
    except Exception as e:
        log.error(f"Error reading config file {path}: {e}")
        raise


def read_env(file_path: Union[str, Path]) -> Dict[str, str]:
    """
    Read environment file (.env) and return as dictionary.

    Args:
        file_path: Path to the environment file

    Returns:
        Dict[str, str]: Parsed environment variables

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    path = Path(file_path)
    log.info(f"Reading env file: {path}")

    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")

    try:
        env_vars: Dict[str, str] = {}

        with path.open("r", encoding="utf-8") as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Parse KEY=VALUE format
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]

                    env_vars[key] = value
                else:
                    log.warning(
                        f"Invalid line format in {path} at line {line_num}: " f"{line}"
                    )

        log.info(f"Successfully read env file with {len(env_vars)} variables")
        return env_vars
    except Exception as e:
        log.error(f"Error reading env file {path}: {e}")
        raise


def read_excel(
    file_path: Union[str, Path], sheet_names: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Read Excel file and return all sheets or specified sheets as pandas DataFrames.

    Args:
        file_path: Path to the Excel file (.xlsx, .xls)
        sheet_names: Optional list of specific sheet names to parse.
                    If None or empty, all sheets will be parsed.

    Returns:
        Dict[str, Any]: Dictionary where keys are sheet names and
                       values are corresponding pandas DataFrames

    Raises:
        FileNotFoundError: If file doesn't exist
        ImportError: If pandas or openpyxl/xlrd is not installed
        ValueError: If specified sheet names don't exist in the Excel file
    """
    path = Path(file_path)
    log.info(f"Reading Excel file: {path}")

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    try:
        import pandas as pd  # type: ignore
    except ImportError:
        raise ImportError(
            "pandas is required to read Excel files. "
            "Install with: pip install pandas openpyxl"
        )

    if sheet_names is None:
        sheet_names = []

    try:
        # First, get all available sheet names
        with pd.ExcelFile(str(path)) as xls:
            available_sheets = xls.sheet_names
            log.info(f"Found {len(available_sheets)} sheets: {available_sheets}")

            # Determine which sheets to read
            if not sheet_names:
                # Read all sheets if no specific sheets requested
                sheets_to_read = available_sheets
                log.info("Reading all sheets")
            else:
                # Validate requested sheet names exist
                missing_sheets = [
                    name for name in sheet_names if name not in available_sheets
                ]
                if missing_sheets:
                    raise ValueError(
                        f"Sheet(s) not found in Excel file: {missing_sheets}. "
                        f"Available sheets: {available_sheets}"
                    )
                sheets_to_read = sheet_names
                log.info(f"Reading specific sheets: {sheets_to_read}")

            # Read the specified sheets
            result: Dict[str, Any] = {}
            for sheet_name in sheets_to_read:
                try:
                    df = pd.read_excel(str(path), sheet_name=sheet_name)
                    result[sheet_name] = df
                    log.info(
                        f"Successfully read sheet '{sheet_name}' with shape {df.shape}"
                    )
                except Exception as e:
                    log.error(f"Error reading sheet '{sheet_name}': {e}")
                    raise

            log.info(f"Successfully read Excel file with {len(result)} sheets")
            return result

    except ImportError:
        raise ImportError(
            "Additional dependencies are required to read Excel files. "
            "Install with: pip install pandas openpyxl xlrd"
        )
    except Exception as e:
        log.error(f"Error reading Excel file {path}: {e}")
        raise


def read_file_by_extension(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Read file based on its extension and return as dictionary.

    Args:
        file_path: Path to the file

    Returns:
        Dict[str, Any]: Parsed file data

    Raises:
        ValueError: If file extension is not supported
        FileNotFoundError: If file doesn't exist
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    log.info(f"Auto-detecting file type for: {path} (extension: {extension})")

    if extension == ".json":
        return read_json(path)
    elif extension == ".xml":
        return read_xml(path)
    elif extension in [".yaml", ".yml"]:
        return read_yaml(path)
    elif extension in [".cfg", ".ini"]:
        return read_config(path)
    elif extension == ".env":
        return read_env(path)  # type: ignore
    elif extension in [".xlsx", ".xls"]:
        return read_excel(path)
    else:
        raise ValueError(f"Unsupported file extension: {extension}")
