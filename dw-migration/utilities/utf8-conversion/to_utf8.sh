#!/usr/bin/env bash
# Bulk-convert UTF-16 files (with BOM) to UTF-8 (no BOM) for Lakebridge / Genie Migrate.
#
# Usage: ./to_utf8.sh <source_dir> <output_dir>
#
# - Writes converted copies to <output_dir>, keeping the folder structure. Source files are never modified.
# - Converts only files that start with a UTF-16 BOM; every other file is copied unchanged.
# - XML exports (.dtsx, .xml, ...): rewrites the declaration encoding="utf-16" to "utf-8".
# - Skips hidden files/folders and the output folder itself (it may sit inside the source).
# Requires: bash, file, iconv, perl (preinstalled on macOS and most Linux distributions).
set -euo pipefail
if [ "$#" -ne 2 ]; then echo "Usage: $0 <source_dir> <output_dir>" >&2; exit 1; fi
src="$(cd "${1%/}" && pwd)"; mkdir -p "${2%/}"; out="$(cd "${2%/}" && pwd)"
converted=0; copied=0
while IFS= read -r -d '' f; do
  rel="${f#"$src"/}"; dest="$out/$rel"
  mkdir -p "$(dirname "$dest")"
  enc=$(file -b --mime-encoding "$f")
  case "$enc" in
    utf-16le|utf-16be|utf-16)
      iconv -f UTF-16 -t UTF-8 "$f" > "$dest"
      # XML-based exports (.dtsx, .xml): fix the declared encoding too
      perl -pi -e 's/(<\?xml[^>]*encoding=")utf-16(")/${1}utf-8${2}/i if $. == 1' "$dest"
      converted=$((converted+1)) ;;
    *) cp "$f" "$dest"; copied=$((copied+1)) ;;
  esac
done < <(find "$src" \( -path "$out" -o -name '.*' \) -prune -o -type f -print0)
echo "Converted: $converted, copied unchanged: $copied -> $out"
echo "Remaining UTF-16 files in output:"
find "$out" -type f -exec file --mime-encoding {} + | grep -i 'utf-16' || echo "  none"
