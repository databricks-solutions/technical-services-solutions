"""Base classes for cloud checkers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import logging


logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a check result."""
    OK = "OK"
    WARNING = "WARNING"
    NOT_OK = "NOT OK"
    SKIPPED = "SKIPPED"


@dataclass
class CheckResult:
    """Result of a single check."""
    name: str
    status: CheckStatus
    message: Optional[str] = None
    details: Optional[str] = None
    remediation: Optional[str] = None  # How to fix the issue
    doc_link: Optional[str] = None  # Link to documentation
    
    def __str__(self) -> str:
        result = f"{self.name}: {self.status.value}"
        if self.message:
            result += f" - {self.message}"
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "remediation": self.remediation,
            "doc_link": self.doc_link,
        }


@dataclass
class CheckCategory:
    """A category of checks with results."""
    name: str
    results: List[CheckResult] = field(default_factory=list)
    
    def add_result(self, result: CheckResult) -> None:
        """Add a check result to this category."""
        self.results.append(result)
        logger.debug(
            "Check result: %s - %s - %s",
            result.name, result.status.value, result.message
        )
    
    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.OK)
    
    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.WARNING)
    
    @property
    def not_ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.NOT_OK)
    
    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.SKIPPED)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "results": [r.to_dict() for r in self.results],
            "summary": {
                "ok": self.ok_count,
                "warning": self.warning_count,
                "not_ok": self.not_ok_count,
                "skipped": self.skipped_count,
            }
        }


@dataclass
class CheckReport:
    """Complete check report for a cloud provider."""
    cloud: str
    region: str
    categories: List[CheckCategory] = field(default_factory=list)
    account_info: Optional[str] = None
    subscription_id: Optional[str] = None  # Azure
    project_id: Optional[str] = None  # GCP
    
    def add_category(self, category: CheckCategory) -> None:
        """Add a category to the report."""
        self.categories.append(category)
        logger.info(
            "Category '%s' completed: %d OK, %d WARNING, %d NOT OK",
            category.name, category.ok_count, 
            category.warning_count, category.not_ok_count
        )
    
    @property
    def total_ok(self) -> int:
        return sum(c.ok_count for c in self.categories)
    
    @property
    def total_warning(self) -> int:
        return sum(c.warning_count for c in self.categories)
    
    @property
    def total_not_ok(self) -> int:
        return sum(c.not_ok_count for c in self.categories)
    
    @property
    def total_skipped(self) -> int:
        return sum(c.skipped_count for c in self.categories)
    
    @property
    def passed(self) -> bool:
        """Returns True if no critical failures."""
        return self.total_not_ok == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "cloud": self.cloud,
            "region": self.region,
            "account_info": self.account_info,
            "subscription_id": self.subscription_id,
            "project_id": self.project_id,
            "categories": [c.to_dict() for c in self.categories],
            "summary": {
                "total_ok": self.total_ok,
                "total_warning": self.total_warning,
                "total_not_ok": self.total_not_ok,
                "total_skipped": self.total_skipped,
                "passed": self.passed,
            }
        }


class BaseChecker(ABC):
    """Base class for cloud checkers."""
    
    def __init__(self, region: Optional[str] = None) -> None:
        self.region = region
        self._report: Optional[CheckReport] = None
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @property
    @abstractmethod
    def cloud_name(self) -> str:
        """Return the name of the cloud provider."""
        pass
    
    @abstractmethod
    def check_credentials(self) -> CheckCategory:
        """Check if credentials are valid."""
        pass
    
    @abstractmethod
    def run_all_checks(self) -> CheckReport:
        """Run all checks and return a complete report."""
        pass
    
    def log_info(self, msg: str, *args: Any) -> None:
        """Log an info message with context."""
        self._logger.info(f"[{self.cloud_name}] {msg}", *args)
    
    def log_debug(self, msg: str, *args: Any) -> None:
        """Log a debug message with context."""
        self._logger.debug(f"[{self.cloud_name}] {msg}", *args)
    
    def log_error(self, msg: str, *args: Any) -> None:
        """Log an error message with context."""
        self._logger.error(f"[{self.cloud_name}] {msg}", *args)
