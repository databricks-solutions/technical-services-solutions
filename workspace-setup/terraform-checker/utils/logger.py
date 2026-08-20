"""
Logging utility for Databricks Terraform Pre-Check.

Provides structured logging with support for file output and different log levels.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class PreCheckLogger:
    """Centralized logger for the pre-check tool."""
    
    _instance: Optional['PreCheckLogger'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if PreCheckLogger._initialized:
            return
            
        self.logger = logging.getLogger('databricks-precheck')
        self.logger.setLevel(logging.DEBUG)
        
        # Console handler (INFO and above by default)
        self.console_handler = logging.StreamHandler(sys.stdout)
        self.console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('%(message)s')
        self.console_handler.setFormatter(console_format)
        self.logger.addHandler(self.console_handler)
        
        # File handler (optional, DEBUG level)
        self.file_handler: Optional[logging.FileHandler] = None
        
        PreCheckLogger._initialized = True
    
    def set_level(self, level: str) -> None:
        """Set the console logging level."""
        level_map = {
            'debug': logging.DEBUG,
            'info': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR,
        }
        log_level = level_map.get(level.lower(), logging.INFO)
        self.console_handler.setLevel(log_level)
    
    def enable_file_logging(self, filepath: Optional[str] = None) -> str:
        """Enable logging to a file."""
        if filepath is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = f'precheck_{timestamp}.log'
        
        self.file_handler = logging.FileHandler(filepath)
        self.file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
        )
        self.file_handler.setFormatter(file_format)
        self.logger.addHandler(self.file_handler)
        
        return filepath
    
    def disable_file_logging(self) -> None:
        """Disable file logging."""
        if self.file_handler:
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()
            self.file_handler = None
    
    # Convenience methods
    def debug(self, msg: str, *args, **kwargs) -> None:
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs) -> None:
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs) -> None:
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs) -> None:
        self.logger.exception(msg, *args, **kwargs)
    
    # Styled output methods (for CLI)
    def success(self, msg: str) -> None:
        """Log a success message (green)."""
        self.info(f"✓ {msg}")
    
    def fail(self, msg: str) -> None:
        """Log a failure message (red)."""
        self.error(f"✗ {msg}")
    
    def step(self, msg: str) -> None:
        """Log a step/progress message."""
        self.info(f"▶ {msg}")
    
    def result(self, name: str, status: str, message: str = "") -> None:
        """Log a check result."""
        if message:
            self.info(f"  {name:<45} {status} - {message}")
        else:
            self.info(f"  {name:<45} {status}")


# Global logger instance
_logger: Optional[PreCheckLogger] = None


def get_logger() -> PreCheckLogger:
    """Get the global logger instance."""
    global _logger
    if _logger is None:
        _logger = PreCheckLogger()
    return _logger


def setup_logging(
    level: str = 'info',
    log_file: Optional[str] = None
) -> PreCheckLogger:
    """Setup logging with the specified configuration."""
    logger = get_logger()
    logger.set_level(level)
    
    if log_file:
        logger.enable_file_logging(log_file)
    
    return logger

