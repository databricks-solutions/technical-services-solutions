# flake8: noqa: E501
"""Base Validator Class for all validators."""

import ast
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import dspy

from migration_accelerator.configs import get_config
from migration_accelerator.core.llms import LLMManager
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class ValidationResult:
    """Container for validation results."""

    def __init__(
        self,
        compilation_flag: bool,
        similarity_score: float,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        feedback: Optional[Dict[str, Any]] = None,
    ):
        """Initialize validation result.

        Args:
            compilation_flag: Flag indicating compilation/syntax correctness
            similarity_score: Score indicating semantic similarity (0-1)
            errors: List of error messages
            warnings: List of warning messages
            feedback: Feedback from the validation step
        """
        self.compilation_flag = compilation_flag
        self.similarity_score = similarity_score
        self.errors = errors or []
        self.warnings = warnings or []
        self.feedback = feedback or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "compilation_flag": self.compilation_flag,
            "similarity_score": self.similarity_score,
            "errors": self.errors,
            "warnings": self.warnings,
            "feedback": self.feedback,
        }

    def __repr__(self) -> str:
        return (
            f"ValidationResult(compilation_flag={self.compilation_flag}, "
            f"similarity_score={self.similarity_score}, "
            f"errors={len(self.errors)}, warnings={len(self.warnings)})"
        )


class BaseValidator(ABC):
    """Base Validator Class for all validators.

    This class provides a framework for validating conversions from source code
    to target code. It is dialect-agnostic and can be extended for specific
    conversion types (e.g., Talend to PySpark, SQL to SQL, etc.).

    The validation process consists of three main steps:
    1. _verify: Verify the correctness of the conversion
    2. _reflect_and_critique: Reflect on the conversion quality and generate final critique scores.

    Attributes:
        source_path: Path to source code file
        target_path: Path to target/converted code file
        source_content: String content of source code (if provided directly)
        target_content: String content of target code (if provided directly)
    """

    def __init__(
        self,
        source: Optional[Union[str, Path]] = None,
        target: Optional[Union[str, Path]] = None,
        source_content: Optional[str] = None,
        target_content: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        **kwargs,
    ):
        """Initialize the validator.

        Args:
            source: Path to source code file or string content
            target: Path to target code file or string content
            source_content: Direct string content of source code
            target_content: Direct string content of target code
            custom_instructions: Custom instructions override from users
            **kwargs: Additional configuration parameters
        """
        self.source_path: Optional[Path] = None
        self.target_path: Optional[Path] = None
        self._source_content: Optional[str] = source_content
        self._target_content: Optional[str] = target_content
        self.custom_instructions: Optional[str] = custom_instructions
        self.config = kwargs

        # Determine if source/target are paths or content
        if source is not None:
            source_path = Path(source) if not isinstance(source, Path) else source
            if source_path.exists():
                self.source_path = source_path
            else:
                # Treat as content string
                self._source_content = str(source)

        if target is not None:
            target_path = Path(target) if not isinstance(target, Path) else target
            if target_path.exists():
                self.target_path = target_path
            else:
                # Treat as content string
                self._target_content = str(target)

        # Initialize the LLM manager
        self.llm_manager = LLMManager(get_config("LLMConfig"))
        self.lm = self.llm_manager.get_dspy_llm()

        dspy.configure(lm=self.lm)

        log.info(f"Initialized {self.__class__.__name__}")

    def get_source_content(self) -> str:
        """Get source code content.

        This method can be overridden in subclasses to implement
        dialect-specific reading logic (e.g., parsing JSON, XML, etc.).

        Returns:
            Source code as string

        Raises:
            ValueError: If neither source path nor content is provided
        """
        if self._source_content is not None:
            return self._source_content

        if self.source_path is not None and self.source_path.exists():
            log.info(f"Reading source content from {self.source_path}")
            with open(self.source_path, "r", encoding="utf-8") as f:
                self._source_content = f.read()
            return self._source_content

        raise ValueError("No source content or valid source path provided")

    def get_target_content(self) -> str:
        """Get target/converted code content.

        This method can be overridden in subclasses to implement
        dialect-specific reading logic.

        Returns:
            Target code as string

        Raises:
            ValueError: If neither target path nor content is provided
        """
        if self._target_content is not None:
            return self._target_content

        if self.target_path is not None and self.target_path.exists():
            log.info(f"Reading target content from {self.target_path}")
            with open(self.target_path, "r", encoding="utf-8") as f:
                self._target_content = f.read()
            return self._target_content

        raise ValueError("No target content or valid target path provided")

    def _verify_python_syntax(self, code: str) -> Dict[str, Any]:
        """Enhanced Python syntax verification with Databricks notebook support.

        Handles:
        - Standard Python syntax errors with accurate line numbers
        - Databricks magic commands (%md, %sql, etc.)
        - Cell-based error reporting
        """
        result = {
            "syntax_valid": False,
            "errors": [],
            "warnings": [],
            "ast_nodes": 0,
            "functions": [],
            "classes": [],
            "imports": [],
            "cells_analyzed": 0,
        }

        # Split into cells based on magic commands
        cells = self._split_into_cells(code)

        all_syntax_valid = True

        for cell_idx, cell_info in enumerate(cells):
            cell_code = cell_info["code"]
            cell_type = cell_info["type"]
            cell_start_line = cell_info["start_line"]

            # Only validate Python cells
            if cell_type != "python":
                continue

            result["cells_analyzed"] += 1

            try:
                # Parse the Python code
                tree = ast.parse(cell_code)
                result["ast_nodes"] += len(list(ast.walk(tree)))

                # Extract metadata
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        result["functions"].append(
                            {
                                "name": node.name,
                                "line": node.lineno + cell_start_line - 1,
                            }
                        )
                    elif isinstance(node, ast.ClassDef):
                        result["classes"].append(
                            {
                                "name": node.name,
                                "line": node.lineno + cell_start_line - 1,
                            }
                        )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            result["imports"].append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        for alias in node.names:
                            result["imports"].append(f"{module}.{alias.name}")

            except SyntaxError as e:
                all_syntax_valid = False
                # Adjust line number to account for cell position in full file
                actual_line = (e.lineno or 0) + cell_start_line - 1

                error_detail = {
                    "type": "SyntaxError",
                    "line": actual_line,  # Actual line in the full file
                    "cell": cell_idx + 1,
                    "cell_line": e.lineno,  # Line within the cell
                    "offset": e.offset,
                    "message": e.msg,
                    "text": e.text.strip() if e.text else None,
                    "context": self._get_error_context(code, actual_line),
                }
                result["errors"].append(error_detail)
                log.error(
                    f"Syntax error at line {actual_line} (cell {cell_idx + 1}): {e.msg}"
                )

            except Exception as e:
                all_syntax_valid = False
                result["errors"].append(
                    {"type": type(e).__name__, "message": str(e), "cell": cell_idx + 1}
                )
                log.error(f"Parsing error in cell {cell_idx + 1}: {e}")

        result["syntax_valid"] = all_syntax_valid and len(result["errors"]) == 0

        log.info(
            f"Python syntax check: valid={result['syntax_valid']}, "
            f"{result['cells_analyzed']} cells analyzed, "
            f"{len(result['functions'])} functions, "
            f"{len(result['errors'])} errors"
        )

        return result

    def _split_into_cells(self, code: str) -> list:
        """Split Databricks notebook code into cells.

        Handles Databricks Python notebook format (.py) where:
        - Cells are delimited by '# COMMAND ----------'
        - Magic commands are prefixed with '# MAGIC' (e.g., '# MAGIC %md')
        - Default cell type is 'python' unless magic command specifies otherwise
        - Cell content is kept as-is (no modification)

        Returns list of dicts with:
        - type: 'python', 'markdown', 'sql', etc.
        - code: the cell content (as-is, no modifications)
        - start_line: line number where cell starts (1-indexed)
        """
        cells = []
        lines = code.split("\n")

        # Cell delimiter for Databricks Python notebooks
        cell_delimiter = "# COMMAND ----------"

        # Magic commands mapping
        magic_commands = {
            "%md": "markdown",
            "%sql": "sql",
            "%python": "python",
            "%scala": "scala",
            "%r": "r",
            "%sh": "shell",
        }

        # Split code into cells by delimiter
        current_cell_lines = []
        current_start_line = 1

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # Check if this is a cell delimiter
            if stripped == cell_delimiter:
                # Save previous cell if it has content
                if current_cell_lines:
                    # Determine cell type by checking first non-empty line
                    cell_type = "python"  # Default
                    first_line_found = False
                    actual_start_line = current_start_line

                    for idx, cell_line in enumerate(current_cell_lines):
                        stripped_cell = cell_line.strip()
                        # Skip empty lines and notebook header
                        if (
                            not stripped_cell
                            or stripped_cell == "# Databricks notebook source"
                        ):
                            continue

                        if not first_line_found:
                            actual_start_line = current_start_line + idx
                            first_line_found = True

                            # Check for '# MAGIC %<command>' pattern
                            if stripped_cell.startswith("# MAGIC "):
                                magic_part = stripped_cell[
                                    8:
                                ].strip()  # Remove '# MAGIC '

                                # Find matching magic command
                                for magic, ctype in magic_commands.items():
                                    if magic_part.startswith(magic):
                                        cell_type = ctype
                                        break
                            break

                    # Only add cell if it has content
                    if first_line_found:
                        cells.append(
                            {
                                "type": cell_type,
                                "code": "\n".join(current_cell_lines),
                                "start_line": actual_start_line,
                            }
                        )

                # Start new cell
                current_cell_lines = []
                current_start_line = line_num + 1
            else:
                current_cell_lines.append(line)

        # Don't forget the last cell
        if current_cell_lines:
            cell_type = "python"  # Default
            first_line_found = False
            actual_start_line = current_start_line

            for idx, cell_line in enumerate(current_cell_lines):
                stripped_cell = cell_line.strip()
                # Skip empty lines and notebook header
                if not stripped_cell or stripped_cell == "# Databricks notebook source":
                    continue

                if not first_line_found:
                    actual_start_line = current_start_line + idx
                    first_line_found = True

                    # Check for '# MAGIC %<command>' pattern
                    if stripped_cell.startswith("# MAGIC "):
                        magic_part = stripped_cell[8:].strip()

                        # Find matching magic command
                        for magic, ctype in magic_commands.items():
                            if magic_part.startswith(magic):
                                cell_type = ctype
                                break
                    break

            if first_line_found:
                cells.append(
                    {
                        "type": cell_type,
                        "code": "\n".join(current_cell_lines),
                        "start_line": actual_start_line,
                    }
                )

        log.info(f"Split code into {len(cells)} cells")
        return cells

    def _get_error_context(
        self, code: str, error_line: int, context_lines: int = 2
    ) -> str:
        """Get surrounding lines for better error context.

        Args:
            code: Full code string
            error_line: Line number with error (1-indexed)
            context_lines: Number of lines before/after to include

        Returns:
            Formatted string with line numbers and code
        """
        lines = code.split("\n")
        start = max(0, error_line - context_lines - 1)
        end = min(len(lines), error_line + context_lines)

        context = []
        for i in range(start, end):
            marker = "→ " if i == error_line - 1 else "  "
            context.append(f"{marker}{i + 1:4d} | {lines[i]}")

        return "\n".join(context)

    def _dry_run_spark(self) -> Dict[str, Any]:
        """Dry run the Spark code to check for compilation errors."""
        # TODO: Implement this method
        return {
            "compilation_flag": True,
            "errors": [],
            "warnings": [],
        }

    @abstractmethod
    def _verify(self) -> Dict[str, Any]:
        """Verify the correctness of the conversion.

        This method should check:
        - Syntax correctness of target code
        - Structural integrity
        - Basic compilation/parsing checks

        Returns:
            Dictionary containing verification results
        """
        pass

    @abstractmethod
    def _reflect_and_critique(
        self,
        verification_result: Dict[str, Any],
    ) -> ValidationResult:
        """Reflect on the conversion quality and generate final critique scores.

        This method should produce:
        - compilation_score: Score for syntax/compilation correctness (0-1)
        - similarity_score: Score for semantic similarity (0-1)
        - Detailed critique and recommendations

        Args:
            verification_result: Results from _verify step

        Returns:
            ValidationResult object with scores and details
        """
        pass

    def validate(self) -> ValidationResult:
        """Run the complete validation pipeline.

        This method orchestrates the validation process by calling:
        1. _verify() to check correctness
        2. _reflect_and_critique() to analyze quality and generate final scores

        Returns:
            ValidationResult with compilation_flag, similarity_score, and details
        """
        log.info(f"Starting validation process with {self.__class__.__name__}")
        try:
            verification_result = self._verify()
            reflection_result = self._reflect_and_critique(verification_result)
            return reflection_result
        except Exception as e:
            return ValidationResult(
                compilation_flag=False,
                similarity_score=0.0,
                errors=[f"Validation failed: {str(e)}"],
                warnings=[],
                feedback={},
            )
