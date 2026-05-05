"""Base class for intent generation.

This module provides the abstract base class for all dialect-specific
intent builders. Intent generation involves analyzing parsed source code
and producing a detailed summary of the ETL logic.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from migration_accelerator.configs.modules import SourceCodeConfig
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class IntentOutput:
    """Structured output for intent generation.

    This class represents the structured intent generated from source code,
    including ETL flow, source/target details, and functional summary.
    """

    def __init__(
        self,
        source_file: str,
        dialect: str,
        etl_flow: Dict[str, Any],
        sources: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        functional_summary: str,
        business_logic: Dict[str, Any],
        dependencies: List[str],
        metadata: Dict[str, Any],
    ):
        """Initialize intent output.

        Args:
            source_file: Path to the source file
            dialect: Source dialect
            etl_flow: ETL flow information
            sources: List of source systems/tables
            targets: List of target systems/tables
            transformations: List of transformations
            functional_summary: High-level functional description
            business_logic: Business logic details
            dependencies: External dependencies
            metadata: Additional metadata
        """
        self.source_file = source_file
        self.dialect = dialect
        self.etl_flow = etl_flow
        self.sources = sources
        self.targets = targets
        self.transformations = transformations
        self.functional_summary = functional_summary
        self.business_logic = business_logic
        self.dependencies = dependencies
        self.metadata = metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert intent output to dictionary.

        Returns:
            Dict[str, Any]: Dictionary representation
        """
        return {
            "source_file": self.source_file,
            "dialect": self.dialect,
            "etl_flow": self.etl_flow,
            "sources": self.sources,
            "targets": self.targets,
            "transformations": self.transformations,
            "functional_summary": self.functional_summary,
            "business_logic": self.business_logic,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
        }


class BaseIntentBuilder(ABC):
    """Base class for all intent builders.

    This class provides common functionality for generating intent from
    parsed source code. Each dialect-specific builder extends this class
    and implements the abstract methods.
    """

    def __init__(
        self,
        source_config: SourceCodeConfig,
        parsed_content_path: Optional[Path] = None,
        use_ai: bool = False,
        llm_config: Optional[Any] = None,
        user_prompt: Optional[str] = None,
    ):
        """Initialize the intent builder.

        Args:
            source_config: Source code configuration
            parsed_content_path: Path to parsed content from previous step
            use_ai: Whether to use AI for intent generation
            llm_config: LLM configuration for AI-powered generation
            user_prompt: Optional user prompt for customization
        """
        self.source_config = source_config
        self.parsed_content_path = parsed_content_path
        self.use_ai = use_ai
        self.llm_config = llm_config
        self.user_prompt = user_prompt
        self.dialect = source_config.source_dialect
        self.source_file = Path(source_config.source_file_path)

        log.info(f"Initialized {self.__class__.__name__} for {self.dialect}")

    def generate_intent(self) -> IntentOutput:
        """Main method to generate intent from source code.

        This orchestrates the entire intent generation process:
        1. Load parsed content
        2. Extract ETL components
        3. Analyze data flow
        4. Generate functional summary
        5. Compile final intent

        Returns:
            IntentOutput: Structured intent output
        """
        log.info(f"Starting intent generation for: {self.source_file}")

        # Step 1: Load parsed content
        parsed_content = self._load_parsed_content()

        # Step 2: Extract ETL components
        etl_components = self._extract_etl_components(parsed_content)

        # Step 3: Extract sources
        sources = self._extract_sources(etl_components)

        # Step 4: Extract targets
        targets = self._extract_targets(etl_components)

        # Step 5: Extract transformations
        transformations = self._extract_transformations(etl_components)

        # Step 6: Analyze data flow
        etl_flow = self._analyze_etl_flow(etl_components)

        # Step 7: Extract business logic
        business_logic = self._extract_business_logic(etl_components)

        # Step 8: Extract dependencies
        dependencies = self._extract_dependencies(etl_components)

        # Step 9: Generate functional summary
        functional_summary = self._generate_functional_summary(
            sources=sources,
            targets=targets,
            transformations=transformations,
            etl_flow=etl_flow,
            business_logic=business_logic,
        )

        # Step 10: Compile metadata
        metadata = self._compile_metadata(parsed_content)

        # Create intent output
        intent = IntentOutput(
            source_file=str(self.source_file),
            dialect=self.dialect,
            etl_flow=etl_flow,
            sources=sources,
            targets=targets,
            transformations=transformations,
            functional_summary=functional_summary,
            business_logic=business_logic,
            dependencies=dependencies,
            metadata=metadata,
        )

        log.info(f"Successfully generated intent for: {self.source_file}")
        return intent

    @abstractmethod
    def _load_parsed_content(self) -> Dict[str, Any]:
        """Load parsed content from the previous parsing step.

        This method should load the parsed content from the location where
        the parser saved it. The format will vary by dialect.

        Returns:
            Dict[str, Any]: Parsed content

        Raises:
            FileNotFoundError: If parsed content not found
        """
        pass

    @abstractmethod
    def _extract_etl_components(self, parsed_content: Dict[str, Any]) -> Dict[str, Any]:
        """Extract ETL components from parsed content.

        This method identifies and extracts key ETL components such as:
        - Data sources (files, tables, APIs)
        - Data targets (files, tables, databases)
        - Transformation steps
        - Business logic

        Args:
            parsed_content: Parsed content from parser

        Returns:
            Dict[str, Any]: Extracted ETL components
        """
        pass

    @abstractmethod
    def _extract_sources(self, etl_components: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract source systems/tables from ETL components.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[Dict[str, Any]]: List of source definitions
                Each source should include:
                - name: Source name
                - type: Source type (file, table, api, etc.)
                - connection: Connection details
                - schema: Schema information (if applicable)
        """
        pass

    @abstractmethod
    def _extract_targets(self, etl_components: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract target systems/tables from ETL components.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[Dict[str, Any]]: List of target definitions
                Each target should include:
                - name: Target name
                - type: Target type (file, table, database, etc.)
                - connection: Connection details
                - schema: Schema information (if applicable)
        """
        pass

    @abstractmethod
    def _extract_transformations(
        self, etl_components: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract transformation logic from ETL components.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[Dict[str, Any]]: List of transformations
                Each transformation should include:
                - name: Transformation name
                - type: Transformation type (map, filter, aggregate, join, etc.)
                - logic: Transformation logic/expression
                - input: Input columns/fields
                - output: Output columns/fields
        """
        pass

    @abstractmethod
    def _analyze_etl_flow(self, etl_components: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the ETL data flow from source to target.

        This method should trace the data flow through the ETL pipeline,
        identifying the sequence of operations.

        Args:
            etl_components: Extracted ETL components

        Returns:
            Dict[str, Any]: ETL flow information
                Should include:
                - flow_type: Type of flow (linear, branching, parallel)
                - steps: Ordered list of processing steps
                - data_lineage: Data lineage from source to target
                - complexity: Complexity metrics
        """
        pass

    @abstractmethod
    def _extract_business_logic(self, etl_components: Dict[str, Any]) -> Dict[str, Any]:
        """Extract business logic from ETL components.

        Args:
            etl_components: Extracted ETL components

        Returns:
            Dict[str, Any]: Business logic details
                Should include:
                - rules: Business rules
                - conditions: Conditional logic
                - calculations: Calculations and formulas
                - validations: Data validation rules
        """
        pass

    @abstractmethod
    def _extract_dependencies(self, etl_components: Dict[str, Any]) -> List[str]:
        """Extract external dependencies.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[str]: List of external dependencies
                (files, libraries, external systems, etc.)
        """
        pass

    @abstractmethod
    def _generate_functional_summary(
        self,
        sources: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        etl_flow: Dict[str, Any],
        business_logic: Dict[str, Any],
    ) -> str:
        """Generate a high-level functional summary.

        This method should produce a human-readable summary of what the
        ETL job does, suitable for documentation or migration planning.

        Args:
            sources: Extracted sources
            targets: Extracted targets
            transformations: Extracted transformations
            etl_flow: Analyzed ETL flow
            business_logic: Extracted business logic

        Returns:
            str: Functional summary in natural language
        """
        pass

    def _compile_metadata(self, parsed_content: Dict[str, Any]) -> Dict[str, Any]:
        """Compile metadata about the intent generation.

        This is a concrete method that can be overridden if needed.

        Args:
            parsed_content: Parsed content

        Returns:
            Dict[str, Any]: Metadata dictionary
        """
        metadata = {
            "source_file": str(self.source_file),
            "dialect": self.dialect,
            "use_ai": self.use_ai,
            "has_parsed_content": bool(parsed_content),
        }

        if parsed_content and "metadata" in parsed_content:
            metadata["source_metadata"] = parsed_content["metadata"]

        return metadata

    def get_summary(self) -> str:
        """Get a summary of the intent builder configuration.

        Returns:
            str: Summary string
        """
        return f"""
        Intent Builder Summary:
        - Dialect: {self.dialect}
        - Source File: {self.source_file.name}
        - Use AI: {self.use_ai}
        - Parsed Content Path: {self.parsed_content_path or 'Not specified'}
        """.strip()
