"""Deterministic application of caller-drafted fixes to a ``serialized_space``.

There is **no LLM** here. The host agent drafts the fix content; this module
validates it, applies it to a deep copy of the space, and preserves every
unknown/unrecognized field so a round-trip PATCH is loss-free.

Determinism: ids for newly appended entries are derived from a content hash
(``sha256(canonical_json)[:32]`` -> 32 lowercase hex chars, matching Genie's id
format) rather than a random UUID, so ``apply_fixes`` is a pure function of its
inputs. A caller may override any generated id by supplying ``"id"`` in
``new_value``.

fixes.json schema -- a JSON array (or ``{"fixes": [...]}``) of objects::

    {
      "check_id": <int 1-12, optional>,     # which scan check this addresses
      "operation": "<operation name>",       # required; see OPERATIONS
      "target": { ... },                     # locator; keys depend on operation
      "new_value": <value>,                  # payload; shape depends on operation
      "rationale": "<free text, optional>"
    }

Operations and their (target / new_value) contracts are documented in
:data:`OPERATIONS` and in scripts/README.md.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
from collections.abc import Callable
from typing import Any


class FixValidationError(ValueError):
    """Raised when a fixes payload is malformed."""


class FixApplicationError(ValueError):
    """Raised when a valid fix cannot be applied (e.g. missing target)."""


# -- small helpers ---------------------------------------------------------

def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _as_line_list(value: Any) -> list[str]:
    """Split SQL text into a list of lines (keep list input verbatim)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    text = str(value)
    lines = text.splitlines(keepends=True)
    return lines or [text]


def _as_content_lines(value: Any) -> list[str]:
    """Normalize text-instruction content; each element must end with ``\\n``."""
    items = _as_str_list(value)
    return [item if item.endswith("\n") else item + "\n" for item in items]


def _deterministic_id(payload: Any) -> str:
    """Stable 32-char lowercase-hex id derived from the entry content."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _ensure_dict(root: dict[str, Any], *keys: str) -> dict[str, Any]:
    current = root
    for key in keys:
        existing = current.get(key)
        if existing is None:
            current[key] = {}
            existing = current[key]
        elif not isinstance(existing, dict):
            kind = type(existing).__name__
            raise FixApplicationError(f"expected object at '{key}', found {kind}")
        current = existing
    return current


def _ensure_list(root: dict[str, Any], *keys: str) -> list[Any]:
    parent = _ensure_dict(root, *keys[:-1])
    last = keys[-1]
    existing = parent.get(last)
    if existing is None:
        parent[last] = []
        existing = parent[last]
    elif not isinstance(existing, list):
        raise FixApplicationError(f"expected list at '{last}', found {type(existing).__name__}")
    return existing


def _find_relation(space: dict[str, Any], identifier: str) -> dict[str, Any]:
    data_sources = space.get("data_sources")
    if isinstance(data_sources, dict):
        for collection in ("tables", "metric_views"):
            entries = data_sources.get(collection)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("identifier") == identifier:
                        return entry
    raise FixApplicationError(f"data source not found: {identifier!r}")


def _find_or_create_column(relation: dict[str, Any], column_name: str) -> dict[str, Any]:
    configs = relation.get("column_configs")
    if not isinstance(configs, list):
        configs = []
        relation["column_configs"] = configs
    for entry in configs:
        if isinstance(entry, dict) and entry.get("column_name") == column_name:
            return entry
    new_col = {"column_name": column_name}
    configs.append(new_col)
    return new_col


def _require(target: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if not target.get(k)]
    if missing:
        raise FixApplicationError(f"target missing required key(s): {', '.join(missing)}")


# -- operation handlers ----------------------------------------------------

def _op_set_table_description(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "identifier")
    relation = _find_relation(space, target["identifier"])
    relation["description"] = _as_str_list(value)


def _op_set_column_description(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "identifier", "column_name")
    relation = _find_relation(space, target["identifier"])
    column = _find_or_create_column(relation, target["column_name"])
    column["description"] = _as_str_list(value)


def _op_add_column_synonyms(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "identifier", "column_name")
    relation = _find_relation(space, target["identifier"])
    column = _find_or_create_column(relation, target["column_name"])
    existing = _as_str_list(column.get("synonyms"))
    additions = [s for s in _as_str_list(value) if s not in existing]
    column["synonyms"] = existing + additions


def _op_enable_entity_matching(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "identifier", "column_name")
    relation = _find_relation(space, target["identifier"])
    column = _find_or_create_column(relation, target["column_name"])
    enabled = True if value is None else bool(value)
    column["enable_entity_matching"] = enabled
    if enabled:
        # Entity matching requires format assistance in the Genie space schema.
        column.setdefault("enable_format_assistance", True)


def _op_enable_format_assistance(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "identifier", "column_name")
    relation = _find_relation(space, target["identifier"])
    column = _find_or_create_column(relation, target["column_name"])
    column["enable_format_assistance"] = True if value is None else bool(value)


def _op_set_text_instruction(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    content = _as_content_lines(value)
    instructions = _ensure_dict(space, "instructions")
    existing = instructions.get("text_instructions")
    if isinstance(existing, list) and existing and isinstance(existing[0], dict):
        entry = dict(existing[0])  # preserve id + any unknown keys on the block
        entry["content"] = content
        entry.setdefault("id", _deterministic_id({"content": content}))
    else:
        entry_id = (target or {}).get("id") or _deterministic_id({"content": content})
        entry = {"id": entry_id, "content": content}
    instructions["text_instructions"] = [entry]  # max 1 block


def _op_add_example_sql(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        raise FixApplicationError("add_example_sql new_value must be an object")
    entry: dict[str, Any] = {
        "question": _as_str_list(value.get("question")),
        "sql": _as_line_list(value.get("sql")),
    }
    if value.get("usage_guidance"):
        entry["usage_guidance"] = _as_str_list(value.get("usage_guidance"))
    if value.get("parameters"):
        entry["parameters"] = copy.deepcopy(value["parameters"])
    entry["id"] = value.get("id") or _deterministic_id(entry)
    _ensure_list(space, "instructions", "example_question_sqls").append(entry)


def _op_add_join_spec(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        raise FixApplicationError("add_join_spec new_value must be an object")
    for key in ("left", "right", "sql"):
        if not value.get(key):
            raise FixApplicationError(f"add_join_spec new_value missing '{key}'")
    entry: dict[str, Any] = {
        "left": copy.deepcopy(value["left"]),
        "right": copy.deepcopy(value["right"]),
        "sql": _as_str_list(value["sql"]),
    }
    for optional in ("comment", "instruction"):
        if value.get(optional):
            entry[optional] = copy.deepcopy(value[optional])
    entry["id"] = value.get("id") or _deterministic_id(entry)
    _ensure_list(space, "instructions", "join_specs").append(entry)


def _op_add_sql_snippet(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "kind")
    kind = target["kind"]
    collection = {"filter": "filters", "expression": "expressions", "measure": "measures"}.get(kind)
    if collection is None:
        raise FixApplicationError(f"unknown sql snippet kind: {kind!r}")
    if not isinstance(value, dict):
        raise FixApplicationError("add_sql_snippet new_value must be an object")
    entry = copy.deepcopy(value)
    entry["sql"] = _as_str_list(entry.get("sql"))
    if "synonyms" in entry:
        entry["synonyms"] = _as_str_list(entry["synonyms"])
    if "instruction" in entry:
        entry["instruction"] = _as_str_list(entry["instruction"])
    if not entry.get("id"):
        entry["id"] = _deterministic_id({k: v for k, v in entry.items() if k != "id"})
    _ensure_list(space, "instructions", "sql_snippets", collection).append(entry)


def _op_add_sql_function(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    identifier = value.get("identifier") if isinstance(value, dict) else value
    if not identifier:
        raise FixApplicationError("add_sql_function requires an identifier")
    entry = {"identifier": str(identifier)}
    entry["id"] = _deterministic_id(entry)
    _ensure_list(space, "instructions", "sql_functions").append(entry)


def _op_add_benchmark_question(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        raise FixApplicationError("add_benchmark_question new_value must be an object")
    if not value.get("question") or not value.get("sql"):
        raise FixApplicationError("add_benchmark_question requires 'question' and 'sql'")
    entry: dict[str, Any] = {
        "question": _as_str_list(value["question"]),
        "answer": [{"format": "SQL", "content": _as_line_list(value["sql"])}],
    }
    entry["id"] = value.get("id") or _deterministic_id(entry)
    _ensure_list(space, "benchmarks", "questions").append(entry)


def _op_add_sample_question(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    question = value.get("question") if isinstance(value, dict) else value
    entry: dict[str, Any] = {"question": _as_str_list(question)}
    supplied_id = value.get("id") if isinstance(value, dict) else None
    entry["id"] = supplied_id or _deterministic_id(entry)
    _ensure_list(space, "config", "sample_questions").append(entry)


def _set_value_at_path(root: dict[str, Any], path: str, value: Any) -> None:
    """Dot/bracket path setter, e.g. ``data_sources.tables[0].description``."""
    tokens: list[Any] = []
    for segment in path.split("."):
        name, _, remainder = segment.partition("[")
        if name:
            tokens.append(name)
        while remainder:
            index_str, _, rest = remainder.partition("]")
            tokens.append(int(index_str))
            _, _, remainder = rest.partition("[")
    if not tokens:
        raise FixApplicationError(f"invalid field path: {path!r}")
    current: Any = root
    for token in tokens[:-1]:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise FixApplicationError(f"index out of range in path: {path!r}")
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                raise FixApplicationError(f"missing key '{token}' in path: {path!r}")
            current = current[token]
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(current, list) or last >= len(current):
            raise FixApplicationError(f"index out of range in path: {path!r}")
        current[last] = value
    else:
        if not isinstance(current, dict):
            raise FixApplicationError(f"cannot set key '{last}' in path: {path!r}")
        current[last] = value


def _op_set_field(space: dict[str, Any], target: dict[str, Any], value: Any) -> None:
    _require(target, "path")
    _set_value_at_path(space, target["path"], value)


# operation name -> {apply, needs_value, description}
OPERATIONS: dict[str, dict[str, Any]] = {
    "set_table_description": {
        "apply": _op_set_table_description,
        "needs_value": True,
        "description": "Set data_sources table/metric_view description. target={identifier}.",
    },
    "set_column_description": {
        "apply": _op_set_column_description,
        "needs_value": True,
        "description": "Set a column description. target={identifier, column_name}.",
    },
    "add_column_synonyms": {
        "apply": _op_add_column_synonyms,
        "needs_value": True,
        "description": "Append column synonyms (existing kept). target={identifier, column_name}.",
    },
    "enable_entity_matching": {
        "apply": _op_enable_entity_matching,
        "needs_value": False,
        "description": "Enable entity matching + format assist. target={identifier, column_name}.",
    },
    "enable_format_assistance": {
        "apply": _op_enable_format_assistance,
        "needs_value": False,
        "description": "Enable format assistance on a column. target={identifier, column_name}.",
    },
    "set_text_instruction": {
        "apply": _op_set_text_instruction,
        "needs_value": True,
        "description": "Replace the single text-instruction block (content lines end with \\n).",
    },
    "add_example_sql": {
        "apply": _op_add_example_sql,
        "needs_value": True,
        "description": "Append an example question/SQL pair. new_value={question, sql}.",
    },
    "add_join_spec": {
        "apply": _op_add_join_spec,
        "needs_value": True,
        "description": "Append a join spec. new_value={left, right, sql:[cond, '--rt=...--']}.",
    },
    "add_sql_snippet": {
        "apply": _op_add_sql_snippet,
        "needs_value": True,
        "description": "Append a sql_snippet. target={kind: filter|expression|measure}.",
    },
    "add_sql_function": {
        "apply": _op_add_sql_function,
        "needs_value": True,
        "description": "Append a TVF/function reference. new_value={identifier} or a string.",
    },
    "add_benchmark_question": {
        "apply": _op_add_benchmark_question,
        "needs_value": True,
        "description": "Append a benchmark question. new_value={question, sql}.",
    },
    "add_sample_question": {
        "apply": _op_add_sample_question,
        "needs_value": True,
        "description": "Append a user-facing sample question. new_value={question} or a string.",
    },
    "set_field": {
        "apply": _op_set_field,
        "needs_value": True,
        "description": "Advanced: set a raw dot/bracket path. target={path}.",
    },
}


def validate_fixes(fixes: Any) -> list[dict[str, Any]]:
    """Validate a fixes payload; return the normalized list of fix objects.

    Raises :class:`FixValidationError` with the offending index on any problem.
    """
    if isinstance(fixes, dict) and "fixes" in fixes:
        fixes = fixes["fixes"]
    if not isinstance(fixes, list):
        raise FixValidationError("fixes must be a JSON array (or {'fixes': [...]})")
    for i, fix in enumerate(fixes):
        if not isinstance(fix, dict):
            raise FixValidationError(f"fix[{i}] must be an object")
        operation = fix.get("operation")
        if operation not in OPERATIONS:
            raise FixValidationError(
                f"fix[{i}] has unknown operation {operation!r}; "
                f"valid: {', '.join(sorted(OPERATIONS))}"
            )
        target = fix.get("target")
        if target is not None and not isinstance(target, dict):
            raise FixValidationError(f"fix[{i}].target must be an object")
        if OPERATIONS[operation]["needs_value"] and "new_value" not in fix:
            raise FixValidationError(f"fix[{i}] ({operation}) requires 'new_value'")
        check_id = fix.get("check_id")
        if check_id is not None and (not isinstance(check_id, int) or not 1 <= check_id <= 12):
            raise FixValidationError(f"fix[{i}].check_id must be an int in 1..12")
    return fixes


def apply_fixes(serialized_space: dict[str, Any], fixes: Any) -> dict[str, Any]:
    """Return a NEW ``serialized_space`` with all fixes applied deterministically.

    The input is not mutated. Every unknown/unrecognized field is preserved,
    because we deep-copy the whole space and only touch targeted paths.
    """
    normalized = validate_fixes(fixes)
    result = copy.deepcopy(serialized_space)
    for i, fix in enumerate(normalized):
        handler: Callable[..., None] = OPERATIONS[fix["operation"]]["apply"]
        try:
            handler(result, fix.get("target") or {}, fix.get("new_value"))
        except FixApplicationError as exc:
            raise FixApplicationError(f"fix[{i}] ({fix['operation']}): {exc}") from exc
    return result


def render_diff(
    before: dict[str, Any],
    after: dict[str, Any],
    space_id: str | None = None,
) -> str:
    """Render a deterministic unified diff of the serialized_space (before/after)."""
    label = f" ({space_id})" if space_id else ""
    before_lines = json.dumps(before, indent=2, sort_keys=True, ensure_ascii=False).split("\n")
    after_lines = json.dumps(after, indent=2, sort_keys=True, ensure_ascii=False).split("\n")
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"serialized_space (before){label}",
        tofile=f"serialized_space (after){label}",
        lineterm="",
    )
    return "\n".join(diff)
