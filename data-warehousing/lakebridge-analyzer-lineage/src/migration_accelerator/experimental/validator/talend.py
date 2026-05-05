# flake8: noqa: E501
"""Talend-specific validator implementation."""

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import dspy

from migration_accelerator.experimental.validator.base import (
    BaseValidator,
    ValidationResult,
)
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class ValidationFeedback(dspy.Signature):
    """As a Critic, you are given a validation result and you need to generate a feedback message
    knowing that this feedback will be used to fix the validation errors on the target code.

    if the feedback contains errors, you also need to reflect on those errors and suggest fix for them.

    You also will be provided with the source code metadata and the target code str, you need
    to provide a similarity_score after assesing the ETL flow of both source and target.

    if you think you have a feedback on why the conversion is not correct or why there's lack of
    similarity in source and target flow, you also need to provide a feedback on that.

    while assessing the target_code, check if any of the talend components have been
    initialiazed more than once. if so, you need to provide a feedback to fix that.

    use key value to provide the feedbacks.

    ** CRITICAL **
    - Make sure you provide feedback on validation (syntax, compilation) errors and warnings if any.
    - Focus more on understanding the lineage of the source and target code. and provide
    details incase you see that there's discrepenacies in the flow of target.
    - Don't provide feedback on adding more exception handling or logging, or something that's not necessary for
    the successful execution of the target code.
    - if the logic of source is already implemented correctly, then leave it as it is.
    - if custom_instructions is present know that it was to convert the target code,
    so don't be surprised if you see there are some changes in the intent of the target code
    while calculating the similarity score.
    """

    source_metadata: Dict[str, Any] = dspy.InputField(
        desc="The source code metadata to assess the ETL flow of the source code."
    )
    target_code: str = dspy.InputField(
        desc="The target code to assess the ETL flow of the target code."
    )
    verification_result: Dict[str, Any] = dspy.InputField(
        desc="The verification result that contains the syntax check and dry run details."
    )
    custom_instructions: str = dspy.InputField(
        desc="Custom instructions override from users that was used to convert the target code.",
        default="",
    )
    feedback: Dict[str, str] = dspy.OutputField(
        desc="The feedback message generated for the validation result."
    )
    similarity_score: float = dspy.OutputField(
        desc="The similarity score generated for the source and target code. between 0 and 1, 1 being the best."
    )


class TalendValidator(BaseValidator):
    """Validator for Talend job conversions to PySpark.

    This validator handles:
    - Talend JSON job definitions (source)
    - Python/PySpark code (target)

    It performs validation through:
    1. Verification: Check Python syntax, imports, and basic structure
    2. Reflection: Analyze semantic equivalence and logic preservation
    3. Critique: Generate scores and detailed feedback
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
        """Initialize Talend validator.

        Args:
            source: Path to Talend JSON file or JSON string
            target: Path to Python file or Python code string
            source_content: Direct Talend JSON content
            target_content: Direct Python code content
            custom_instructions: Custom instructions override from users
            **kwargs: Additional configuration (e.g., strict_mode, check_best_practices)
        """
        super().__init__(
            source,
            target,
            source_content,
            target_content,
            custom_instructions,
            **kwargs,
        )
        self.strict_mode = kwargs.get("strict_mode", False)
        self.check_best_practices = kwargs.get("check_best_practices", True)
        self._talend_metadata: Optional[Dict[str, Any]] = None

    def get_source_content(self) -> str:
        """Get Talend JSON content.

        Overrides base method to handle Talend-specific JSON reading.
        Validates that the content is valid JSON.

        Returns:
            Talend JSON as string

        Raises:
            ValueError: If content is not valid JSON
        """
        content = super().get_source_content()

        # Validate that it's valid JSON
        try:
            parsed = json.loads(content)
            self._talend_metadata = parsed
            log.info(f"Successfully parsed Talend JSON with {len(parsed)} root keys")
            return content
        except json.JSONDecodeError as e:
            error_msg = f"Invalid Talend JSON: {str(e)}"
            log.error(error_msg)
            raise ValueError(error_msg)

    def get_target_content(self) -> str:
        """Get Python/PySpark target code.

        Overrides base method to handle Python file reading.

        Returns:
            Python code as string
        """
        return super().get_target_content()

    def _parse_talend_components(self) -> Dict[str, Any]:
        """Parse Talend job components and extract metadata.

        Returns:
            Dictionary with component information
        """
        if self._talend_metadata is None:
            self.get_source_content()  # Ensure metadata is loaded

        components = {}

        if self._talend_metadata:
            # Extract nodes/components
            components = copy.deepcopy(self._talend_metadata.get("content", {}))
            nodes = list(components["node"].keys())
            components["node"] = nodes
            log.info(f"Detected {len(nodes)} Talend components")

        return components

    # def _verify_python_syntax(self, code: str) -> Dict[str, Any]:
    #     """Verify Python syntax correctness.

    #     Args:
    #         code: Python code to verify

    #     Returns:
    #         Dictionary with syntax verification results
    #     """
    #     result = {
    #         'syntax_valid': False,
    #         'errors': [],
    #         'warnings': [],
    #         'ast_nodes': 0,
    #         'functions': [],
    #         'classes': [],
    #         'imports': [],
    #     }

    #     try:
    #         # Parse the Python code
    #         tree = ast.parse(code)
    #         result['syntax_valid'] = True
    #         result['ast_nodes'] = len(list(ast.walk(tree)))

    #         # Extract functions, classes, and imports
    #         for node in ast.walk(tree):
    #             if isinstance(node, ast.FunctionDef):
    #                 result['functions'].append(node.name)
    #             elif isinstance(node, ast.ClassDef):
    #                 result['classes'].append(node.name)
    #             elif isinstance(node, ast.Import):
    #                 for alias in node.names:
    #                     result['imports'].append(alias.name)
    #             elif isinstance(node, ast.ImportFrom):
    #                 module = node.module or ''
    #                 for alias in node.names:
    #                     result['imports'].append(f"{module}.{alias.name}")

    #         log.info(f"Python syntax valid: {len(result['functions'])} functions, "
    #                 f"{len(result['classes'])} classes, {len(result['imports'])} imports")

    #     except SyntaxError as e:
    #         result['syntax_valid'] = False
    #         result['errors'].append(f"Syntax error at line {e.lineno}: {e.msg}")
    #         log.error(f"Python syntax error: {e}")
    #     except Exception as e:
    #         result['syntax_valid'] = False
    #         result['errors'].append(f"Parsing error: {str(e)}")
    #         log.error(f"Python parsing error: {e}")

    #     return result

    def _verify(self) -> Dict[str, Any]:
        """Verify the correctness of the Talend to PySpark conversion.

        Checks:
        - Python syntax validity
        - PySpark API usage
        - Basic structural elements

        Returns:
            Dictionary containing verification results
        """
        log.info("Starting verification step")

        result = {
            "target_valid": False,
            "target_metadata": {},
            "errors": [],
            "warnings": [],
        }

        try:
            # Verify target (Python/PySpark)
            target_content = self.get_target_content()
            syntax_check = self._verify_python_syntax(target_content)
            # TODO Syntax check for identifying compilation errors : spark dry run
            pyspark_check = self._dry_run_spark()

            syntax_valid = (
                syntax_check["syntax_valid"]
                and len(syntax_check["errors"]) == 0
                and syntax_check["cells_analyzed"] > 1
            )

            log.info(f"Syntax valid: {syntax_valid}")

            if not syntax_valid:
                result["errors"].extend(syntax_check["errors"])
                result["warnings"].extend(syntax_check["warnings"])

            spark_valid = (
                pyspark_check["compilation_flag"]
                and len(pyspark_check["errors"]) == 0
                and len(pyspark_check["warnings"]) == 0
            )

            log.info(f"Spark valid: {spark_valid}")

            if not spark_valid:
                result["errors"].extend(pyspark_check["errors"])
                result["warnings"].extend(pyspark_check["warnings"])

            result["target_valid"] = syntax_valid and spark_valid
            result["target_metadata"] = {
                k: v
                for k, v in syntax_check.items()
                if k in ["functions", "classes", "imports"]
            }

        except Exception as e:
            result["errors"].append(f"Target verification failed: {str(e)}")
            log.error(f"Target verification error: {e}")

        log.info(f"Verification complete: target_valid={result['target_valid']}")
        return result

    def _reflect_and_critique(
        self,
        verification_result: Dict[str, Any],
    ) -> ValidationResult:
        """Reflect on the conversion quality and generate final critique scores."""
        log.info("Starting critique step")

        compilation_flag = verification_result["target_valid"]
        errors = verification_result.get("errors", [])
        warnings = verification_result.get("warnings", [])

        source_metadata = self._parse_talend_components()
        target_code = self.get_target_content()

        feedback = {
            "file_formatting": """Make sure the %md placements are such that it only covers the text cells and
            not accidentally covers the code cells. verify if the cell splitting is done correctly
            using # COMMAND ---------- as the delimiter.""",
            "imports": """Make sure there are no duplicate imports. If needed
            consolidate all the imports into a single import statement and add them in the beginning of the file.""",
        }

        critique = dspy.ChainOfThought(ValidationFeedback)

        critique_result = critique(
            source_metadata=source_metadata,
            target_code=target_code,
            verification_result=verification_result,
            custom_instructions=self.custom_instructions,
        )

        similarity_score = critique_result.similarity_score
        critique_feedback = critique_result.feedback

        total_feedback = {
            **feedback,
            **critique_feedback,
        }

        log.info(
            f"Critique complete: compilation_flag={compilation_flag}, "
            f"similarity_score={similarity_score:.2f}"
        )

        return ValidationResult(
            compilation_flag=compilation_flag,
            similarity_score=round(similarity_score, 2),
            errors=errors,
            warnings=warnings,
            feedback=total_feedback,
        )
