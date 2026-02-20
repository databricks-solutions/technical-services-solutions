"""This module contains the LLM calls for the migration accelerator."""

from databricks_dspy import DatabricksLM
from databricks_langchain import ChatDatabricks  # type: ignore

from migration_accelerator.configs.modules import LLMConfig
from migration_accelerator.utils.user import get_ws_client


class LLMManager:
    """This class manages the LLM calls for the migration accelerator."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.llm = None
        self.dspy_llm = None
        self.client = get_ws_client()

    def _initialize_llm(self) -> None:
        self.llm = ChatDatabricks(
            endpoint=self.config.endpoint_name,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            client=self.client,
        )

    def _initialize_dspy_llm(self) -> None:
        self.dspy_llm = DatabricksLM(
            model=f"databricks/{self.config.endpoint_name}",
            workspace_client=self.client,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def get_dspy_llm(self) -> DatabricksLM:
        if not self.dspy_llm:
            self._initialize_dspy_llm()
        return self.dspy_llm

    def get_llm(self) -> ChatDatabricks:
        if not self.llm:
            self._initialize_llm()
        return self.llm
