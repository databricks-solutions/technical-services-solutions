# flake8: noqa: E501
"""Virtual file system tools for agent state management.

This module provides tools for managing a virtual filesystem stored in agent state,
enabling context offloading and information persistence across agent interactions.
"""

import json
import re
from typing import Annotated, Union

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from migration_accelerator.core.prompts.base import (
    EDIT_FILE_TOOL_DESCRIPTION,
    GREP_FILE_TOOL_DESCRIPTION,
    LIST_FILES_TOOL_DESCRIPTION,
    READ_FILE_TOOL_DESCRIPTION,
    READ_JSON_FILE_TOOL_DESCRIPTION,
    WRITE_FILE_TOOL_DESCRIPTION,
    WRITE_JSON_FILE_TOOL_DESCRIPTION,
)
from migration_accelerator.core.state import DeepAgentState
from migration_accelerator.utils.files import read_json, write_json


@tool(description=LIST_FILES_TOOL_DESCRIPTION)
def ls(state: Annotated[DeepAgentState, InjectedState]) -> list[str]:
    """List all files"""
    return list(state.get("files", {}).keys())


@tool(description=READ_FILE_TOOL_DESCRIPTION)
def read_file(
    file_path: str,
    state: Annotated[DeepAgentState, InjectedState],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    mock_filesystem = state.get("files", {})
    if file_path not in mock_filesystem:
        return f"Error: File '{file_path}' not found"

    # Get file content
    content = mock_filesystem[file_path]

    # Handle empty file
    if not content or content.strip() == "":
        return "System reminder: File exists but has empty contents"

    # Split content into lines
    lines = content.splitlines()

    # Apply line offset and limit
    start_idx = offset
    end_idx = min(start_idx + limit, len(lines))

    # Handle case where offset is beyond file length
    if start_idx >= len(lines):
        return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

    # Format output with line numbers (cat -n format)
    result_lines = []
    for i in range(start_idx, end_idx):
        line_content = lines[i]

        # Truncate lines longer than 2000 characters
        if len(line_content) > 2000:
            line_content = line_content[:2000]

        # Line numbers start at 1, so add 1 to the index
        line_number = i + 1
        result_lines.append(f"{line_number:6d}\t{line_content}")

    return "\n".join(result_lines)


@tool(description=WRITE_FILE_TOOL_DESCRIPTION)
def write_file(
    file_path: str,
    content: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    files = state.get("files", {})
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)
            ],
        }
    )


@tool(description=EDIT_FILE_TOOL_DESCRIPTION)
def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    replace_all: bool = False,
) -> Union[Command, str]:
    """Write to a file."""
    mock_filesystem = state.get("files", {})
    # Check if file exists in mock filesystem
    if file_path not in mock_filesystem:
        return f"Error: File '{file_path}' not found"

    # Get current file content
    content = mock_filesystem[file_path]

    # Check if old_string exists in the file
    if old_string not in content:
        return f"Error: String not found in file: '{old_string}'"

    # If not replace_all, check for uniqueness
    if not replace_all:
        occurrences = content.count(old_string)
        if occurrences > 1:
            return f"Error: String '{old_string}' appears {occurrences} times in file. Use replace_all=True to replace all instances, or provide a more specific string with surrounding context."
        elif occurrences == 0:
            return f"Error: String not found in file: '{old_string}'"

    # Perform the replacement
    if replace_all:
        new_content = content.replace(old_string, new_string)
        replacement_count = content.count(old_string)
        result_msg = f"Successfully replaced {replacement_count} instance(s) of the string in '{file_path}'"
    else:
        new_content = content.replace(
            old_string, new_string, 1
        )  # Replace only first occurrence
        result_msg = f"Successfully replaced string in '{file_path}'"

    # Update the mock filesystem
    mock_filesystem[file_path] = new_content
    return Command(
        update={
            "files": mock_filesystem,
            "messages": [ToolMessage(result_msg, tool_call_id=tool_call_id)],
        }
    )


@tool(description=READ_JSON_FILE_TOOL_DESCRIPTION)
def read_json_file(file_path: str) -> str:
    """Read a JSON file from the actual filesystem and return as formatted JSON string."""
    try:
        # Use the existing read_json utility function
        json_data = read_json(file_path)

        # Format the JSON data as a multi-line string for LLM comprehension
        formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)

        return formatted_json
    except FileNotFoundError:
        return f"Error: JSON file '{file_path}' not found"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in file '{file_path}': {e}"
    except Exception as e:
        return f"Error reading JSON file '{file_path}': {e}"


@tool(description=WRITE_JSON_FILE_TOOL_DESCRIPTION)
def write_json_file(
    file_path: str,
    json_content: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Union[Command, str]:
    """Write JSON data to the actual filesystem after parsing the provided JSON string."""
    try:
        # Parse the JSON string provided by the LLM
        json_data = json.loads(json_content)

        # Use the existing write_json utility function
        write_json(json_data, file_path)

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Successfully wrote JSON file: {file_path}",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON string provided: {e}"
    except Exception as e:
        return f"Error writing JSON file '{file_path}': {e}"


@tool(description=GREP_FILE_TOOL_DESCRIPTION)
def grep_file(
    file_path: str,
    pattern: str,
    state: Annotated[DeepAgentState, InjectedState],
    case_insensitive: bool = False,
    context_before: int = 0,
    context_after: int = 0,
    max_matches: int = 100,
) -> str:
    """Search for a pattern in a file from the virtual filesystem using regular expressions.

    Args:
        file_path: Path to file in virtual filesystem
        pattern: Regular expression pattern to search for
        state: Agent state containing the virtual filesystem
        case_insensitive: Whether to perform case-insensitive search
        context_before: Number of lines to show before each match
        context_after: Number of lines to show after each match
        max_matches: Maximum number of matches to return (default: 100)

    Returns:
        String containing matching lines with line numbers and context, or error message
    """
    mock_filesystem = state.get("files", {})

    # Check if file exists
    if file_path not in mock_filesystem:
        return f"Error: File '{file_path}' not found in virtual filesystem"

    # Get file content
    content = mock_filesystem[file_path]

    # Handle empty file
    if not content or content.strip() == "":
        return f"Error: File '{file_path}' is empty"

    # Split content into lines
    lines = content.splitlines()

    # Compile regex pattern
    try:
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern '{pattern}': {e}"

    # Find all matching lines
    matched_line_numbers = set()

    for line_idx, line in enumerate(lines):
        if regex.search(line):
            matched_line_numbers.add(line_idx)

    # If no matches found
    if not matched_line_numbers:
        return f"No matches found for pattern '{pattern}' in file '{file_path}'"

    # Limit number of matches
    if len(matched_line_numbers) > max_matches:
        matched_line_numbers = set(sorted(matched_line_numbers)[:max_matches])
        truncated = True
    else:
        truncated = False

    # Build output with context
    output_lines = []
    lines_to_show = set()

    # Determine which lines to show (matches + context)
    for match_idx in matched_line_numbers:
        # Add context before
        for i in range(max(0, match_idx - context_before), match_idx):
            lines_to_show.add(i)
        # Add the match itself
        lines_to_show.add(match_idx)
        # Add context after
        for i in range(match_idx + 1, min(len(lines), match_idx + context_after + 1)):
            lines_to_show.add(i)

    # Convert to sorted list for sequential output
    lines_to_show = sorted(lines_to_show)

    # Format output
    prev_line_idx = -2  # Initialize to detect gaps
    for line_idx in lines_to_show:
        # Add separator if there's a gap
        if line_idx > prev_line_idx + 1:
            output_lines.append("--")

        # Line numbers start at 1
        line_number = line_idx + 1

        # Mark matching lines with ':' and context lines with '-'
        marker = ":" if line_idx in matched_line_numbers else "-"

        # Format: line_number marker content
        output_lines.append(f"{line_number:6d}{marker} {lines[line_idx]}")

        prev_line_idx = line_idx

    # Add header with match count
    header = f"Found {len(matched_line_numbers)} match(es) for pattern '{pattern}' in '{file_path}'"
    if truncated:
        header += f" (showing first {max_matches} matches)"
    if context_before > 0 or context_after > 0:
        header += (
            f" (with {context_before} lines before and {context_after} lines after)"
        )

    result = header + "\n\n" + "\n".join(output_lines)

    return result
