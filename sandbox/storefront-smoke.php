<?php
defined('ABSPATH') || exit;

if (wp_get_environment_type() !== 'local' || get_option('blog_public') !== '0') {
    WP_CLI::error('Use the local test store.');
}

$about = wp_insert_post([
    'post_type' => 'page',
    'post_status' => 'publish',
    'post_name' => 'about',
    'post_title' => 'О компании',
    'post_content' => 'Existing About page fixture.',
], true);
$menu = wp_create_nav_menu('Existing storefront menu');
if (is_wp_error($about) || is_wp_error($menu)) {
    WP_CLI::error('Could not create storefront fixtures.');
}
set_theme_mod('nav_menu_locations', ['primary' => $menu]);

$catalog_item = wp_update_nav_menu_item($menu, 0, [
    'menu-item-type' => 'custom',
    'menu-item-title' => 'Shop',
    'menu-item-url' => home_url('/old-shop/'),
    'menu-item-status' => 'publish',
]);
if (is_wp_error($catalog_item)) {
    WP_CLI::error($catalog_item->get_error_message());
}

$snapshot = static function () use ($menu) {
    return [
        wp_count_posts('page')->publish,
        wp_list_pluck(wp_get_nav_menu_items($menu), 'ID'),
        get_option('page_on_front'),
        ...array_map('wc_get_page_id', ['shop', 'cart', 'checkout', 'myaccount']),
    ];
};

$result = tp_provision_storefront();
if (is_wp_error($result)) {
    WP_CLI::error($result->get_error_message());
}
$first = $snapshot();
$result = tp_provision_storefront();
if (is_wp_error($result) || $first !== $snapshot()) {
    WP_CLI::error('Repeated provisioning changed storefront page or menu IDs.');
}

$page_ids = array_slice($first, 2);
if (get_option('show_on_front') !== 'page' || count(array_unique($page_ids)) !== 5
    || min($page_ids) <= 0 || get_post_field('post_content', $about) !== 'Existing About page fixture.'
    || (int) get_post_meta($catalog_item, '_menu_item_object_id', true) !== wc_get_page_id('shop')
    || count($first[1]) !== 5
) {
    WP_CLI::error('Storefront provisioning lost content, links, or page mappings.');
}

WP_CLI::success('Storefront pages, existing content, menu repair and repeated provisioning verified.');
