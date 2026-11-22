<?php
defined('ABSPATH') || exit;

// The sandbox suppresses mail, so customers choose a password at registration.
update_option('woocommerce_enable_myaccount_registration', 'yes');
update_option('woocommerce_registration_generate_password', 'no');

if (get_option('top_pariks_test_seeded')) {
    return;
}

update_option('blog_public', '0');
update_option('woocommerce_default_country', 'US:CA');
update_option('woocommerce_currency', 'USD');
update_option('woocommerce_enable_guest_checkout', 'yes');
update_option('woocommerce_calc_taxes', 'no');
update_option('woocommerce_ship_to_countries', 'disabled');
update_option('woocommerce_cod_settings', [
    'enabled' => 'yes',
    'title' => 'Test only — offline payment',
    'description' => 'Demo checkout. No payment will be collected.',
    'instructions' => 'Test order only. Do not send payment.',
    'enable_for_virtual' => 'yes',
]);

WC_Install::create_pages();
foreach (['cart' => '[woocommerce_cart]', 'checkout' => '[woocommerce_checkout]'] as $page => $shortcode) {
    $page_id = wc_get_page_id($page);
    if ($page_id <= 0) {
        WP_CLI::error("Missing WooCommerce page: $page");
    }

    $updated = wp_update_post(['ID' => $page_id, 'post_content' => $shortcode], true);
    if (is_wp_error($updated)) {
        WP_CLI::error($updated->get_error_message());
    }
}

$categories = [
    'natural-wigs' => 'ТЕСТ — натуральные парики',
    'synthetic-wigs' => 'ТЕСТ — синтетические парики',
    'short-wigs' => 'ТЕСТ — короткие парики',
    'long-wigs' => 'ТЕСТ — длинные парики',
];
$category_ids = [];
foreach ($categories as $slug => $label) {
    $term = term_exists($slug, 'product_cat') ?: wp_insert_term($label, 'product_cat', ['slug' => $slug]);
    if (is_wp_error($term)) {
        WP_CLI::error($term->get_error_message());
    }

    $category_ids[$slug] = (int) $term['term_id'];
}

$fixtures = [
    ['TOPQA-NATURAL', 'ТЕСТ — модель Atelier', '19.00', ['natural-wigs', 'long-wigs']],
    ['TOPQA-SYNTHETIC', 'ТЕСТ — модель Studio', '11.00', ['synthetic-wigs', 'short-wigs']],
];
foreach ($fixtures as [$sku, $name, $price, $slugs]) {
    $existing_id = wc_get_product_id_by_sku($sku);
    $product = new WC_Product_Simple($existing_id ?: 0);
    $product->set_sku($sku);
    $product->set_name($name);
    $product->set_slug(strtolower($sku));
    $product->set_regular_price($price);
    $product->set_status('publish');
    $product->set_virtual(true);
    $product->set_category_ids(array_map(static function ($slug) use ($category_ids) {
        return $category_ids[$slug];
    }, $slugs));
    $product->save();
}

flush_rewrite_rules();
update_option('top_pariks_test_seeded', '1');
WP_CLI::success('Created four test categories and two virtual products.');
