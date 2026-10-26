"""Genie Spaces REST access via the Databricks SDK (default auth).

Reuses the genie-rooms REST GET/PATCH patterns, but is fully self-contained:
the ``databricks-sdk`` import is lazy (inside :meth:`GenieSpaceApi._client`), so
importing this module, running the offline scan, or running the mocked tests
needs no SDK and makes no network call. A caller/test may inject any object with
an ``api_client.do(method, path, query=None, body=None)`` method.

Endpoints (Genie Spaces public REST API):

* GET  ``/api/2.0/genie/spaces/{id}?include_serialized_space=true``
* GET  ``/api/2.0/genie/spaces``                       (list; read-only)
* PATCH ``/api/2.0/genie/spaces/{id}``  body ``{"serialized_space": json.dumps(space)}``

:meth:`patch_space` round-trips the FULL space dict verbatim -- it does not strip
to a top-level allowlist -- so every unknown/unrecognized field is preserved.

Unity Catalog enrichment (read-only, no SQL warehouse) uses the SDK Tables API,
``WorkspaceClient.tables.get(full_name)``, via :meth:`GenieSpaceApi.get_uc_table`.
:func:`fetch_uc_metadata` maps identifiers -> normalized UC metadata and degrades
gracefully (a per-table permission/not-found error is collected as a warning
rather than raised), so a partial or empty result never crashes the scan.
"""

from __future__ import annotations

import json
from typing import Any

GENIE_SPACES_PATH = "/api/2.0/genie/spaces"


class SpaceListingError(RuntimeError):
    """Raised when the Genie space listing cannot be paged safely.

    Currently signals a pagination fault (the service returned a page token it
    already returned), which would otherwise loop forever.
    """


class GenieSpaceApi:
    """Thin, injectable client for reading and writing a Genie space config."""

    def __init__(self, client: Any = None, profile: str | None = None):
        self._injected_client = client
        self._profile = profile

    def _client(self) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        # Lazy import: only needed for live calls, never for offline/tests.
        from databricks.sdk import WorkspaceClient

        if self._profile:
            self._injected_client = WorkspaceClient(profile=self._profile)
        else:
            self._injected_client = WorkspaceClient()
        return self._injected_client

    def get_space(self, space_id: str, include_serialized_space: bool = True) -> dict[str, Any]:
        """GET a space; return the response dict with ``serialized_space`` parsed.

        The ``serialized_space`` field comes back as a JSON-encoded *string*; we
        parse it into a dict in place. All other response metadata (title,
        description, warehouse_id, ...) is left untouched.
        """
        query = {"include_serialized_space": "true"} if include_serialized_space else None
        response = self._client().api_client.do(
            "GET", f"{GENIE_SPACES_PATH}/{space_id}", query=query
        )
        result = dict(response) if isinstance(response, dict) else {}
        serialized = result.get("serialized_space")
        if isinstance(serialized, str):
            result["serialized_space"] = json.loads(serialized)
        return result

    def list_spaces(self) -> list[dict[str, Any]]:
        """List Genie spaces (READ-ONLY); return ``[{space_id, title}, ...]``.

        Pages through the ``GET /api/2.0/genie/spaces`` endpoint following
        ``next_page_token`` until exhausted. Never writes. The ``space_id`` is
        read defensively (``space_id``/``id``) so a minor payload variation does
        not drop a space, but the ``title`` is taken ONLY from ``title``: an
        entry carrying just ``name`` is treated as title-less and can never be
        resolved by ``--space-name`` (see :func:`resolve_space_name`).
        """
        spaces: list[dict[str, Any]] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            query: dict[str, Any] = {}
            if page_token:
                query["page_token"] = page_token
            response = self._client().api_client.do(
                "GET", GENIE_SPACES_PATH, query=query or None
            )
            result = dict(response) if isinstance(response, dict) else {}
            entries = result.get("spaces")
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    spaces.append(
                        {
                            "space_id": entry.get("space_id") or entry.get("id"),
                            # Title comes ONLY from ``title`` -- an entry with just
                            # ``name`` is title-less and must not be name-matchable.
                            "title": entry.get("title"),
                        }
                    )
            next_token = result.get("next_page_token") or None
            if not next_token:
                break
            # A malformed (e.g. unhashable) token would blow up the membership
            # check below with a raw TypeError; surface it as a controlled error.
            if not isinstance(next_token, str):
                raise SpaceListingError(
                    f"Genie space listing returned a non-string page token "
                    f"{next_token!r}; aborting pagination"
                )
            # Guard against a service that keeps handing back the same token,
            # which would otherwise loop forever.
            if next_token in seen_tokens:
                raise SpaceListingError(
                    f"Genie space listing returned a repeated page token "
                    f"{next_token!r}; aborting to avoid an infinite pagination loop"
                )
            seen_tokens.add(next_token)
            page_token = next_token
        return spaces

    def patch_space(self, space_id: str, serialized_space: dict[str, Any]) -> Any:
        """PATCH the space with a JSON-encoded serialized_space (verbatim).

        The whole dict is serialized as-is, preserving unknown fields.
        """
        body = {"serialized_space": json.dumps(serialized_space, ensure_ascii=False)}
        return self._client().api_client.do(
            "PATCH", f"{GENIE_SPACES_PATH}/{space_id}", body=body
        )

    def get_uc_table(self, full_name: str) -> dict[str, Any]:
        """Fetch Unity Catalog metadata for one table via the SDK Tables API.

        Read-only; needs no SQL warehouse. Returns the SDK ``TableInfo`` as a
        plain dict (``as_dict()``). Any failure propagates to the caller, which
        is expected to degrade gracefully (see :func:`fetch_uc_metadata`).
        """
        table = self._client().tables.get(full_name)
        if hasattr(table, "as_dict"):
            return table.as_dict()
        if isinstance(table, dict):
            return table
        raise TypeError(
            f"unexpected UC table payload for {full_name!r}: {type(table).__name__}"
        )


def normalize_uc_table(raw: Any) -> dict[str, Any]:
    """Reduce a raw UC ``TableInfo`` dict to the scorer's UC schema.

    Output shape: ``{comment: str|None, table_type: str|None,
    columns: [{name, comment}]}`` -- the same shape the offline
    ``--uc-metadata-file`` supplies, so the pure scorer sees one contract.
    """
    if not isinstance(raw, dict):
        return {"comment": None, "table_type": None, "columns": []}
    columns: list[dict[str, Any]] = []
    for col in raw.get("columns") or []:
        if isinstance(col, dict):
            columns.append({"name": col.get("name"), "comment": col.get("comment")})
    return {
        "comment": raw.get("comment"),
        "table_type": raw.get("table_type"),
        "columns": columns,
    }


def fetch_uc_metadata(
    api: GenieSpaceApi, identifiers: list[str]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Fetch + normalize UC metadata for each identifier, degrading gracefully.

    Returns ``(uc_metadata, warnings)`` where ``uc_metadata`` maps only the
    identifiers that resolved, and ``warnings`` is a list of ``(identifier,
    error_message)`` for the ones that did not (permission denied, not found,
    transient errors). A caller that gets an empty map should treat UC as
    unavailable (pass ``None`` to the scorer).
    """
    # Only *expected* Databricks API failures (permission denied, not found,
    # transient/unavailable, ...) degrade to a warning. DatabricksError is their
    # common base; a TypeError/KeyError from a payload-shape change is NOT a
    # DatabricksError and must propagate rather than be masked as "UC missing".
    # Imported lazily so the offline scan never needs the SDK.
    from databricks.sdk.errors import DatabricksError

    uc_metadata: dict[str, Any] = {}
    warnings: list[tuple[str, str]] = []
    for identifier in identifiers:
        try:
            raw = api.get_uc_table(identifier)
        except DatabricksError as exc:
            warnings.append((identifier, str(exc)))
            continue
        uc_metadata[identifier] = normalize_uc_table(raw)
    return uc_metadata, warnings
