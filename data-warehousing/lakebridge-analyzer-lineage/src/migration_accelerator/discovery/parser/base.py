"""Base parser for all discovery parsers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from migration_accelerator.configs.modules import (
    LLMConfig,
    ParserPromptConfig,
    SourceCodeConfig,
)
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class BaseSourceCodeParser(ABC):
    """Base class for all source code parsers.

    This class provides common functionality for parsing source code files
    and extracting structured information that can be consumed by LLMs.
    """

    def __init__(
        self,
        config: SourceCodeConfig,
        user_prompt: Optional[ParserPromptConfig] = None,
        use_ai: Optional[bool] = False,
        llm_config: Optional[LLMConfig] = None,
        max_concurrent_requests: Optional[int] = 5,
    ) -> None:
        """Initialize the parser with configuration.

        Args:
            config: SourceCodeConfig containing file path and dialect info
            user_prompt: Optional[ParserPromptConfig] containing user prompt override
            use_ai: Optional[bool] containing use_ai flag
            llm_config: Optional[LLMConfig] containing LLM configuration
            max_concurrent_requests: Optional[int] containing max concurrent requests
        """
        self.config = config
        self.file_path = Path(config.source_file_path)
        self.dialect = config.source_dialect
        self.formatted_content: Optional[Dict[str, Any]] = None
        self.user_prompt = user_prompt
        self.use_ai = use_ai
        self.llm_config = llm_config
        self.max_concurrent_requests = max_concurrent_requests
        # Validate file exists
        if not self.file_path.exists():
            raise FileNotFoundError(f"Source file not found: {self.file_path}")

    def parse(self) -> Dict[str, Any]:
        """Main parsing method that orchestrates the entire parsing process.

        Returns:
            Dict[str, Any]: Structured representation of the source code
        """
        log.info(f"Starting to parse {self.dialect} file: {self.file_path}")

        # Step 1: Parse content from source file (dialect-specific)
        parsed_content = self._parse_content()

        # Step 2: Clean and format content (dialect-specific)
        self.formatted_content = self._format_content(parsed_content)

        # Step 3: Extract metadata and analyze structure
        # result = {
        #     "metadata": self._extract_metadata(),
        #     "structure": self._analyze_structure(self.formatted_content),
        #     "content": self.formatted_content,
        #     "analysis": self._perform_analysis(self.formatted_content)
        # }
        result = {
            "metadata": self._extract_metadata(),
            "content": self.formatted_content,
        }

        log.info(f"Successfully parsed {self.dialect} file with {len(result)} sections")
        return result

    @abstractmethod
    def _parse_content(self) -> Dict[str, Any]:
        """Parse raw content into structured format.

        This method should be implemented by each dialect-specific parser.

        Returns:
            Dict[str, Any]: Structured content
        """
        pass

    @abstractmethod
    def _format_content(self, parsed_content: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and filter content specific to the dialect.

        This method should remove unnecessary details specific to each dialect.

        Args:
            parsed_content: Parsed content

        Returns:
            Dict[str, Any]: Cleaned content
        """
        pass

    def _extract_metadata(self) -> Dict[str, Any]:
        """Extract metadata about the source file.

        Returns:
            Dict[str, Any]: File metadata
        """
        return {
            "file_path": str(self.file_path),
            "file_name": self.file_path.name,
            "file_size": self.file_path.stat().st_size,
            "file_extension": self.file_path.suffix,
            "dialect": self.dialect,
            "last_modified": self.file_path.stat().st_mtime,
        }

    def _analyze_structure(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the structure of the parsed content.

        Args:
            content: Cleaned content

        Returns:
            Dict[str, Any]: Structure analysis
        """
        structure = {
            "total_elements": self._count_elements(content),
            "depth": self._calculate_depth(content),
            "element_types": self._get_element_types(content),
            "complexity_score": self._calculate_complexity(content),
        }
        return structure

    def _perform_analysis(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Perform automated analysis of the source code.

        Args:
            content: Cleaned content

        Returns:
            Dict[str, Any]: Analysis results
        """
        analysis = {
            "dependencies": self._extract_dependencies(content),
            "data_flows": self._analyze_data_flows(content),
            "transformations": self._identify_transformations(content),
            "connections": self._extract_connections(content),
            "business_logic": self._extract_business_logic(content),
        }
        return analysis

    # Helper methods for analysis
    def _count_elements(
        self, content: Dict[str, Any], visited: Optional[Set] = None
    ) -> int:
        """Recursively count all elements in the content."""
        if visited is None:
            visited = set()

        count = 0
        content_id = id(content)

        if content_id in visited:
            return count
        visited.add(content_id)

        if isinstance(content, dict):
            count += len(content)
            for value in content.values():
                if isinstance(value, (dict, list)):
                    count += self._count_elements(value, visited)
        elif isinstance(content, list):
            count += len(content)
            for item in content:
                if isinstance(item, (dict, list)):
                    count += self._count_elements(item, visited)

        return count

    def _calculate_depth(self, content: Dict[str, Any], current_depth: int = 0) -> int:
        """Calculate the maximum depth of nested structures."""
        if not isinstance(content, (dict, list)):
            return current_depth

        max_depth = current_depth

        if isinstance(content, dict):
            for value in content.values():
                depth = self._calculate_depth(value, current_depth + 1)
                max_depth = max(max_depth, depth)
        elif isinstance(content, list):
            for item in content:
                depth = self._calculate_depth(item, current_depth + 1)
                max_depth = max(max_depth, depth)

        return max_depth

    def _get_element_types(self, content: Dict[str, Any]) -> Dict[str, int]:
        """Get count of different element types."""
        types = {}

        def count_types(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    types[key] = types.get(key, 0) + 1
                    count_types(value)
            elif isinstance(obj, list):
                for item in obj:
                    count_types(item)

        count_types(content)
        return types

    def _calculate_complexity(self, content: Dict[str, Any]) -> float:
        """Calculate a complexity score based on structure."""
        element_count = self._count_elements(content)
        depth = self._calculate_depth(content)
        type_variety = len(self._get_element_types(content))

        # Simple complexity score formula
        complexity = (element_count * 0.1) + (depth * 2) + (type_variety * 0.5)
        return round(complexity, 2)

    def _extract_dependencies(self, content: Dict[str, Any]) -> List[str]:
        """Extract dependencies from the source code."""
        # Base implementation - can be overridden by dialect-specific parsers
        dependencies = []

        def find_dependencies(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    if key.lower() in ["import", "include", "reference", "dependency"]:
                        if isinstance(value, str):
                            dependencies.append(value)
                        elif isinstance(value, list):
                            dependencies.extend([str(v) for v in value if v])
                    find_dependencies(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_dependencies(item, f"{path}[{i}]")

        find_dependencies(content)
        return list(set(dependencies))  # Remove duplicates

    def _analyze_data_flows(self, content: Dict[str, Any]) -> List[Dict[str, str]]:
        """Analyze data flows in the source code."""
        # Base implementation - should be overridden by specific parsers
        flows = []

        def find_flows(obj, path=""):
            if isinstance(obj, dict):
                source = obj.get("source") or obj.get("input") or obj.get("from")
                target = obj.get("target") or obj.get("output") or obj.get("to")

                if source and target:
                    flows.append(
                        {"source": str(source), "target": str(target), "path": path}
                    )

                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    find_flows(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_flows(item, f"{path}[{i}]")

        find_flows(content)
        return flows

    def _identify_transformations(self, content: Dict[str, Any]) -> List[str]:
        """Identify transformations in the source code."""
        transformations = []

        def find_transformations(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if any(
                        keyword in key.lower()
                        for keyword in [
                            "transform",
                            "convert",
                            "map",
                            "filter",
                            "aggregate",
                            "join",
                        ]
                    ):
                        transformations.append(key)
                    find_transformations(value)
            elif isinstance(obj, list):
                for item in obj:
                    find_transformations(item)

        find_transformations(content)
        return list(set(transformations))

    def _extract_connections(self, content: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract connection information."""
        connections = []

        def find_connections(obj, path=""):
            if isinstance(obj, dict):
                if any(
                    key.lower() in ["connection", "database", "server", "host", "url"]
                    for key in obj.keys()
                ):
                    conn_info = {}
                    for key, value in obj.items():
                        if key.lower() in [
                            "host",
                            "server",
                            "database",
                            "schema",
                            "table",
                            "url",
                        ]:
                            conn_info[key] = str(value)
                    if conn_info:
                        conn_info["path"] = path
                        connections.append(conn_info)

                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    find_connections(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_connections(item, f"{path}[{i}]")

        find_connections(content)
        return connections

    def _extract_business_logic(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Extract business logic patterns."""
        logic = {"conditions": [], "loops": [], "functions": [], "variables": []}

        def find_logic(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = key.lower()
                    if "condition" in key_lower or "if" in key_lower:
                        logic["conditions"].append({"key": key, "path": path})
                    elif (
                        "loop" in key_lower
                        or "for" in key_lower
                        or "while" in key_lower
                    ):
                        logic["loops"].append({"key": key, "path": path})
                    elif "function" in key_lower or "method" in key_lower:
                        logic["functions"].append({"key": key, "path": path})
                    elif "variable" in key_lower or "param" in key_lower:
                        logic["variables"].append(
                            {"key": key, "path": path, "value": str(value)}
                        )

                    current_path = f"{path}.{key}" if path else key
                    find_logic(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_logic(item, f"{path}[{i}]")

        find_logic(content)
        return logic

    def get_summary(self) -> str:
        """Get a human-readable summary of the parsed content."""
        if not self.formatted_content:
            return "File not yet parsed. Call parse() first."

        # This will be used later for LLM consumption
        metadata = self._extract_metadata()
        structure = self._analyze_structure(self.formatted_content)

        return f"""
        Source Code Analysis Summary:
        - File: {metadata['file_name']} ({metadata['dialect']})
        - Size: {metadata['file_size']} bytes
        - Elements: {structure['total_elements']}
        - Depth: {structure['depth']}
        - Complexity: {structure['complexity_score']}
        """.strip()
