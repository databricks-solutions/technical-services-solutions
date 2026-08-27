"""Defines exceptions for Migration Accelerator"""


class MigrationAcceleratorException(Exception):
    """Base exception for Migration Accelerator"""

    pass


class MigrationAcceleratorConfigurationException(MigrationAcceleratorException):
    """Exception raised for configuration errors"""

    pass


class MigrationAcceleratorEnvironmentException(MigrationAcceleratorException):
    """Exception raised for environment errors"""

    pass


class MigrationAcceleratorToolException(MigrationAcceleratorException):
    """Exception raised for tool errors"""

    pass
