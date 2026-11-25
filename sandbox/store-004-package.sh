#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${COMPOSE_PROJECT_NAME:?Use the isolated STORE-004 source project}"
: "${TOP_PARIKS_URL:?Source site URL required}"
[[ "$COMPOSE_PROJECT_NAME" == top-pariks-store003 ]]
[[ "$TOP_PARIKS_URL" == http://localhost:8080 ]]
output="${1:?Output directory required}"
mkdir "$output"
extra=()
docker compose exec -T wordpress tar -czf - --exclude='./wp-config.php' --exclude='./wp-content/debug.log' --exclude='.env*' -C /var/www/html . > "$output/site-files.tar.gz"
docker compose exec -T db sh -ec 'mariadb-dump -u "$MARIADB_USER" -p"$MARIADB_PASSWORD" --single-transaction --no-tablespaces "$MARIADB_DATABASE"' > "$output/site.sql"
if [[ "${TOP_PARIKS_STORE005:-}" == yes ]]; then
    docker compose exec -T --user www-data wordpress php /tmp/top-pariks-wp-cli.phar eval 'foreach (get_users() as $user) { echo $user->user_pass, PHP_EOL; }' \
        | python3 -B sandbox/store-005-secret-audit.py "$output"
fi
docker compose cp wordpress:/tmp/top-pariks-wp-cli.phar "$output/wp-cli.phar"
chmod a+r "$output/wp-cli.phar"
cp sandbox/store-004-portable.yaml "$output/compose.yaml"
cp sandbox/store-004-restore.sh "$output/restore.sh"
cp sandbox/STORE-004-portability.md "$output/README.md"
if [[ "${TOP_PARIKS_STORE005:-}" == yes ]]; then
    cp docs/STORE-005-admin.md "$output/ADMIN-RU.md"
    extra+=(ADMIN-RU.md)
fi
printf '%s\n' "$TOP_PARIKS_URL" > "$output/source-url.txt"
(cd "$output" && sha256sum site-files.tar.gz site.sql wp-cli.phar compose.yaml restore.sh source-url.txt README.md "${extra[@]}" > SHA256SUMS)
