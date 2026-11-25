<?php
defined('ABSPATH') || exit;

if (!defined('WP_CLI') || 'local' !== wp_get_environment_type() || '0' !== get_option('blog_public')) {
    throw new RuntimeException('Use the STORE-005 synthetic test store.');
}

require_once ABSPATH . 'wp-admin/includes/file.php';
require_once WC_ABSPATH . 'includes/import/abstract-wc-product-importer.php';
require_once WC_ABSPATH . 'includes/import/class-wc-product-csv-importer.php';

$source = '/tmp/store-005-catalog-template.csv';
$template = file_get_contents($source);
$demo = wc_get_product(wc_get_product_id_by_sku('TOPQA-NATURAL'));
$image_id = $demo ? $demo->get_image_id() : 0;
$image_url = $image_id ? wp_get_attachment_url($image_id) : '';
if (!$template || !$image_url) {
    WP_CLI::error('CSV fixture or the isolated media attachment is missing.');
}

$columns = [
    'Type' => 'type',
    'SKU' => 'sku',
    'Name' => 'name',
    'Published' => 'published',
    'Short description' => 'short_description',
    'Description' => 'description',
    'Regular price' => 'regular_price',
    'In stock?' => 'stock_status',
    'Stock' => 'stock_quantity',
    'Categories' => 'category_ids',
    'Images' => 'images',
    'Parent' => 'parent_id',
    'Meta: atelier_seo_title' => 'meta:atelier_seo_title',
    'Meta: atelier_seo_description' => 'meta:atelier_seo_description',
];
for ($position = 1; $position <= 5; $position++) {
    foreach (['name' => 'name', 'value(s)' => 'value', 'visible' => 'visible', 'global' => 'taxonomy'] as $header => $schema) {
        $columns["Attribute $position $header"] = 'attributes:' . $schema . $position;
    }
}

$check = static function ($valid, $message) {
    if (!$valid) {
        throw new RuntimeException($message);
    }
};
$codes = ['STORE005-SIMPLE', 'STORE005-PARENT', 'STORE005-PARENT-CHESTNUT', 'STORE005-PARENT-BLOND'];
$ids_for = static function () use ($codes) {
    return array_map('wc_get_product_id_by_sku', $codes);
};
$check(!array_filter($ids_for()), 'Start the import test with unused synthetic SKUs.');

$file = wp_tempnam('atelier-store005.csv');
if (!$file) {
    WP_CLI::error('Cannot create isolated CSV workspace.');
}
try {
    $import = static function ($input, $update) use ($file, $columns, $image_url, $check) {
        $check(false !== file_put_contents($file, str_replace('atelier-demo-photo.webp', $image_url, $input)), 'Cannot write test CSV.');
        $importer = new WC_Product_CSV_Importer($file, [
            'mapping' => $columns,
            'parse' => true,
            'update_existing' => $update,
            'prevent_timeouts' => false,
            'character_encoding' => 'UTF-8',
        ]);
        $outcome = $importer->import();
        foreach (array_merge($outcome['failed'], $outcome['skipped']) as $error) {
            WP_CLI::warning($error->get_error_message());
        }
        $check(!$outcome['failed'] && !$outcome['skipped'], 'WooCommerce reported failed or skipped CSV rows.');
        return $outcome;
    };

    $import($template, false);
    $ids = $ids_for();
    $check(count(array_filter($ids)) === 4 && count(array_unique($ids)) === 4, 'Expected two products and two variants.');
    $simple = wc_get_product($ids[0]);
    $parent = wc_get_product($ids[1]);
    $variant = wc_get_product($ids[2]);
    $check($simple->is_type('simple') && $simple->get_status() === 'draft', 'Simple product was not imported as a draft.');
    $check($parent->is_type('variable') && count($parent->get_children()) === 2 && $variant->get_parent_id() === $ids[1], 'Variation links are invalid.');
    $check($simple->get_image_id() === $image_id, 'Existing media attachment was not reused.');
    $check(count($simple->get_attributes()) === 5, 'Expected five CSV attributes.');
    $check((float) $simple->get_regular_price() === 19.0 && (int) $simple->get_stock_quantity() === 8, 'Price or stock did not import.');
    $check('Тестовая модель для импорта' === get_post_meta($ids[0], 'atelier_seo_title', true), 'SEO metadata was not imported.');
    $category = get_term_by('name', 'Демонстрационные парики', 'product_cat');
    $child = get_term_by('name', 'Тестовый подраздел', 'product_cat');
    $check($category && $child && (int) $child->parent === (int) $category->term_id, 'Category hierarchy was not imported.');

    $changed = str_replace(',19.00,1,8,', ',21.00,1,6,', $template);
    $check($changed !== $template, 'Update fixture did not change price and stock.');
    $second = $import($changed, true);
    $check($ids_for() === $ids && !$second['imported'] && !$second['imported_variations'] && count($second['updated']) === 4, 'SKU update created a duplicate or skipped an existing record.');
    clean_post_cache($ids[0]);
    $simple = wc_get_product($ids[0]);
    $check((float) $simple->get_regular_price() === 21.0 && (int) $simple->get_stock_quantity() === 6, 'Repeat import did not update price and stock.');
    WP_CLI::success('Native WooCommerce CSV import: two products, two variations, five attributes, media, categories, SEO metadata and four SKU updates without duplicates.');
} finally {
    unlink($file);
}
