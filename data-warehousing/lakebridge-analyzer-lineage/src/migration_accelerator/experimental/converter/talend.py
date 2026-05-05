# flake8: noqa: E501
"""Talend to PySpark Converter using DSPy ReAct Agent.

This module implements a converter that uses a custom DSPy ReAct agent (TalendReAct)
to convert parsed Talend ETL jobs into Databricks-native PySpark code. The converter
takes a greedy approach, reading node details incrementally and writing PySpark code
step by step to avoid context loss.

Key Features:
- TalendReAct: Custom ReAct module with intelligent trajectory truncation
- Preserves critical tool calls (create_session, read_json_file for _parsed files)
- Greedy conversion approach for large jobs
- Context-aware conversion with summarization
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

import dspy
from pydantic import BaseModel, Field

from migration_accelerator.core.llms import LLMManager
from migration_accelerator.core.tools.dspy_tools import (
    create_session,
    edit_file,
    grep_file,
    ls,
    read_file,
    read_json_file,
    read_todos,
    write_file,
    write_json_file,
    write_todos,
)
from migration_accelerator.core.tools.retriever_tools import (
    retrieve_talend_knowledge,
)
from migration_accelerator.exceptions import MigrationAcceleratorToolException
from migration_accelerator.experimental.validator import (
    TalendValidator,
    ValidationResult,
)
from migration_accelerator.utils.files import read_json
from migration_accelerator.utils.logger import get_logger

log = get_logger()

if TYPE_CHECKING:
    from dspy.signatures.signature import Signature


# ============================================================================
# Additional Tools for Conversion with Compaction
# ============================================================================


def append_to_pyspark_file(
    file_path: str, code_block: str, section_name: str = ""
) -> str:
    """Append a code block to a PySpark file with optional section header.

    Use this to incrementally build the PySpark output file. Each call appends
    a new section of code, allowing for step-by-step conversion without loading
    the entire output in memory.

    Args:
        file_path: Path to the PySpark .py file to append to
        code_block: The PySpark code to append
        section_name: Optional section name for documentation
        (e.g., "tFileInputDelimited_1 - Read CSV")

    Returns:
        Success message or error message.

    Examples:
        >>> append_to_pyspark_file("/output/job.py", \
        ...  "df = spark.read.csv('input.csv')", "Read Input")
        "Successfully appended code section 'Read Input' to /output/job.py"
    """
    log.info("LLM Tool Call ::START:: append_to_pyspark_file")
    try:
        path = Path(file_path)

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Build the content to append
        content_to_append = "\n"
        # if section_name:
        #     content_to_append += f"# {'-' * 70}\n"
        #     content_to_append += f"# {section_name}\n"
        #     content_to_append += f"# {'-' * 70}\n"
        content_to_append += code_block.strip() + "\n"

        # Append to file
        with open(path, "a", encoding="utf-8") as f:
            f.write(content_to_append)

        msg = "Successfully appended code"
        if section_name:
            msg += f" section '{section_name}'"
        msg += f" to {file_path}"

        return msg

    except PermissionError:
        return f"Error: Permission denied writing to '{file_path}'"
    except Exception as e:
        return f"Error appending to file '{file_path}': {e}"


def summarize_conversion_context(
    converted_nodes: List[str],
    current_dataframes: Dict[str, str],
    session_id: Optional[str] = None,
) -> str:
    """Create a compact summary of conversion progress for context awareness.

    Use this to maintain context awareness during greedy conversion. This creates
    a lightweight summary of what has been converted so far, which dataframes
    exist, and their purposes. This summary can be referenced in subsequent steps.

    Args:
        converted_nodes: List of node names that have been converted
        current_dataframes: Dictionary mapping dataframe variable names to their
        purposes. Example:
        {"df_input": "Customer data from CSV", "df_lookup": "Product reference data"}
        session_id: Optional session ID for storing the summary

    Returns:
        Formatted summary string.

    Examples:
        >>> summarize_conversion_context(
        ...     ["tFileInputDelimited_1", "tMap_1"],
        ...     {"df_input": "Customer CSV data",
        ...     "df_transformed": "Mapped customer data"}
        ... )
        "Conversion Context Summary:
        Converted Nodes (2): tFileInputDelimited_1, tMap_1
        Available DataFrames (2):
          - df_input: Customer CSV data
          - df_transformed: Mapped customer data"
    """
    try:
        summary = f"""=== Conversion Context Summary ===\n\n
        Converted Nodes ({len(converted_nodes)}): {', '.join(converted_nodes)}\n\n
        Available DataFrames ({len(current_dataframes)}):\n"""

        for df_name, df_purpose in current_dataframes.items():
            summary += f"  - {df_name}: {df_purpose}\n"

        for df_name, df_purpose in current_dataframes.items():
            summary += f"  - {df_name}: {df_purpose}\n"

        # Optionally save to session for persistence
        if session_id:
            from migration_accelerator.core.tools.dspy_tools import (
                SESSION_BASE_DIR,
                _get_session_path,
            )

            session_path = _get_session_path(session_id, SESSION_BASE_DIR)
            summary_file = session_path / "conversion_context.json"

            context_data = {
                "converted_nodes": converted_nodes,
                "current_dataframes": current_dataframes,
            }

            with open(summary_file, "w") as f:
                json.dump(context_data, f, indent=2)

            summary += f"\n(Context saved to session {session_id})"

        return summary

    except Exception as e:
        return f"Error creating summary: {e}"


def load_conversion_context(session_id: str) -> str:
    """Load previously saved conversion context from a session.

    Use this to restore context awareness after previous conversion steps.

    Args:
        session_id: Session ID where context was saved

    Returns:
        Formatted context summary or error message.
    """
    try:
        from migration_accelerator.core.tools.dspy_tools import (
            SESSION_BASE_DIR,
            _get_session_path,
        )

        session_path = _get_session_path(session_id, SESSION_BASE_DIR)
        summary_file = session_path / "conversion_context.json"

        if not summary_file.exists():
            return "No conversion context found in this session"

        with open(summary_file, "r") as f:
            context_data = json.load(f)

        return summarize_conversion_context(
            context_data["converted_nodes"],
            context_data["current_dataframes"],
            session_id=None,  # Don't re-save when loading
        )

    except Exception as e:
        return f"Error loading conversion context: {e}"


# ============================================================================
# Custom DSPy ReAct Module with Trajectory Truncation
# ============================================================================


class TalendReAct(dspy.ReAct):
    """Custom ReAct module with intelligent trajectory truncation.

    This class extends dspy.ReAct to implement custom trajectory truncation
    that preserves critical tool calls during context window management:
    - Preserves create_session calls (needed for workspace setup)
    - Preserves read_json_file calls for _parsed files (main input files)
    """

    def __init__(
        self,
        signature: type["Signature"],
        tools: List[Callable],
        max_iters: int = 10,
        keys_to_remove: int = 16,
    ):
        """Initialize TalendReAct with custom trajectory truncation.

        Args:
            signature: DSPy signature for the task
            max_iters: Maximum iterations for ReAct
            tools: List of tool functions
            keys_to_remove: Number of trajectory keys to remove during truncation (default: 16)
        """
        super().__init__(signature, tools, max_iters)
        self.keys_to_remove = keys_to_remove

    def truncate_trajectory(self, trajectory: dict) -> dict:
        """Truncate trajectory while preserving critical tool calls.

        This method removes older trajectory entries when context gets too large,
        but intelligently skips removal of:
        1. create_session calls (needed for workspace context)
        2. read_json_file calls for _parsed files (main input files)

        Args:
            trajectory: Dictionary containing trajectory keys (thought_N, tool_name_N, etc.)

        Returns:
            Truncated trajectory dictionary
        """
        # Step 1: Check trajectory length against context window
        # This is the original first step that should remain
        keys = list(trajectory.keys())
        if len(keys) < 4:
            # Every tool call has 4 keys: thought, tool_name, tool_args, and observation.
            raise ValueError(
                "The trajectory is too long so your prompt exceeded the context window, but the trajectory cannot be "
                "truncated because it only has one tool call."
            )

        # Step 2: Identify all trajectory step indices
        step_indices = set()
        for key in trajectory.keys():
            if key.startswith(("thought_", "tool_name_", "tool_args_", "observation_")):
                # Extract step number
                parts = key.split("_")
                if len(parts) >= 2 and parts[-1].isdigit():
                    step_indices.add(int(parts[-1]))

        step_indices = sorted(step_indices)

        # Step 3: Identify steps to skip (preserve)
        steps_to_skip = set()

        for step_idx in step_indices:
            tool_name_key = f"tool_name_{step_idx}"
            tool_args_key = f"tool_args_{step_idx}"

            if tool_name_key not in trajectory:
                continue

            tool_name = trajectory[tool_name_key]

            # Skip create_session calls
            if tool_name == "create_session":
                steps_to_skip.add(step_idx)
                log.info(f"Preserving step {step_idx}: create_session call")
                continue

            # Skip read_json_file calls for _parsed files
            if tool_name == "read_json_file" and tool_args_key in trajectory:
                tool_args = trajectory[tool_args_key]
                if isinstance(tool_args, dict):
                    file_path = tool_args.get("file_path", "")
                    if "_parsed" in file_path:
                        steps_to_skip.add(step_idx)
                        log.info(
                            f"Preserving step {step_idx}: read_json_file for _parsed file"
                        )
                        continue

        # Step 4: Remove keys from oldest steps first (but skip preserved ones)
        keys_removed = 0
        keys_to_remove_target = self.keys_to_remove

        for step_idx in step_indices:
            # Stop if we've removed enough keys
            if keys_removed >= keys_to_remove_target:
                break

            # Skip if this step should be preserved
            if step_idx in steps_to_skip:
                continue

            # Remove all 4 keys for this step
            keys_for_step = [
                f"thought_{step_idx}",
                f"tool_name_{step_idx}",
                f"tool_args_{step_idx}",
                f"observation_{step_idx}",
            ]

            step_keys_removed = 0
            for key in keys_for_step:
                if key in trajectory:
                    del trajectory[key]
                    step_keys_removed += 1

            if step_keys_removed > 0:
                keys_removed += step_keys_removed
                log.info(f"Removed {step_keys_removed} keys from step {step_idx}")

        log.info(f"Trajectory truncation complete: removed {keys_removed} keys total")

        return trajectory


# ============================================================================
# DSPy Signatures for Talend to PySpark Conversion
# ============================================================================


class TalendJobToPySpark(dspy.Signature):
    """Convert an entire Talend job to PySpark code orchestrating the conversion flow.

    You are an expert ETL migration engineer converting Talend ETL jobs to Databricks
    PySpark code.

    # YOUR MISSION
    - Convert a parsed Talend JSON file into production-ready Databricks PySpark code
    (.py file).
    - Don't include conversion summary to the output file.
    - Don't implement any aditional data validation checks in the output file.
    - Since the output file will be rendered as a Databricks notebook, you may include
    markdown headers to make the code more readable.

    # IMPORTANT FILE PATHS
    You will receive TWO file paths as inputs:
    1. parsed_talend_path: READ the parsed Talend job from this path using tools.
    2. target_pyspark_path: WRITE the generated PySpark code to this path

    CRITICAL:
    1. When using file writing tools, ALWAYS use the target_pyspark_path value
    for the output file.
    Example: append_to_pyspark_file(target_pyspark_path, code, section_name)
    2. You also have other file tools that you can use to offload and read context
    for next iteration.
    3. You need to make sure you convert the entire input by processing all the
    nodes.
    4. Nodes are related to each other by connection, so Connections and subjobs help
    you decide the flow of your pyspark code.
    5. Don't call the finish tool unless you are done converting all the components.
    6. Use Databricks widgets to initialize the Talend context variables. Keep the
    variables names as the same as the Talend context variables.

    # CONVERSION STRATEGY (GREEDY APPROACH)

    ## Phase 1: Planning
    1. Read the main parsed Talend JSON from parsed_talend_path
    2. Analyze the connection graph to determine execution order
    3. Create a TODO list for converting each node in the correct order
    4. Initialize the target PySpark file at target_pyspark_path with imports:
       write_file(target_pyspark_path, "# Databricks notebook source\n
       from pyspark.sql import *\n...")
    5. Make sure you are completing all the tasks in the TODO list.
    6. If you are not able to see the parsed talend Json due to context truncation,
    use read_todos() to read the todos and load_conversion_context() to load
    the necessary context from previous steps for the current iteration.

    ## Phase 2: Incremental Conversion
    For each node in execution order:
    1. Read the node's JSON file to get detailed configuration of each node.
    2. Use retrieve_talend_knowledge() to understand the node or connection you
    are converting.
    3. Generate PySpark code equivalent for that node
    4. Use append_to_pyspark_file(target_pyspark_path, code, section) to add code
    5. Update the conversion context with new dataframes created
    6. Occationally Use summarize_conversion_context() to maintain context for next nodes or
    iterations and also use load_conversion_context() to restore context when needed. This
    should help you maintain the talend Connection details available in the context for all iterations.
    7. If the node has a connection to another node, make sure you are converting the
    connected node in such a way that the connection flow is maintained.
    8. If Users provide custom instructions, make sure you are following them.

    ## Phase 3: Finalization
    1. Add final cleanup code using append_to_pyspark_file(target_pyspark_path, ...)
    2. Verify the generated PySpark file exists at target_pyspark_path
    3. Provide a conversion summary including the target_pyspark_path

    # KEY PRINCIPLES
    - ALWAYS write output to target_pyspark_path (don't make up file names!)
    - Use greedy approach: read each node JSON only when needed
    - Maintain context awareness through summarization
    - Generate clean, production-ready PySpark code
    - Add appropriate comments and documentation
    - Handle errors appropriately
    """

    parsed_talend_path: str = dspy.InputField(
        desc="Path to the parsed Talend JSON file to READ from"
    )
    target_pyspark_path: str = dspy.InputField(
        desc="Path to the target PySpark .py file to WRITE to (use this in all file writing tools!)"
    )
    custom_instructions: str = dspy.InputField(
        desc="Custom conversion instructions (node types to skip, custom mappings, etc.)",
        default="",
    )

    conversion_summary: str = dspy.OutputField(
        desc="Summary of the conversion process including status and generated code structure"
    )


class ConversionSummary(BaseModel):
    talend_nodes_converted: List[str] = Field(
        description="The list of talend nodes converted so far."
    )
    dataframes_created: Dict[str, str] = Field(
        description="The list of dataframes created so far and their names and very high level description of their purpose."
    )
    relevant_connection_names: List[str] = Field(
        description="""List of specific talend connection names or context variable names that 
    you just finished converting and might be relevant for the next iteration."""
    )


class TalendToPySparkIter(dspy.Signature):
    """Convert a Talend job (parsed into a Json file) to PySpark code orchestrating the
    conversion flow.

    You are an expert ETL migration engineer converting Talend ETL jobs to Databricks
    PySpark code. The file will be rendered as a Databricks notebook, so you may include
    markdown headers to make the code more readable.

    # YOUR MISSION
    - Convert a parsed Talend JSON file into production-ready Databricks PySpark code
    (.py file). Continue from where you left off in the previous iteration.
    - Don't include conversion summary to the output file.
    - Don't implement any aditional data validation checks in the output file.
    - Since the output file will be rendered as a Databricks notebook, you may include
    markdown headers to make the code more readable.


    # IMPORTANT FILE PATH
    1. target_pyspark_path: WRITE the generated PySpark code to this path or append to it.

    CRITICAL:
    1. When using file writing tools, ALWAYS use the target_pyspark_path value to write to or
    append to the output file. You can use the ls tool to see if the output file exists, in case
    the file exists, you can append your conversion code to it.
    Example: append_to_pyspark_file(target_pyspark_path, code, section_name)
    2. You also have other file tools that you can use to offload and read context
    for next iteration.
    3. You need to make sure you convert the entire input by processing all the nodes.
    4. Nodes are related to each other by connection, so Connections and subjobs help
    you decide the flow of your pyspark code.
    5. Use Databricks widgets to initialize the Talend context variables. Keep the
    variables names as the same as the Talend context variables.

    # CONVERSION STRATEGY (GREEDY APPROACH)

    ## Phase 1: Planning
    0. You must check the old/previous conversion trajectory to see what's the progress of the conversion so far.
    if the conversion is not complete, you must continue from where you left off. If there is no previous conversion trajectory,
    you must start from scratch.
    1. Read the main parsed Talend code from parsed_talend_code
    2. Analyze the connection graph to determine execution order
    3. Create a TODO list for converting each node in the correct order.
    you will be provided with a session_id. use the read_todos() tool to read the todos for the current session
    given the todos file already exists. If you don't find any todos list, create a new one using the write_todos() tool.
    4. Initialize the target PySpark file (if it doesn't exist) at target_pyspark_path with imports:
       write_file(target_pyspark_path, "# Databricks notebook source\n
       from pyspark.sql import *\n...")
    5. Make sure you are updating the TODO list with the current tasks you are working on.
       - If you have the previous conversion trajectory, you should update the TODO list with the tasks that you see are
       already completed in the previous iteration. Once the TODO list is updated then you may proceed with the
       conversion for the current iteration.
    6. Only read the target_pyspark_path to understand the progress if you don't have the previous conversion trajectory.


    ## Phase 2: Incremental Conversion
    For each node in execution order:
    1. Read the node's JSON file to get detailed configuration of each node.
    You may use to read multiple nodes at once using read_json_file() tool.
    Read atleast 2 nodes at a time to avoid too many tool calls.
    2. You should use retrieve_talend_knowledge() to understand the node or connection you
    are converting.
    3. Generate PySpark code equivalent for that node
    4. Use append_to_pyspark_file(target_pyspark_path, code, section) to add code
    5. If the node has a connection to another node, make sure you are converting the
    connected node in such a way that the connection flow is maintained.
    6. If Users provide custom instructions, make sure you are following them.

    ## Phase 3: Finalization
    1. Make sure that you update the TODO list when you feel like you are about to
    finish the process.
    2. Verify the generated PySpark file exists at target_pyspark_path.
    3. Provide a conversion summary of the conversion progress so far. it should include:
        - the list of talend nodes converted so far.
        - the list of dataframes created so far and their names and very high level description of their purpose.
        - List of specific talend connection name or context variable name that you just finished converting and might be
        relevant for the next iteration.
        * If a summary already exists in the old conversion trajectory, you should append to those lists.
    4. Set the completion_status to True if you have completed the conversion of all the nodes.

    # KEY PRINCIPLES
    - ALWAYS write output to target_pyspark_path (don't make up file names!)
    - Use greedy approach: read each node JSON only when needed
    - Maintain context awareness through summarization
    - Generate clean, production-ready PySpark code without any syntax issues.
    - Add appropriate comments and documentation
    - Handle errors appropriately
    """

    session_id: str = dspy.InputField(
        desc="The session ID. This is the session ID for the current conversion.",
    )
    parsed_talend_code: Dict[str, Any] = dspy.InputField(
        desc="This is the parsed input Talend code in JSON format."
    )
    target_pyspark_path: str = dspy.InputField(
        desc="Path to the target PySpark .py file to WRITE the converted output code to."
    )
    custom_instructions: str = dspy.InputField(
        desc="Custom conversion instructions (node types to skip, custom mappings, etc.)",
        default="",
    )
    old_conversion_trajectory: Dict[str, Any] = dspy.InputField(
        desc="""The old/previous conversion trajectory. This is the trajectory of the conversion progress so far.
        This also includes the conversion summary of the previous conversion.""",
        default={},
    )
    conversion_summary: ConversionSummary = dspy.OutputField(
        desc="""Summary of the conversion progress including the talend nodes converted so far and the 
        names of the dataframes created so far."""
    )
    completion_status: bool = dspy.OutputField(
        desc="""Whether the conversion is complete or not. Only set this to true if you see all the 
        talend nodes converted in the conversion summary.""",
        default=False,
    )


class FixValidationErrors(dspy.Signature):
    """Fix the validation errors in the target PySpark file.
    The fixed pyspark python file should be able to be rendered as a Databricks notebook
    without any syntax & compilation errors.
    you shouldn't remove any critical code that's already implemented correctly.
    focus more on fixing the syntax and compilation errors (if there are any) related to spark dataframe
    operations and transformations."""

    input_pyspark_code: str = dspy.InputField(
        desc="The input PySpark code to fix the validation errors in."
    )
    validation_errors: List[str] = dspy.InputField(
        desc="List of validation errors to fix."
    )
    critique_feedback: Dict[str, Any] = dspy.InputField(
        desc="Critique feedback from the validation step."
    )
    fixed_pyspark_code: str = dspy.OutputField(
        desc="The fixed PySpark code that can be rendered as a Databricks notebook without any syntax errors."
    )


# ============================================================================
# TalendConverter Class
# ============================================================================


class TalendConverter:
    """Converter for transforming parsed Talend ETL jobs to Databricks PySpark code.

    This converter uses a DSPy ReAct agent with a greedy approach to:
    1. Read the parsed Talend JSON structure
    2. Process nodes incrementally based on connection flow
    3. Generate PySpark code for each node
    4. Append code to the output file step by step
    5. Maintain context awareness through summarization

    The converter has access to:
    - File system tools (read, write, edit, ls, grep)
    - JSON file tools (read_json, write_json)
    - Talend knowledge retrieval (for understanding components)
    - TODO management (for complex conversion planning)
    - Session management (for isolated concurrent execution)
    - Conversion-specific tools (append code, summarize context)
    """

    def __init__(
        self,
        llm_config: Optional[Any] = None,
        max_iterations: int = 10,
        custom_instructions: Optional[str] = None,
        keys_to_remove: int = 16,
        conversion_session_id: Optional[str] = None,
        conversion_max_iters: int = 20,
        verbose: bool = True,
    ):
        """Initialize the TalendConverter.

        Args:
            llm_config: LLM configuration (LLMConfig instance). If None, will try to get from config.
            max_iterations: Maximum iterations for ReAct agent
            verbose: Whether to show detailed logging
            custom_instructions: Optional custom instructions for conversion
            (e.g., skip certain nodes, custom mappings)
            keys_to_remove: Number of trajectory keys to remove during truncation (default: 16)
            conversion_session_id: Session ID for the existing conversion process.
            conversion_max_iters: Maximum iterations for the converter to invoke the ReAct agent.
        """
        self.llm_config = llm_config
        self.max_iterations = max_iterations
        self.conversion_max_iters = conversion_max_iters
        self.verbose = verbose
        self.custom_instructions = custom_instructions
        self.keys_to_remove = keys_to_remove
        self.session_id = conversion_session_id

        log.info("Initializing TalendConverter")
        if custom_instructions:
            log.info("Custom instructions provided for conversion")

        # Initialize DSPy LLM
        self._initialize_dspy_lm()

        # Prepare tools for ReAct agent
        self.tools = self._prepare_tools()

        # Create custom TalendReAct agent
        self.agent = self._create_talend_react_agent()

        # Create DSPy ReAct agent for multiple iterations
        self.iter_agent = self._create_react_agent()

        log.info(f"TalendConverter initialized with {len(self.tools)} tools")

    def _initialize_dspy_lm(self) -> None:
        """Initialize the DSPy language model."""
        try:
            if not self.llm_config:
                # Try to get from config
                from migration_accelerator.configs import get_config

                self.llm_config = get_config("LLMConfig")

            llm_manager = LLMManager(self.llm_config)
            dspy_llm = llm_manager.get_dspy_llm()

            # Configure DSPy
            dspy.configure(lm=dspy_llm)

            log.info(
                f"DSPy LM configured with endpoint: {self.llm_config.endpoint_name}"
            )

        except Exception as e:
            log.error(f"Failed to initialize DSPy LM: {e}")
            raise

    def _prepare_tools(self) -> List:
        """Prepare all tools for the ReAct agent.

        Returns:
            List of tool functions
        """
        tools = [
            # File system tools
            ls,
            # read_file,
            write_file,
            edit_file,
            # grep_file,
            # JSON tools
            read_json_file,
            write_json_file,
            # TODO management
            write_todos,
            read_todos,
            # Talend knowledge retrieval
            retrieve_talend_knowledge,
            # Conversion-specific tools
            append_to_pyspark_file,
        ]

        return tools

    def _create_react_agent(self) -> dspy.ReAct:
        """Create the DSPy ReAct agent for conversion.

        Returns:
            Configured DSPy ReAct agent
        """
        agent = dspy.ReAct(
            signature=TalendToPySparkIter,
            tools=self.tools,
            max_iters=self.max_iterations,
        )
        return agent

    def _create_talend_react_agent(self) -> TalendReAct:
        """Create the custom TalendReAct agent for conversion.

        Returns:
            Configured custom TalendReAct agent with custom trajectory truncation
        """
        # Create TalendReAct agent with signature that includes instructions
        # Using custom TalendReAct for intelligent trajectory truncation
        agent = TalendReAct(
            signature=TalendJobToPySpark,
            tools=self.tools,
            max_iters=self.max_iterations,
            keys_to_remove=self.keys_to_remove,  # Default: remove 16 keys (4 complete steps) during truncation
        )

        return agent

    def fix_validation_errors(
        self,
        input_pyspark_code: str,
        validation_errors: List[str],
        critique_feedback: Dict[str, Any],
    ) -> str:
        """Fix the validation errors in the target PySpark file."""
        log.info("Fixing validation errors in the converted PySpark code")

        fix_agent = dspy.ChainOfThought(
            signature=FixValidationErrors,
        )
        result = fix_agent(
            input_pyspark_code=input_pyspark_code,
            validation_errors=validation_errors,
            critique_feedback=critique_feedback,
        )

        return result.fixed_pyspark_code

    def convert(
        self,
        parsed_talend_path: Union[str, Path],
        target_pyspark_path: Union[str, Path],
        validation_enabled: bool = False,
        validation_iterations: int = 2,
    ) -> Dict[str, Any]:
        """Convert a parsed Talend job to PySpark code.

        This is the main entry point for conversion. It uses the DSPy ReAct agent
        to orchestrate the entire conversion process.

        Args:
            parsed_talend_path: Path to the parsed Talend JSON file (output from TalendParser)
            target_pyspark_path: Path where the PySpark .py file should be created
            validation_enabled: Whether to run the validation loop.
        Returns:
            Dictionary containing:
                - status: "success" or "error"
                - target_file: Path to generated PySpark file
                - summary: Conversion summary from agent
                - session_id: Session ID used for conversion
                - errors: Any errors encountered

        Example:
            >>> converter = TalendConverter(llm_config=my_config)
            >>> result = converter.convert(
            ...     "/data/parsed/job_parsed.json",
            ...     "/output/job.py"
            ... )
            >>> print(result["status"])
            "success"
        """
        parsed_talend_path = Path(parsed_talend_path)
        target_pyspark_path = Path(target_pyspark_path)

        log.info("=" * 80)
        log.info("STARTING TALEND TO PYSPARK CONVERSION")
        log.info("=" * 80)
        log.info(f"Input: {parsed_talend_path}")
        log.info(f"Output: {target_pyspark_path}")

        try:
            # Validate input file exists
            if not parsed_talend_path.exists():
                raise FileNotFoundError(
                    f"Parsed Talend file not found: {parsed_talend_path}"
                )
            # Read the parsed Talend code from the file
            parsed_talend_code = read_json(parsed_talend_path)

            # Create target directory if needed
            target_pyspark_path.parent.mkdir(parents=True, exist_ok=True)

            # Invoke the ReAct agent with custom instructions
            log.info("Invoking DSPy ReAct agent for conversion...")

            # Prepare custom instructions string
            custom_instructions_str = (
                self.custom_instructions if self.custom_instructions else ""
            )

            # TODO: Update
            # create a new session id for the conversion
            session_id = self.session_id if self.session_id else create_session()
            log.info(f"Session ID for DSPy ReAct agent: {session_id}")
            if "Error" in session_id:
                raise MigrationAcceleratorToolException(
                    f"Failed to create DSPy session for conversion: {session_id}"
                )

            # Run the ReAct module in loop until the completion status is true
            iteration_count = 0
            old_conversion_trajectory = {}
            while True:
                iteration_count += 1
                log.info(
                    f"Invoking DSPy ReAct agent for iteration {iteration_count}..."
                )
                result = self.iter_agent(
                    parsed_talend_code=parsed_talend_code,
                    target_pyspark_path=str(target_pyspark_path),
                    custom_instructions=custom_instructions_str,
                    session_id=session_id,
                    old_conversion_trajectory=old_conversion_trajectory,
                )

                log.info("=" * 80)
                log.info(f"COMPLETED ITERATION: {iteration_count}")
                log.info(f"Completion Status: {result.completion_status}")
                log.info(f"Conversion Summary: {result.conversion_summary.dict()}")
                log.info("=" * 80)

                log.debug(
                    "Tool calls made after iteration {iteration_count}: Storing that for debugging purposes..."
                )
                traj_file_path = str(
                    target_pyspark_path.parent
                    / f"iter{iteration_count}_{target_pyspark_path.stem}.json"
                )
                write_json_file(traj_file_path, result.trajectory)

                if iteration_count == self.conversion_max_iters:
                    log.info(
                        "Reached maximum number of iterations. Stopping the conversion."
                    )
                    break

                missing_from_converted_filtered = []
                if result.completion_status:
                    nodes_converted = result.conversion_summary.talend_nodes_converted
                    nodes_available = list(parsed_talend_code["content"]["node"].keys())
                    missing_from_converted = set(nodes_available) - set(nodes_converted)
                    exclude_substrings = [
                        "tPrejob",
                        "tPostjob",
                        "tDBConnection",
                        "tDBClose",
                    ]
                    missing_from_converted_filtered = [
                        item
                        for item in missing_from_converted
                        if not any(substr in item for substr in exclude_substrings)
                    ]
                    if missing_from_converted_filtered:
                        log.info(
                            f"The following nodes are missing from the converted list: {missing_from_converted_filtered}"
                        )
                        log.info(
                            "Continuing the conversion to complete the missing nodes."
                        )
                    else:
                        log.info(
                            "All nodes have been converted successfully. Stopping the conversion."
                        )
                        break

                conversion_summary = result.conversion_summary.dict()
                trajectory = result.trajectory
                keys = list(trajectory.keys())
                # truncating the trajectory to last 16 loops
                truncated_trajectory = (
                    trajectory
                    if len(keys) < 16
                    else {key: trajectory[key] for key in keys[:-16]}
                )
                old_conversion_trajectory = {
                    "conversion_summary": conversion_summary,
                    "conversion_trajectory": truncated_trajectory,
                    "nodes_yet_to_convert": missing_from_converted_filtered,
                }

            # Extract final results from the last iteration
            conversion_summary = (
                result.conversion_summary.dict()
                if hasattr(result, "conversion_summary")
                else str(result)
            )

            log.info("Conversion Summary after final iteration:")
            log.info(conversion_summary)

            # Verify output file was created
            if target_pyspark_path.exists():
                file_size = target_pyspark_path.stat().st_size
                log.info(
                    f"Generated PySpark file: {target_pyspark_path} ({file_size} bytes)"
                )
            else:
                log.warning(
                    f"Target PySpark file was not created: {target_pyspark_path}"
                )

            final_summary = {
                "conversion_summary": conversion_summary,
            }

            # Validation loop
            if validation_enabled:
                log.info("Running validation loop...")
                log.info(f"Validation iterations set to: {validation_iterations}")
                validator = TalendValidator(
                    source=parsed_talend_path,
                    target=target_pyspark_path,
                    custom_instructions=custom_instructions_str,
                )

                iteration_count = 0
                while iteration_count < validation_iterations:
                    log.info(
                        f"Running validation loop for iteration {iteration_count + 1}..."
                    )
                    validation_result = validator.validate()

                    if (
                        validation_result.compilation_flag
                        and validation_result.similarity_score >= 0.8
                    ):
                        log.info("Validation loop completed successfully.")
                        final_summary["validation_summary"] = (
                            validation_result.to_dict()
                        )
                        break
                    else:
                        log.error(
                            "Validation loop identified errors in the converted PySpark code. Fixing the errors..."
                        )
                        input_pyspark_str = validator.get_target_content()
                        fixed_pyspark_code = self.fix_validation_errors(
                            input_pyspark_code=input_pyspark_str,
                            validation_errors=validation_result.errors,
                            critique_feedback=validation_result.feedback,
                        )
                        write_file(target_pyspark_path, fixed_pyspark_code)

                    iteration_count += 1

                return {
                    "status": "success",
                    "target_file": str(target_pyspark_path),
                    "summary": final_summary,
                    "errors": None,
                }
            return {
                "status": "success",
                "target_file": str(target_pyspark_path),
                "summary": conversion_summary,
                "errors": None,
            }

        except Exception as e:
            log.error(f"Conversion failed: {e}", exc_info=True)

            return {
                "status": "error",
                "target_file": str(target_pyspark_path),
                "summary": None,
                "errors": str(e),
            }

    def convert_batch(
        self,
        parsed_files: List[Union[str, Path]],
        output_dir: Union[str, Path],
    ) -> List[Dict[str, Any]]:
        """Convert multiple parsed Talend jobs to PySpark.

        Args:
            parsed_files: List of paths to parsed Talend JSON files
            output_dir: Directory where PySpark files should be created

        Returns:
            List of conversion results for each file

        Example:
            >>> converter = TalendConverter(llm_config=my_config)
            >>> results = converter.convert_batch(
            ...     ["/data/job1_parsed.json", "/data/job2_parsed.json"],
            ...     "/output/"
            ... )
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []

        log.info(f"Starting batch conversion of {len(parsed_files)} files")

        for idx, parsed_file in enumerate(parsed_files, 1):
            parsed_path = Path(parsed_file)

            # Generate output filename
            output_filename = parsed_path.stem.replace("_parsed", "") + ".py"
            target_path = output_dir / output_filename

            log.info(f"[{idx}/{len(parsed_files)}] Converting {parsed_path.name}")

            result = self.convert(parsed_path, target_path)
            result["input_file"] = str(parsed_path)
            results.append(result)

        # Summary
        successful = sum(1 for r in results if r["status"] == "success")
        failed = len(results) - successful

        log.info("=" * 80)
        log.info("BATCH CONVERSION COMPLETED")
        log.info(f"Total: {len(results)} | Successful: {successful} | Failed: {failed}")
        log.info("=" * 80)

        return results


# ============================================================================
# Convenience Functions
# ============================================================================


def convert_talend_to_pyspark(
    parsed_talend_path: Union[str, Path],
    target_pyspark_path: Union[str, Path],
    llm_config: Optional[Any] = None,
    custom_instructions: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience function to convert a single Talend job to PySpark.

    Args:
        parsed_talend_path: Path to parsed Talend JSON file
        target_pyspark_path: Path for output PySpark file
        llm_config: Optional LLM configuration
        custom_instructions: Optional custom instructions for conversion

    Returns:
        Conversion result dictionary
    """
    converter = TalendConverter(
        llm_config=llm_config, custom_instructions=custom_instructions
    )
    return converter.convert(parsed_talend_path, target_pyspark_path)
