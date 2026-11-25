<?php
defined('ABSPATH') || exit;

if ('local' !== wp_get_environment_type() && !defined('TOP_PARIKS_STORE003_SANDBOX')) {
    throw new RuntimeException('STORE-003 fixtures require an isolated sandbox.');
}
if (get_option('top_pariks_store003_seeded')) {
    return;
}
if (!class_exists('WooCommerce') || !wc_get_product_id_by_sku('TOPQA-NATURAL')) {
    throw new RuntimeException('Run the existing test-store seed first.');
}

$definitions = [
    'material' => ['Материал', ['natural' => 'Натуральный', 'synthetic' => 'Искусственный']],
    'length' => ['Длина', ['short' => 'Короткие', 'long' => 'Длинные']],
    'color' => ['Цвет', ['chestnut' => 'Каштановый', 'blond' => 'Светлый']],
];
$attributes = [];
foreach ($definitions as $slug => [$label, $values]) {
    $taxonomy = wc_attribute_taxonomy_name($slug);
    $id = wc_attribute_taxonomy_id_by_name($slug);
    if (!$id) {
        $id = wc_create_attribute(['name' => $label, 'slug' => $slug]);
    }
    if (is_wp_error($id)) {
        throw new RuntimeException($id->get_error_message());
    }
    if (!taxonomy_exists($taxonomy)) {
        register_taxonomy($taxonomy, ['product'], ['hierarchical' => true]);
    }
    foreach ($values as $term_slug => $name) {
        $term = term_exists($term_slug, $taxonomy) ?: wp_insert_term($name, $taxonomy, ['slug' => $term_slug]);
        if (is_wp_error($term)) {
            throw new RuntimeException($term->get_error_message());
        }
        $attributes[$slug][$term_slug] = [$id, (int) $term['term_id']];
    }
}

$build_attributes = static function ($material, $length, $colors, $variations = false) use ($attributes) {
    $items = [];
    foreach (['material' => [$material], 'length' => [$length], 'color' => $colors] as $slug => $values) {
        $attribute = new WC_Product_Attribute();
        $attribute->set_id($attributes[$slug][$values[0]][0]);
        $attribute->set_name(wc_attribute_taxonomy_name($slug));
        $attribute->set_options(array_map(static function ($value) use ($attributes, $slug) {
            return $attributes[$slug][$value][1];
        }, $values));
        $attribute->set_visible(true);
        $attribute->set_variation($variations && 'color' === $slug);
        $items[] = $attribute;
    }
    return $items;
};

$get_fixture_image = static function ($name) {
    $existing = get_page_by_path('topqa-store003-' . $name, OBJECT, 'attachment');
    if ($existing) {
        return (int) $existing->ID;
    }
    $file = get_template_directory() . '/assets/images/' . $name . '.webp';
    $upload = wp_upload_bits('topqa-store003-' . $name . '.webp', null, file_get_contents($file));
    if ($upload['error']) {
        throw new RuntimeException($upload['error']);
    }
    $id = wp_insert_attachment([
        'post_name' => 'topqa-store003-' . $name,
        'post_title' => 'ТЕСТ — иллюстрация модели',
        'post_mime_type' => 'image/webp',
        'post_status' => 'inherit',
    ], $upload['file'], 0, true);
    if (is_wp_error($id)) {
        throw new RuntimeException($id->get_error_message());
    }
    require_once ABSPATH . 'wp-admin/includes/image.php';
    wp_update_attachment_metadata($id, wp_generate_attachment_metadata($id, $upload['file']));
    update_post_meta($id, '_wp_attachment_image_alt', 'Иллюстрация тестовой модели парика');
    return $id;
};

$natural = wc_get_product(wc_get_product_id_by_sku('TOPQA-NATURAL'));
$natural->set_attributes($build_attributes('natural', 'long', ['chestnut']));
$natural->set_short_description('Тестовая модель. Характеристики и цена предназначены для проверки магазина.');
$natural->set_manage_stock(true);
$natural->set_stock_quantity(40);
$natural->set_image_id($get_fixture_image('product-1'));
$natural->set_gallery_image_ids([$get_fixture_image('product-2')]);
$natural->save();
// The existing Studio fixture deliberately has no photo or attributes.

$variable = new WC_Product_Variable(wc_get_product_id_by_sku('TOPQA-CHOICE') ?: 0);
$variable->set_sku('TOPQA-CHOICE');
$variable->set_name('ТЕСТ — модель с выбором цвета');
$variable->set_slug('topqa-choice');
$variable->set_status('publish');
$variable->set_short_description('Синтетические данные для проверки выбора цвета и остатков.');
$variable->set_attributes($build_attributes('synthetic', 'short', ['chestnut', 'blond'], true));
$variable->set_category_ids(wc_get_product(wc_get_product_id_by_sku('TOPQA-SYNTHETIC'))->get_category_ids());
$variable->set_image_id($get_fixture_image('product-3'));
$variable->save();

foreach (['chestnut' => ['24.00', 8], 'blond' => ['26.00', 0]] as $color => [$price, $quantity]) {
    $sku = 'TOPQA-CHOICE-' . strtoupper($color);
    $variation = new WC_Product_Variation(wc_get_product_id_by_sku($sku) ?: 0);
    $variation->set_parent_id($variable->get_id());
    $variation->set_sku($sku);
    $variation->set_status('publish');
    $variation->set_attributes(['pa_color' => $color]);
    $variation->set_virtual(true);
    $variation->set_regular_price($price);
    $variation->set_manage_stock(true);
    $variation->set_stock_quantity($quantity);
    $variation->save();
}
WC_Product_Variable::sync($variable->get_id());

$cod = get_option('woocommerce_cod_settings', []);
$cod['title'] = 'Тестовая оплата без списания';
$cod['description'] = 'Проверка оформления заказа. Деньги не списываются.';
$cod['instructions'] = 'Это тестовый заказ. Оплата не требуется.';
update_option('woocommerce_cod_settings', $cod);
update_option('woocommerce_coming_soon', 'no');

foreach (['returns' => 'Возврат', 'privacy-policy' => 'Политика конфиденциальности'] as $slug => $name) {
    $page = get_page_by_path($slug);
    if (!$page || 'publish' !== $page->post_status) {
        $page_id = wp_insert_post([
            'post_type' => 'page',
            'post_status' => 'publish',
            'post_name' => $page ? 'store-003-' . $slug : $slug,
            'post_title' => $name,
            'post_content' => 'Тестовая витрина. Раздел ожидает утверждённого текста владельца магазина.',
        ], true);
        if (is_wp_error($page_id)) {
            throw new RuntimeException($page_id->get_error_message());
        }
    } else {
        $page_id = $page->ID;
    }
    if ('privacy-policy' === $slug) {
        update_option('wp_page_for_privacy_policy', $page_id);
    }
}
flush_rewrite_rules(false);
update_option('top_pariks_store003_seeded', '1');
