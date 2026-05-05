"""Talend-specific source code parser.

This module implements a parser specifically designed for Talend XML files.
It extends the BaseSourceCodeParser and provides Talend-specific parsing logic.
"""

import asyncio
from typing import Any, Dict, List

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent

from migration_accelerator.core.llms import LLMManager
from migration_accelerator.core.prompts.base import (
    FILE_USAGE_INSTRUCTIONS,
    TODO_USAGE_INSTRUCTIONS,
)
from migration_accelerator.core.prompts.talend import PARSE_TALEND_NODE_PROMPT
from migration_accelerator.core.state import DeepAgentState
from migration_accelerator.core.tools.files_tools import (
    edit_file,
    read_file,
    write_file,
)
from migration_accelerator.core.tools.todo_tools import read_todos, write_todos
from migration_accelerator.discovery.parser.base import BaseSourceCodeParser
from migration_accelerator.discovery.parser.registry import register_parser
from migration_accelerator.utils.environment import (
    get_migration_accelerator_base_directory,
)
from migration_accelerator.utils.files.reader import read_xml
from migration_accelerator.utils.files.writer import write_json
from migration_accelerator.utils.jupyter.messages import format_messages
from migration_accelerator.utils.logger import get_logger

log = get_logger()


@register_parser("talend")
class TalendParser(BaseSourceCodeParser):
    """Parser for Talend XML source files.

    This parser is specifically designed to handle Talend job files (.item files)
    and extract meaningful information while filtering out Talend-specific
    signature fields and other unnecessary details.
    """

    def _parse_content(self) -> Dict[str, Any]:
        """Parse Talend .item content into structured format.

        Args:
            raw_content: Raw .item content from Talend file

        Returns:
            Dict[str, Any]: Structured Talend content
        """
        log.info("Parsing Talend .item content")

        raw_content = read_xml(self.file_path)

        # Extract main process information
        parsed = {
            "@attributes": raw_content["@attributes"],
            "context": raw_content["context"],
            "node": raw_content["node"],
            "connection": raw_content["connection"],
            "subjob": raw_content["subjob"],
        }

        log.info("Successfully parsed Talend XML content.")

        return parsed

    def _format_content(self, parsed_content: Dict[str, Any]) -> Dict[str, Any]:
        """Clean Talend-specific content by removing signatures and verbose fields.

        Args:
            parsed_content: Parsed Talend content

        Returns:
            Dict[str, Any]: Cleaned content suitable for LLM consumption
        """
        log.info("Cleaning Talend content for LLM consumption")

        formatted = {}

        formatted = {
            "job_info": self._extract_job_info(parsed_content.get("@attributes", {})),
            "context_variables": self._extract_context_variables(
                parsed_content.get("context", {})
            ),
            "node": self._parse_node(parsed_content.get("node", [])),
            "connection": self._extract_connections(
                parsed_content.get("connection", [])
            ),
            "subjob": self._extract_subjobs(parsed_content.get("subjob", [])),
        }

        return formatted

    def _extract_job_info(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Extract basic job information."""
        job_info = {}

        job_info["job_type"] = content.get("jobType", "Standard")

        return job_info

    def _parse_node(
        self,
        content: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Parse a single Talend node/component."""
        component = {}

        node_names = []
        base_dir = get_migration_accelerator_base_directory() / self.file_path.name
        base_dir.mkdir(parents=True, exist_ok=True)

        for node in content:
            for element in node["elementParameter"]:
                if (
                    element["@attributes"]["name"] == "UNIQUE_NAME"
                    and element["@attributes"]["field"] == "TEXT"
                ):
                    node_names.append(element["@attributes"]["value"])
                    node_path = base_dir / f"{element['@attributes']['value']}.json"
                    write_json(node, node_path)
                    component[element["@attributes"]["value"]] = node_path.as_posix()
                    break

        if not self.use_ai:
            return component
        else:
            processed_nodes = asyncio.run(self._process_nodes(content))
            for node_name, processed_node in zip(node_names, processed_nodes):
                if isinstance(processed_node, Exception):
                    log.error(f"Error processing node {node_name}: {processed_node}")
                    component[node_name] = {"error": str(processed_node)}
                else:
                    node_path = base_dir / f"{node_name}.json"
                    write_json(processed_node, node_path)
                    component[node_name] = node_path.as_posix()
            return component

    async def _process_nodes(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process nodes in parallel."""
        process_semaphore = asyncio.Semaphore(self.max_concurrent_requests)

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._process_single_node(node, process_semaphore))
                for node in content
            ]

        processed_nodes = [task.result() for task in tasks]

        return processed_nodes

    async def _process_single_node(
        self, node: Dict[str, Any], semaphore: asyncio.Semaphore
    ) -> Dict[str, Any]:
        """Asynchronously parse a single Talend node/component using AI.

        Args:
            content: Node dictionary to parse
            semaphore: Semaphore to limit concurrent API calls

        Returns:
            Parsed node data
        """
        async with semaphore:
            user_prompt = self.user_prompt.prompt if self.user_prompt else ""
            if not self.llm_config:
                raise ValueError("LLM configuration is required for AI parsing")

            # await asyncio.sleep(20)
            llm_manager = LLMManager(self.llm_config)
            model = llm_manager.get_llm()

            template = """{parse_prompt}

            Below is the Talend ETL Node:
            ```{content}```

            {user_prompt}

            Parse the output in Json Format and don't provide any other text
            Your output should be parsed as a Python dictionary."""

            prompt = ChatPromptTemplate.from_template(template)

            agent = prompt | model | JsonOutputParser()

            parsed_content = await agent.ainvoke(
                {
                    "parse_prompt": PARSE_TALEND_NODE_PROMPT,
                    "content": node,
                    "user_prompt": user_prompt,
                }
            )

            return parsed_content

    def _parse_node_deep_ai(
        self,
        content: Dict[str, Any],
    ) -> Dict[str, Any] | str:
        """Parse a single Talend node/component using AI."""

        user_prompt = self.user_prompt.prompt if self.user_prompt else ""
        if not self.llm_config:
            raise ValueError("LLM configuration is required for AI parsing")

        llm_manager = LLMManager(self.llm_config)
        model = llm_manager.get_llm()

        INSTRUCTIONS = (
            "# TODO MANAGEMENT\n"
            + TODO_USAGE_INSTRUCTIONS
            + "\n\n"
            + "=" * 80
            + "\n\n"
            + "# FILE SYSTEM USAGE\n"
            + FILE_USAGE_INSTRUCTIONS
            + "\n\n"
            + "=" * 80
            + "\n\n"
            + "# TALEND NODE PARSING\n"
            + PARSE_TALEND_NODE_PROMPT
        )

        tools = [read_file, write_file, edit_file, write_todos, read_todos]

        agent = create_react_agent(
            model,
            tools,
            prompt=INSTRUCTIONS,
            state_schema=DeepAgentState,
        )

        prompt = f"""
        Below is the Talend ETL Node:\n\n{content}\n\n{user_prompt}
        Parse the output in Json Format and don't provide any other text
        Your output should be parsed as a Python dictionary."""

        parsed_content = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ]
            }
        )

        format_messages(parsed_content["messages"])
        return parsed_content["messages"][-1].content

    def _extract_connections(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract connections between Talend components."""
        connections = []

        for connection in content:
            if connection["@attributes"]["connectorName"] == "RUN_IF":
                connections.append(
                    {
                        "attributes": {
                            "connectorName": connection["@attributes"]["connectorName"],
                            "label": connection["@attributes"]["label"],
                            "metaname": connection["@attributes"]["metaname"],
                            "source": connection["@attributes"]["source"],
                            "target": connection["@attributes"]["target"],
                        },
                        "elementParameter": {
                            "field": connection["elementParameter"][0]["@attributes"][
                                "field"
                            ],
                            "name": connection["elementParameter"][0]["@attributes"][
                                "name"
                            ],
                            "value": connection["elementParameter"][0]["@attributes"][
                                "value"
                            ],
                        },
                    }
                )
            else:
                connections.append(
                    {
                        "attributes": {
                            "connectorName": connection["@attributes"]["connectorName"],
                            "label": connection["@attributes"]["label"],
                            "metaname": connection["@attributes"]["metaname"],
                            "source": connection["@attributes"]["source"],
                            "target": connection["@attributes"]["target"],
                        },
                    }
                )

        return connections

    def _extract_subjobs(self, content: List[Dict[str, Any]]) -> List[str]:
        """Extract subjob information."""
        subjobs = []

        for subjob in content:
            for element in subjob["elementParameter"]:
                if (
                    element["@attributes"]["name"] == "UNIQUE_NAME"
                    and element["@attributes"]["field"] == "TEXT"
                ):
                    subjobs.append(element["@attributes"]["value"])
                    break

        return subjobs

    def _extract_context_variables(
        self, content: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract context variables."""
        context_vars = []

        if "contextParameter" in content:
            context_params = content["contextParameter"]
            context_vars = [
                {
                    "name": el["@attributes"]["name"],
                    "type": el["@attributes"]["type"],
                    "value": el["@attributes"]["value"],
                }
                for el in context_params
            ]

        return context_vars

    def get_talend_summary(self) -> str:
        """Get a Talend-specific summary."""
        if not self.formatted_content:
            return "Talend job not yet parsed. Call parse() first."

        job_info = self.formatted_content.get("job_info", {})
        components = self.formatted_content.get("components", [])
        connections = self.formatted_content.get("connections", [])

        return f"""
        Talend Job Analysis:
        - Job Name: {job_info.get('name', 'Unknown')}
        - Components: {len(components)}
        - Connections: {len(connections)}
        - Description: {job_info.get('description', 'No description')}
        """.strip()
