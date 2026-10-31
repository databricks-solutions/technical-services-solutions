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
         "ug_migration_store.py", "README.md", "USER_GUIDE.md", "HOW_TO_READ.md",
         "notebook/run_planner.py", "notebook/run_account.py", "notebook/run_scan.py", "notebook/run_apply.py",
         "app/requirements.txt", "app/backend/__init__.py", "app/backend/main.py"]


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
    files = list(FILES)
    for root, _, names in os.walk(static):
        files += [os.path.relpath(os.path.join(root, n), HERE) for n in names]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            info = zipfile.ZipInfo(f, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(os.path.join(HERE, f), "rb") as fh:
                z.writestr(info, fh.read())
    payload = base64.b64encode(buf.getvalue()).decode()
    tpl = open(os.path.join(HERE, "installer/install_template.py")).read()
    out = tpl.replace("__VERSION__", version).replace("__PAYLOAD__", payload)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"INSTALL_unity_gateway_migration_toolkit_{version.replace('.', '_')}.py")
    open(path, "w").write(out)
    return path


def main() -> str:
    return build(os.path.join(HERE, "dist"))


if __name__ == "__main__":
    p = main()
    print(p, f"{os.path.getsize(p) // 1024} KB")
