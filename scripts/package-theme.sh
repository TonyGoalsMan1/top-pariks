#!/usr/bin/env bash
set -euo pipefail

output="${1:-/tmp/top-pariks.zip}"
case "$output" in
    /*) ;;
    *) output="$PWD/$output" ;;
esac

cd "$(dirname "${BASH_SOURCE[0]}")/.."
theme=theme/top-pariks
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT

for file in style.css index.php functions.php header.php footer.php front-page.php page.php woocommerce.php assets/site.js; do
    test -s "$theme/$file" || { echo "Missing or empty theme file: $theme/$file" >&2; exit 1; }
done
head -c 8192 "$theme/style.css" > "$scratch/theme-header"
grep -Ei '^[[:space:]/*#@]*Theme Name:[[:space:]]*[^[:space:]]' "$scratch/theme-header"
grep -Ei '^[[:space:]/*#@]*Version:[[:space:]]*[0-9]' "$scratch/theme-header"

git archive --format=zip --output="$scratch/top-pariks.zip" HEAD:theme top-pariks
unzip -tq "$scratch/top-pariks.zip"
unzip -q "$scratch/top-pariks.zip" -d "$scratch/built"
diff -qr "$theme" "$scratch/built/top-pariks"
unzip -tq top-pariks.zip
unzip -q top-pariks.zip -d "$scratch/checked-in"
diff -qr "$scratch/built" "$scratch/checked-in"

cp "$scratch/top-pariks.zip" "$output"
sha256sum "$output"
