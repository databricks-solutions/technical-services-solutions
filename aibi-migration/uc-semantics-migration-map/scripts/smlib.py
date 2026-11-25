"""smlib.py — shared helpers for the UC Semantics Migration Map.

Three ideas make assess→apply repeatable (idempotent):
  1. STABLE KEYS   every object has a key derived from *evidence* (a fact table, a metric
                   caption), never from a display name — so renaming does not change identity.
  2. SPEC HASHES   the 'spec' of an object (what apply would write) is hashed canonically;
                   unchanged spec ⇒ unchanged hash ⇒ no write.
  3. PINNING       a human edit is recorded in `pinned`, and a refresh never overwrites a
                   pinned field.
"""
import hashlib
import json
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required:  pip install pyyaml")

SCHEMA_VERSION = 1
MARKER = "uc-semantics-migration-map"  # stamped on managed objects where UC allows it

# ---- which fields of each object kind make up its *spec* (what the human approves) -------
KINDS = ["domains", "concepts", "metric_views", "pages", "wikis", "asset_tags"]
SPEC_FIELDS = {
    "domains": ["tag_key", "parent", "subtitle", "description", "icon", "technical_owners",
                "business_owners", "draft"],
    # a Metric View is approved in two gates: the SHELL (this spec) in Stage 1, then its authored YAML
    # (yaml_approved_hash) in Stage 2. The YAML is deliberately NOT part of the shell spec.
    "metric_views": ["fqn", "source_table", "comment", "concepts", "concept_hash"],
    "concepts": ["name", "domain", "mv", "definition", "chosen"],
    "pages": ["domain", "title", "synonyms", "description", "body", "related", "sources"],
    "wikis": ["table", "body"],
    "asset_tags": ["securable", "name", "tag_key", "tag_value"],
}
# fields a refresh may regenerate for `source: derived` objects (everything else is identity)
DERIVED_FIELDS = {
    "domains": ["name", "subtitle", "description", "tag_key", "parent", "evidence"],
    "concepts": ["name", "domain", "fact_table", "variants", "reports", "drift", "need", "patterns", "mv", "evidence"],
    "metric_views": ["title", "domain", "source_table", "grain", "purpose", "concepts", "long_tail",
                     "time_dimension", "absorbs", "patterns", "evidence", "joins", "filter", "fqn"],
    "pages": ["title", "domain", "description", "body", "related", "synonyms", "sources", "evidence"],
    "wikis": ["table", "body", "evidence"],
    "asset_tags": ["securable", "name", "tag_key", "domain", "evidence"],
}


def slug(s, sep="_"):
    s = re.sub(r"[^A-Za-z0-9]+", sep, str(s or "").strip()).strip(sep).lower()
    return s or "unnamed"


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def h12(obj):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()[:12]


def spec_of(kind, obj):
    """The slice of an object that apply would write — hashed to detect change."""
    return {f: obj.get(f) for f in SPEC_FIELDS[kind] if obj.get(f) not in (None, [], "")}


def spec_hash(kind, obj):
    return h12(spec_of(kind, obj))


def read_yaml(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or default


def write_yaml(path, data, header=""):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def humanize(tok):
    t = re.sub(r"(_fct|_fact|_dim|_data|_txn|_dm$|^fact_|^dim_|^dm_)", " ", str(tok), flags=re.I)
    t = re.sub(r"[_\-\.]+", " ", t).strip()
    return " ".join(w.capitalize() for w in t.split()) or str(tok)


def find(items, key):
    for it in items:
        if it.get("key") == key:
            return it
    return None


def yaml_ok(mv):
    """A metric view's authored YAML is present AND explicitly approved in its current form."""
    y = mv.get("yaml")
    return (bool(y) and mv.get("yaml_approved_hash") == h12(y)
            and mv.get("yaml_concept_hash") == mv.get("concept_hash"))


def approved_ok(obj, kind):
    """Approved AND unchanged since approval (an edit after approval needs re-approval)."""
    return obj.get("approval") == "approved" and obj.get("approved_hash") == spec_hash(kind, obj)
