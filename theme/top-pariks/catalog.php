<?php
defined('ABSPATH') || exit;

function tp_catalog_filters() {
    $fields = [];
    foreach (wc_get_attribute_taxonomies() as $attribute) {
        $taxonomy = wc_attribute_taxonomy_name($attribute->attribute_name);
        if (!taxonomy_exists($taxonomy)) {
            continue;
        }
        $terms = get_terms(['taxonomy' => $taxonomy, 'hide_empty' => true]);
        if (!is_wp_error($terms) && $terms) {
            $fields['filter_' . wc_attribute_taxonomy_slug($taxonomy)] = [wc_attribute_label($taxonomy), $terms];
        }
    }
    if (!$fields) {
        return;
    }

    $url = is_product_taxonomy() ? get_term_link(get_queried_object()) : tp_catalog_url();
    if (is_wp_error($url)) {
        return;
    }

    $chosen = WC_Query::get_layered_nav_chosen_attributes();
    $excluded = ['paged', 'product-page', 's', 'post_type'];
    foreach ($fields as $name => $field) {
        $excluded[] = $name;
        $excluded[] = 'query_type_' . substr($name, 7);
    }
    // Keep route arguments when plain permalinks are enabled.
    $route = [];
    parse_str((string) wp_parse_url($url, PHP_URL_QUERY), $route);
    $excluded = array_merge($excluded, array_keys($route));
    if (is_search()) {
        $route['s'] = get_search_query(false);
        $route['post_type'] = 'product';
    }
    ?>
    <form class="atelier-filters" method="get" action="<?php echo esc_url(strtok($url, '?')); ?>" aria-label="Фильтры товаров">
        <?php foreach ($fields as $name => [$label, $terms]) :
            $taxonomy = wc_attribute_taxonomy_name(substr($name, 7));
            $active = $chosen[$taxonomy]['terms'] ?? [];
            ?>
            <label>
                <span><?php echo esc_html($label); ?></span>
                <select name="<?php echo esc_attr($name); ?>">
                    <option value="">Все варианты</option>
                    <?php if (count($active) > 1) : ?>
                        <option value="<?php echo esc_attr(implode(',', $active)); ?>" selected>Выбрано: <?php echo count($active); ?></option>
                    <?php endif; ?>
                    <?php foreach ($terms as $term) : ?>
                        <option value="<?php echo esc_attr($term->slug); ?>"<?php selected($active === [$term->slug]); ?>><?php echo esc_html($term->name); ?></option>
                    <?php endforeach; ?>
                </select>
            </label>
        <?php endforeach; ?>
        <?php foreach ($route as $name => $value) : ?>
            <input type="hidden" name="<?php echo esc_attr($name); ?>" value="<?php echo esc_attr($value); ?>">
        <?php endforeach; ?>
        <?php wc_query_string_form_fields(null, $excluded); ?>
        <button class="btn" type="submit">Применить</button>
        <?php if (tp_has_catalog_parameters()) : ?>
            <a class="atelier-link" href="<?php echo esc_url(add_query_arg($route, strtok($url, '?'))); ?>">Сбросить</a>
        <?php endif; ?>
    </form>
    <?php
}

function tp_product_details_preview($product) {
    $values = [];
    foreach ($product->get_attributes() as $attribute) {
        if ($attribute->get_visible()) {
            $value = $product->get_attribute($attribute->get_name());
            if ('' !== trim($value)) {
                $values[] = [wc_attribute_label($attribute->get_name(), $product), $value];
            }
        }
        if (count($values) === 2) {
            break;
        }
    }
    if (!$values) {
        return;
    }
    echo '<dl class="atelier-card-specs">';
    foreach ($values as [$label, $value]) {
        printf('<div><dt>%s</dt><dd>%s</dd></div>', esc_html($label), esc_html($value));
    }
    echo '</dl>';
}

function tp_loop_product_details_preview() {
    global $product;
    if ($product instanceof WC_Product) {
        tp_product_details_preview($product);
    }
}
add_action('woocommerce_after_shop_loop_item_title', 'tp_loop_product_details_preview', 12);
