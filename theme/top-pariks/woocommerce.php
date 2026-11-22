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
    woocommerce_content();
    ?>
</div>
<?php get_footer(); ?>
