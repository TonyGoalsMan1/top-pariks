<?php
defined('ABSPATH') || exit;

if (wp_get_environment_type() !== 'local' || ! get_option('top_pariks_test_seeded')) {
    WP_CLI::error('Run the demo import only in the seeded local sandbox.');
}

require_once WC_ABSPATH . 'includes/import/class-wc-product-csv-importer.php';
$path = '/opt/top-pariks/demo-products.csv';
$columns = [
    'Type' => 'type',
    'SKU' => 'sku',
    'Name' => 'name',
    'Published' => 'published',
    'Visibility in catalog' => 'catalog_visibility',
    'Short description' => 'short_description',
    'In stock?' => 'stock_status',
    'Regular price' => 'regular_price',
    'Categories' => 'category_ids',
];
$file = fopen($path, 'r');
$headers = fgetcsv($file);
fclose($file);
if ($headers !== array_keys($columns)) {
    WP_CLI::error('Unexpected demo CSV columns.');
}

$expected = ['STAGE001-DEMO-ATELIER' => '19.00', 'STAGE001-DEMO-STUDIO' => '11.00'];
foreach ($expected as $sku => $price) {
    if (wc_get_product_id_by_sku($sku)) {
        WP_CLI::error('Use a fresh sandbox for the demo import smoke check.');
    }
}

$importer = new WC_Product_CSV_Importer($path, [
    'mapping' => $columns,
    'parse' => true,
]);
$result = $importer->import();
foreach ($result['failed'] as $failure) {
    WP_CLI::warning($failure->get_error_message());
}
if (count($result['imported']) !== count($expected) || ! empty($result['failed'])) {
    WP_CLI::error('Demo CSV did not import exactly two products.');
}

foreach ($expected as $sku => $price) {
    $product = wc_get_product(wc_get_product_id_by_sku($sku));
    if (! $product || $product->get_status() !== 'draft' || ! $product->is_virtual()
        || ! $product->is_in_stock() || count($product->get_category_ids()) !== 1
        || strpos($product->get_name(), '[ДЕМО] ') !== 0
        || wc_format_decimal($product->get_regular_price(), 2) !== $price) {
        WP_CLI::error("Incorrect imported demo product: $sku");
    }
}

WP_CLI::success('Imported two marked virtual demo products as drafts.');
