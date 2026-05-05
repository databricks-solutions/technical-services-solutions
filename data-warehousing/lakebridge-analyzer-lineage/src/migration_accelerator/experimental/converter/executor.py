# flake8: noqa: E501
"""Main Entrypoint for converting ETL jobs to different formats.

This module provides the Executor class that orchestrates the entire migration
pipeline including parsing, intent generation, conversion, and validation.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from migration_accelerator.configs import get_config, set_config
from migration_accelerator.configs.modules import SourceCodeConfig
from migration_accelerator.discovery.parser import SourceCodeParser
from migration_accelerator.settings import SUPPORTED_DIALECTS
from migration_accelerator.utils.environment import (
    get_migration_accelerator_base_directory,
)
from migration_accelerator.utils.files import write_json
from migration_accelerator.utils.logger import get_logger

log = get_logger()


# Dialect-specific file extensions mapping
DIALECT_EXTENSIONS = SUPPORTED_DIALECTS


class ExecutorConfig:
    """Configuration for the Executor.

    This class manages configuration by using the set_config/get_config pattern
    to ensure configurations are persisted and retrievable.
    """

    def __init__(
        self,
        source_config: Dict[str, Any],
        llm_config: Optional[Dict[str, Any]] = None,
        parser_prompt_config: Optional[Dict[str, Any]] = None,
        converter_prompt_config: Optional[Dict[str, Any]] = None,
        target_config: Optional[Dict[str, Any]] = None,
        use_ai: bool = False,
        max_concurrent_requests: int = 5,
        parser_output_dir: Optional[Union[str, Path]] = None,
        is_directory: bool = False,
        recursive: bool = True,
        keys_to_remove: int = 16,
        validation_enabled: bool = False,
        validation_iterations: int = 2,
        conversion_session_id: Optional[str] = None,
        max_react_iters: int = 10,
        conversion_max_iters: int = 20,
    ):
        """Initialize executor configuration.

        Args:
            source_config: Source code configuration as dict
            llm_config: LLM configuration as dict (optional)
            parser_prompt_config: Parser prompt configuration as dict (optional)
            converter_prompt_config: Converter prompt configuration with custom instructions (optional)
            target_config: Target code configuration as dict with target_file_path (optional)
            use_ai: Whether to use AI for parsing
            max_concurrent_requests: Maximum concurrent API requests
            parser_output_dir: Output directory for parsing results (optional)
            is_directory: Whether source_file_path is a directory
            recursive: Whether to search recursively in directories
            keys_to_remove: Number of keys to remove from the context during truncation
            validation_enabled: Whether to run the validation loop.
            validation_iterations: Number of iterations to run the validation loop.
            conversion_session_id: Session ID for the existing conversion process.
            max_react_iters: Maximum iterations for the ReAct agent.
            conversion_max_iters: Maximum iterations for the converter to invoke the ReAct agent.
        """
        log.info("Initializing ExecutorConfig with provided configurations")

        # Set configurations using the config system
        log.info("Setting SourceCodeConfig")
        self.source_config = set_config("SourceCodeConfig", source_config)

        if llm_config:
            log.info("Setting LLMConfig")
            self.llm_config = set_config("LLMConfig", llm_config)
        else:
            self.llm_config = None

        if parser_prompt_config:
            log.info("Setting ParserPromptConfig")
            self.parser_prompt_config = set_config(
                "ParserPromptConfig", parser_prompt_config
            )
        else:
            self.parser_prompt_config = None

        if converter_prompt_config:
            log.info("Setting ConverterPromptConfig")
            self.converter_prompt_config = set_config(
                "ConverterPromptConfig", converter_prompt_config
            )
        else:
            self.converter_prompt_config = None

        if target_config:
            log.info("Setting TargetCodeConfig")
            self.target_config = set_config("TargetCodeConfig", target_config)
        else:
            self.target_config = None

        self.use_ai = use_ai
        self.max_concurrent_requests = max_concurrent_requests
        self.is_directory = is_directory
        self.recursive = recursive
        self.keys_to_remove = keys_to_remove
        self.validation_enabled = validation_enabled
        self.validation_iterations = validation_iterations
        self.conversion_session_id = conversion_session_id
        self.max_react_iters = max_react_iters
        self.conversion_max_iters = conversion_max_iters

        # Set output directory for parsing
        if parser_output_dir:
            self.output_dir = Path(parser_output_dir)
        else:
            # Default to base directory with dialect-specific subdirectory
            base_dir = get_migration_accelerator_base_directory()
            self.output_dir = (
                base_dir / "parser_output" / self.source_config.source_dialect
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Parsing output directory set to: {self.output_dir}")

        # Set output directory for conversion based on target_config.target_file_path
        if self.target_config and hasattr(self.target_config, "target_file_path"):
            # Use the directory from target_file_path
            target_path = Path(self.target_config.target_file_path)
            # if target_path.is_dir():
            #     # If it's already a directory, use it
            #     self.conversion_output_dir = target_path
            # else:
            #     # If it's a file path, use its parent directory
            #     self.conversion_output_dir = target_path.parent
            # log.info(
            #     f"Conversion output directory derived from target_file_path: {self.conversion_output_dir}"
            # )
            self.conversion_output_dir = target_path
        else:
            # Default fallback
            base_dir = get_migration_accelerator_base_directory()
            target_name = (
                self.target_config.target_dialect if self.target_config else "pyspark"
            )
            self.conversion_output_dir = base_dir / "conversion_output" / target_name
            log.info(
                f"Conversion output directory set to default: {self.conversion_output_dir}"
            )

        self.conversion_output_dir.mkdir(parents=True, exist_ok=True)

        if self.is_directory:
            self.parsing_summary_file_name = (
                self.source_config.source_file_path.rstrip("/").split("/")[-1]
            ) + "_parsing_summary.json"
            self.conversion_summary_file_name = (
                self.source_config.source_file_path.rstrip("/").split("/")[-1]
            ) + "_conversion_summary.json"
        else:
            self.parsing_summary_file_name = (
                self.source_config.source_file_path.rstrip("/")
                .split("/")[-1]
                .split(".")[0]
            ) + "_parsing_summary.json"
            self.conversion_summary_file_name = (
                self.source_config.source_file_path.split("/")[-1].split(".")[0]
            ) + "_conversion_summary.json"

        if self.conversion_session_id:
            log.info(
                f"Using an existing conversion session ID: {self.conversion_session_id}"
            )
        if self.validation_enabled:
            log.info("Validation Loop is enabled.")

    @classmethod
    def from_existing_configs(
        cls,
        use_ai: bool = False,
        max_concurrent_requests: int = 5,
        parser_output_dir: Optional[Union[str, Path]] = None,
        is_directory: bool = False,
        recursive: bool = True,
        keys_to_remove: int = 16,
        validation_enabled: bool = False,
        validation_iterations: int = 2,
        conversion_session_id: Optional[str] = None,
        max_react_iters: int = 10,
        conversion_max_iters: int = 20,
    ) -> "ExecutorConfig":
        """Create ExecutorConfig from existing set configurations.

        This method retrieves previously set configurations using get_config().

        Args:
            use_ai: Whether to use AI for parsing
            max_concurrent_requests: Maximum concurrent API requests
            parser_output_dir: Output directory for parsing results
            is_directory: Whether source_file_path is a directory
            recursive: Whether to search recursively in directories
            keys_to_remove: Number of keys to remove from the context during truncation
            validation_enabled: Whether to run the validation loop.
            validation_iterations: Number of iterations to run the validation loop.
            conversion_session_id: Session ID for the existing conversion process.
            max_react_iters: Maximum iterations for the ReAct agent.
            conversion_max_iters: Maximum iterations for the converter to invoke the ReAct agent.
        Returns:
            ExecutorConfig: Configured executor config instance
        """
        log.info("Creating ExecutorConfig from existing configurations")

        # Get configurations using the config system
        source_config = get_config("SourceCodeConfig")

        try:
            llm_config = get_config("LLMConfig")
        except Exception:
            log.info("No LLMConfig found, proceeding without it")
            llm_config = None

        try:
            parser_prompt_config = get_config("ParserPromptConfig")
        except Exception:
            log.info("No ParserPromptConfig found, proceeding without it")
            parser_prompt_config = None

        try:
            converter_prompt_config = get_config("ConverterPromptConfig")
        except Exception:
            log.info("No ConverterPromptConfig found, proceeding without it")
            converter_prompt_config = None

        try:
            target_config = get_config("TargetCodeConfig")
        except Exception:
            log.info("No TargetCodeConfig found, proceeding without it")
            target_config = None

        # Create instance by converting configs back to dicts
        instance = cls.__new__(cls)
        instance.source_config = source_config
        instance.llm_config = llm_config
        instance.parser_prompt_config = parser_prompt_config
        instance.converter_prompt_config = converter_prompt_config
        instance.target_config = target_config
        instance.use_ai = use_ai
        instance.max_concurrent_requests = max_concurrent_requests
        instance.is_directory = is_directory
        instance.recursive = recursive
        instance.keys_to_remove = keys_to_remove
        instance.validation_enabled = validation_enabled
        instance.validation_iterations = validation_iterations
        instance.conversion_session_id = conversion_session_id
        instance.max_react_iters = max_react_iters
        instance.conversion_max_iters = conversion_max_iters
        # Set parsing output directory
        if parser_output_dir:
            instance.output_dir = Path(parser_output_dir)
        else:
            base_dir = get_migration_accelerator_base_directory()
            instance.output_dir = (
                base_dir / "parser_output" / source_config.source_dialect
            )

        instance.output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Parsing output directory set to: {instance.output_dir}")

        # Set conversion output directory based on target_config.target_file_path
        if target_config and hasattr(target_config, "target_file_path"):
            # Use the directory from target_file_path
            target_path = Path(target_config.target_file_path)
            if target_path.is_dir():
                instance.conversion_output_dir = target_path
            else:
                instance.conversion_output_dir = target_path.parent
            log.info(
                f"Conversion output directory derived from target_file_path: {instance.conversion_output_dir}"
            )
        else:
            # Default fallback
            base_dir = get_migration_accelerator_base_directory()
            target_name = target_config.target_dialect if target_config else "pyspark"
            instance.conversion_output_dir = (
                base_dir / "conversion_output" / target_name
            )
            log.info(
                f"Conversion output directory set to default: {instance.conversion_output_dir}"
            )

        instance.conversion_output_dir.mkdir(parents=True, exist_ok=True)

        return instance


class Executor:
    """Executor class for orchestrating the ETL migration pipeline.

    This class handles the entire migration process including:
    - Parsing source code
    - Generating intent (future)
    - Converting to target format (future)
    - Validating output (future)
    """

    def __init__(self, config: ExecutorConfig):
        """Initialize the executor with configuration.

        Args:
            config: ExecutorConfig object containing all necessary configurations
        """
        self.config = config
        self.results: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []

        log.info(
            f"Initialized Executor for dialect: {config.source_config.source_dialect}"
        )
        log.info(f"AI enabled for parsing: {config.use_ai}")
        log.info(
            f"Processing mode: {'directory' if config.is_directory else 'single file'}"
        )

    @classmethod
    def from_json_config(cls, config_path: Union[str, Path]) -> "Executor":
        """Create an Executor from a JSON configuration file.

        Args:
            config_path: Path to JSON configuration file

        Returns:
            Executor: Configured executor instance

        Example JSON format:
        {
            "source_config": {
                "source_file_path": "/path/to/file.item",
                "source_dialect": "talend"
            },
            "llm_config": {
                "endpoint_name": "databricks-claude-sonnet-4",
                "temperature": 0.0,
                "max_tokens": 30000
            },
            "use_ai": true,
            "is_directory": false,
            "recursive": true
        }
        """
        config_path = Path(config_path)
        log.info(f"Loading configuration from: {config_path}")

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_dict = json.load(f)

        executor_config = ExecutorConfig(**config_dict)
        return cls(executor_config)

    def discover_files(self) -> List[Path]:
        """Discover files to process based on configuration.

        Returns:
            List[Path]: List of file paths to process
        """
        source_path = Path(self.config.source_config.source_file_path)
        dialect = self.config.source_config.source_dialect.lower()

        if not self.config.is_directory:
            # Single file mode
            if not source_path.exists():
                raise FileNotFoundError(f"Source file not found: {source_path}")
            log.info(f"Single file mode: {source_path}")
            return [source_path]

        # Directory mode
        if not source_path.is_dir():
            raise NotADirectoryError(
                f"Expected directory but got file: {source_path}. "
                "Set is_directory=False for single file processing."
            )

        log.info(f"Discovering files in directory: {source_path}")
        log.info(f"Recursive search: {self.config.recursive}")

        # Get allowed extensions for the dialect
        extensions = DIALECT_EXTENSIONS.get(dialect, [".item"])
        log.info(f"Looking for files with extensions: {extensions}")

        discovered_files = []

        if self.config.recursive:
            # Recursive search
            for ext in extensions:
                pattern = f"**/*{ext}"
                found = list(source_path.glob(pattern))
                discovered_files.extend(found)
                log.info(f"Found {len(found)} files with pattern {pattern}")
        else:
            # Non-recursive search (immediate directory only)
            for ext in extensions:
                pattern = f"*{ext}"
                found = list(source_path.glob(pattern))
                discovered_files.extend(found)
                log.info(f"Found {len(found)} files with pattern {pattern}")

        # Remove duplicates and sort
        discovered_files = sorted(set(discovered_files))

        log.info(f"Total files discovered: {len(discovered_files)}")

        if not discovered_files:
            log.warning(f"No files found with extensions {extensions} in {source_path}")

        return discovered_files

    def parse(self) -> Dict[str, Any]:
        """Execute the parsing step for all discovered files.

        Returns:
            Dict[str, Any]: Summary of parsing results including successes and errors
        """
        log.info("=" * 80)
        log.info("STARTING PARSING STEP")
        log.info("=" * 80)

        files_to_process = self.discover_files()

        if not files_to_process:
            log.warning("No files to process")
            return {
                "status": "completed",
                "total_files": 0,
                "successful": 0,
                "failed": 0,
                "results": [],
                "errors": [],
            }

        total_files = len(files_to_process)
        successful = 0
        failed = 0

        log.info(f"Processing {total_files} file(s)...")

        for idx, file_path in enumerate(files_to_process, 1):
            log.info("-" * 80)
            log.info(f"Processing file {idx}/{total_files}: {file_path.name}")
            log.info("-" * 80)

            try:
                # Create source config for this specific file
                file_config = SourceCodeConfig(
                    source_file_path=str(file_path),
                    source_dialect=self.config.source_config.source_dialect,
                )

                # Create parser
                parser = SourceCodeParser.create_parser(
                    config=file_config,
                    user_prompt=self.config.parser_prompt_config,
                    use_ai=self.config.use_ai,
                    llm_config=self.config.llm_config,
                )

                # Parse the file
                log.info(f"Parsing file: {file_path}")
                parsed_content = parser.parse()

                # Save parsed content to output directory
                output_file = self.config.output_dir / f"{file_path.stem}_parsed.json"
                write_json(parsed_content, output_file)

                result = {
                    "file_path": str(file_path),
                    "file_name": file_path.name,
                    "status": "success",
                    "output_file": str(output_file),
                    "metadata": parsed_content.get("metadata", {}),
                }

                self.results.append(result)
                successful += 1

                log.info(f"✓ Successfully parsed: {file_path.name}")
                log.info(f"  Output saved to: {output_file}")

            except Exception as e:
                error = {
                    "file_path": str(file_path),
                    "file_name": file_path.name,
                    "status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }

                self.errors.append(error)
                failed += 1

                log.error(f"✗ Failed to parse: {file_path.name}")
                log.error(f"  Error: {str(e)}")

        log.info("=" * 80)
        log.info("PARSING STEP COMPLETED")
        log.info(f"Total: {total_files} | Successful: {successful} | Failed: {failed}")
        log.info("=" * 80)

        # Save summary
        summary = {
            "status": "completed",
            "total_files": total_files,
            "successful": successful,
            "failed": failed,
            "results": self.results,
            "errors": self.errors,
            "config": {
                "source_dialect": self.config.source_config.source_dialect,
                "use_ai": self.config.use_ai,
                "is_directory": self.config.is_directory,
                "output_dir": str(self.config.output_dir),
            },
        }

        summary_file = self.config.output_dir / self.config.parsing_summary_file_name
        write_json(summary, summary_file)
        log.info(f"Summary saved to: {summary_file}")

        return summary

    def generate_intent(self) -> Dict[str, Any]:
        """Execute the intent generation step (placeholder for future implementation).

        Returns:
            Dict[str, Any]: Summary of intent generation results
        """
        log.info("=" * 80)
        log.info("INTENT GENERATION STEP")
        log.info("=" * 80)
        log.warning("Intent generation not yet implemented")
        return {
            "status": "not_implemented",
            "message": "Intent generation step is not yet implemented",
        }

    def convert(self) -> Dict[str, Any]:
        """Execute the conversion step for all parsed files.

        This method converts parsed files to the target format (e.g., PySpark).
        It uses dialect-specific converters based on the source dialect.

        Returns:
            Dict[str, Any]: Summary of conversion results including successes and errors
        """
        log.info("=" * 80)
        log.info("STARTING CONVERSION STEP")
        log.info("=" * 80)

        # Get parsed files from parse results or discover them
        if not self.results:
            log.info(
                "No parsed results found, looking for parsed files in output directory"
            )
            # parsed_files = list(self.config.output_dir.glob("*_parsed.json"))
            parsed_files = []
        else:
            parsed_files = [Path(r["output_file"]) for r in self.results]

        if not parsed_files:
            log.warning("No parsed files found to convert")
            return {
                "status": "completed",
                "total_files": 0,
                "successful": 0,
                "failed": 0,
                "results": [],
                "errors": [],
            }

        total_files = len(parsed_files)
        successful = 0
        failed = 0
        conversion_results = []
        conversion_errors = []

        log.info(f"Found {total_files} parsed file(s) to convert")

        # Initialize dialect-specific converter
        converter = self._create_converter()

        if not converter:
            log.error(
                f"No converter available for dialect: {self.config.source_config.source_dialect}"
            )
            return {
                "status": "error",
                "total_files": total_files,
                "successful": 0,
                "failed": total_files,
                "results": [],
                "errors": [
                    f"No converter for dialect {self.config.source_config.source_dialect}"
                ],
            }

        for idx, parsed_file in enumerate(parsed_files, 1):
            log.info("-" * 80)
            log.info(f"Converting file {idx}/{total_files}: {parsed_file.name}")
            log.info("-" * 80)

            try:
                # Generate output filename
                output_filename = parsed_file.stem.replace("_parsed", "") + ".py"
                target_path = self.config.conversion_output_dir / output_filename

                # Convert the file
                log.info(f"Converting: {parsed_file} -> {target_path}")
                result = converter.convert(
                    parsed_talend_path=parsed_file,
                    target_pyspark_path=target_path,
                    validation_enabled=self.config.validation_enabled,
                    validation_iterations=self.config.validation_iterations,
                )

                if result["status"] == "success":
                    conversion_result = {
                        "parsed_file": str(parsed_file),
                        "target_file": result["target_file"],
                        "status": "success",
                        "summary": result.get("summary", ""),
                    }
                    conversion_results.append(conversion_result)
                    successful += 1
                    log.info(f"✓ Successfully converted: {parsed_file.name}")
                else:
                    error = {
                        "parsed_file": str(parsed_file),
                        "status": "failed",
                        "error": result.get("errors", "Unknown error"),
                    }
                    conversion_errors.append(error)
                    failed += 1
                    log.error(f"✗ Failed to convert: {parsed_file.name}")

            except Exception as e:
                error = {
                    "parsed_file": str(parsed_file),
                    "status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
                conversion_errors.append(error)
                failed += 1
                log.error(f"✗ Exception during conversion of {parsed_file.name}: {e}")

        log.info("=" * 80)
        log.info("CONVERSION STEP COMPLETED")
        log.info(f"Total: {total_files} | Successful: {successful} | Failed: {failed}")
        log.info("=" * 80)

        # Save conversion summary
        summary = {
            "status": "completed",
            "total_files": total_files,
            "successful": successful,
            "failed": failed,
            "results": conversion_results,
            "errors": conversion_errors,
            "config": {
                "source_dialect": self.config.source_config.source_dialect,
                "target_dialect": (
                    self.config.target_config.target_dialect
                    if self.config.target_config
                    else "pyspark"
                ),
                "conversion_output_dir": str(self.config.conversion_output_dir),
            },
        }

        summary_file = (
            self.config.conversion_output_dir / self.config.conversion_summary_file_name
        )
        write_json(summary, summary_file)
        log.info(f"Conversion summary saved to: {summary_file}")

        return summary

    def _create_converter(self):
        """Create a dialect-specific converter based on source dialect.

        Returns:
            Converter instance or None if dialect not supported
        """
        dialect = self.config.source_config.source_dialect.lower()

        log.info(f"Creating converter for dialect: {dialect}")

        if dialect == "talend":
            from migration_accelerator.experimental.converter.talend import (
                TalendConverter,
            )

            # Build custom instructions if converter_prompt_config is provided
            custom_instructions = self._build_custom_instructions()

            converter = TalendConverter(
                llm_config=self.config.llm_config,
                max_iterations=self.config.max_react_iters,
                conversion_max_iters=self.config.conversion_max_iters,
                keys_to_remove=self.config.keys_to_remove,
                conversion_session_id=self.config.conversion_session_id,
                verbose=True,
            )

            # If custom instructions exist, we'll need to augment the converter
            if custom_instructions:
                log.info("Applying custom conversion instructions")
                converter.custom_instructions = custom_instructions

            return converter

        else:
            log.warning(f"No converter implemented for dialect: {dialect}")
            return None

    def _build_custom_instructions(self) -> Optional[str]:
        """Build custom instructions from converter_prompt_config.

        Returns:
            Custom instructions string or None
        """
        if not self.config.converter_prompt_config:
            return None

        instructions = []

        # Add base prompt
        if (
            hasattr(self.config.converter_prompt_config, "prompt")
            and self.config.converter_prompt_config.prompt
        ):
            instructions.append("# CUSTOM CONVERSION INSTRUCTIONS\n")
            instructions.append(self.config.converter_prompt_config.prompt)
            instructions.append("\n")

        # Add skip node types
        if (
            hasattr(self.config.converter_prompt_config, "skip_node_types")
            and self.config.converter_prompt_config.skip_node_types
        ):
            instructions.append("# NODES TO SKIP\n")
            instructions.append("Skip the following node types during conversion:\n")
            for node_type in self.config.converter_prompt_config.skip_node_types:
                instructions.append(f"  - {node_type}\n")
            instructions.append("\n")

        # Add custom mappings
        if (
            hasattr(self.config.converter_prompt_config, "custom_mappings")
            and self.config.converter_prompt_config.custom_mappings
        ):
            instructions.append("# CUSTOM COMPONENT MAPPINGS\n")
            instructions.append("Use these custom mappings for specific components:\n")
            for (
                component,
                mapping,
            ) in self.config.converter_prompt_config.custom_mappings.items():
                instructions.append(f"  - {component}: {mapping}\n")
            instructions.append("\n")

        if not instructions:
            return None

        return "".join(instructions)

    def validate(self) -> Dict[str, Any]:
        """Execute the validation step (placeholder for future implementation).

        Returns:
            Dict[str, Any]: Summary of validation results
        """
        log.info("=" * 80)
        log.info("VALIDATION STEP")
        log.info("=" * 80)
        log.warning("Validation not yet implemented")
        return {
            "status": "not_implemented",
            "message": "Validation step is not yet implemented",
        }

    def execute(self, steps: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute the complete migration pipeline or specific steps.

        Args:
            steps: Optional list of steps to execute. If None, executes all
            available steps.
            Available steps: ['parse', 'generate_intent', 'convert', 'validate']

        Returns:
            Dict[str, Any]: Summary of all executed steps
        """
        if steps is None:
            steps = ["parse", "convert"]  # Parse and convert are implemented

        log.info("=" * 80)
        log.info("STARTING EXECUTOR")
        log.info("=" * 80)
        log.info(f"Steps to execute: {steps}")

        results = {}

        for step in steps:
            if step == "parse":
                results["parse"] = self.parse()
            elif step == "generate_intent":
                results["generate_intent"] = self.generate_intent()
            elif step == "convert":
                results["convert"] = self.convert()
            elif step == "validate":
                results["validate"] = self.validate()
            else:
                log.warning(f"Unknown step: {step}")
                results[step] = {
                    "status": "error",
                    "message": f"Unknown step: {step}",
                }

        log.info("=" * 80)
        log.info("EXECUTOR COMPLETED")
        log.info("=" * 80)

        return results

    def get_results(self) -> List[Dict[str, Any]]:
        """Get the results of successful operations.

        Returns:
            List[Dict[str, Any]]: List of successful results
        """
        return self.results

    def get_errors(self) -> List[Dict[str, Any]]:
        """Get the errors from failed operations.

        Returns:
            List[Dict[str, Any]]: List of errors
        """
        return self.errors

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the execution.

        Returns:
            Dict[str, Any]: Summary statistics
        """
        return {
            "total_processed": len(self.results) + len(self.errors),
            "successful": len(self.results),
            "failed": len(self.errors),
            "success_rate": (
                len(self.results) / (len(self.results) + len(self.errors)) * 100
                if (len(self.results) + len(self.errors)) > 0
                else 0
            ),
        }
