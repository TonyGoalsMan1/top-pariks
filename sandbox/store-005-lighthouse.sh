#!/usr/bin/env bash
set -euo pipefail
: "${TOP_PARIKS_URL:?Set the isolated test origin}"
[[ "$TOP_PARIKS_URL" == http://localhost:8080 ]]
output="${1:-store-005-lighthouse}"
mkdir -p "$output"
export CHROME_PATH
CHROME_PATH="$(node -p "require('playwright-core').chromium.executablePath()")"
for profile in mobile desktop; do
    extra=()
    if [[ "$profile" == desktop ]]; then
        extra=(--preset=desktop)
    fi
    for page in home product; do
        path=/
        if [[ "$page" == product ]]; then
            path=/product/topqa-natural/
        fi
        for run in 1 2 3; do
            ./node_modules/.bin/lighthouse "$TOP_PARIKS_URL$path" "${extra[@]}" --chrome-flags='--headless --no-sandbox' \
                --only-categories=performance,accessibility,best-practices,seo --output=json \
                --output-path="$output/$profile-$page-$run.json" --quiet
        done
    done
done
python3 -B sandbox/store-005-lighthouse.py "$output"
