"""--space-name resolution: resolve a Genie space title to its id via a
READ-ONLY listing, matching case-insensitively, with the 0 / 1 / many cases.

Everything here mocks the space listing -- NO live calls. Two layers are
covered:

* ``resolve_space_name`` -- the pure 0/1/many decision (fake ``list_spaces``).
* ``GenieSpaceApi.list_spaces`` -- pagination + read-only (fake ``api_client``).
* ``scan.py`` -- the CLI wiring: name -> id -> scan (happy path) and the
  non-zero exit on the ambiguous / not-found cases.
"""

from __future__ import annotations

from typing import Any

import genie_space_iq
import pytest
import scan as scan_cli
from genie_space_iq import (
    GenieSpaceApi,
    SpaceListingError,
    SpaceNameResolutionError,
    resolve_space_name,
)


class _FakeApi:
    """Stand-in exposing only ``list_spaces`` for the resolver decision tests."""

    def __init__(self, spaces: list[dict[str, Any]]):
        self._spaces = spaces

    def list_spaces(self) -> list[dict[str, Any]]:
        return self._spaces


_THREE_SPACES = [
    {"space_id": "s_retail", "title": "Retail Analytics"},
    {"space_id": "s_fin", "title": "Finance"},
    {"space_id": "s_ops", "title": "Operations"},
]


# -- resolve_space_name: exactly one match ---------------------------------
def test_resolve_exactly_one_match_returns_id():
    api = _FakeApi(_THREE_SPACES)
    assert resolve_space_name(api, "Retail Analytics") == "s_retail"


def test_resolve_is_case_insensitive():
    api = _FakeApi(_THREE_SPACES)
    assert resolve_space_name(api, "  retail ANALYTICS  ") == "s_retail"


# -- resolve_space_name: zero matches --------------------------------------
def test_resolve_zero_matches_raises_and_lists_candidates():
    api = _FakeApi(_THREE_SPACES)
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, "Marketing")
    message = str(exc.value)
    assert "no Genie space titled 'Marketing'" in message
    # The error lists the available candidate titles + ids so the user can pick.
    assert "Retail Analytics" in message
    assert "s_retail" in message
    assert "Finance" in message and "s_fin" in message


# -- resolve_space_name: multiple matches ----------------------------------
def test_resolve_multiple_matches_raises_and_lists_matches():
    spaces = [
        {"space_id": "s_a", "title": "Sales"},
        {"space_id": "s_b", "title": "sales"},  # same title, different id/case
        {"space_id": "s_c", "title": "Finance"},
    ]
    api = _FakeApi(spaces)
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, "Sales")
    message = str(exc.value)
    assert "2 Genie spaces match title 'Sales'" in message
    # Both ambiguous candidates (title + id) are listed; the unrelated one is not.
    assert "s_a" in message and "s_b" in message
    assert "s_c" not in message


# -- GenieSpaceApi.list_spaces: pagination + read-only ---------------------
class _FakeApiClient:
    """Records every call; returns two pages of spaces for a GET on the list path."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def do(self, method: str, path: str, query: Any = None, body: Any = None) -> Any:
        self.calls.append({"method": method, "path": path, "query": query, "body": body})
        if query and query.get("page_token") == "PAGE2":
            return {"spaces": [{"space_id": "s2", "title": "Second"}]}
        return {
            "spaces": [{"space_id": "s1", "title": "First"}],
            "next_page_token": "PAGE2",
        }


class _FakeClient:
    def __init__(self) -> None:
        self.api_client = _FakeApiClient()


def test_list_spaces_paginates_and_is_read_only():
    client = _FakeClient()
    api = GenieSpaceApi(client=client)

    spaces = api.list_spaces()

    assert spaces == [
        {"space_id": "s1", "title": "First"},
        {"space_id": "s2", "title": "Second"},
    ]
    # Two GETs against the collection path; NO write (PATCH/POST/PUT/DELETE).
    assert [c["method"] for c in client.api_client.calls] == ["GET", "GET"]
    assert all(c["path"] == "/api/2.0/genie/spaces" for c in client.api_client.calls)
    assert all(c["body"] is None for c in client.api_client.calls)
    assert client.api_client.calls[1]["query"] == {"page_token": "PAGE2"}


# -- resolve via list_spaces end-to-end (fake api_client) ------------------
def test_resolve_uses_list_spaces_over_fake_client():
    client = _FakeClient()  # yields spaces titled "First" and "Second"
    api = GenieSpaceApi(client=client)
    assert resolve_space_name(api, "second") == "s2"


# -- scan.py CLI wiring ----------------------------------------------------
class _FakeCliApi:
    """A GenieSpaceApi stand-in for the scan.py CLI: list + get, no network."""

    spaces: list[dict[str, Any]] = _THREE_SPACES

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def list_spaces(self) -> list[dict[str, Any]]:
        return type(self).spaces

    def get_space(self, space_id: str, include_serialized_space: bool = True) -> dict[str, Any]:
        # Minimal envelope, no data sources -> no UC fetch is attempted.
        return {"space_id": space_id, "serialized_space": {"version": 2, "data_sources": {}}}


def test_cli_space_name_resolves_and_scans(monkeypatch, capsys):
    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _FakeCliApi)
    rc = scan_cli.main(["--space-name", "Retail Analytics"])
    out = capsys.readouterr().out
    assert rc == 0
    # The resolved id flows into the report header.
    assert "s_retail" in out
    assert "Genie Space IQ Scan" in out


def test_cli_space_name_not_found_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _FakeCliApi)
    rc = scan_cli.main(["--space-name", "Does Not Exist"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no Genie space titled 'Does Not Exist'" in err


def test_cli_space_name_ambiguous_exits_nonzero(monkeypatch, capsys):
    class _DupApi(_FakeCliApi):
        spaces = [
            {"space_id": "s_a", "title": "Retail"},
            {"space_id": "s_b", "title": "Retail"},
        ]

    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _DupApi)
    rc = scan_cli.main(["--space-name", "Retail"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "match title 'Retail'" in err


def test_cli_space_name_mutually_exclusive_with_space_id():
    # argparse enforces the mutually-exclusive group -> SystemExit(2).
    with pytest.raises(SystemExit):
        scan_cli.main(["--space-name", "X", "--space-id", "abc"])


def test_cli_space_name_mutually_exclusive_with_serialized_file(tmp_path):
    space_file = tmp_path / "space.json"
    space_file.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        scan_cli.main(["--space-name", "X", "--serialized-space-file", str(space_file)])


# -- blank / whitespace-only --space-name (rejected, no false match) -------
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_resolve_rejects_blank_name(blank):
    # A blank/whitespace-only name is rejected BEFORE any listing entry can match.
    api = _FakeApi(_THREE_SPACES)
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, blank)
    assert "non-empty title" in str(exc.value)


def test_resolve_blank_name_never_matches_titleless_entry():
    # A listing full of title-less entries + a blank name must NOT resolve to any
    # of them; it errors as a blank name, not a (false) successful match.
    spaces = [
        {"space_id": "s_none", "title": None},
        {"space_id": "s_empty", "title": ""},
        {"space_id": "s_ws", "title": "   "},
        {"space_id": "s_missing"},  # no title key at all
    ]
    api = _FakeApi(spaces)
    for blank in ("", "   "):
        with pytest.raises(SpaceNameResolutionError) as exc:
            resolve_space_name(api, blank)
        assert "non-empty title" in str(exc.value)


# -- title-less listing entries are never candidates -----------------------
def test_resolve_excludes_titleless_entries_from_candidates():
    # Real space resolves; the title-less entries sitting next to it are ignored.
    spaces = [
        {"space_id": "s_none", "title": None},
        {"space_id": "s_empty", "title": ""},
        {"space_id": "s_ws", "title": "   "},
        {"space_id": "s_missing"},  # no title key
        {"space_id": "s_real", "title": "Real Space"},
    ]
    api = _FakeApi(spaces)
    assert resolve_space_name(api, "real space") == "s_real"


def test_resolve_all_titleless_is_a_zero_match_not_a_crash():
    # No usable titles at all -> a real name simply finds zero candidates.
    spaces = [{"space_id": "s_none", "title": None}, {"space_id": "s_empty", "title": ""}]
    api = _FakeApi(spaces)
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, "Anything")
    assert "no Genie space titled 'Anything'" in str(exc.value)


def test_cli_empty_space_name_exits_nonzero(monkeypatch, capsys):
    # "--space-name ''" (empty string) must route through the resolver and be
    # rejected with a clear error, NOT fall through to get_space(None).
    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _FakeCliApi)
    rc = scan_cli.main(["--space-name", ""])
    err = capsys.readouterr().err
    assert rc == 2
    assert "non-empty title" in err


def test_cli_whitespace_space_name_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _FakeCliApi)
    rc = scan_cli.main(["--space-name", "   "])
    err = capsys.readouterr().err
    assert rc == 2
    assert "non-empty title" in err


# -- malformed `spaces` payloads handled gracefully ------------------------
class _MalformedApiClient:
    """Returns a single page whose `spaces` list mixes junk with sparse dicts."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def do(self, method: str, path: str, query: Any = None, body: Any = None) -> Any:
        self.calls.append(method)
        return self._payload


class _MalformedClient:
    def __init__(self, payload: Any) -> None:
        self.api_client = _MalformedApiClient(payload)


def test_list_spaces_skips_non_dict_entries_and_fills_missing_fields():
    payload = {
        "spaces": [
            "not-a-dict",
            42,
            None,
            ["nested"],
            {"space_id": "s1"},  # missing title
            {"title": "Only Title"},  # missing space_id
            {},  # both missing
            {"id": "alt", "name": "Alt Fields"},  # id honored; name is NOT a title
        ]
    }
    api = GenieSpaceApi(client=_MalformedClient(payload))
    spaces = api.list_spaces()
    # Non-dict entries dropped; sparse dicts kept with None for absent fields.
    # ``space_id`` falls back to ``id``, but ``title`` comes ONLY from ``title``:
    # the ``name``-only entry is title-less (not name-matchable by --space-name).
    assert spaces == [
        {"space_id": "s1", "title": None},
        {"space_id": None, "title": "Only Title"},
        {"space_id": None, "title": None},
        {"space_id": "alt", "title": None},
    ]


@pytest.mark.parametrize("bad_spaces", [None, "a string", {"not": "a list"}, 123])
def test_list_spaces_tolerates_non_list_spaces_field(bad_spaces):
    api = GenieSpaceApi(client=_MalformedClient({"spaces": bad_spaces}))
    assert api.list_spaces() == []


def test_list_spaces_tolerates_non_dict_response():
    api = GenieSpaceApi(client=_MalformedClient("totally not a dict"))
    assert api.list_spaces() == []


def test_resolve_over_malformed_payload_does_not_crash():
    payload = {
        "spaces": [
            "junk",
            {"space_id": "s_real", "title": "Real Space"},
            {"space_id": "s_none", "title": None},
        ]
    }
    api = GenieSpaceApi(client=_MalformedClient(payload))
    assert resolve_space_name(api, "Real Space") == "s_real"


# -- repeated next_page_token guard (no infinite loop) ---------------------
class _RepeatTokenApiClient:
    """Always returns the SAME next_page_token, which must NOT loop forever."""

    def __init__(self) -> None:
        self.calls = 0

    def do(self, method: str, path: str, query: Any = None, body: Any = None) -> Any:
        self.calls += 1
        # Bound the damage in case the guard fails: don't actually spin forever.
        assert self.calls <= 10, "list_spaces did not stop on a repeated page token"
        return {
            "spaces": [{"space_id": f"s{self.calls}", "title": f"T{self.calls}"}],
            "next_page_token": "SAME_TOKEN",
        }


class _RepeatTokenClient:
    def __init__(self) -> None:
        self.api_client = _RepeatTokenApiClient()


def test_list_spaces_stops_on_repeated_page_token():
    client = _RepeatTokenClient()
    api = GenieSpaceApi(client=client)
    with pytest.raises(SpaceListingError) as exc:
        api.list_spaces()
    assert "repeated page token" in str(exc.value)
    # Terminated quickly (page 1 sets the token, page 2 detects the repeat).
    assert client.api_client.calls == 2


def test_resolve_propagates_listing_error_over_repeated_token():
    api = GenieSpaceApi(client=_RepeatTokenClient())
    with pytest.raises(SpaceListingError):
        resolve_space_name(api, "T1")


def test_cli_space_name_listing_error_exits_nonzero(monkeypatch, capsys):
    # A pagination fault during --space-name resolution exits cleanly (rc 2),
    # it does not crash scan.py with an unhandled traceback.
    class _LoopingApi:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._real = GenieSpaceApi(client=_RepeatTokenClient())

        def list_spaces(self) -> list[dict[str, Any]]:
            return self._real.list_spaces()

    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _LoopingApi)
    rc = scan_cli.main(["--space-name", "T1"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "repeated page token" in err


# -- title comes ONLY from `title` (a `name`-only entry is not matchable) --
def test_list_spaces_does_not_map_name_to_title():
    # An entry carrying only `name` (no `title`) is title-less after listing.
    client = _MalformedClient({"spaces": [{"space_id": "s_named", "name": "Only Name"}]})
    api = GenieSpaceApi(client=client)
    assert api.list_spaces() == [{"space_id": "s_named", "title": None}]


def test_resolve_cannot_match_name_only_entry():
    # --space-name must NOT resolve an entry whose only label is `name` (blocking
    # fix): `name` is never treated as a title fallback.
    client = _MalformedClient({"spaces": [{"space_id": "s_named", "name": "Only Name"}]})
    api = GenieSpaceApi(client=client)
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, "Only Name")
    assert "no Genie space titled 'Only Name'" in str(exc.value)


# -- unique title but missing space_id -------------------------------------
def test_resolve_unique_title_missing_space_id_raises():
    api = _FakeApi([{"title": "Solo"}])  # exactly one title match, but no space_id
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, "Solo")
    assert "has no space_id" in str(exc.value)


# -- zero-match candidate list omits title-less entries (plain title form) -
def test_resolve_zero_match_omits_titleless_from_candidate_list():
    spaces = [
        {"space_id": "s_real", "title": "Real Space"},
        {"space_id": "s_none", "title": None},  # title-less
        {"space_id": "s_name_only", "name": "Name Only"},  # name-only == title-less
    ]
    api = _FakeApi(spaces)
    with pytest.raises(SpaceNameResolutionError) as exc:
        resolve_space_name(api, "Marketing")
    message = str(exc.value)
    # The titled entry is shown plainly as `title (id)`; title-less ones are absent.
    assert "Real Space (s_real)" in message
    assert "s_none" not in message
    assert "s_name_only" not in message
    assert "None (" not in message


# -- malformed (unhashable) next_page_token -> SpaceListingError, not TypeError -
class _BadTokenApiClient:
    """Returns a page whose `next_page_token` is an unhashable dict."""

    def __init__(self) -> None:
        self.calls = 0

    def do(self, method: str, path: str, query: Any = None, body: Any = None) -> Any:
        self.calls += 1
        assert self.calls <= 5, "list_spaces did not stop on a malformed page token"
        return {
            "spaces": [{"space_id": "s1", "title": "T1"}],
            "next_page_token": {"bad": "token"},  # unhashable -> would raise TypeError
        }


class _BadTokenClient:
    def __init__(self) -> None:
        self.api_client = _BadTokenApiClient()


def test_list_spaces_rejects_non_string_page_token():
    client = _BadTokenClient()
    api = GenieSpaceApi(client=client)
    with pytest.raises(SpaceListingError) as exc:
        api.list_spaces()
    assert "non-string page token" in str(exc.value)
    # Detected on the very first page; no membership check (no raw TypeError).
    assert client.api_client.calls == 1
