# flake8: noqa: E501
"""DSPy-compatible tools for file system operations and task management.

This module provides DSPy-compatible versions of all tools, using actual filesystem
instead of virtual filesystem, and removing state management dependencies.
These tools are designed to work with DSPy ReAct agents.
"""

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from migration_accelerator.core.tools.utils import trace_tool_call
from migration_accelerator.utils.environment import get_config_directory
from migration_accelerator.utils.files import read_json, write_json
from migration_accelerator.utils.logger import get_logger

log = get_logger()

# ============================================================================
# Session Management for Concurrent Execution
# ============================================================================

# Base directory for session workspaces
SESSION_BASE_DIR = (get_config_directory() / "dspy_session").as_posix()


def create_session(
    session_id: Optional[str] = None, base_dir: str = SESSION_BASE_DIR
) -> str:
    """Create a unique session workspace for isolated agent execution.

    Use this at the start of agent execution to create an isolated workspace.
    This prevents file conflicts when multiple agents run concurrently.

    Args:
        session_id: Optional session identifier. If not provided, generates a UUID.
        base_dir: Base directory for sessions (default: /tmp/dspy_sessions)

    Returns:
        Session ID that should be used for all subsequent tool calls.

    Examples:
        >>> create_session()
        "550e8400-e29b-41d4-a716-446655440000"

        >>> create_session("user_123_20240115")
        "user_123_20240115"
    """
    try:
        # Generate session ID if not provided
        if session_id is None:
            session_id = str(uuid.uuid4())

        # Create session directory
        session_path = Path(base_dir) / session_id
        session_path.mkdir(parents=True, exist_ok=True)

        # Create session metadata
        metadata = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "base_dir": str(session_path),
            "todos_file": str(session_path / "todos.json"),
            "status": "active",
        }

        metadata_file = session_path / "session_metadata.json"
        write_json(metadata, str(metadata_file))

        return session_id

    except Exception as e:
        return f"Error creating session: {e}"


def get_session_info(session_id: str, base_dir: str = SESSION_BASE_DIR) -> str:
    """Get information about a session workspace.

    Use this to check session details and workspace location.

    Args:
        session_id: The session identifier
        base_dir: Base directory for sessions

    Returns:
        Formatted session information or error message.

    Examples:
        >>> get_session_info("550e8400-e29b-41d4-a716-446655440000")
        "Session ID: 550e8400-e29b-41d4-a716-446655440000
        Status: active
        Created: 2024-01-15T10:30:00
        Workspace: /tmp/dspy_sessions/550e8400-e29b-41d4-a716-446655440000"
    """
    try:
        session_path = Path(base_dir) / session_id
        metadata_file = session_path / "session_metadata.json"

        if not metadata_file.exists():
            return f"Error: Session '{session_id}' not found"

        metadata = read_json(str(metadata_file))

        result = f"""Session ID: {metadata['session_id']}
Status: {metadata['status']}
Created: {metadata['created_at']}
Workspace: {metadata['base_dir']}
TODOs file: {metadata['todos_file']}"""

        return result

    except Exception as e:
        return f"Error getting session info: {e}"


def cleanup_session(session_id: str, base_dir: str = SESSION_BASE_DIR) -> str:
    """Clean up and remove a session workspace.

    Use this when agent execution is complete to free up resources.
    This removes all files created in the session workspace.

    Args:
        session_id: The session identifier to clean up
        base_dir: Base directory for sessions

    Returns:
        Success message or error message.

    Examples:
        >>> cleanup_session("550e8400-e29b-41d4-a716-446655440000")
        "Successfully cleaned up session 550e8400-e29b-41d4-a716-446655440000"
    """
    try:
        session_path = Path(base_dir) / session_id

        if not session_path.exists():
            return f"Session '{session_id}' not found (may already be cleaned up)"

        # Remove entire session directory
        shutil.rmtree(session_path)

        return f"Successfully cleaned up session {session_id}"

    except Exception as e:
        return f"Error cleaning up session: {e}"


def list_active_sessions(base_dir: str = SESSION_BASE_DIR) -> str:
    """List all active sessions.

    Use this to see what sessions are currently active and may need cleanup.

    Args:
        base_dir: Base directory for sessions

    Returns:
        Formatted list of active sessions.
    """
    try:
        base_path = Path(base_dir)

        if not base_path.exists():
            return "No active sessions found"

        sessions = []
        for session_dir in base_path.iterdir():
            if session_dir.is_dir():
                metadata_file = session_dir / "session_metadata.json"
                if metadata_file.exists():
                    metadata = read_json(str(metadata_file))
                    sessions.append(metadata)

        if not sessions:
            return "No active sessions found"

        result = f"Active Sessions ({len(sessions)}):\n\n"
        for session in sessions:
            result += f"  - {session['session_id']}\n"
            result += f"    Created: {session['created_at']}\n"
            result += f"    Status: {session['status']}\n\n"

        return result.strip()

    except Exception as e:
        return f"Error listing sessions: {e}"


def _get_session_path(
    session_id: Optional[str], base_dir: str = SESSION_BASE_DIR
) -> Path:
    """Internal helper to get session path."""
    if session_id is None:
        # Fallback to default for backward compatibility
        return Path("/tmp/dspy_agent_default")
    return Path(base_dir) / session_id


# ============================================================================
# File System Tools (DSPy-compatible versions)
# ============================================================================


@trace_tool_call
def ls(directory_path: str = ".") -> list[str]:
    """List all files and directories in the specified path.

    This tool lists the contents of a directory on the actual filesystem.
    Use this to explore the file system and find the right file to read or edit.

    Args:
        directory_path: Path to directory to list (default: current directory)

    Returns:
        List of file and directory names in the specified path.

    Examples:
        >>> ls(".")
        ['file1.json', 'file2.txt', 'subdir/']

        >>> ls("/dbfs/mnt/data")
        ['input.json', 'output.csv']
    """
    try:
        path = Path(directory_path)
        if not path.exists():
            return [f"Error: Directory '{directory_path}' does not exist"]

        if not path.is_dir():
            return [f"Error: '{directory_path}' is not a directory"]

        # List all items, adding '/' suffix for directories
        items = []
        for item in sorted(path.iterdir()):
            if item.is_dir():
                items.append(f"{item.name}/")
            else:
                items.append(item.name)

        return items
    except PermissionError:
        return [f"Error: Permission denied accessing '{directory_path}'"]
    except Exception as e:
        return [f"Error listing directory '{directory_path}': {e}"]


@trace_tool_call
def read_file(
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Read a file from the actual filesystem with optional line offset and limit.

    Use this to read file contents. You can read the entire file or specify
    an offset and limit for large files.

    Args:
        file_path: Path to the file to read
        offset: Line number to start reading from (0-based)
        limit: Maximum number of lines to read

    Returns:
        File content with line numbers (cat -n format), or error message.
        Lines are numbered starting at 1. Format: "line_number\tline_content"

    Examples:
        >>> read_file("/path/to/file.txt")
        # Returns entire file with line numbers

        >>> read_file("/path/to/large_file.json", offset=100, limit=50)
        # Returns lines 101-150
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return f"Error: File '{file_path}' not found"

        if not path.is_file():
            return f"Error: '{file_path}' is not a file"

        # Read file content
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

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
            return (
                f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"
            )

        # Format output with line numbers (cat -n format)
        result_lines = []
        for i in range(start_idx, end_idx):
            line_content = lines[i]

            # Truncate lines longer than 2000 characters
            if len(line_content) > 2000:
                line_content = line_content[:2000]

            # Line numbers start at 1, so add 1 to the index
            # line_number = i + 1
            # result_lines.append(f"{line_number:6d}\t{line_content}")
            result_lines.append(f"{line_content}")

        return "\n".join(result_lines)

    except UnicodeDecodeError:
        return f"Error: File '{file_path}' is not a text file or has encoding issues"
    except PermissionError:
        return f"Error: Permission denied reading '{file_path}'"
    except Exception as e:
        return f"Error reading file '{file_path}': {e}"


@trace_tool_call
def write_file(file_path: str, content: str) -> str:
    """Write content to a file on the actual filesystem.

    This will create a new file or overwrite an existing file with the provided content.
    Parent directories will be created automatically if they don't exist.

    Args:
        file_path: Path to the file to write
        content: Content to write to the file

    Returns:
        Success message or error message.

    Examples:
        >>> write_file("/path/to/output.txt", "Hello World")
        "Successfully wrote to file '/path/to/output.txt'"
    """
    try:
        path = Path(file_path)

        # Create parent directories if they don't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write content to file
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote to file '{file_path}'"

    except PermissionError:
        return f"Error: Permission denied writing to '{file_path}'"
    except Exception as e:
        return f"Error writing to file '{file_path}': {e}"


@trace_tool_call
def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Edit a file by replacing old_string with new_string.

    Performs exact string replacements in files. The old_string must exist
    in the file and should be unique unless replace_all is True.

    Args:
        file_path: Path to the file to edit
        old_string: The exact string to find and replace
        new_string: The replacement string
        replace_all: If True, replace all occurrences; if False, only replace first occurrence

    Returns:
        Success message with number of replacements, or error message.

    Examples:
        >>> edit_file("/path/to/file.py", "old_value", "new_value")
        "Successfully replaced string in '/path/to/file.py'"

        >>> edit_file("/path/to/config.json", "false", "true", replace_all=True)
        "Successfully replaced 3 instance(s) of the string in '/path/to/config.json'"
    """
    try:
        path = Path(file_path)

        if not path.exists():
            return f"Error: File '{file_path}' not found"

        if not path.is_file():
            return f"Error: '{file_path}' is not a file"

        # Read current file content
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

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

        # Write the updated content back to the file
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return result_msg

    except PermissionError:
        return f"Error: Permission denied editing '{file_path}'"
    except Exception as e:
        return f"Error editing file '{file_path}': {e}"


@trace_tool_call
def read_json_file(file_path: Union[str, list[str]]) -> str:
    """Read one or more JSON files from the filesystem and return as formatted JSON string.

    Use this when you need to read structured JSON data from files.
    The JSON will be returned as a formatted, indented string for easy reading.

    IMPORTANT: While this tool accepts a list of file paths, you should pass AT MOST 4 files
    at a time to avoid overwhelming the context. Minimum is 1 file.

    Args:
        file_path: Either a single path to a JSON file (str) or a list of paths (list[str]).
                   Maximum 4 files recommended per call.

    Returns:
        - If single file: Formatted JSON string (Python dict)
        - If multiple files: Formatted JSON string representing a list of Python dicts,
          where each dict corresponds to the content of each file in order
        - Returns error message if any file doesn't exist or contains invalid JSON

    Examples:
        >>> read_json_file("/path/to/data.json")
        # Returns: {"key": "value", ...}

        >>> read_json_file(["/path/to/file1.json", "/path/to/file2.json"])
        # Returns: [{"content": "from file1"}, {"content": "from file2"}]
    """
    try:
        # Handle single file path
        if isinstance(file_path, str):
            json_data = read_json(file_path)
            # formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
            formatted_json = json.dumps(json_data, separators=(",", ":"))
            return formatted_json

        # Handle list of file paths
        if isinstance(file_path, list):
            # Validate file count
            if len(file_path) == 0:
                return "Error: No file paths provided. Please provide at least 1 file path."

            # if len(file_path) > 4:
            #     return f"Error: Too many files ({len(file_path)}). Provide at most 4 files."

            # Read all files
            results = []
            errors = []

            for idx, path in enumerate(file_path):
                try:
                    json_data = read_json(path)
                    results.append(json_data)
                except FileNotFoundError:
                    errors.append(f"File {idx + 1} ('{path}'): File not found")
                except json.JSONDecodeError as e:
                    errors.append(f"File {idx + 1} ('{path}'): Invalid JSON - {e}")
                except Exception as e:
                    errors.append(f"File {idx + 1} ('{path}'): {e}")

            # If there were any errors, return them
            if errors:
                error_msg = "Errors reading JSON files:\n" + "\n".join(errors)
                if results:
                    error_msg += f"\n\nSuccessfully read {len(results)} out of {len(file_path)} files."
                    error_msg += "\n" + json.dumps(results, separators=(",", ":"))
                return error_msg

            # Format as list of dicts
            formatted_json = json.dumps(results, separators=(",", ":"))
            return formatted_json

    except FileNotFoundError:
        return f"Error: JSON file '{file_path}' not found"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in file '{file_path}': {e}"
    except Exception as e:
        return f"Error reading JSON file(s): {e}"


@trace_tool_call
def write_json_file(file_path: str, json_content: Union[str, dict]) -> str:
    """Write JSON data to the filesystem.

    Accepts either a JSON string or a Python dictionary and writes it to a file
    with proper formatting. Parent directories will be created if they don't exist.

    Args:
        file_path: Path to the JSON file to write
        json_content: Either a JSON string or a Python dictionary

    Returns:
        Success message or error message.

    Examples:
        >>> write_json_file("/path/to/output.json", '{"key": "value"}')
        "Successfully wrote JSON file: /path/to/output.json"

        >>> write_json_file("/path/to/data.json", {"name": "test", "value": 123})
        "Successfully wrote JSON file: /path/to/data.json"
    """
    try:
        # Parse the JSON if it's a string
        if isinstance(json_content, str):
            json_data = json.loads(json_content)
        else:
            json_data = json_content

        # Use the existing write_json utility function
        write_json(json_data, file_path)

        return f"Successfully wrote JSON file: {file_path}"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON string provided: {e}"
    except Exception as e:
        return f"Error writing JSON file '{file_path}': {e}"


@trace_tool_call
def grep_file(
    file_path: str,
    pattern: str,
    case_insensitive: bool = False,
    context_before: int = 0,
    context_after: int = 0,
    max_matches: int = 100,
) -> str:
    """Search for a pattern in a file using regular expressions.

    Use this to quickly find specific content or patterns in files without
    reading the entire file. Supports regex patterns and context lines.

    Args:
        file_path: Path to file to search
        pattern: Regular expression pattern to search for
        case_insensitive: Whether to perform case-insensitive search
        context_before: Number of lines to show before each match
        context_after: Number of lines to show after each match
        max_matches: Maximum number of matches to return (default: 100)

    Returns:
        String containing matching lines with line numbers and context, or error message.
        Format: "line_number: matching_line_content" for matches
                "line_number- context_line_content" for context lines

    Examples:
        >>> grep_file("/path/to/file.py", "def \\w+")
        # Finds all function definitions

        >>> grep_file("/path/to/log.txt", "error", case_insensitive=True, context_after=2)
        # Finds all error messages with 2 lines of context after each
    """
    try:
        path = Path(file_path)

        if not path.exists():
            return f"Error: File '{file_path}' not found"

        if not path.is_file():
            return f"Error: '{file_path}' is not a file"

        # Read file content
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

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
            for i in range(
                match_idx + 1, min(len(lines), match_idx + context_after + 1)
            ):
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

    except UnicodeDecodeError:
        return f"Error: File '{file_path}' is not a text file or has encoding issues"
    except PermissionError:
        return f"Error: Permission denied reading '{file_path}'"
    except Exception as e:
        return f"Error searching file '{file_path}': {e}"


# ============================================================================
# TODO Management Tools (DSPy-compatible versions)
# ============================================================================


@trace_tool_call
def write_todos(
    todos: list[dict],
    session_id: Optional[str] = None,
    base_dir: str = SESSION_BASE_DIR,
) -> str:
    """Create or update a TODO list for task planning and tracking.

    Use this to manage complex tasks by breaking them into smaller steps.
    Each TODO should have 'content' (description) and 'status' (pending/in_progress/completed).
    Uses session-based storage to prevent conflicts in concurrent execution.

    Args:
        todos: List of TODO items. Each item should be a dict with:
               - 'content': str - Description of the task
               - 'status': str - One of: 'pending', 'in_progress', 'completed', 'cancelled'
        session_id: Session ID from create_session(). If None, uses default location.
        base_dir: Base directory for sessions (default: /tmp/dspy_sessions)

    Returns:
        Success message or error message.

    Examples:
        >>> session = create_session()
        >>> write_todos([
        ...     {"content": "Read input file", "status": "completed"},
        ...     {"content": "Process data", "status": "in_progress"},
        ...     {"content": "Write output", "status": "pending"}
        ... ], session_id=session)
        "Successfully updated TODO list with 3 items in session 550e8400-..."
    """
    try:
        # Ensure todos have required fields
        for i, todo in enumerate(todos):
            if "content" not in todo:
                return f"Error: TODO item {i} missing 'content' field"
            if "status" not in todo:
                return f"Error: TODO item {i} missing 'status' field"
            if todo["status"] not in [
                "pending",
                "in_progress",
                "completed",
                "cancelled",
            ]:
                return f"Error: TODO item {i} has invalid status '{todo['status']}'"

        # Get session-specific todos file path
        session_path = _get_session_path(session_id, base_dir)
        session_path.mkdir(parents=True, exist_ok=True)
        todos_file = session_path / "todos.json"

        # Write todos to file
        write_json(todos, str(todos_file))

        session_info = f" in session {session_id}" if session_id else ""
        return f"Successfully updated TODO list with {len(todos)} items{session_info}"

    except Exception as e:
        return f"Error writing TODO list: {e}"


@trace_tool_call
def read_todos(
    session_id: Optional[str] = None, base_dir: str = SESSION_BASE_DIR
) -> str:
    """Read the current TODO list.

    Use this to review your current tasks and track progress through complex workflows.
    Uses session-based storage to read from the correct session workspace.

    Args:
        session_id: Session ID from create_session(). If None, uses default location.
        base_dir: Base directory for sessions (default: /tmp/dspy_sessions)

    Returns:
        Formatted string representation of the current TODO list, or error message.

    Examples:
        >>> session = create_session()
        >>> read_todos(session_id=session)
        "Current TODO List (session: 550e8400-...):
        1. ✅ Read input file (completed)
        2. 🔄 Process data (in_progress)
        3. ⏳ Write output (pending)"
    """
    try:
        # Get session-specific todos file path
        session_path = _get_session_path(session_id, base_dir)
        todos_file = session_path / "todos.json"

        if not todos_file.exists():
            return "No todos currently in the list."

        todos = read_json(str(todos_file))

        if not todos:
            return "No todos currently in the list."

        session_info = f" (session: {session_id[:8]}...)" if session_id else ""
        result = f"Current TODO List{session_info}:\n"
        for i, todo in enumerate(todos, 1):
            status_emoji = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "cancelled": "❌",
            }
            emoji = status_emoji.get(todo.get("status", "pending"), "❓")
            content = todo.get("content", "Unknown task")
            status = todo.get("status", "unknown")
            result += f"{i}. {emoji} {content} ({status})\n"

        return result.strip()

    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in TODO file: {e}"
    except Exception as e:
        return f"Error reading TODO list: {e}"


# ============================================================================
# List all available DSPy tools
# ============================================================================

DSPY_TOOLS = [
    # Session management (use these first for concurrent execution)
    create_session,
    get_session_info,
    cleanup_session,
    list_active_sessions,
    # File system tools
    ls,
    read_file,
    write_file,
    edit_file,
    read_json_file,
    write_json_file,
    grep_file,
    # TODO management tools (session-aware)
    write_todos,
    read_todos,
]
