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

1. In the widgets at the top, pick **1. Catalog** and **2. SQL warehouse**.
2. Leave **3. Schema for new model services** blank: the installer creates `<catalog>.ug_migrated` for you. If you
   already have a schema for them, or want another name, enter it as `catalog.schema`.
3. Click **Run all** (about 5 minutes). The app link is printed at the end.

**Before anything changes**, the notebook runs every check and prints one checklist: what passed, what to fix (with
the exact SQL or screen), and what it will create. If something needs fixing, nothing is changed.

**What it creates**
- In the catalog you pick: the results schema `ug_migration` (scan results and history), and the schema for new
  model services `ug_migrated` (empty until you run Apply). The service names end up in your callers' code
  (`catalog.schema.service`), so pick the schema you want to keep.
- The toolkit files in your home folder (`ug-migration-toolkit`).
- Three jobs the app starts (account snapshot, workspace scan, apply), tagged `Project = unity-gateway-migration-toolkit`.
- The **Unity Gateway Migration Toolkit** app. The first snapshot starts at the end; it reads account-wide system tables.

**What you need:** to be a workspace admin, `USE CATALOG` and `CREATE SCHEMA` on the catalog, `CAN USE` on the
warehouse, and `SELECT` on the system tables (if it's missing, the checklist prints the GRANT to send an account admin).

**To update**, import the newer installer and click Run all. It finds the install and keeps its settings.

**Custom setup** (set **4. Setup** to `custom`, then Run all): more widgets appear for the app name, operators, a
service principal for the jobs, central mode, secret mapping and more. To remove the toolkit, use the UNINSTALL notebook
from the same zip.""",
    "uninstall": """\
Removes a toolkit install from this workspace.

1. Leave **1. Action** at `preview` and click **Run all**. It lists what would be removed and kept, and changes nothing.
2. Choose what else goes (widgets 3 to 5), set **1. Action** to `remove`, and click Run all again.

Model services created by Apply stay unless you set **3** to `yes`. Schemas that hold services are never removed.
Uninstall refuses while a toolkit job is running.""",
}
TITLE = {"install": "Install the Unity Gateway Migration Toolkit", "uninstall": "Uninstall the Unity Gateway Migration Toolkit"}
PROMPT = {"install": "Pick 1. Catalog and 2. SQL warehouse above, then Run all",
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
