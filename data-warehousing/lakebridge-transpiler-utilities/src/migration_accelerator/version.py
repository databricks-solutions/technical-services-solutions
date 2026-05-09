from pathlib import Path
from typing import Any, Dict


def _get_version() -> str:
    """
    Get version from installed package metadata or pyproject.toml fallback.
    """
    # Try to get version from installed package metadata
    try:
        from importlib.metadata import PackageNotFoundError, version

        return str(version("migration-accelerator"))
    except (PackageNotFoundError, ImportError):
        pass

    # Fallback: read version from pyproject.toml
    try:
        # Python 3.11+ built-in tomllib
        import tomllib  # type: ignore
    except ImportError:
        try:
            # Python 3.10 - use tomli
            import tomli as tomllib  # type: ignore
        except ImportError:
            # Final fallback if no TOML parser available
            return "0.1.0"

    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject_data: Dict[str, Any] = tomllib.load(f)
        version_value = pyproject_data.get("project", {}).get("version", "0.1.0")
        return str(version_value)
    except (FileNotFoundError, KeyError, Exception):
        return "0.1.0"
