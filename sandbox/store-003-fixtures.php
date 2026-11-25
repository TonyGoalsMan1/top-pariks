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
$studio_categories = wc_get_product(wc_get_product_id_by_sku('TOPQA-SYNTHETIC'))->get_category_ids();
$short = get_term_by('slug', 'short-wigs', 'product_cat');
$child = term_exists('pixie-test', 'product_cat', $short->term_id)
    ?: wp_insert_term('ТЕСТ — пикси', 'product_cat', ['slug' => 'pixie-test', 'parent' => $short->term_id]);
if (is_wp_error($child)) {
    throw new RuntimeException($child->get_error_message());
}
$variable->set_category_ids(array_merge($studio_categories, [(int) $child['term_id']]));
$variable->set_image_id($get_fixture_image('product-3'));
$variable->save();

foreach (['chestnut' => ['24.00', 8], 'blond' => ['26.00', 0]] as $color => [$price, $quantity]) {
    $sku = 'TOPQA-CHOICE-' . strtoupper($color);
    $variation = new WC_Product_Variation(wc_get_product_id_by_sku($sku) ?: 0);
    $variation->set_parent_id($variable->get_id());
    $variation->set_sku($sku);
    $variation->set_status('publish');
    $variation->set_attributes(['pa_color' => $color]);
    $variation->set_virtual(false);
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
update_option('woocommerce_ship_to_countries', 'specific');
update_option('woocommerce_specific_ship_to_countries', ['US']);
update_option('woocommerce_ship_to_destination', 'shipping');
$zone = null;
foreach (WC_Shipping_Zones::get_zones() as $configured_zone) {
    if ('ТЕСТ — доставка' === $configured_zone['zone_name']) {
        $zone = WC_Shipping_Zones::get_zone($configured_zone['zone_id']);
        break;
    }
}
if (!$zone) {
    $zone = new WC_Shipping_Zone();
    $zone->set_zone_name('ТЕСТ — доставка');
    $zone->add_location('US', 'country');
    $zone->save();
}
if (!$zone->get_shipping_methods()) {
    $instance_id = $zone->add_shipping_method('flat_rate');
    if (!$instance_id) {
        throw new RuntimeException('Cannot create sandbox shipping method.');
    }
    update_option('woocommerce_flat_rate_' . $instance_id . '_settings', [
        'title' => 'Тестовая доставка',
        'cost' => '0',
        'tax_status' => 'none',
    ]);
}

$store_page_titles = [
    'shop' => ['Shop', 'Каталог'],
    'cart' => ['Cart', 'Корзина'],
    'checkout' => ['Checkout', 'Оформление заказа'],
    'myaccount' => ['My account', 'Личный кабинет'],
];
foreach ($store_page_titles as $key => [$original, $translated]) {
    $page_id = wc_get_page_id($key);
    if ($page_id > 0 && 0 === strcasecmp(get_post_field('post_title', $page_id), $original)) {
        $updated = wp_update_post(['ID' => $page_id, 'post_title' => $translated], true);
        if (is_wp_error($updated)) {
            throw new RuntimeException($updated->get_error_message());
        }
    }
}
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
