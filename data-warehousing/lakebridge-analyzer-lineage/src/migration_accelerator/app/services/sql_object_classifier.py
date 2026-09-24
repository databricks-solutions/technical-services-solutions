"""
SQL object classifier.

Cross-references the analyzer's `SQL Programs` (or `Embedded SQL Programs`) +
`Functions` sheets to assign each referenced object an explicit subtype
(TABLE, VIEW, PROCEDURE, etc.) and to drop CTE / function-name false positives.
Also drops known pseudo-tables (e.g. Oracle ``DUAL``) by basename regardless of sheets.

Pure logic, no IO. Tolerates missing inputs: if `sql_programs_df` is None,
classify() returns the legacy TABLE_OR_VIEW fallback and only enforces the
existing temp-table / variable / table-variable drops. Drops driven by the
`Functions` sheet are skipped if `functions_df` is None.

Note on program-name matching: the analyzer often uses basenames in the
`SQL Programs` sheet (e.g. ``output_row_100.sql``) while the
`Program-Object Xref` sheet uses absolute paths
(e.g. ``/Users/.../output_row_100.sql``). The classifier builds both
exact-match and basename-fallback lookups so it works either way.
"""

import os
from typing import Any, Dict, Optional, Set, Tuple

import pandas as pd

from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.utils.logger import get_logger

log = get_logger()


# Map analyzer Script Category tokens to node subtypes.
# Order in the priority list below matters - first match wins.
_CATEGORY_TO_TYPE_PRIORITY = [
    ("CREATE_MATERIALIZED_VIEW", NodeTypeHelper.MATERIALIZED_VIEW),
    ("CREATE_VIEW", NodeTypeHelper.VIEW),
    ("CREATE_PROCEDURE", NodeTypeHelper.PROCEDURE),
    ("CREATE_SEQUENCE", NodeTypeHelper.SEQUENCE),
    ("CREATE_INDEX", NodeTypeHelper.INDEX),
    ("CREATE_MACRO", NodeTypeHelper.MACRO),
    ("TABLE_DDL_AS_SELECT", NodeTypeHelper.TABLE),
    ("TABLE_DDL_LIKE", NodeTypeHelper.TABLE),
    ("TABLE_DDL", NodeTypeHelper.TABLE),
    ("SELECT_INTO_REAL_TABLE", NodeTypeHelper.TABLE),
    ("INSERT_INTO", NodeTypeHelper.TABLE),
    ("MERGE", NodeTypeHelper.TABLE),
    ("TRUNCATE_TABLE", NodeTypeHelper.TABLE),
    ("DELETE", NodeTypeHelper.TABLE),
]

# Drop reasons surfaced in stats
DROP_LOCAL_TEMP = "local_temp_table"
DROP_VARIABLE = "variable"
DROP_TABLE_VARIABLE = "table_variable"
DROP_CTE = "cte"
DROP_FUNCTION = "function"
DROP_PSEUDO_TABLE = "pseudo_table"

# Last segment of object name (after final ".") matching these is dropped from
# lineage — e.g. Oracle DUAL appears in embedded SQL / Informatica xref but is
# not a persisted migration target.
_PSEUDO_TABLE_BASE_NAMES = frozenset({"DUAL"})


def is_lineage_pseudo_table_name(object_name: str) -> bool:
    """True if the object's basename (final qualifier segment) is a pseudo-table."""
    if object_name is None:
        return False
    name = object_name.strip()
    if not name:
        return False
    base = name.split(".")[-1].strip().upper()
    return base in _PSEUDO_TABLE_BASE_NAMES


class SQLObjectClassifier:
    """Classify analyzer-extracted objects into TABLE/VIEW/etc. and drop false positives."""

    def __init__(
        self,
        sql_programs_df: Optional[pd.DataFrame] = None,
        functions_df: Optional[pd.DataFrame] = None,
    ) -> None:
        self._sql_programs_df = sql_programs_df
        self._functions_df = functions_df
        # Exact match (e.g. full path) lookup
        self._program_to_categories: Dict[str, Set[str]] = {}
        # Basename fallback - many analyzer outputs key SQL Programs by basename
        # while Program-Object Xref uses full paths.
        self._basename_to_categories: Dict[str, Set[str]] = {}
        self._function_names_upper: Set[str] = set()
        self._has_categories = False
        self._has_functions = False

    def build_lookups(self) -> None:
        """Populate program→categories and function-name lookups (idempotent)."""
        if self._sql_programs_df is not None and not self._sql_programs_df.empty:
            self._build_program_categories(self._sql_programs_df)
            self._has_categories = True
        else:
            log.info(
                "SQLObjectClassifier: no SQL Programs sheet provided; "
                "subtype refinement disabled (falling back to TABLE_OR_VIEW)"
            )

        if self._functions_df is not None and not self._functions_df.empty:
            self._build_function_names(self._functions_df)
            self._has_functions = True
        else:
            log.info(
                "SQLObjectClassifier: no Functions sheet provided; "
                "function-name false-positive drops disabled"
            )

    def _build_program_categories(self, df: pd.DataFrame) -> None:
        cols = {str(c).strip(): c for c in df.columns}
        program_col = cols.get("Program Name") or cols.get("Program")
        category_col = cols.get("Script Category") or cols.get("Category")
        if not program_col or not category_col:
            log.warning(
                f"SQLObjectClassifier: SQL Programs sheet missing expected columns "
                f"(Program Name, Script Category). Found: {list(df.columns)}"
            )
            return
        for row in df[[program_col, category_col]].itertuples(index=False):
            program, category = row
            if pd.isna(program) or pd.isna(category):
                continue
            program_s = str(program).strip()
            tokens = {t.strip().upper() for t in str(category).split(",") if t.strip()}
            if not program_s or not tokens:
                continue
            existing = self._program_to_categories.get(program_s)
            if existing is None:
                self._program_to_categories[program_s] = tokens
            else:
                existing.update(tokens)
            # Always index by basename too, so a full-path lookup from the
            # xref sheet finds a basename-keyed SQL Programs row (and vice
            # versa). This is the common case in real analyzer outputs.
            base = os.path.basename(program_s.replace("\\", "/"))
            if base:
                bucket = self._basename_to_categories.get(base)
                if bucket is None:
                    self._basename_to_categories[base] = set(tokens)
                else:
                    bucket.update(tokens)

    def _build_function_names(self, df: pd.DataFrame) -> None:
        cols = {str(c).strip(): c for c in df.columns}
        fn_col = cols.get("Function") or cols.get("Function Name")
        if not fn_col:
            log.warning(
                f"SQLObjectClassifier: Functions sheet missing 'Function' column. "
                f"Found: {list(df.columns)}"
            )
            return
        for value in df[fn_col].dropna().astype(str):
            name = value.strip().upper()
            if name:
                self._function_names_upper.add(name)

    def _categories_for_program(self, program_name: str) -> Set[str]:
        """Look up Script Category tokens for a program, with basename fallback."""
        if not program_name:
            return set()
        cats = self._program_to_categories.get(program_name)
        if cats:
            return cats
        base = os.path.basename(program_name.replace("\\", "/"))
        if base and base != program_name:
            return self._basename_to_categories.get(base, set())
        return set()

    @staticmethod
    def _classify_by_categories(categories: Set[str]) -> Optional[str]:
        for token, node_type in _CATEGORY_TO_TYPE_PRIORITY:
            if token in categories:
                return node_type
        return None

    def classify(
        self,
        object_name: str,
        creating_programs: Set[str],
        operations: Set[str],
        program_count: int,
        is_table_variable: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Classify an object.

        Args:
            object_name: raw object name (case preserved).
            creating_programs: program names that issue CREATE for this object.
            operations: set of normalized operations seen for this object
                (uppercase, e.g. {"READ", "WRITE", "CREATE"}).
            program_count: how many distinct programs reference this object.
            is_table_variable: True iff Referenced Objects shows TABLE_VARIABLE
                non-null for this object (SQL Server table variable).

        Returns:
            (node_type, drop_reason). When drop_reason is non-None the caller
            should skip emitting this node (and any edges touching it).
        """
        if object_name is None:
            return None, "empty"

        name = object_name.strip()
        if not name:
            return None, "empty"

        # Existing prefix-based drops, centralized here for one source of truth.
        if name.startswith("@"):
            return None, DROP_VARIABLE
        if name.startswith("#") and not name.startswith("##"):
            return None, DROP_LOCAL_TEMP

        if is_table_variable:
            return None, DROP_TABLE_VARIABLE

        if is_lineage_pseudo_table_name(name):
            return None, DROP_PSEUDO_TABLE

        unqualified = "." not in name
        ops_upper = {o.upper() for o in operations if o}
        read_only = ops_upper.issubset({"READ"})

        # Function false-positive: name matches a SQL function, READ-only,
        # unqualified. Tight rule - real tables that happen to share a name
        # with a function (e.g. fully-qualified DW.DATE) survive because they
        # have a "." in the name or non-READ ops somewhere in the corpus.
        if (
            self._has_functions
            and unqualified
            and read_only
            and name.upper() in self._function_names_upper
        ):
            return None, DROP_FUNCTION

        # Conservative CTE detection: appears in exactly one program, READ-only,
        # unqualified, AND that program is flagged CTE_TABLE by the analyzer.
        if (
            self._has_categories
            and unqualified
            and read_only
            and program_count == 1
            and len(creating_programs) == 0
        ):
            # Need to look up the single referencing program. Caller must pass
            # it in via creating_programs OR we infer indirectly: when the
            # parser tracks per-object referencing programs separately we can
            # use them here. For now, detect via analyzer flag on ANY program
            # category list - keep tight by requiring CTE_TABLE specifically.
            # (See classify_with_program_set for the variant the parser uses.)
            pass

        # Subtype from creating programs' Script Category union.
        node_type: Optional[str] = None
        if creating_programs and self._has_categories:
            cats: Set[str] = set()
            for p in creating_programs:
                cats.update(self._categories_for_program(p))
            node_type = self._classify_by_categories(cats)

        if node_type is None:
            node_type = NodeTypeHelper.TABLE_OR_VIEW

        return node_type, None

    def classify_with_referencing_programs(
        self,
        object_name: str,
        creating_programs: Set[str],
        referencing_programs: Set[str],
        operations: Set[str],
        is_table_variable: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Classify an object using both CREATE-programs and the full referencing-program set.

        This is the variant the parser uses because CTE detection needs to
        know the single referencing program to look up its Script Category.
        """
        if object_name is None:
            return None, "empty"

        name = object_name.strip()
        if not name:
            return None, "empty"

        if name.startswith("@"):
            return None, DROP_VARIABLE
        if name.startswith("#") and not name.startswith("##"):
            return None, DROP_LOCAL_TEMP

        if is_table_variable:
            return None, DROP_TABLE_VARIABLE

        if is_lineage_pseudo_table_name(name):
            return None, DROP_PSEUDO_TABLE

        unqualified = "." not in name
        ops_upper = {o.upper() for o in operations if o}
        read_only = ops_upper.issubset({"READ"})

        # Function false-positive
        if (
            self._has_functions
            and unqualified
            and read_only
            and name.upper() in self._function_names_upper
        ):
            return None, DROP_FUNCTION

        # CTE: exactly one referencing program AND that program is flagged CTE_TABLE
        if (
            self._has_categories
            and unqualified
            and read_only
            and len(referencing_programs) == 1
        ):
            (only_program,) = tuple(referencing_programs)
            cats = self._categories_for_program(only_program)
            if "CTE_TABLE" in cats:
                return None, DROP_CTE

        node_type: Optional[str] = None
        if creating_programs and self._has_categories:
            cats: Set[str] = set()
            for p in creating_programs:
                cats.update(self._categories_for_program(p))
            node_type = self._classify_by_categories(cats)

        if node_type is None:
            node_type = NodeTypeHelper.TABLE_OR_VIEW

        return node_type, None

    @property
    def has_categories(self) -> bool:
        return self._has_categories

    @property
    def has_functions(self) -> bool:
        return self._has_functions

    def stats_summary(self) -> Dict[str, Any]:
        return {
            "programs_with_categories": len(self._program_to_categories),
            "function_names": len(self._function_names_upper),
        }
