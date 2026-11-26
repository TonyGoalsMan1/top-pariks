#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

site_url="${TOP_PARIKS_URL:-http://localhost:${TOP_PARIKS_PORT:-8080}}"
site_url="${site_url%/}"
runtime_dir="$(mktemp -d)"
trap 'rm -rf -- "$runtime_dir"' EXIT

docker compose up -d --wait --wait-timeout 90
for (( attempt = 0; attempt < 30; attempt++ )); do
    if docker compose exec -T wordpress test -s /var/www/html/wp-config.php; then
        break
    fi
    sleep 1
done
docker compose exec -T wordpress test -s /var/www/html/wp-config.php

download() {
    local url="$1" destination="$2" sha256="$3"
    curl --fail --silent --show-error --location --max-time 90 "$url" --output "$destination"
    printf '%s  %s\n' "$sha256" "$destination" | sha256sum --check
    chmod 644 "$destination"
}

if ! docker compose exec -T --user www-data wordpress test -r /tmp/top-pariks-wp-cli.phar; then
    download https://github.com/wp-cli/wp-cli/releases/download/v2.12.0/wp-cli-2.12.0.phar \
        "$runtime_dir/wp-cli.phar" ce34ddd838f7351d6759068d09793f26755463b4a4610a5a5c0a97b68220d85c
    docker compose cp "$runtime_dir/wp-cli.phar" wordpress:/tmp/top-pariks-wp-cli.phar
fi
docker compose exec -T --user www-data wordpress sh -ec '
    test -r /opt/top-pariks/seed.php
    test -r /var/www/html/.htaccess
    test -r /var/www/html/wp-content/mu-plugins/test-only.php
    test -r /var/www/html/wp-content/themes/top-pariks/style.css
'

wp() {
    docker compose exec -T --user www-data wordpress \
        php /tmp/top-pariks-wp-cli.phar --path=/var/www/html --url="$site_url" "$@"
}

if ! wp core is-installed; then
    wp core install --title='TOP-PARIKS TEST' \
        --admin_user=topqa --admin_email=qa@example.test --skip-email >/dev/null
fi

# Install the pinned package directly into the test container. Core blocks
# external HTTP and dashboard-based plugin installs for this environment.
if ! wp plugin is-installed woocommerce; then
    download https://github.com/woocommerce/woocommerce/releases/download/11.3.1/woocommerce.zip \
        "$runtime_dir/woocommerce.zip" 8fe15ed36796eefd8aebc84363520ea10b95e034071353ba3e4773333f09f278
    docker compose cp "$runtime_dir/woocommerce.zip" wordpress:/tmp/top-pariks-woocommerce.zip
    docker compose exec -T --user www-data wordpress php -r '
        $archive = new ZipArchive();
        if ($archive->open("/tmp/top-pariks-woocommerce.zip") !== true ||
            !$archive->extractTo("/var/www/html/wp-content/plugins") || !$archive->close()) {
            exit(1);
        }
    '
fi
wp option update home "$site_url"
wp option update siteurl "$site_url"
wp plugin activate woocommerce
wp theme activate top-pariks
wp rewrite structure '/%postname%/'
wp eval-file /opt/top-pariks/seed.php
printf '\nTOP-PARIKS TEST: %s\n' "$site_url"
