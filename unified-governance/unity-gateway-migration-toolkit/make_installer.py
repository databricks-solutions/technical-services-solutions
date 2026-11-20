"""Build dist/INSTALL_unity_gateway_migration_toolkit_<version>.py: one notebook that installs the app inside a workspace.

The notebook embeds the runtime files (modules, job notebooks, app backend, built frontend, docs) as a
base64 zip, so customers only import this one file and click Run all. The zip has fixed timestamps and
permissions, so the same sources always give the same bytes (check_release.py relies on that).
"""

import base64
import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["ug_migration_planner.py", "ug_migration_apply.py", "ug_migration_account.py",
         "ug_migration_store.py", "README.md", "INSTALL.md", "USER_GUIDE.md", "HOW_TO_READ.md",
         "notebook/run_planner.py", "notebook/run_account.py", "notebook/run_scan.py", "notebook/run_apply.py",
         "app/requirements.txt", "app/backend/__init__.py", "app/backend/main.py"]
# The app imports these modules (one copy of the rules for the app and the jobs). The app is deployed from app/
# alone, so the installer also writes them next to main.py: app/backend/<module> in the zip, from the root file.
APP_MODULES = ["ug_migration_store.py", "ug_migration_apply.py", "ug_migration_planner.py"]


def build(out_dir: str, check_fresh: bool = True) -> str:
    """Write the installer into out_dir and return its path. check_fresh=False skips the mtime check (a fresh
    git checkout gives every file the same mtime, so CI can't use it)."""
    version = re.search(r'^__version__ = "(.+)"', open(os.path.join(HERE, "ug_migration_planner.py")).read(), re.M).group(1)
    static = os.path.join(HERE, "app/frontend/static")
    if not os.path.exists(os.path.join(static, "index.html")):
        sys.exit("build the frontend first: cd app/frontend && npm run build")
    src = os.path.join(HERE, "app/frontend/src")
    if check_fresh:
        newest_src = max(os.path.getmtime(os.path.join(r, n)) for r, _, ns in os.walk(src) for n in ns)
        if newest_src > os.path.getmtime(os.path.join(static, "index.html")):
            sys.exit("app/frontend/static is older than app/frontend/src: run ./package.sh (or npm run build) first")
    files = [(f, f) for f in FILES] + [(f"app/backend/{m}", m) for m in APP_MODULES]  # (name in the zip, source)
    for root, _, names in os.walk(static):
        files += [(f, f) for f in (os.path.relpath(os.path.join(root, n), HERE) for n in names)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f, src in sorted(files):
            info = zipfile.ZipInfo(f, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(os.path.join(HERE, src), "rb") as fh:
                z.writestr(info, fh.read())
    payload = base64.b64encode(buf.getvalue()).decode()
    tpl = open(os.path.join(HERE, "installer/install_template.py")).read()
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for mode in ("install", "uninstall"):
        path = os.path.join(out_dir, notebook_name(mode, version))
        open(path, "w").write(render(tpl, mode, version, payload if mode == "install" else ""))
        paths.append(path)
    return paths[0]


def notebook_name(mode: str, version: str) -> str:
    return f"{mode.upper()}_unity_gateway_migration_toolkit_{version.replace('.', '_')}.py"


INTRO = {
    "install": """\
Installs the toolkit in this workspace. No CLI, Git or local setup.

1. Click **Run all**. The first run checks the workspace and shows what it will create, but changes nothing.
2. Review the checklist and plan, then set `preview=False` in `install(...)` and click **Run all** again to install.

The usual settings need no edit: `catalog=None` uses the workspace default, `warehouse=None` finds an unambiguous running
warehouse, and `target_schema=None` creates `<catalog>.ug_migrated`. Use `catalog="main"`, `warehouse="Shared"` or
`target_schema="main.models"` to override them. `help(install)` lists every advanced setting, including central mode and
secret mapping. Lists or comma-separated strings work for `operators`, `central_workspaces` and `secret_schemas`.

The checklist marks each check OK, FIX or NOTE. A stopped warehouse and missing schemas are created or started only after
confirmation. FIX stops before any write and names the exact GRANT or setting to fix.

**What it creates after confirmation**
- In the chosen catalog: results schema `ug_migration` and model-service schema `ug_migrated` (empty until Apply).
- The toolkit files, three jobs and the **Unity Gateway Migration Toolkit** app. The first snapshot reads account-wide system tables.

**What you need:** permission to create apps and jobs (usually a workspace admin), `USE CATALOG` and `CREATE SCHEMA`
on the catalog, `CAN USE` on the warehouse, and `SELECT` on the system tables (if it's missing, the checklist prints
the GRANT to send an account admin).

**To update**, import the newer installer and use the same call. None reuses every existing setting. (From 0.10 or
earlier it asks once for the operators, who can start jobs in the app: Databricks doesn't return them.) Notebook jobs
execute with `preview=False` and keep the old parameter names. To remove the toolkit, use the UNINSTALL notebook.""",
    "uninstall": """\
Removes a toolkit install from this workspace.

1. Click **Run all**. **1. Action** starts at `preview`: it lists what would be removed and kept, and changes nothing.
2. Choose what else goes (widgets 3 to 5), set **1. Action** to `remove`, and click Run all again.

Model services created by Apply stay unless you set **3** to `yes`. Schemas that hold services are never removed.
Uninstall refuses while a toolkit job is running.""",
}
TITLE = {"install": "Install the Unity Gateway Migration Toolkit", "uninstall": "Uninstall the Unity Gateway Migration Toolkit"}
PROMPT = {"install": "Run all to preview; the result is under '1. Toolkit files'. Set preview=False to install",
          "uninstall": "Run all with 1. Action = preview first: it changes nothing"}


def render(tpl: str, mode: str, version: str, payload: str) -> str:
    intro = "\n".join("# MAGIC" + (" " + line if line else "") for line in INTRO[mode].splitlines())
    return (tpl.replace("__TITLE__", TITLE[mode]).replace("__INTRO__", intro).replace("__PROMPT__", PROMPT[mode])
            .replace("__MODE__", mode).replace("__VERSION__", version).replace("__PAYLOAD__", payload))


def main() -> str:
    return build(os.path.join(HERE, "dist"))


if __name__ == "__main__":
    p = main()
    print(p, f"{os.path.getsize(p) // 1024} KB")
