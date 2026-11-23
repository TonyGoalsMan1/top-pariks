#!/usr/bin/env bash
set -euo pipefail
umask 077

operation="$1"
wp_path="$(realpath -e -- "$2")"
backup_root="$(realpath -e -- "$3")"
run_id="$4"
backup_id="$5"
url=https://top-pariks-test.freehosting.dev
slug=top-pariks

die() { echo "$*" >&2; exit 1; }
[[ "$run_id" =~ ^[0-9]+-[0-9]+$ ]] || die 'Invalid run ID.'
case "$operation" in
    deploy) [[ -z "$backup_id" ]] || die 'Unexpected backup ID.' ;;
    rollback) [[ "$backup_id" =~ ^[0-9]+-[0-9]+$ ]] || die 'Invalid backup ID.' ;;
    *) die 'Invalid staging operation.' ;;
esac

[[ -d "$backup_root" && "$backup_root" != / && "$backup_root/" != "$wp_path/"* ]] ||
    die 'Provision a private backup directory outside the WordPress root.'
[[ "$(stat -c '%a:%u' "$backup_root")" == "700:$(id -u)" ]] ||
    die 'The backup directory must be owned by the SSH user and have mode 0700.'

wp_staging() { wp --path="$wp_path" --url="$url" "$@"; }
wp_safe() { wp_staging --skip-plugins --skip-themes "$@"; }
site="$(wp_safe eval 'if (is_multisite()) { exit(1); } echo untrailingslashit(home_url()), "\n", untrailingslashit(site_url());')"
[[ "$site" == "$url"$'\n'"$url" ]] || die 'WordPress home and site URL must both match the staging domain.'
theme_root="$(wp_safe eval 'echo get_theme_root("top-pariks");')"
theme_root="$(realpath -e -- "$theme_root")"
[[ "$theme_root" == "$wp_path/wp-content/themes" && -w "$theme_root" ]] ||
    die 'Expected a writable, standard staging themes directory.'
[[ "$(stat -c %d "$theme_root")" == "$(stat -c %d "$backup_root")" ]] ||
    die 'Themes and backups must be on the same filesystem.'

exec 9>"$backup_root/.deploy.lock"
flock -n 9 || die 'Another staging update is in progress.'
live="$theme_root/$slug"
[[ ! -L "$live" && ( ! -e "$live" || -d "$live" ) ]] ||
    die 'Expected a theme directory or an absent theme.'
previous="$(wp_safe option get stylesheet)"
[[ "$previous" =~ ^[A-Za-z0-9_-]+$ ]] || die 'Unexpected active theme slug.'
wp_safe theme is-installed "$previous"

record="$backup_root/$run_id"
mkdir -- "$record"
printf '%s\n' "$previous" > "$record/active-theme"
candidate="$record/candidate"
mkdir -- "$candidate"

case "$operation" in
    deploy)
        write_archive > "$record/top-pariks.zip"
        printf '%s  %s\n' "$artifact_sha256" "$record/top-pariks.zip" | sha256sum --check --status
        unzip -tq "$record/top-pariks.zip"
        unzip -q "$record/top-pariks.zip" -d "$candidate"
        find "$candidate/$slug" -type d -exec chmod 0755 {} +
        find "$candidate/$slug" -type f -exec chmod 0644 {} +
        rm -- "$record/top-pariks.zip"
        desired="$slug"
        ;;
    rollback)
        source="$backup_root/$backup_id"
        [[ -f "$source/complete" ]] || die 'Completed staging backup not found.'
        desired="$(cat "$source/active-theme")"
        [[ "$desired" =~ ^[A-Za-z0-9_-]+$ ]] || die 'Invalid active theme in backup.'
        if [[ -d "$source/$slug" ]]; then
            cp -a -- "$source/$slug" "$candidate/$slug"
        else
            [[ -f "$source/absent" && "$desired" != "$slug" ]] || die 'Incomplete staging backup.'
        fi
        ;;
esac

set_active_theme() {
    if [[ "$(wp_safe option get stylesheet)" != "$1" ]]; then
        wp_safe theme activate "$1" || return
    fi
    [[ "$(wp_safe option get stylesheet)" == "$1" ]]
}

restore_on_failure() {
    local status=$?
    trap - EXIT
    trap '' INT TERM HUP
    if (( status == 0 )); then
        return
    fi
    echo "Staging operation failed. Restoring previous theme from $run_id." >&2
    rm -f -- "$record/complete"
    if [[ -d "$record/$slug" || -f "$record/absent" ]]; then
        if [[ -d "$live" ]] && ! mv -T -- "$live" "$record/rejected-theme"; then
            die "Automatic rollback could not move the candidate. Recover backup $run_id on the server."
        fi
        if [[ -d "$record/$slug" ]] && ! mv -T -- "$record/$slug" "$live"; then
            die "Automatic rollback could not restore the theme files. Recover backup $run_id on the server."
        fi
    fi
    set_active_theme "$previous" || die "Automatic rollback could not restore the active theme. Check backup $run_id."
    echo 'Previous theme files and active theme restored.' >&2
    exit "$status"
}

echo "Staging backup ID: $run_id"
trap restore_on_failure EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
if [[ -d "$live" ]]; then
    mv -T -- "$live" "$record/$slug"
else
    touch "$record/absent"
fi
if [[ -d "$candidate/$slug" ]]; then
    mv -T -- "$candidate/$slug" "$live"
fi
set_active_theme "$desired"

wp_staging plugin is-active woocommerce
routes="$(wp_staging eval '
foreach (array("shop", "cart", "checkout") as $page) {
    $id = wc_get_page_id($page);
    if ($id <= 0 || get_post_status($id) !== "publish") {
        fwrite(STDERR, "Missing published WooCommerce page: " . $page . PHP_EOL);
        exit(1);
    }
    echo get_permalink($id), PHP_EOL;
}')"
mapfile -t store_urls <<< "$routes"
[[ "${#store_urls[@]}" == 3 ]] || die 'Expected three WooCommerce page URLs.'
for page in "${store_urls[@]}"; do
    [[ "$page" == "$url/"* ]] || die 'Unexpected WooCommerce URL outside staging.'
done

# Empty carts can redirect from checkout. Verify its page in WordPress above
# and exercise checkout with a populated cart only in the isolated CI store.
for page in "$url/" "${store_urls[0]}" "${store_urls[1]}"; do
    response="$(curl --disable --silent --show-error --proto '=https' --max-time 20 \
        --header 'Cache-Control: no-cache' --output "$record/response.html" \
        --write-out '%{http_code}' -- "$page")"
    [[ "$response" == 200 ]] || die "Staging returned HTTP $response."
    if grep -Eiq 'critical error on this website|class="wp-die-message"|fatal error:|there has been a critical error' "$record/response.html"; then
        die 'WordPress returned an error page.'
    fi
    if [[ "$desired" == "$slug" ]]; then
        grep -Fq 'class="site-header"' "$record/response.html" || die 'Staging did not render the TOP-PARIKS header.'
    fi
done
rm -- "$record/response.html"
touch "$record/complete"
trap - EXIT INT TERM HUP
echo "Staging verified. Active theme: $desired. Backup ID: $run_id."
