"""Tools module for agent capabilities.

This module contains tools for both LangGraph agents (with state management)
and DSPy agents (with actual filesystem operations).
"""

# DSPy-compatible tools (with actual filesystem and no state management)
from migration_accelerator.core.tools.dspy_tools import DSPY_TOOLS

# LangGraph tools (with state management and virtual filesystem)
from migration_accelerator.core.tools.files_tools import (
    edit_file,
    grep_file,
    ls,
    read_file,
    read_json_file,
    write_file,
    write_json_file,
)
from migration_accelerator.core.tools.retriever_tools import retrieve_talend_knowledge
from migration_accelerator.core.tools.todo_tools import read_todos, write_todos

__all__ = [
    # LangGraph tools
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "read_json_file",
    "write_json_file",
    "grep_file",
    "write_todos",
    "read_todos",
    "retrieve_talend_knowledge",
    # DSPy tools list
    "DSPY_TOOLS",
]
