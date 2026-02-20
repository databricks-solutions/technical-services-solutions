"""Visualization utilities for Intent Generation.

This module provides utilities for visualizing ETL flows using Mermaid diagrams.
"""

from typing import Optional

from migration_accelerator.configs.modules import LLMConfig
from migration_accelerator.core.llms import LLMManager
from migration_accelerator.discovery.intent.base import IntentOutput
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class MermaidDiagramGenerator:
    """Generator for Mermaid diagrams from IntentOutput."""

    def __init__(
        self,
        intent: IntentOutput,
        use_ai: bool = False,
        llm_config: Optional[LLMConfig] = None,
    ):
        """Initialize Mermaid diagram generator.

        Args:
            intent: IntentOutput to visualize
            use_ai: Whether to use AI for enhanced diagram generation
            llm_config: LLM configuration for AI-powered generation
        """
        self.intent = intent
        self.use_ai = use_ai
        self.llm_config = llm_config
        log.info("Initialized MermaidDiagramGenerator")

    def generate_flowchart(self, orientation: str = "TD") -> str:
        """Generate a Mermaid flowchart diagram.

        Args:
            orientation: Flow direction - TD (top-down), LR (left-right),
                        RL (right-left), BT (bottom-top)

        Returns:
            str: Mermaid diagram syntax
        """
        log.info(f"Generating Mermaid flowchart (orientation: {orientation})")

        if self.use_ai and self.llm_config:
            return self._generate_ai_flowchart(orientation)
        else:
            return self._generate_rule_based_flowchart(orientation)

    def _generate_rule_based_flowchart(self, orientation: str) -> str:
        """Generate flowchart using rule-based approach.

        Args:
            orientation: Flow direction

        Returns:
            str: Mermaid diagram syntax
        """
        log.info("Generating rule-based flowchart")

        mermaid = [f"flowchart {orientation}"]

        # Add title
        job_name = self.intent.source_file.split("/")[-1].replace(".item", "")
        mermaid.append(f"    title[{job_name}]")
        mermaid.append("")

        # Define styles
        mermaid.append(
            "    classDef sourceStyle fill:#e1f5e1,stroke:#4caf50,stroke-width:2px"
        )
        mermaid.append(
            "    classDef transformStyle fill:#e3f2fd,stroke:#2196f3,stroke-width:2px"
        )
        mermaid.append(
            "    classDef targetStyle fill:#fff3e0,stroke:#ff9800,stroke-width:2px"
        )
        mermaid.append("")

        # Add sources
        for idx, source in enumerate(self.intent.sources):
            source_id = f"source{idx}"
            source_name = source.get("name", f"Source {idx}")
            source_type = source.get("type", "Unknown")
            mermaid.append(f'    {source_id}[["{source_name}<br/>{source_type}"]]')
            mermaid.append(f"    class {source_id} sourceStyle")

        mermaid.append("")

        # Add transformations
        for idx, transform in enumerate(self.intent.transformations):
            trans_id = f"trans{idx}"
            trans_name = transform.get("name", f"Transform {idx}")
            trans_type = transform.get("type", "Unknown")
            mermaid.append(f'    {trans_id}{{{{"{trans_name}<br/>{trans_type}"}}}}}}')
            mermaid.append(f"    class {trans_id} transformStyle")

        mermaid.append("")

        # Add targets
        for idx, target in enumerate(self.intent.targets):
            target_id = f"target{idx}"
            target_name = target.get("name", f"Target {idx}")
            target_type = target.get("type", "Unknown")
            mermaid.append(f'    {target_id}[["{target_name}<br/>{target_type}"]]')
            mermaid.append(f"    class {target_id} targetStyle")

        mermaid.append("")

        # Add connections (simplified)
        # Sources -> Transformations
        if self.intent.transformations:
            for sidx in range(len(self.intent.sources)):
                mermaid.append(f"    source{sidx} --> trans0")

            # Transformations chain
            for tidx in range(len(self.intent.transformations) - 1):
                mermaid.append(f"    trans{tidx} --> trans{tidx + 1}")

            # Transformations -> Targets
            last_trans = len(self.intent.transformations) - 1
            for tidx in range(len(self.intent.targets)):
                mermaid.append(f"    trans{last_trans} --> target{tidx}")
        else:
            # Direct source to target
            for sidx in range(len(self.intent.sources)):
                for tidx in range(len(self.intent.targets)):
                    mermaid.append(f"    source{sidx} --> target{tidx}")

        return "\n".join(mermaid)

    def _generate_ai_flowchart(self, orientation: str) -> str:
        """Generate flowchart using AI.

        Args:
            orientation: Flow direction

        Returns:
            str: Mermaid diagram syntax
        """
        log.info("Generating AI-powered flowchart")

        if not self.llm_config:
            log.warning("No LLM config provided, falling back to rule-based")
            return self._generate_rule_based_flowchart(orientation)

        # Prepare context for LLM
        context = self._prepare_context_for_llm()

        # Create prompt
        prompt = f"""Generate a Mermaid flowchart diagram for the following ETL job.

Job Information:
{context}

Requirements:
1. Use flowchart {orientation} syntax
2. Include all sources with [[double brackets]] and class sourceStyle
3. Include all transformations with {{{{curly braces}}}} and class transformStyle
4. Include all targets with [[double brackets]] and class targetStyle
5. Show the data flow with arrows (-->)
6. Add labels to arrows if there are conditions or data types
7. Use clear, descriptive node labels
8. Define the styles:
   - classDef sourceStyle fill:#e1f5e1,stroke:#4caf50,stroke-width:2px
   - classDef transformStyle fill:#e3f2fd,stroke:#2196f3,stroke-width:2px
   - classDef targetStyle fill:#fff3e0,stroke:#ff9800,stroke-width:2px

Output ONLY the Mermaid diagram syntax, no explanation or markdown code blocks.
Start with 'flowchart {orientation}' and end with the last connection.
"""

        try:
            llm_manager = LLMManager(self.llm_config)
            model = llm_manager.get_llm()

            response = model.invoke(prompt)

            # Extract content
            if hasattr(response, "content"):
                mermaid_diagram = response.content
            else:
                mermaid_diagram = str(response)

            # Clean up the response
            mermaid_diagram = mermaid_diagram.strip()

            # Remove markdown code blocks if present
            if mermaid_diagram.startswith("```"):
                lines = mermaid_diagram.split("\n")
                # Remove first and last line (```)
                mermaid_diagram = (
                    "\n".join(lines[1:-1]) if len(lines) > 2 else mermaid_diagram
                )

            log.info("Successfully generated AI-powered flowchart")
            return mermaid_diagram

        except Exception as e:
            log.error(f"Error generating AI flowchart: {e}")
            log.warning("Falling back to rule-based generation")
            return self._generate_rule_based_flowchart(orientation)

    def _prepare_context_for_llm(self) -> str:
        """Prepare context for LLM.

        Returns:
            str: Formatted context string
        """
        context_parts = []

        # Job name
        job_name = self.intent.source_file.split("/")[-1]
        context_parts.append(f"Job Name: {job_name}")

        # Sources
        context_parts.append(f"\nSources ({len(self.intent.sources)}):")
        for source in self.intent.sources:
            context_parts.append(f"  - {source.get('name')}: {source.get('type')}")

        # Transformations
        context_parts.append(f"\nTransformations ({len(self.intent.transformations)}):")
        for trans in self.intent.transformations:
            context_parts.append(f"  - {trans.get('name')}: {trans.get('type')}")

        # Targets
        context_parts.append(f"\nTargets ({len(self.intent.targets)}):")
        for target in self.intent.targets:
            context_parts.append(f"  - {target.get('name')}: {target.get('type')}")

        # ETL Flow
        if self.intent.etl_flow:
            context_parts.append("\nETL Flow:")
            context_parts.append(
                f"  Type: {self.intent.etl_flow.get('flow_type', 'unknown')}"
            )
            if "steps" in self.intent.etl_flow:
                context_parts.append(f"  Steps: {len(self.intent.etl_flow['steps'])}")

        # Functional Summary
        if self.intent.functional_summary:
            context_parts.append("\nFunctional Summary:")
            context_parts.append(f"  {self.intent.functional_summary[:200]}...")

        return "\n".join(context_parts)

    def generate_html(self, orientation: str = "TD") -> str:
        """Generate HTML with embedded Mermaid diagram for Databricks display.

        Args:
            orientation: Flow direction

        Returns:
            str: HTML string with Mermaid diagram
        """
        log.info("Generating HTML with Mermaid diagram")

        mermaid_diagram = self.generate_flowchart(orientation)

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            flowchart: {{
                useMaxWidth: true,
                htmlLabels: true,
                curve: 'basis'
            }}
        }});
    </script>
    <style>
        .mermaid {{
            font-family: Arial, sans-serif;
            font-size: 14px;
        }}
        body {{
            padding: 20px;
            background-color: #ffffff;
        }}
        h2 {{
            font-family: Arial, sans-serif;
            color: #333;
        }}
    </style>
</head>
<body>
    <h2>ETL Flow Diagram: {self.intent.source_file.split("/")[-1]}</h2>
    <div class="mermaid">
{mermaid_diagram}
    </div>
</body>
</html>
"""
        return html

    def display_in_databricks(self, orientation: str = "TD") -> None:
        """Display the Mermaid diagram in Databricks notebook.

        This method uses Databricks displayHTML to render the diagram.

        Args:
            orientation: Flow direction

        Example:
            >>> generator = MermaidDiagramGenerator(intent, use_ai=True,
                llm_config=llm_config)
            >>> generator.display_in_databricks()
        """
        log.info("Displaying Mermaid diagram in Databricks")

        html = self.generate_html(orientation)

        try:
            # Import displayHTML (available in Databricks)
            from IPython.display import HTML, display

            display(HTML(html))
            log.info("Successfully displayed diagram in Databricks")
        except ImportError:
            log.warning("IPython.display not available, attempting alternative method")
            try:
                # Try Databricks display
                displayHTML(html)  # noqa: F821
                log.info("Successfully displayed diagram using displayHTML")
            except NameError:
                log.error("Neither IPython.display nor displayHTML available")
                print(
                    """ERROR: Cannot display diagram. Are you running
                in Databricks notebook?"""
                )
                print("\nYou can save the HTML and open it manually:")
                print("```python")
                print("with open('diagram.html', 'w') as f:")
                print("    f.write(generator.generate_html())")
                print("```")

    def save_html(self, output_path: str, orientation: str = "TD") -> str:
        """Save the Mermaid diagram as HTML file.

        Args:
            output_path: Path to save the HTML file
            orientation: Flow direction

        Returns:
            str: Path where file was saved
        """
        log.info(f"Saving Mermaid diagram to: {output_path}")

        html = self.generate_html(orientation)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        log.info(f"Successfully saved diagram to: {output_path}")
        return output_path


def create_mermaid_diagram(
    intent: IntentOutput,
    orientation: str = "TD",
    use_ai: bool = False,
    llm_config: Optional[LLMConfig] = None,
) -> str:
    """Convenience function to create a Mermaid diagram from IntentOutput.

    Args:
        intent: IntentOutput to visualize
        orientation: Flow direction (TD, LR, RL, BT)
        use_ai: Whether to use AI for enhanced diagram generation
        llm_config: LLM configuration for AI-powered generation

    Returns:
        str: Mermaid diagram syntax
    """
    generator = MermaidDiagramGenerator(intent, use_ai, llm_config)
    return generator.generate_flowchart(orientation)


def display_mermaid_in_databricks(
    intent: IntentOutput,
    orientation: str = "TD",
    use_ai: bool = False,
    llm_config: Optional[LLMConfig] = None,
) -> None:
    """Convenience function to display Mermaid diagram in Databricks.

    Args:
        intent: IntentOutput to visualize
        orientation: Flow direction (TD, LR, RL, BT)
        use_ai: Whether to use AI for enhanced diagram generation
        llm_config: LLM configuration for AI-powered generation
    """
    generator = MermaidDiagramGenerator(intent, use_ai, llm_config)
    generator.display_in_databricks(orientation)


__all__ = [
    "MermaidDiagramGenerator",
    "create_mermaid_diagram",
    "display_mermaid_in_databricks",
]
