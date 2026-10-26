"""Typed, read-only accessors over a Genie ``serialized_space`` document.

The model never mutates or drops data. It is a *view* used by the deterministic
scan; the fix-application path (:mod:`genie_space_iq.fixes`) operates on the raw
dict so that unknown/unrecognized fields survive a round-trip PATCH.

Shape reference (``serialized_space`` version 2, top-level allowlist
``version, config, data_sources, instructions, benchmarks``)::

    config.sample_questions[]        {id, question:[str]}
    data_sources.tables[]            {identifier, description:[str], column_configs[]}
    data_sources.metric_views[]      {identifier, description:[str], column_configs[]}
    column_configs[]                 {column_name, description:[str], synonyms:[str],
                                      exclude, enable_entity_matching,
                                      enable_format_assistance, ...}
    instructions.text_instructions[] {id, content:[str]}   # max 1 block
    instructions.example_question_sqls[] {id, question:[str], sql:[str], usage_guidance:[str]}
    instructions.sql_functions[]     {id, identifier}
    instructions.join_specs[]        {id, left, right, sql:[cond, "--rt=...--"]}
    instructions.sql_snippets        {filters[], expressions[], measures[]}
    benchmarks.questions[]           {id, question:[str], answer:[{format:"SQL", content:[str]}]}
"""

from __future__ import annotations

import json
from typing import Any


def as_str_list(value: Any) -> list[str]:
    """Normalize a Genie text field (``str`` | ``list[str]`` | ``None``) to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def text_is_nonempty(value: Any) -> bool:
    """True when a description/comment-style field carries non-whitespace text."""
    return any(part.strip() for part in as_str_list(value))


def unwrap_serialized_space(document: Any) -> dict[str, Any]:
    """Return the inner ``serialized_space`` dict from any accepted input shape.

    Accepts a raw ``serialized_space`` dict, an API GET response / envelope that
    carries a ``serialized_space`` key (string or dict), or a JSON string of
    either. Unknown sibling fields on the envelope are ignored here (they are
    metadata, not part of the space definition).
    """
    if isinstance(document, str):
        document = json.loads(document)
    if not isinstance(document, dict):
        raise TypeError("space document must be a dict or JSON string")
    if "serialized_space" in document:
        inner = document["serialized_space"]
        if isinstance(inner, str):
            inner = json.loads(inner)
        if not isinstance(inner, dict):
            raise TypeError("serialized_space must decode to an object")
        return inner
    return document


class Column:
    """A single ``column_configs`` entry."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @property
    def column_name(self) -> str:
        return str(self.raw.get("column_name", ""))

    @property
    def description(self) -> list[str]:
        return as_str_list(self.raw.get("description") or self.raw.get("comment"))

    @property
    def has_description(self) -> bool:
        return text_is_nonempty(self.raw.get("description")) or text_is_nonempty(
            self.raw.get("comment")
        )

    @property
    def synonyms(self) -> list[str]:
        return as_str_list(self.raw.get("synonyms"))

    @property
    def enable_entity_matching(self) -> bool:
        return bool(self.raw.get("enable_entity_matching"))

    @property
    def enable_format_assistance(self) -> bool:
        return bool(self.raw.get("enable_format_assistance"))

    @property
    def excluded(self) -> bool:
        return bool(self.raw.get("exclude"))


class Relation:
    """A curated data source: a table or a metric view (identical shape).

    ``kind`` is where the entry was *declared* in ``serialized_space``
    (``data_sources.tables`` vs ``data_sources.metric_views``). ``uc_entry`` is
    the optional Unity Catalog metadata for this identifier -- ``{comment,
    table_type, columns:[{name, comment}]}`` -- which lets the scan (a) classify
    a declared "table" that UC reports as a ``METRIC_VIEW`` and (b) treat a UC
    ``comment`` as an *effective* description even without a space-level override.
    """

    def __init__(self, raw: dict[str, Any], kind: str, uc_entry: dict[str, Any] | None = None):
        self.raw = raw
        self.kind = kind  # declared location: "table" | "metric_view"
        self.uc_entry = uc_entry if isinstance(uc_entry, dict) else None

    @property
    def identifier(self) -> str:
        return str(self.raw.get("identifier", ""))

    @property
    def description(self) -> list[str]:
        return as_str_list(self.raw.get("description") or self.raw.get("comment"))

    @property
    def has_description(self) -> bool:
        """Config-only: a space-level description override (or inline comment)."""
        return text_is_nonempty(self.raw.get("description")) or text_is_nonempty(
            self.raw.get("comment")
        )

    # -- Unity Catalog enrichment ------------------------------------------
    @property
    def uc_table_type(self) -> str | None:
        return self.uc_entry.get("table_type") if self.uc_entry else None

    @property
    def uc_comment(self) -> Any:
        return self.uc_entry.get("comment") if self.uc_entry else None

    @property
    def is_metric_view(self) -> bool:
        """Whether this data source is a metric view.

        Precedence: when UC metadata EXISTS for this entry, classification is
        driven STRICTLY by ``table_type`` -- ``METRIC_VIEW`` is a metric view and
        ANY other type (MANAGED, VIEW, MATERIALIZED_VIEW, STREAMING_TABLE, ...) is
        a regular table -- regardless of which ``data_sources`` bucket it was
        declared under. Only when UC metadata is ABSENT do we fall back to the
        declared bucket (``kind``).
        """
        if self.uc_entry is not None:
            return self.uc_table_type == "METRIC_VIEW"
        return self.kind == "metric_view"

    @property
    def effective_has_description(self) -> bool:
        """Space-level description override OR a non-empty UC comment."""
        return self.has_description or text_is_nonempty(self.uc_comment)

    @property
    def columns(self) -> list[Column]:
        """Columns *configured in the space* (``column_configs``); never UC columns."""
        configs = self.raw.get("column_configs")
        if not isinstance(configs, list):
            return []
        return [Column(c) for c in configs if isinstance(c, dict)]


class Space:
    """Read-only typed view over a ``serialized_space`` (plus optional run info)."""

    def __init__(
        self,
        serialized_space: dict[str, Any],
        optimization_run: dict[str, Any] | None = None,
        space_id: str | None = None,
        uc_metadata: dict[str, Any] | None = None,
    ):
        self.raw = serialized_space
        self.optimization_run = optimization_run
        self.space_id = space_id
        self.uc_metadata = uc_metadata if isinstance(uc_metadata, dict) else None

    @classmethod
    def from_document(
        cls,
        document: Any,
        optimization_run: dict[str, Any] | None = None,
        space_id: str | None = None,
        uc_metadata: dict[str, Any] | None = None,
    ) -> Space:
        """Build a :class:`Space` from any accepted input shape.

        ``optimization_run`` is resolved in priority order:
        explicit argument, envelope sibling key, then a key inside the space.
        ``uc_metadata`` (full-table-name -> UC metadata) is optional; when absent
        the UC-dependent checks fall back to a config-only reading.
        """
        opt = optimization_run
        if isinstance(document, str):
            document = json.loads(document)
        if isinstance(document, dict) and opt is None:
            opt = document.get("optimization_run")
        inner = unwrap_serialized_space(document)
        if opt is None:
            opt = inner.get("optimization_run")
        if opt is not None and not isinstance(opt, dict):
            raise TypeError("optimization_run must be an object")
        return cls(inner, optimization_run=opt, space_id=space_id, uc_metadata=uc_metadata)

    @property
    def uc_available(self) -> bool:
        """True when Unity Catalog metadata was supplied for this scan."""
        return self.uc_metadata is not None

    # -- top-level ----------------------------------------------------------
    @property
    def version(self) -> Any:
        return self.raw.get("version")

    def _list(self, *path: str) -> list[dict[str, Any]]:
        current: Any = self.raw
        for key in path:
            if not isinstance(current, dict):
                return []
            current = current.get(key)
        if not isinstance(current, list):
            return []
        return [item for item in current if isinstance(item, dict)]

    def _relations(self, collection: str, kind: str) -> list[Relation]:
        """Build UC-enriched relations for one ``data_sources`` collection."""
        result: list[Relation] = []
        for raw in self._list("data_sources", collection):
            uc_entry = None
            if self.uc_metadata is not None:
                uc_entry = self.uc_metadata.get(str(raw.get("identifier", "")))
            result.append(Relation(raw, kind, uc_entry=uc_entry))
        return result

    @property
    def _all_relations(self) -> list[Relation]:
        """Every declared data source (tables bucket first, then metric_views)."""
        return self._relations("tables", "table") + self._relations("metric_views", "metric_view")

    @property
    def tables(self) -> list[Relation]:
        """Data sources classified as tables (see :attr:`Relation.is_metric_view`).

        Classification is by UC ``table_type`` when UC metadata exists, else by
        the declared bucket -- so a declared metric view UC types as MANAGED lands
        here, and a declared table UC types as METRIC_VIEW does not.
        """
        return [r for r in self._all_relations if not r.is_metric_view]

    @property
    def metric_views(self) -> list[Relation]:
        """Data sources classified as metric views (see :attr:`Relation.is_metric_view`)."""
        return [r for r in self._all_relations if r.is_metric_view]

    @property
    def relations(self) -> list[Relation]:
        return self.tables + self.metric_views

    @property
    def data_source_identifiers(self) -> list[str]:
        """Every data-source identifier declared in the space (tables + metric views).

        Used by the live path to know which UC tables to fetch; independent of
        UC classification so it works before any UC metadata is available.
        """
        idents: list[str] = []
        for collection in ("tables", "metric_views"):
            for raw in self._list("data_sources", collection):
                ident = str(raw.get("identifier", "")).strip()
                if ident:
                    idents.append(ident)
        return idents

    @property
    def uc_missing_identifiers(self) -> list[str]:
        """Declared data sources with no UC entry (only meaningful when UC is in use).

        Empty when UC metadata was not supplied at all (that is the ``uc_available
        is False`` case, not a partial enrichment).
        """
        if self.uc_metadata is None:
            return []
        return [ident for ident in self.data_source_identifiers if ident not in self.uc_metadata]

    def all_columns(self) -> list[Column]:
        columns: list[Column] = []
        for relation in self.relations:
            columns.extend(relation.columns)
        return columns

    @property
    def text_instructions(self) -> list[dict[str, Any]]:
        return self._list("instructions", "text_instructions")

    @property
    def example_sqls(self) -> list[dict[str, Any]]:
        return self._list("instructions", "example_question_sqls")

    @property
    def join_specs(self) -> list[dict[str, Any]]:
        return self._list("instructions", "join_specs")

    @property
    def sql_functions(self) -> list[dict[str, Any]]:
        return self._list("instructions", "sql_functions")

    @property
    def snippet_filters(self) -> list[dict[str, Any]]:
        return self._list("instructions", "sql_snippets", "filters")

    @property
    def snippet_expressions(self) -> list[dict[str, Any]]:
        return self._list("instructions", "sql_snippets", "expressions")

    @property
    def snippet_measures(self) -> list[dict[str, Any]]:
        return self._list("instructions", "sql_snippets", "measures")

    @property
    def benchmark_questions(self) -> list[dict[str, Any]]:
        return self._list("benchmarks", "questions")

    @property
    def sample_questions(self) -> list[dict[str, Any]]:
        return self._list("config", "sample_questions")

    # -- derived helpers ----------------------------------------------------
    @property
    def data_source_count(self) -> int:
        return len(self.tables) + len(self.metric_views)

    def instruction_text(self) -> str:
        parts: list[str] = []
        for block in self.text_instructions:
            parts.extend(as_str_list(block.get("content")))
        return "".join(parts)
