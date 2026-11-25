<?php
defined('ABSPATH') || exit;

$attribute_labels = [
    'material' => __('Материал', 'top-pariks'),
    'length'   => __('Длина', 'top-pariks'),
    'color'    => __('Цвет', 'top-pariks'),
];
$archive_url = is_product_taxonomy() ? get_term_link(get_queried_object()) : tp_catalog_url();
if (is_wp_error($archive_url)) {
    return;
}

$query_args = [];
parse_str((string) wp_parse_url($archive_url, PHP_URL_QUERY), $query_args);
$request_value = static function ($key) {
    return isset($_GET[$key]) && is_string($_GET[$key]) ? wp_unslash($_GET[$key]) : '';
};
$active = [];
foreach ($attribute_labels as $attribute => $label) {
    $key = 'filter_' . $attribute;
    foreach (explode(',', $request_value($key)) as $slug) {
        if ('' === $slug || !taxonomy_exists(wc_attribute_taxonomy_name($attribute))) {
            continue;
        }
        $term = get_term_by('slug', sanitize_title($slug), wc_attribute_taxonomy_name($attribute));
        if ($term) {
            $active[$key][] = [$label, $term->name, $term->slug];
        }
    }
}
foreach (['min_price' => __('Цена от', 'top-pariks'), 'max_price' => __('Цена до', 'top-pariks')] as $key => $label) {
    $value = $request_value($key);
    if (is_numeric($value) && (float) $value >= 0) {
        $active[$key][] = [$label, wp_strip_all_tags(html_entity_decode(wc_price($value), ENT_QUOTES, 'UTF-8')), $value];
    }
}
$active_query = array_map(static function ($values) {
    return implode(',', array_column($values, 2));
}, $active);
if ($orderby = sanitize_key($request_value('orderby'))) {
    $active_query['orderby'] = $orderby;
}
?>
<?php if ($active) : ?>
    <ul class="atelier-filter-chips" aria-label="<?php esc_attr_e('Выбранные фильтры', 'top-pariks'); ?>">
        <?php foreach ($active as $key => $values) : ?>
            <?php foreach ($values as [$label, $value, $slug]) :
                $remaining = array_diff(array_column($values, 2), [$slug]);
                $query = $active_query;
                unset($query[$key]);
                if ($remaining) {
                    $query[$key] = implode(',', $remaining);
                }
                $name = $label . ' · ' . $value;
                ?>
                <li><a href="<?php echo esc_url(add_query_arg($query, $archive_url)); ?>" aria-label="<?php echo esc_attr(sprintf(__('Удалить фильтр %s', 'top-pariks'), $name)); ?>"><?php echo esc_html($name); ?> <span aria-hidden="true">×</span></a></li>
            <?php endforeach; ?>
        <?php endforeach; ?>
        <li><a class="reset" href="<?php echo esc_url($archive_url); ?>"><?php esc_html_e('Сбросить все', 'top-pariks'); ?></a></li>
    </ul>
<?php endif; ?>
<button hidden class="btn atelier-filter-toggle" type="button" aria-controls="atelier-filter-form" aria-expanded="false"><?php esc_html_e('Фильтры', 'top-pariks'); ?><?php if ($active) { echo ' (' . esc_html(array_sum(array_map('count', $active))) . ')'; } ?></button>
<form id="atelier-filter-form" class="atelier-filters" method="get" action="<?php echo esc_url($archive_url); ?>" aria-label="<?php esc_attr_e('Фильтры каталога', 'top-pariks'); ?>">
    <input type="hidden" name="atelier_filters" value="1">
    <?php foreach ($query_args as $key => $value) : ?>
        <?php if (is_scalar($value)) : ?>
            <input type="hidden" name="<?php echo esc_attr($key); ?>" value="<?php echo esc_attr($value); ?>">
        <?php endif; ?>
    <?php endforeach; ?>
    <?php if ($orderby = sanitize_key($request_value('orderby'))) : ?>
        <input type="hidden" name="orderby" value="<?php echo esc_attr($orderby); ?>">
    <?php endif; ?>
    <?php foreach ($attribute_labels as $attribute => $label) :
        $taxonomy = wc_attribute_taxonomy_name($attribute);
        if (!taxonomy_exists($taxonomy)) {
            continue;
        }
        $terms = get_terms(['taxonomy' => $taxonomy, 'hide_empty' => true]);
        if (is_wp_error($terms) || !$terms) {
            continue;
        }
        $parameter = 'filter_' . $attribute;
        $current = sanitize_title($request_value($parameter));
        ?>
        <label>
            <?php echo esc_html($label); ?>
            <select name="<?php echo esc_attr($parameter); ?>">
                <option value=""><?php esc_html_e('Любое', 'top-pariks'); ?></option>
                <?php foreach ($terms as $term) : ?>
                    <option value="<?php echo esc_attr($term->slug); ?>" <?php selected($current, $term->slug); ?>><?php echo esc_html($term->name); ?></option>
                <?php endforeach; ?>
            </select>
        </label>
    <?php endforeach; ?>
    <?php foreach (['min_price' => __('Цена от', 'top-pariks'), 'max_price' => __('Цена до', 'top-pariks')] as $key => $label) :
        $current = $request_value($key);
        ?>
        <label>
            <?php echo esc_html($label); ?>
            <input type="number" min="0" step="any" inputmode="decimal" name="<?php echo esc_attr($key); ?>" value="<?php echo esc_attr(is_numeric($current) ? $current : ''); ?>">
        </label>
    <?php endforeach; ?>
    <div class="atelier-filter-actions">
        <button class="btn" type="submit"><?php esc_html_e('Применить', 'top-pariks'); ?></button>
        <a href="<?php echo esc_url($archive_url); ?>"><?php esc_html_e('Сбросить', 'top-pariks'); ?></a>
    </div>
</form>
