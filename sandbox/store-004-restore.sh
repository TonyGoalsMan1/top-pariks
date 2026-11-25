#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
: "${ATELIER_DEMO_DB_PASSWORD:?Set a fresh demo database password}"
: "${ATELIER_RESTORE_PROJECT:?Name a new project starting with atelier-restore-}"
[[ "$ATELIER_RESTORE_PROJECT" =~ ^atelier-restore-[a-z0-9][a-z0-9_-]*$ ]]
dc=(docker compose -p "$ATELIER_RESTORE_PROJECT" -f compose.yaml)
[[ -z "$("${dc[@]}" ps -aq)" ]]
[[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$ATELIER_RESTORE_PROJECT")" ]]
sha256sum -c SHA256SUMS
"${dc[@]}" up -d --wait --wait-timeout 90
for (( attempt = 0; attempt < 30; attempt++ )); do
    if "${dc[@]}" exec -T wordpress test -s /var/www/html/wp-config.php; then
        break
    fi
    sleep 1
done
"${dc[@]}" exec -T wordpress test -s /var/www/html/wp-config.php
"${dc[@]}" exec -T wordpress tar -xzf - -C /var/www/html < site-files.tar.gz
"${dc[@]}" exec -T db sh -ec 'mariadb -u "$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' < site.sql
"${dc[@]}" cp wp-cli.phar wordpress:/tmp/atelier-wp-cli.phar
site="http://localhost:${ATELIER_DEMO_PORT:-8086}"
"${dc[@]}" exec -T --user www-data wordpress php /tmp/atelier-wp-cli.phar --url="$site" search-replace \
    "$(cat source-url.txt)" "$site" --all-tables-with-prefix --skip-columns=guid --precise
printf 'Restored demonstration: %s\n' "$site"
