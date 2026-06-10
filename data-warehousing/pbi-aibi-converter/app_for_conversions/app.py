"""
Power BI to Databricks AI/BI Dashboard Converter — Streamlit entrypoint.

This module handles the UI layout, user interaction, and orchestration.
All business logic lives in sub-modules:
  - clients.py   — Databricks + LLM client factories and shared constants
  - converter.py  — PBI parsing, LLM conversion, explanation generation
  - validator.py  — .lvdash.json structural and SQL validation
"""

import os
import json
import traceback
from dataclasses import dataclass, field
from typing import Any

import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.dashboards import Dashboard
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel

from clients import MODEL, STATIC_DIR, VALID_WIDGET_VERSIONS
from color_utils import normalize_render_colors
from export_pdf import build_export_pdf
from converter import (
    extract_upload,
    find_pbi_folders,
    collect_pbi_context,
    collect_pbi_context_chunked,
    extract_pbi_source_tables,
    detect_external_sources,
    extract_pbi_theme_colors,
    build_color_context,
    parse_pbi_layout,
    build_free_layout_blueprint_prompt,
    call_llm,
    call_llm_chunked,
    generate_explanation,
    extract_json_from_response,
    apply_brand_colors,
    _ensure_fqn_tables,
    fix_dataset_columns,
    _estimate_tokens,
    MAX_PROMPT_TOKENS,
)
from validator import validate_dashboard, validate_layout_fidelity, validate_table_coverage

# ---------------------------------------------------------------------------
# Page config (must be the first Streamlit command)
# ---------------------------------------------------------------------------

st.set_page_config(page_title="PBI to AI/BI Converter", page_icon=":bar_chart:", layout="centered")
st.markdown(
    """
    <style>
    /* Widen the centered main column. Streamlit's default centered layout
       caps the main block container at ~46rem which feels cramped once the
       per-file controls (name + Overwrite + Remove) share a row. Bumping to
       64rem keeps the page comfortably centered on widescreens while giving
       each row enough horizontal space. Targets the modern testid and the
       legacy class for cross-version robustness. */
    [data-testid='stMainBlockContainer'],
    section.main > .block-container,
    .main .block-container {
        max-width: 64rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    /* Light first-pass: hide any <small> Streamlit might still emit. */
    [data-testid='stFileUploader'] small,
    section[data-testid='stFileUploaderDropzone'] small {
        display: none !important;
    }
    /* Collapse the now-empty stock "drag and drop / Limit XGB" instructions
       container so it stops eating flex space inside the dropzone. The JS
       scrub below already hides its text leaves; this also removes the
       wrapper from the layout entirely. NOTE: only the plural -Instructions
       container — the singular -Instruction testid is the button in some
       Streamlit versions and MUST stay visible. */
    [data-testid='stFileUploaderDropzoneInstructions'] {
        display: none !important;
    }
    /* Center the Upload button in the dropzone. Since the instructions
       container is now collapsed, the button is the only visible child,
       and Streamlit's default flex-start alignment leaves it stranded on
       the left. Force a centered flex layout so the button sits in the
       middle of the grey dropzone. */
    section[data-testid='stFileUploaderDropzone'] {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
# JS-based scrub for Streamlit's stock "Limit XGB per file • TYPES" helper.
# The element's testid and tag have shifted across Streamlit releases, so a
# pure CSS selector is fragile. Match on text content instead: any
# child of the file-uploader dropzone whose own text starts with a
# size-limit pattern gets hidden. Runs once on mount and again on every
# DOM mutation (Streamlit re-renders the dropzone often).
import streamlit.components.v1 as components
components.html(
    """
    <script>
    (function() {
      const LIMIT_RE = /^\\s*\\d+(\\.\\d+)?\\s*(GB|MB|KB)\\b.*per\\s+file/i;
      function scrub() {
        const root = window.parent.document;
        if (!root) return;
        root.querySelectorAll(
          '[data-testid="stFileUploader"] *, ' +
          'section[data-testid="stFileUploaderDropzone"] *'
        ).forEach(el => {
          if (el.children.length === 0 && LIMIT_RE.test(el.textContent || '')) {
            el.style.display = 'none';
          }
        });
      }
      scrub();
      const obs = new MutationObserver(scrub);
      obs.observe(window.parent.document.body, { childList: true, subtree: true });
    })();
    </script>
    """,
    height=0,
)


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

@dataclass
class ReportResult:
    """All output data for a single converted report."""
    name: str = ""
    status: str = "pending"  # pending | running | done | error
    error_msg: str = ""
    raw_traceback: str = ""
    dashboard_json: dict = field(default_factory=dict)
    dashboard_id: str = ""
    dash_url: str = ""
    workspace_path: str = ""
    n_datasets: int = 0
    n_widgets: int = 0
    n_canvas: int = 0
    n_pages: int = 0
    layout_fidelity: Any = None
    explanation: str = ""
    validation: Any = None
    data_sources: list = field(default_factory=list)
    external_sources: list = field(default_factory=list)
    pdf_bytes: bytes | None = None


if "results" not in st.session_state:
    st.session_state["results"] = []
if "batch_running" not in st.session_state:
    st.session_state["batch_running"] = False


# ---------------------------------------------------------------------------
# Core conversion function (single report)
# ---------------------------------------------------------------------------

def _find_existing_dashboard(
    client: WorkspaceClient, report_name: str, parent_path: str,
) -> tuple[str | None, str | None]:
    """Look up an existing AI/BI dashboard matching `report_name`.

    Returns `(exact_id, fallback_id)`:
      * `exact_id`    — set when a dashboard matches BOTH `display_name`
                        and `parent_path` (modulo trailing slashes).
      * `fallback_id` — first dashboard with a matching `display_name`,
                        regardless of folder. Used when the conflict is
                        with a dashboard in a different parent or with no
                        parent_path field surfaced.
    """
    target = parent_path.rstrip("/")
    exact_id, fallback_id = None, None
    try:
        for d in client.lakeview.list():
            if d.display_name != report_name:
                continue
            dpp = (getattr(d, "parent_path", None) or "").rstrip("/")
            if dpp == target:
                exact_id = d.dashboard_id
                break
            if fallback_id is None:
                fallback_id = d.dashboard_id
    except Exception:
        pass
    return exact_id, fallback_id


def _executing_user_email() -> str | None:
    """Resolve the email of the user currently using the app.

    Databricks Apps forwards the authenticated user's email as the
    `X-Forwarded-Email` HTTP header on every request. Streamlit
    surfaces request headers via `st.context.headers`. Returns None
    if the header is missing (e.g. running outside Databricks Apps,
    such as local `streamlit run`).
    """
    try:
        headers = st.context.headers
    except Exception:
        return None
    if not headers:
        return None
    for key in ("X-Forwarded-Email", "x-forwarded-email"):
        val = headers.get(key)
        if val:
            val = val.strip()
            if val:
                return val
    return None


def _grant_user_can_manage(
    client: WorkspaceClient,
    dashboard_id: str,
    progress,
) -> None:
    """Best-effort: grant CAN_MANAGE on the freshly-created AI/BI
    dashboard to whoever is currently using the app.

    Uses `permissions.update` (PATCH semantics) rather than `set`
    (PUT semantics), so the service principal's implicit ownership
    and any existing ACEs are preserved. Failures are surfaced to
    the progress log but never raise — the dashboard remains usable
    by the SP regardless of whether the share succeeds.
    """
    user_email = _executing_user_email()
    if not user_email:
        progress.write(
            "(skipped) Could not determine the executing user's email; "
            "the dashboard is owned by the app's service principal. "
            "Open the dashboard and use Share to grant yourself access."
        )
        return
    try:
        client.permissions.update(
            request_object_type="dashboards",
            request_object_id=dashboard_id,
            access_control_list=[
                AccessControlRequest(
                    user_name=user_email,
                    permission_level=PermissionLevel.CAN_MANAGE,
                )
            ],
        )
        progress.write(f"Granted CAN_MANAGE on dashboard to {user_email}.")
    except Exception as perm_err:
        progress.write(
            f"(non-fatal) Could not grant CAN_MANAGE to {user_email}: "
            f"{perm_err}"
        )


def convert_single_report(
    uploaded_file,
    report_name: str,
    progress,
    custom_instructions: str = "",
    preserve_colors: bool = True,
    overwrite: bool = False,
) -> ReportResult:
    """Run the full conversion pipeline for one report. Returns a ReportResult."""
    result = ReportResult(name=report_name, status="running")

    try:
        client = WorkspaceClient()

        warehouse_id = (os.getenv("DATABRICKS_WAREHOUSE_ID") or "").strip()
        if not warehouse_id:
            try:
                first = next(iter(client.warehouses.list()), None)
                if first is None:
                    result.status = "error"
                    result.error_msg = (
                        "No SQL warehouse available. Set DATABRICKS_WAREHOUSE_ID in app.yaml "
                        "or grant the app's service principal CAN_USE on a warehouse."
                    )
                    return result
                warehouse_id = first.id
            except Exception as e:
                result.status = "error"
                result.error_msg = f"Could not list SQL warehouses: {e}"
                return result

        # --- Phase 1: Extract & Parse ---
        progress.write("Extracting uploaded files...")
        tmpdir = extract_upload(uploaded_file)
        report_dir, semantic_dir = find_pbi_folders(tmpdir)

        if not report_dir or not semantic_dir:
            found = []
            for r, dirs, files in os.walk(tmpdir):
                for f in files:
                    found.append(os.path.relpath(os.path.join(r, f), tmpdir))
            result.status = "error"
            result.error_msg = (
                "Could not find `.Report` and `.SemanticModel` folders.\n\nFiles found:\n"
                + "\n".join(found[:30])
            )
            return result

        progress.write(f"Report: `{os.path.basename(report_dir)}`")
        progress.write(f"Model: `{os.path.basename(semantic_dir)}`")

        progress.write("Reading PBI report files...")
        pbi_context = collect_pbi_context(report_dir, semantic_dir)
        pbi_source_tables = extract_pbi_source_tables(semantic_dir)
        data_sources = detect_external_sources(semantic_dir)
        result.data_sources = data_sources

        external_sources = [s for s in data_sources if not s["is_databricks"] and s["source_type"] != "Calculated (PBI)"]
        result.external_sources = external_sources
        if external_sources:
            unique_types = sorted({s["source_type"] for s in external_sources})
            progress.write(f"Warning: {len(external_sources)} table(s) from external sources: {', '.join(unique_types)}")

        progress.write("Extracting PBI theme colors...")
        color_palette = extract_pbi_theme_colors(report_dir)
        if color_palette.data_colors:
            preview = ", ".join(color_palette.data_colors[:6])
            progress.write(f"Found {len(color_palette.data_colors)} theme colors: {preview}")

        progress.write("Parsing PBI layout structure...")
        pbi_layout = parse_pbi_layout(report_dir, color_palette=color_palette)
        progress.write(
            f"Found {pbi_layout.total_canvas_pages} page(s), "
            f"{pbi_layout.total_data_visuals} data visual(s), "
            f"{pbi_layout.total_page_slicers} page-level slicer(s), "
            f"{pbi_layout.total_global_slicers} global slicer(s)"
        )

        layout_blueprint = build_free_layout_blueprint_prompt(pbi_layout)
        color_context = build_color_context(color_palette, pbi_layout)

        # --- Phase 2: LLM Conversion ---
        if custom_instructions and custom_instructions.strip():
            progress.write(f"Custom instructions included ({len(custom_instructions)} chars)")

        est_tokens = _estimate_tokens(pbi_context + layout_blueprint + color_context)
        progress.write(f"Estimated context size: ~{est_tokens:,} tokens")

        use_chunked = est_tokens > MAX_PROMPT_TOKENS
        if use_chunked:
            progress.write(f"Context exceeds limit — using multi-turn chunked mode")
            semantic_ctx, page_chunks = collect_pbi_context_chunked(report_dir, semantic_dir)
            progress.write(f"Split into {len(page_chunks)} page chunk(s)")
            raw_response = call_llm_chunked(
                report_name, semantic_ctx, page_chunks, layout_blueprint,
                color_context=color_context,
                custom_instructions=custom_instructions,
                progress_callback=lambda msg: progress.write(f"  {msg}"),
            )
        else:
            progress.write(f"Sending to {MODEL} for conversion...")
            raw_response = call_llm(report_name, pbi_context, layout_blueprint, color_context=color_context, custom_instructions=custom_instructions)

        progress.write("Parsing dashboard JSON...")
        dashboard_json = extract_json_from_response(raw_response)

        result.dashboard_json = dashboard_json
        result.n_datasets = len(dashboard_json.get("datasets", []))
        result.n_pages = len(dashboard_json.get("pages", []))
        result.n_widgets = sum(len(p.get("layout", [])) for p in dashboard_json.get("pages", []))
        progress.write(f"Generated {result.n_datasets} datasets, {result.n_pages} pages, {result.n_widgets} widgets")

        # --- Phase 3: SQL column check & fix ---
        progress.write("Ensuring fully-qualified table names...")
        dashboard_json = _ensure_fqn_tables(dashboard_json)

        progress.write("Checking dataset SQL against UC tables...")
        dashboard_json = fix_dataset_columns(dashboard_json, warehouse_id, client)

        # Brand color injection runs AFTER fix_dataset_columns so the SQL it
        # uses to query for distinct categorical values is the corrected,
        # column-validated version. Skipped when the user turned off
        # "Preserve brand colors" — in that case AI/BI defaults apply.
        colored_visuals = [
            v for p in pbi_layout.pages for v in p.data_visuals if v.colors
        ]
        if preserve_colors and colored_visuals:
            progress.write(
                f"Injecting brand colors from {len(colored_visuals)} PBI visual(s)..."
            )
            dashboard_json = apply_brand_colors(
                dashboard_json,
                pbi_layout,
                warehouse_id=warehouse_id,
                sp_client=client,
                free_layout=True,
            )
        elif preserve_colors:
            progress.write(
                "No per-visual brand colors found in PBI report — "
                "using Databricks default palette."
            )
        else:
            progress.write(
                "Brand color preservation disabled — using Databricks defaults."
            )

        # Color scheme validation: ensures the AI/BI renderer actually
        # honors the colors we just injected (pie charts ignore scale.colors,
        # single-series line/bar charts need mark.color singular, etc.).
        # Categorical pie charts get scale.mappings built by querying the
        # warehouse for distinct values of the color field.
        if preserve_colors:
            progress.write("Normalizing chart colors for AI/BI renderer...")
            dashboard_json = normalize_render_colors(
                dashboard_json, sp_client=client, warehouse_id=warehouse_id,
            )
        result.dashboard_json = dashboard_json

        # --- Phase 4: Validation ---
        progress.write("Validating dashboard...")
        validation = validate_dashboard(dashboard_json, warehouse_id, client)

        progress.write("Validating layout fidelity against PBI source...")
        layout_fidelity = validate_layout_fidelity(dashboard_json, pbi_layout)
        validation.layout_fidelity = layout_fidelity
        result.layout_fidelity = layout_fidelity

        progress.write("Validating table coverage...")
        table_coverage = validate_table_coverage(dashboard_json, pbi_source_tables)
        validation.table_coverage = table_coverage
        result.validation = validation

        result.n_canvas = layout_fidelity.actual_pages

        # --- Phase 5: Deploy ---
        progress.write("Deploying to Databricks workspace...")
        parent_root = (
            os.getenv("DASHBOARD_PARENT_PATH") or "/Workspace/Shared/aibi_converter"
        ).rstrip("/")
        parent_path = f"{parent_root}/{report_name}"
        client.workspace.mkdirs(parent_path)

        serialized = json.dumps(dashboard_json, indent=2)
        dashboard_obj = Dashboard(
            display_name=report_name,
            parent_path=parent_path,
            serialized_dashboard=serialized,
            warehouse_id=warehouse_id,
        )

        if overwrite:
            exact_id, fallback_id = _find_existing_dashboard(
                client, report_name, parent_path,
            )
            for victim in filter(None, [exact_id, fallback_id]):
                try:
                    progress.write(f"Overwrite: trashing existing dashboard {victim}...")
                    client.lakeview.trash(dashboard_id=victim)
                except Exception as trash_err:
                    progress.write(f"(non-fatal) could not trash {victim}: {trash_err}")
            target_file = f"{parent_path}/{report_name}.lvdash.json"
            try:
                progress.write(f"Overwrite: deleting workspace file {target_file}...")
                client.workspace.delete(path=target_file, recursive=False)
            except Exception:
                pass

        try:
            api_result = client.lakeview.create(dashboard=dashboard_obj)
        except Exception as create_err:
            err_text = str(create_err).lower()
            if "already exists" not in err_text:
                raise
            exact_id, fallback_id = _find_existing_dashboard(
                client, report_name, parent_path,
            )
            if exact_id:
                progress.write(f"Dashboard already exists, updating {exact_id}...")
                api_result = client.lakeview.update(
                    dashboard_id=exact_id, dashboard=dashboard_obj,
                )
            elif not overwrite:
                result.status = "error"
                result.error_msg = (
                    f"A node named '{report_name}' already exists at "
                    f"`{parent_path}` (likely an orphaned workspace file or a "
                    "dashboard in a different folder). Check the **Overwrite** "
                    "box next to this report's name and re-run to replace it, "
                    "or pick a different dashboard name."
                )
                return result
            else:
                raise

        result.dashboard_id = api_result.dashboard_id
        host = client.config.host.rstrip("/")
        result.dash_url = f"{host}/sql/dashboardsv3/{result.dashboard_id}"
        result.workspace_path = f"{parent_path}/{report_name}.lvdash.json"

        progress.write("Granting CAN_MANAGE to the executing user...")
        _grant_user_can_manage(client, result.dashboard_id, progress)

        progress.write("Publishing dashboard...")
        client.lakeview.publish(
            dashboard_id=result.dashboard_id, warehouse_id=warehouse_id,
        )

        progress.write("Generating conversion report...")
        result.explanation = generate_explanation(report_name, pbi_context, dashboard_json)

        # --- PDF ---
        try:
            result.pdf_bytes = build_export_pdf(
                report_name=report_name, model=MODEL,
                workspace_path=result.workspace_path, dash_url=result.dash_url,
                n_datasets=result.n_datasets, n_widgets=result.n_widgets,
                n_canvas=result.n_canvas, n_pages=result.n_pages,
                layout_fidelity=layout_fidelity, explanation=result.explanation,
                validation=validation, data_sources=data_sources,
                external_sources=external_sources, dashboard_json=dashboard_json,
                valid_widget_versions=VALID_WIDGET_VERSIONS,
            )
        except Exception:
            pass

        result.status = "done"

    except json.JSONDecodeError as e:
        result.status = "error"
        result.error_msg = f"LLM returned invalid JSON: {e}"
        result.raw_traceback = traceback.format_exc()

    except Exception as e:
        result.status = "error"
        result.error_msg = f"Conversion failed: {e}"
        result.raw_traceback = traceback.format_exc()

    return result


# ---------------------------------------------------------------------------
# Results display function (single report tab)
# ---------------------------------------------------------------------------

def render_report_results(res: ReportResult):
    """Render the full results UI for one converted report inside a tab."""

    if res.status == "error":
        st.error(res.error_msg)
        if res.raw_traceback:
            with st.expander("Full traceback"):
                st.code(res.raw_traceback, language="text")
        return

    if res.status == "pending" or res.status == "running":
        st.info("This report is still being processed...")
        return

    st.success("Dashboard converted and published successfully!")

    n_filter_pages = res.n_pages - res.n_canvas
    lf = res.layout_fidelity
    page_match = "ok" if (lf and lf.page_count_match) else "mismatch"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Datasets", res.n_datasets)
    col2.metric("Widgets", res.n_widgets)
    col3.metric("Canvas Pages", f"{res.n_canvas}", delta=f"+ {n_filter_pages} filter page(s)" if n_filter_pages else None)
    col4.metric("PBI Tabs Matched", f"{lf.expected_pages} -> {res.n_canvas}" if lf else "N/A")

    st.markdown(f"**Report:** {res.name}")
    st.markdown(f"**Model:** `{MODEL}`")
    st.markdown(f"**Workspace path:** `{res.workspace_path}`")
    st.markdown(f"**[Open Dashboard]({res.dash_url})**")

    # PDF download
    if res.pdf_bytes:
        st.download_button(
            ":material/download: Export Validation Report (PDF)",
            data=res.pdf_bytes,
            file_name=f"{res.name}_validation_report.pdf",
            mime="application/pdf",
            key=f"pdf_{res.name}",
        )

    # Conversion explanation
    with st.expander("Conversion Report", expanded=False):
        st.markdown(res.explanation)

    # Tables & Data Sources
    _render_tables_section(res)

    # Validation
    _render_validation_section(res)


def _render_tables_section(res: ReportResult):
    """Render the Tables & Data Sources expander."""
    validation = res.validation
    if not validation:
        return

    has_external = bool(res.external_sources)
    section_title = "Tables & Data Sources" if not has_external else "Tables, Data Sources & Migration"
    with st.expander(section_title, expanded=False):
        tc = getattr(validation, "table_coverage", None)
        ds_lookup = {s["pbi_table"]: s for s in res.data_sources} if res.data_sources else {}

        if tc:
            n_physical = len(tc.queried_tables) + len(tc.missing_tables)
            n_calc = len(tc.calculated_tables)
            n_internal = len(tc.internal_tables)

            summary_parts = []
            if tc.passed and n_physical > 0:
                summary_parts.append(f"All **{len(tc.queried_tables)} physical table(s)** queried in the dashboard")
            elif tc.missing_tables:
                summary_parts.append(f"{len(tc.queried_tables)} of {n_physical} physical table(s) queried")
            if n_calc:
                summary_parts.append(f"**{n_calc} calculated** (DAX -> SQL)")
            if n_internal:
                summary_parts.append(f"{n_internal} local PBI table(s)")

            if has_external:
                unique_types = sorted({s["source_type"] for s in res.external_sources})
                st.warning(
                    f"**{len(res.external_sources)} table(s)** come from external sources "
                    f"({', '.join(unique_types)}). These need to be accessible from your Databricks workspace."
                )
            elif summary_parts:
                st.success(". ".join(summary_parts) + ". No data migration needed.")

            table_rows = []
            for tbl in tc.queried_tables:
                ds_info = ds_lookup.get(tbl["pbi_table"], {})
                table_rows.append({
                    "Status": "Queried", "PBI Table": tbl["pbi_table"],
                    "Source": ds_info.get("source_type", "Databricks"),
                    "Connection": ds_info.get("connector_detail") or tbl["source_fqn"],
                })
            for tbl in tc.missing_tables:
                ds_info = ds_lookup.get(tbl["pbi_table"], {})
                table_rows.append({
                    "Status": "Unused", "PBI Table": tbl["pbi_table"],
                    "Source": ds_info.get("source_type", "Databricks"),
                    "Connection": ds_info.get("connector_detail") or tbl["source_fqn"],
                })
            for tbl in tc.calculated_tables:
                table_rows.append({
                    "Status": "Calculated", "PBI Table": tbl["pbi_table"],
                    "Source": "DAX -> SQL (CTE)", "Connection": "-",
                })
            for tbl in tc.internal_tables:
                table_rows.append({
                    "Status": "Local", "PBI Table": tbl["pbi_table"],
                    "Source": "PBI auto-generated", "Connection": "-",
                })

            if table_rows:
                import pandas as pd
                df = pd.DataFrame(table_rows)
                st.dataframe(df, hide_index=True, use_container_width=True)

            if has_external:
                st.markdown("### How to bring external data into Databricks")
                st.markdown(
                    "- **Lakehouse Federation** — Query external databases in-place without moving data. "
                    "Create a *foreign catalog* in Unity Catalog.\n\n"
                    "- **Lakeflow Connect** — Ingest data into Delta tables with managed CDC pipelines.\n\n"
                    "- **Lakebridge** — Migrate entire data warehouses and their workloads to Databricks."
                )
        else:
            st.info("Table validation was not run.")


def _render_validation_section(res: ReportResult):
    """Render the Validation Results expander."""
    validation = res.validation
    if not validation:
        return

    dashboard_json = res.dashboard_json
    n_datasets = res.n_datasets
    n_pages = res.n_pages
    n_widgets = res.n_widgets
    lf = res.layout_fidelity

    with st.expander("Validation Results", expanded=False):
        if validation.passed and not validation.warnings:
            st.success("All checks passed — no errors or warnings.")
        elif validation.passed:
            st.info(f"No errors, but {len(validation.warnings)} warning(s) found.")
        else:
            st.warning(f"{len(validation.errors)} error(s) and {len(validation.warnings)} warning(s) found.")

        st.markdown("#### Dashboard Structure")
        st.markdown(f"- **Datasets:** {n_datasets}")
        st.markdown(f"- **Pages:** {n_pages}")
        st.markdown(f"- **Widgets:** {n_widgets}")

        if lf:
            st.markdown("#### Layout Fidelity (PBI -> AI/BI)")

            if lf.page_count_match:
                st.markdown(
                    f"- **Page count:** {lf.actual_pages} canvas page(s) — "
                    f"matches PBI source ({lf.expected_pages} tab(s))"
                )
            else:
                st.markdown(
                    f"- **Page count mismatch:** expected {lf.expected_pages} canvas page(s) "
                    f"from PBI, got {lf.actual_pages}"
                )
                if lf.missing_pages:
                    for mp in lf.missing_pages:
                        st.markdown(f"  - Missing page: \"{mp}\"")
                if lf.extra_pages:
                    for ep in lf.extra_pages:
                        st.markdown(f"  - Extra page: \"{ep}\"")

            for entry in lf.page_visual_counts:
                match = entry["actual"] >= entry["expected"]
                icon = "ok" if match else "warning"
                st.markdown(
                    f"- **Page \"{entry['name']}\":** {entry['actual']} data widget(s) "
                    f"(expected {entry['expected']} from PBI)"
                )

            if lf.missing_visuals:
                st.markdown(f"- **{len(lf.missing_visuals)} PBI visual(s) not found in dashboard:**")
                for mv in lf.missing_visuals:
                    st.markdown(f"  - `{mv['visual_type']}` — {mv['description']} (page: {mv['page']})")
            else:
                st.markdown("- All PBI visuals are represented in the dashboard")

            if lf.position_warnings:
                st.markdown(f"- **{len(lf.position_warnings)} widget(s) with position drift:**")
                for pw in lf.position_warnings:
                    st.markdown(
                        f"  - `{pw['visual_type']}` ({pw['description']}): "
                        f"expected x={pw['expected_x']}, w={pw['expected_w']} -> "
                        f"got x={pw['actual_x']}, w={pw['actual_w']}"
                    )
            else:
                st.markdown("- Widget positions approximate PBI layout")

        st.markdown("#### Widget Inventory")
        for page in dashboard_json.get("pages", []):
            p_name = page.get("displayName", page.get("name", ""))
            p_type = page.get("pageType", "unknown")
            widgets_on_page = page.get("layout", [])
            st.markdown(f"**{p_name}** ({p_type}) — {len(widgets_on_page)} widget(s)")
            for item in widgets_on_page:
                w = item.get("widget", {})
                pos = item.get("position", {})
                w_name = w.get("name", "")
                pos_str = f"x={pos.get('x')}, y={pos.get('y')}, w={pos.get('width')}, h={pos.get('height')}"
                if "multilineTextboxSpec" in w:
                    text_preview = (w["multilineTextboxSpec"].get("lines", [""])[0] or "")[:60]
                    st.markdown(f"- `{w_name}` — **text** — {pos_str} — *{text_preview}*")
                else:
                    spec = w.get("spec", {})
                    wt = spec.get("widgetType", "unknown")
                    ver = spec.get("version", "?")
                    expected = VALID_WIDGET_VERSIONS.get(wt)
                    ver_status = "ok" if expected is None or ver == expected else f"expected {expected}"
                    st.markdown(f"- `{w_name}` — **{wt}** v{ver} ({ver_status}) — {pos_str}")

        if validation.sql_results:
            st.markdown("#### SQL Query Validation")
            for ds_name, succeeded, error_msg, cols in validation.sql_results:
                if succeeded:
                    st.markdown(f"- `{ds_name}` — query OK, {len(cols)} columns returned: `{'`, `'.join(cols[:15])}`")
                else:
                    st.markdown(f"- `{ds_name}` — {error_msg}")

        field_issues = [e for e in validation.errors if "fieldName" in e or "query fields" in e]
        dataset_issues = [e for e in validation.errors if "references dataset" in e]
        other_errors = [e for e in validation.errors if e not in field_issues and e not in dataset_issues and "SQL" not in e]

        if field_issues or dataset_issues or other_errors:
            st.markdown("#### Structural Errors")
            for err in field_issues + dataset_issues + other_errors:
                st.markdown(f"- {err}")
        else:
            st.markdown("#### Structural Checks")
            st.markdown("- All widget versions are correct")
            st.markdown("- All encoding fieldNames match query field names")
            st.markdown("- All dataset references are valid")
            st.markdown("- All widget positions are within the 6-column grid")

        if validation.warnings:
            st.markdown("#### Warnings")
            for warn in validation.warnings:
                st.markdown(f"- {warn}")


# ---------------------------------------------------------------------------
# UI Layout
# ---------------------------------------------------------------------------

st.title("Power BI -> AI/BI Converter")
st.caption(
    f"Upload up to **10** Power BI reports and convert them to "
    f"Databricks AI/BI dashboards using Gen AI with **{MODEL}**."
)

with st.expander("How to prepare your upload", icon=":material/help:"):
    st.warning(
        "**One report per file.** Each upload (`.pbit` or `.zip`) must "
        "contain exactly one Power BI report. Do not bundle multiple "
        "reports into the same zip; upload them as separate files instead "
        "(the converter handles batches of up to 10)."
    )
    st.markdown(
        "Two upload formats are supported:\n\n"
        "### Option A: Upload a `.pbit` template (simplest)\n"
        "In Power BI Desktop, go to **File -> Export -> Power BI template** "
        "and save the resulting `.pbit` file. Drag it into the uploader below "
        "as-is (no zipping needed).\n\n"
        "### Option B: Upload a zipped `.pbip` project\n"
        "In Power BI Desktop, go to **File -> Save As** and select "
        '**Power BI project files (*.pbip)** from the "Save as type" dropdown:'
    )
    pbip_img = STATIC_DIR / "power_bi_save_as_pbip.png"
    if pbip_img.is_file():
        st.image(str(pbip_img))
    st.markdown(
        "This creates three items in the same folder:\n"
        "- `YourReport.pbip` — project file\n"
        "- `YourReport.Report/` — report visuals & pages\n"
        "- `YourReport.SemanticModel/` — data model & table definitions\n\n"
        "Select all three items, right-click -> **Compress** (macOS) or **Send to -> Compressed folder** (Windows). "
        "Upload the resulting `.zip` file below."
    )

st.divider()

def _dash_name_key(uf) -> str:
    """Stable session_state key for a file's dashboard name input.

    Uses (name, size) so the key survives Streamlit reruns and is unaffected
    by file reordering. Independent of file_uploader's internal `file_id`.
    """
    size = getattr(uf, "size", None)
    return f"dashname::{uf.name}::{size}"


def _resolve_dashboard_name(uf) -> str:
    """Read the user-entered dashboard name from session_state, falling back
    to the filename basename."""
    default = os.path.splitext(uf.name)[0]
    val = st.session_state.get(_dash_name_key(uf), default)
    if not isinstance(val, str):
        val = default
    val = val.strip()
    return val or default


def _dash_overwrite_key(uf) -> str:
    """Stable session_state key for a file's overwrite checkbox."""
    size = getattr(uf, "size", None)
    return f"dashoverwrite::{uf.name}::{size}"


def _resolve_overwrite(uf) -> bool:
    return bool(st.session_state.get(_dash_overwrite_key(uf), False))


def _remove_uploaded_file(key: str) -> None:
    """Mark a single uploaded file as removed and rerun.

    The widget itself still holds the file internally, but we filter it out
    of every downstream consumer by checking `removed_file_keys`.
    """
    st.session_state.setdefault("removed_file_keys", set()).add(key)


def _clear_all_uploaded_files() -> None:
    """Reset the file_uploader widget entirely.

    Increments the nonce so the widget gets a new `key` on the next render,
    which forces Streamlit to treat it as a fresh widget with no files. Also
    clears the per-file `removed_file_keys` set so re-uploaded files behave
    normally.
    """
    st.session_state["uploader_nonce"] = (
        st.session_state.get("uploader_nonce", 0) + 1
    )
    st.session_state["removed_file_keys"] = set()


st.markdown(
    "**One report per file.** Upload one `.pbit` template or one "
    "compressed `.pbip` project (`.zip` file) per dashboard. "
)

if "uploader_nonce" not in st.session_state:
    st.session_state["uploader_nonce"] = 0
if "removed_file_keys" not in st.session_state:
    st.session_state["removed_file_keys"] = set()

uploaded_files = st.file_uploader(
    "Upload .pbit or zipped .pbip project(s)",
    type=["zip", "pbit"],
    accept_multiple_files=True,
    help=(
        ".zip (full .pbip project, including .Report and .SemanticModel "
        "folders) and .pbit are supported (do not zip more than one "
        "dashboard altogether)"
    ),
    key=f"uploader_{st.session_state['uploader_nonce']}",
)

if uploaded_files:
    uploaded_files = [
        uf
        for uf in uploaded_files
        if _dash_name_key(uf) not in st.session_state["removed_file_keys"]
    ]

if uploaded_files and len(uploaded_files) > 10:
    st.error("Please upload at most 10 files at a time.")
    st.stop()


if uploaded_files:
    with st.container(border=True):
        st.markdown("**Dashboard names**")
        st.caption(
            "These will be the published dashboard names. Edit any of them "
            "below before clicking Convert & Publish. If a dashboard with "
            "the same name already exists, check **Overwrite** to replace it. "
            "Use **Remove** to drop a single file, or **Clear all uploaded "
            "files** at the bottom to start over."
        )
        for uf in uploaded_files:
            default = os.path.splitext(uf.name)[0]
            name_col, ovw_col, rm_col = st.columns([5, 1, 1])
            with name_col:
                st.text_input(
                    label=uf.name,
                    value=default,
                    key=_dash_name_key(uf),
                    help=f"Source file: `{uf.name}`",
                )
            with ovw_col:
                st.markdown(
                    "<div style='height:1.75rem'></div>",
                    unsafe_allow_html=True,
                )
                st.checkbox(
                    "Overwrite",
                    value=False,
                    key=_dash_overwrite_key(uf),
                    help=(
                        "Replace any existing dashboard with this name. "
                        "Trashes the matching AI/BI dashboard and deletes "
                        "the target workspace file before publishing fresh. "
                        "Leave unchecked to fail safely on name conflicts."
                    ),
                )
            with rm_col:
                st.markdown(
                    "<div style='height:1.75rem'></div>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Remove",
                    key=f"remove::{_dash_name_key(uf)}",
                    help=(
                        "Drop this file from the batch. Other uploaded files "
                        "and their settings are kept."
                    ),
                    on_click=_remove_uploaded_file,
                    args=(_dash_name_key(uf),),
                    use_container_width=True,
                )
        st.divider()
        st.button(
            "Clear all uploaded files",
            type="secondary",
            help=(
                "Reset the uploader to empty. Removes every file from the "
                "batch but keeps your color and custom-instructions settings."
            ),
            on_click=_clear_all_uploaded_files,
        )

with st.container(border=True):
    st.markdown("**Color scheme**")
    _preserve_colors = st.toggle(
        "Preserve brand colors from the PBI report",
        value=st.session_state.get("preserve_colors_toggle", True),
        help=(
            "Extract hex colors from each PBI visual (data point fills, "
            "category color assignments) and inject them into the generated "
            "AI/BI dashboard widgets. Turn off to fall back to the Databricks "
            "default palette."
        ),
        key="preserve_colors_toggle",
    )

custom_instructions = st.text_area(
    "Custom Instructions (optional)",
    placeholder=(
        "e.g. rename the table from 'sales' to 'sales_data'"
    ),
    help=(
        "Add any extra context for the conversion. Common uses:\n"
        "- Map external sources to a federated catalog (catalog.schema.table)\n"
        "- Rename or remap specific tables\n"
        "- Specify default catalog/schema for unqualified table names\n"
        "- Request specific SQL transformations or filters"
    ),
    height=100,
)

convert_clicked = st.button("Convert & Publish", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Batch Conversion Orchestration
# ---------------------------------------------------------------------------

if convert_clicked:
    if not uploaded_files:
        st.error("Please upload at least one .pbit file or zipped .pbip project.")
        st.stop()

    # Resolve and validate the per-file dashboard names from the rename inputs.
    invalid_chars = set('/\\:*?"<>|')
    resolved_names: list[str] = []
    for uf in uploaded_files:
        name = _resolve_dashboard_name(uf)
        bad = sorted(c for c in invalid_chars if c in name)
        if bad:
            st.error(
                f"Dashboard name for `{uf.name}` contains invalid character(s): "
                f"`{''.join(bad)}`. Avoid `/ \\ : * ? \" < > |`."
            )
            st.stop()
        resolved_names.append(name)

    if len(set(resolved_names)) < len(resolved_names):
        seen: dict[str, int] = {}
        for n in resolved_names:
            seen[n] = seen.get(n, 0) + 1
        dupes = sorted(n for n, c in seen.items() if c > 1)
        st.error(
            "Two or more uploads share the same dashboard name. "
            f"Please make each unique. Duplicates: {', '.join(repr(d) for d in dupes)}."
        )
        st.stop()

    st.session_state["results"] = []
    st.session_state["batch_running"] = True
    n_files = len(uploaded_files)
    results: list[ReportResult] = []

    overall = st.container()
    overall.markdown(f"### Batch conversion: {n_files} report(s)")

    for idx, uf in enumerate(uploaded_files):
        report_name = resolved_names[idx]
        overwrite_flag = _resolve_overwrite(uf)

        overall.markdown(f"---\n**[{idx + 1}/{n_files}]** Converting **{report_name}**...")
        progress = overall.status(f"Converting {report_name}...", expanded=True)

        result = convert_single_report(
            uf, report_name, progress,
            custom_instructions=custom_instructions,
            preserve_colors=_preserve_colors,
            overwrite=overwrite_flag,
        )
        results.append(result)

        if result.status == "done":
            progress.update(label=f"{report_name} — done!", state="complete")
            with overall.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.markdown(f"**{report_name}** — [Open Dashboard]({result.dash_url})")
                c2.metric("Widgets", result.n_widgets)
                c3.metric("Pages", result.n_canvas)
        else:
            progress.update(label=f"{report_name} — failed", state="error")
            overall.error(f"**{report_name}** failed: {result.error_msg}")

        st.session_state["results"] = list(results)

    st.session_state["results"] = results
    st.session_state["batch_running"] = False

    summary_ok = sum(1 for r in results if r.status == "done")
    summary_err = sum(1 for r in results if r.status == "error")
    overall.markdown(f"### Batch complete: {summary_ok} succeeded, {summary_err} failed")
    overall.info("Scroll down for full results, validation details, and PDF exports for each report.")

# ---------------------------------------------------------------------------
# Results Tabs (persistent across reruns via session_state)
# ---------------------------------------------------------------------------

results: list[ReportResult] = st.session_state.get("results", [])

if results:
    st.divider()
    st.subheader("Conversion Results")

    tab_labels = [f"{r.name}" for r in results]
    tabs = st.tabs(tab_labels)

    for tab, res in zip(tabs, results):
        with tab:
            render_report_results(res)
