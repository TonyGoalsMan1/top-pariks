<?php get_header(); ?>
<div class="wrap page-content">
    <?php
    if (is_shop() || is_product_category() || is_product_tag() || is_search()) :
        $categories = get_terms(['taxonomy' => 'product_cat', 'parent' => 0, 'hide_empty' => true]);
        if (!is_wp_error($categories) && $categories) :
            ?>
            <nav class="catalog-nav" aria-label="Категории товаров">
                <ul>
                    <li><a href="<?php echo esc_url(tp_catalog_url()); ?>"<?php if (is_shop() && !is_search()) echo ' aria-current="page"'; ?>>Весь каталог</a></li>
                    <?php foreach ($categories as $category) :
                        $url = get_term_link($category);
                        if (is_wp_error($url)) {
                            continue;
                        }
                        ?>
                        <li><a href="<?php echo esc_url($url); ?>"<?php if (is_product_category($category->term_id)) echo ' aria-current="page"'; ?>><?php echo esc_html($category->name); ?></a></li>
                    <?php endforeach; ?>
                </ul>
            </nav>
            <?php
        endif;
    endif;
    if (!is_search() && (is_shop() || is_product_taxonomy())) {
        get_template_part('catalog-filters');
    }
    $custom_empty_state = is_shop() && !is_search() && !is_paged() && !tp_has_catalog_parameters();
    $render_empty_state = static function () {
        echo '<p class="notice">В каталоге пока нет товаров. Загляните позже, чтобы посмотреть новые модели TOP-PARIKS.</p>';
    };
    if ($custom_empty_state) {
        remove_action('woocommerce_no_products_found', 'wc_no_products_found');
        add_action('woocommerce_no_products_found', $render_empty_state);
    }
    woocommerce_content();
    if ($custom_empty_state) {
        remove_action('woocommerce_no_products_found', $render_empty_state);
        add_action('woocommerce_no_products_found', 'wc_no_products_found');
    }
    ?>
</div>
<?php get_footer(); ?>
