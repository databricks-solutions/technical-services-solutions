"""
Logging module for Migration Accelerator

This module provides centralized logging functionality with formatted output
to both stdout and a log file in the user's home directory.
"""

import logging
import sys
from datetime import datetime
from typing import Any, Optional

from migration_accelerator.utils.environment import get_log_directory


class MigrationAcceleratorFormatter(logging.Formatter):
    """Custom formatter that includes file name and function name"""

    def __init__(self) -> None:
        super().__init__()
        self.base_format = (
            "[%(asctime)s] [%(levelname)s] [%(filename)s:%(funcName)s] %(message)s"
        )
        self.date_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with custom format"""
        formatter = logging.Formatter(self.base_format, self.date_format)
        return formatter.format(record)


class MigrationAcceleratorLogger:
    """Main logger class for Migration Accelerator"""

    def __init__(self, log_level: int = logging.INFO, persist: bool = False) -> None:
        """
        Initialize the logger with specified log level.

        Args:
            log_level: The logging level (default: INFO)
            persist: Whether to persist logs to a file (default: False)
        """
        self.logger = logging.getLogger("migration_accelerator")
        self.logger.setLevel(log_level)

        # Avoid adding handlers multiple times
        if not self.logger.handlers:
            # Create formatters
            formatter = MigrationAcceleratorFormatter()

            # File handler (only if persist is True)
            if persist:
                # Create environment-appropriate log directory
                log_dir = get_log_directory()
                log_dir.mkdir(parents=True, exist_ok=True)

                # Create log file with date
                timestamp = datetime.now().strftime("%Y%m%d")
                log_file = log_dir / f"client_migration_accelerator_{timestamp}.log"

                file_handler = logging.FileHandler(log_file)
                file_handler.setLevel(log_level)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)

            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        """Get the configured logger instance"""
        return self.logger


# Global logger instance
_logger_instance: Optional[MigrationAcceleratorLogger] = None


def get_logger(persist: bool = False) -> logging.Logger:
    """
    Get or create a logger instance

    Args:
        persist: Whether to persist logs to a file (default: False)

    Returns:
        logging.Logger: Configured logger instance
    """
    global _logger_instance

    if _logger_instance is None:
        _logger_instance = MigrationAcceleratorLogger(persist=persist)

    return _logger_instance.get_logger()


def setup_logger(persist: bool = False) -> logging.Logger:
    """
    Setup and configure the logger

    Args:
        persist: Whether to persist logs to a file (default: False)

    Returns:
        logging.Logger: Configured logger instance
    """
    return get_logger(persist=persist)


# Convenience functions for common log levels
def info(message: str, *args: Any, **kwargs: Any) -> None:
    """Log info message"""
    get_logger().info(message, *args, **kwargs)  # type: ignore


def warning(message: str, *args: Any, **kwargs: Any) -> None:
    """Log warning message"""
    get_logger().warning(message, *args, **kwargs)  # type: ignore


def error(message: str, *args: Any, **kwargs: Any) -> None:
    """Log error message"""
    get_logger().error(message, *args, **kwargs)  # type: ignore


def debug(message: str, *args: Any, **kwargs: Any) -> None:
    """Log debug message"""
    get_logger().debug(message, *args, **kwargs)  # type: ignore


def critical(message: str, *args: Any, **kwargs: Any) -> None:
    """Log critical message"""
    get_logger().critical(message, *args, **kwargs)  # type: ignore
