<?php
defined('ABSPATH') || exit;

foreach ([
    'material' => ['Материал', ['Натуральные волосы', 'Искусственное волокно']],
    'length' => ['Длина', ['Длинные', 'Короткие']],
    'color' => ['Цвет', ['Каштановый', 'Тёмно-русый']],
    'size' => ['Размер', ['M', 'S']],
] as $slug => [$label, $values]) {
    $id = wc_attribute_taxonomy_id_by_name($slug);
    if (!$id) {
        $id = wc_create_attribute(['name' => $label, 'slug' => $slug]);
        if (is_wp_error($id)) {
            throw new RuntimeException($id->get_error_message());
        }
    }
    $taxonomy = wc_attribute_taxonomy_name($slug);
    if (!taxonomy_exists($taxonomy)) {
        register_taxonomy($taxonomy, ['product'], ['label' => $label]);
    }
    foreach (['TOPQA-NATURAL', 'TOPQA-SYNTHETIC'] as $index => $sku) {
        $product = wc_get_product(wc_get_product_id_by_sku($sku));
        if (!$product) {
            throw new RuntimeException('Missing test product: ' . $sku);
        }
        $term = term_exists($values[$index], $taxonomy) ?: wp_insert_term($values[$index], $taxonomy);
        if (is_wp_error($term)) {
            throw new RuntimeException($term->get_error_message());
        }
        $attribute = new WC_Product_Attribute();
        $attribute->set_id($id);
        $attribute->set_name($taxonomy);
        $attribute->set_options([(int) $term['term_id']]);
        $attribute->set_visible(true);
        $attributes = $product->get_attributes();
        $attribute->set_position(count($attributes));
        $attributes[$taxonomy] = $attribute;
        $product->set_attributes($attributes);
        $product->save();
    }
}
