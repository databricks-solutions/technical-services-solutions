"""Build dist/INSTALL_unity_gateway_migration_toolkit_<version>.py: one notebook that installs the app inside a workspace.

The notebook embeds the runtime files (modules, job notebooks, app backend, built frontend, docs) as a
base64 zip, so customers only import this one file and click Run all.
"""

import base64
import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["ug_migration_planner.py", "ug_migration_apply.py", "ug_migration_account.py",
         "ug_migration_store.py", "README.md", "USER_GUIDE.md", "HOW_TO_READ.md",
         "notebook/run_planner.py", "notebook/run_account.py", "notebook/run_scan.py", "notebook/run_apply.py",
         "app/requirements.txt", "app/backend/__init__.py", "app/backend/main.py"]


def main() -> str:
    version = re.search(r'^__version__ = "(.+)"', open(os.path.join(HERE, "ug_migration_planner.py")).read(), re.M).group(1)
    static = os.path.join(HERE, "app/frontend/static")
    if not os.path.exists(os.path.join(static, "index.html")):
        sys.exit("build the frontend first: cd app/frontend && npm run build")
    src = os.path.join(HERE, "app/frontend/src")
    newest_src = max(os.path.getmtime(os.path.join(r, n)) for r, _, ns in os.walk(src) for n in ns)
    if newest_src > os.path.getmtime(os.path.join(static, "index.html")):
        sys.exit("app/frontend/static is older than app/frontend/src: run ./package.sh (or npm run build) first")
    files = list(FILES)
    for root, _, names in os.walk(static):
        files += [os.path.relpath(os.path.join(root, n), HERE) for n in names]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            z.write(os.path.join(HERE, f), f)
    payload = base64.b64encode(buf.getvalue()).decode()
    tpl = open(os.path.join(HERE, "installer/install_template.py")).read()
    out = tpl.replace("__VERSION__", version).replace("__PAYLOAD__", payload)
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    path = os.path.join(HERE, "dist", f"INSTALL_unity_gateway_migration_toolkit_{version.replace('.', '_')}.py")
    open(path, "w").write(out)
    return path


if __name__ == "__main__":
    p = main()
    print(p, f"{os.path.getsize(p) // 1024} KB")
