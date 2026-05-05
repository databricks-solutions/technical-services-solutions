"""
LLM service for natural language queries.

NOTE: This service is currently reserved for future use.

For analyzer-specific queries, use AnalyzerQueryService instead:
- AnalyzerQueryService.query_single() - Query a single analyzer file
- AnalyzerQueryService.query_multiple() - Query multiple analyzer files

This LLMService provides a generic LLM querying interface that can be
extended for other use cases beyond analyzer queries.
"""

from typing import Any, Dict, Optional

from migration_accelerator.configs.modules import LLMConfig
from migration_accelerator.core.llms import LLMManager
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class LLMService:
    """Service for LLM operations."""

    def __init__(self, llm_endpoint: str):
        """
        Initialize LLM service.

        Args:
            llm_endpoint: LLM endpoint name
        """
        self.llm_config = LLMConfig(
            endpoint_name=llm_endpoint, temperature=0.1, max_tokens=2000
        )
        self.llm_manager = LLMManager(self.llm_config)

    async def query(
        self, question: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Query LLM with a question.

        Args:
            question: Natural language question
            context: Optional context dictionary

        Returns:
            Query response
        """
        try:
            llm = self.llm_manager.get_llm()

            # Format prompt with context if provided
            if context:
                prompt = f"Context: {context}\n\nQuestion: {question}"
            else:
                prompt = question

            # Invoke LLM
            log.info(f"Querying LLM: {question}")
            response = llm.invoke(prompt)

            return {
                "question": question,
                "answer": response.content if hasattr(response, "content") else str(response),
                "model": self.llm_config.endpoint_name,
            }

        except Exception as e:
            log.error(f"Failed to query LLM: {e}")
            raise

    def get_llm(self):
        """Get LLM instance."""
        return self.llm_manager.get_llm()


