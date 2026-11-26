#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${ATELIER_DEMO_DB_PASSWORD:?Use a fresh test database password}"
: "${ATELIER_RESTORE_PROJECT:?Use a fresh isolated restore project}"
: "${ATELIER_DEMO_PORT:?Use a separate local HTTP port}"
[[ "$ATELIER_RESTORE_PROJECT" =~ ^atelier-restore-[a-z0-9][a-z0-9_-]*$ ]]
[[ "$ATELIER_DEMO_PORT" =~ ^[0-9]{4,5}$ && "$ATELIER_DEMO_PORT" != 8080 ]]
output="${1:?Output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
work="$(mktemp -d)"
archive=top-pariks-atelier-portable.tar.gz

TOP_PARIKS_STORE005=yes bash sandbox/store-004-package.sh "$work/package"
(
    cd "$work/package"
    tar -czf "$output/$archive" .
)
(
    cd "$output"
    sha256sum "$archive" > "$archive.sha256"
    sha256sum -c "$archive.sha256"
    cat "$archive.sha256"
)

# Restore a new database and a new URL from the exact downloadable archive.
mkdir "$work/restore"
tar -xzf "$output/$archive" -C "$work/restore"
dc=(docker compose -p "$ATELIER_RESTORE_PROJECT" -f "$work/restore/compose.yaml")
(
    cd "$work/restore"
    bash restore.sh
)
trap '"${dc[@]}" down --volumes' EXIT
site="http://localhost:$ATELIER_DEMO_PORT"
for route in / /shop/ /product/topqa-natural/ /product/topqa-choice/ /cart/ /my-account/ /wig-care/; do
    curl --fail --silent --show-error --location --max-redirs 3 --max-time 20 "$site$route" -o /dev/null
done
"${dc[@]}" exec -T --user www-data wordpress php /tmp/atelier-wp-cli.phar --url="$site" eval '
    $product = wc_get_product(wc_get_product_id_by_sku("TOPQA-NATURAL"));
    $variable = wc_get_product(wc_get_product_id_by_sku("TOPQA-CHOICE"));
    if (home_url() !== WP_CLI::get_runner()->config["url"] || strpos(home_url(), ":8080") !== false
        || get_bloginfo("version") !== "7.1.5" || WC_VERSION !== "11.3.1"
        || wp_get_theme()->get("Version") !== "1.3.3" || get_locale() !== "ru_RU"
        || get_option("blog_public") !== "0" || !$product || !$product->get_image_id()
        || !is_file(get_attached_file($product->get_image_id())) || !$variable || count($variable->get_children()) !== 2) {
        WP_CLI::error("Restored URL, versions, locale, index settings or catalog data do not match.");
    }
    foreach (get_users() as $user) {
        if ($user->user_pass !== "*" || !str_ends_with($user->user_email, "@example.test")) {
            WP_CLI::error("Unexpected account data in the exported snapshot.");
        }
    }
    WP_CLI::success("Independent restore verified: WordPress 7.1.5, WooCommerce 11.3.1, Atelier 1.3.3, Russian locale, noindex, products, images and variations.");
'