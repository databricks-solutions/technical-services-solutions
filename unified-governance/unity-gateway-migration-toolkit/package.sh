#!/bin/sh
# Build the release zip: the installer notebook at the top, plus the toolkit files for CLI and bundle users
# (no tests, fixtures or sample outputs).
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' ug_migration_planner.py)
(cd app/frontend && npm run build >/dev/null)  # never ship a stale frontend
INSTALLER=$(python3 make_installer.py | cut -d" " -f1)
NAME="unity-gateway-migration-toolkit-$VERSION"
rm -rf "dist/$NAME" "dist/$NAME.zip"
mkdir -p "dist/$NAME/notebook" "dist/$NAME/app/backend" "dist/$NAME/app/frontend"
cp "$INSTALLER" "dist/$NAME/"
cp ug_migration_planner.py ug_migration_apply.py ug_migration_account.py \
   README.md HOW_TO_READ.md USER_GUIDE.md "dist/$NAME/"
# The shipped bundle doesn't need the repo-only sync excludes (they'd only produce validate warnings).
python3 -c "import re,sys; s=open('databricks.yml').read(); print(re.sub(r'  exclude:\n(    - .*\n)+', '', s), end='')" \
  > "dist/$NAME/databricks.yml"
cp notebook/run_planner.py notebook/run_account.py notebook/run_scan.py notebook/run_apply.py "dist/$NAME/notebook/"
cp ug_migration_store.py "dist/$NAME/"
cp app/requirements.txt "dist/$NAME/app/"
cp app/backend/main.py app/backend/__init__.py "dist/$NAME/app/backend/"
cp -R app/frontend/src app/frontend/static "dist/$NAME/app/frontend/"
cp app/frontend/package.json app/frontend/tsconfig.json app/frontend/vite.config.ts \
   app/frontend/index.html "dist/$NAME/app/frontend/"
(cd dist && zip -qr "$NAME.zip" "$NAME")
rm -rf "dist/$NAME"
echo "dist/$NAME.zip (includes $(basename "$INSTALLER"))"
