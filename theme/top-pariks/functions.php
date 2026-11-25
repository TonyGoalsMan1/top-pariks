<?php
if (!defined('ABSPATH')) exit;
function tp_setup(){add_theme_support('title-tag');add_theme_support('post-thumbnails');add_theme_support('custom-logo');add_theme_support('woocommerce');add_theme_support('wc-product-gallery-zoom');add_theme_support('wc-product-gallery-lightbox');add_theme_support('wc-product-gallery-slider');register_nav_menus(['primary'=>__('Основное меню','top-pariks')]);}
add_action('after_setup_theme','tp_setup');
function tp_assets(){wp_enqueue_style('tp-style',get_stylesheet_uri(),[],wp_get_theme()->get('Version'));wp_enqueue_script('tp-script',get_template_directory_uri().'/assets/site.js',[],wp_get_theme()->get('Version'),true);}
add_action('wp_enqueue_scripts','tp_assets');

function tp_cart_count_markup() {
    $count = function_exists('WC') && WC()->cart ? WC()->cart->get_cart_contents_count() : 0;
    return sprintf('<span class="cart-count">%d</span>', $count);
}

function tp_cart_count_fragment($fragments) {
    $fragments['.site-header .cart-count'] = tp_cart_count_markup();
    return $fragments;
}
add_filter('woocommerce_add_to_cart_fragments', 'tp_cart_count_fragment');

function tp_enqueue_cart_fragments() {
    if (function_exists('WC')) {
        wp_enqueue_script('wc-cart-fragments');
    }
}
add_action('wp_enqueue_scripts', 'tp_enqueue_cart_fragments', 20);

function tp_image($name){return esc_url(get_template_directory_uri().'/assets/images/'.$name.'.webp');}
function tp_catalog_url(){return class_exists('WooCommerce')?wc_get_page_permalink('shop'):home_url('/');}
function tp_cart_url(){return class_exists('WooCommerce')?wc_get_cart_url():home_url('/');}
function tp_products(){if(!class_exists('WooCommerce'))return [];return wc_get_products(['limit'=>4,'status'=>'publish','orderby'=>'date','order'=>'DESC']);}

function tp_homepage_products($featured = false) {
    if (!function_exists('wc_get_product_visibility_term_ids')) {
        return [];
    }

    $visibility = wc_get_product_visibility_term_ids();
    $excluded = [$visibility['exclude-from-catalog']];
    if ('yes' === get_option('woocommerce_hide_out_of_stock_items')) {
        $excluded[] = $visibility['outofstock'];
    }

    $tax_query = [[
        'taxonomy' => 'product_visibility',
        'field' => 'term_taxonomy_id',
        'terms' => $excluded,
        'operator' => 'NOT IN',
    ]];
    if ($featured) {
        $tax_query[] = [
            'taxonomy' => 'product_visibility',
            'field' => 'term_taxonomy_id',
            'terms' => [$visibility['featured']],
        ];
    }

    $query = new WP_Query([
        'post_type' => 'product',
        'post_status' => 'publish',
        'has_password' => false,
        'posts_per_page' => 4,
        'no_found_rows' => true,
        'fields' => 'ids',
        'tax_query' => $tax_query,
    ]);
    return array_values(array_filter(array_map('wc_get_product', $query->posts)));
}
function tp_published_page_url($slug) {
    $page = get_page_by_path($slug, OBJECT, ['page']);
    return $page && 'publish' === $page->post_status ? get_permalink($page) : '';
}

function tp_fallback_menu() {
    $links = [
        'Главная' => home_url('/'),
        'Каталог' => tp_catalog_url(),
        'О компании' => tp_published_page_url('about'),
        'Доставка и оплата' => tp_published_page_url('delivery'),
        'Контакты' => tp_published_page_url('contacts'),
    ];
    foreach ($links as $label => $url) {
        if ($url) {
            printf('<a href="%s">%s</a>', esc_url($url), esc_html($label));
        }
    }
}

function tp_storefront_description() {
    if (is_404() || is_search() || tp_is_service_page() || (is_singular() && post_password_required(get_queried_object()))) {
        return '';
    }

    $description = '';
    if (is_front_page() && !is_paged()) {
        $description = get_bloginfo('description');
        if ('' === trim($description) || in_array($description, ['Just another WordPress site', 'Ещё один сайт на WordPress'], true)) {
            $description = 'Натуральные и искусственные модели на каждый день и для особых случаев.';
        }
    } elseif (is_singular() || (function_exists('is_shop') && is_shop() && !is_paged() && !tp_has_catalog_parameters())) {
        $post = is_singular() ? get_queried_object() : get_post(wc_get_page_id('shop'));
        if ($post instanceof WP_Post && 'publish' === $post->post_status && '' === $post->post_password) {
            if ('product' === $post->post_type) {
                $description = (string) get_post_meta($post->ID, 'atelier_seo_description', true);
            }
            if ('' === trim($description)) {
                $description = $post->post_excerpt;
            }
            if ('' === trim($description)) {
                $description = wp_trim_words(strip_shortcodes(str_replace(['</p>', '</li>'], ' ', $post->post_content)), 30, '…');
            }
        }
    } elseif (function_exists('is_product_taxonomy') && is_product_taxonomy() && !is_paged() && !tp_has_catalog_parameters()) {
        $description = term_description();
    }

    $description = wp_strip_all_tags(strip_shortcodes($description), true);
    $description = trim(preg_replace('/\s+/u', ' ', $description) ?? $description);
    return $description;
}

function tp_meta_description() {
    $description = tp_storefront_description();
    if ('' !== $description && apply_filters('tp_emit_meta_description', true)) {
        printf("<meta name=\"description\" content=\"%s\" />\n", esc_attr($description));
    }
}
add_action('wp_head', 'tp_meta_description');

function tp_has_catalog_parameters() {
    foreach (array_keys($_GET) as $parameter) {
        if (preg_match('/^(?:orderby|min_price|max_price|rating_filter|stock_status|(?:filter|query_type)_.+)$/D', (string) $parameter)) {
            return true;
        }
    }
    return false;
}

function tp_archive_canonical() {
    if (is_404() || !apply_filters('tp_emit_archive_canonical', true)) {
        return;
    }
    if (is_front_page() && !is_singular() && !is_paged()) {
        $url = home_url('/');
    } else {
        $url = tp_catalog_canonical_url();
        if ($url === '') {
            return;
        }
    }

    printf("<link rel=\"canonical\" href=\"%s\" />\n", esc_url($url));
}
add_action('wp_head', 'tp_archive_canonical');

function tp_service_page_ids() {
    $ids = [];
    if (function_exists('wc_get_page_id')) {
        foreach (['cart', 'checkout', 'myaccount'] as $page) {
            $page_id = wc_get_page_id($page);
            if ($page_id > 0) {
                $ids[] = $page_id;
            }
        }
    }
    $wishlist = get_page_by_path('wishlist', OBJECT, ['page']);
    if ($wishlist) {
        $ids[] = $wishlist->ID;
    }
    return array_unique($ids);
}

function tp_is_service_page() {
    return (is_page() && in_array(get_queried_object_id(), tp_service_page_ids(), true))
        || (function_exists('is_checkout') && is_checkout())
        || (function_exists('is_cart') && is_cart())
        || (function_exists('is_account_page') && is_account_page());
}

function tp_storefront_robots($robots) {
    if (isset($robots['noindex'])) {
        return $robots;
    }

    $is_catalog = function_exists('is_shop') && (is_shop() || is_product_taxonomy());
    if (is_search() || ($is_catalog && tp_has_catalog_parameters()) || tp_is_service_page()) {
        $robots['noindex'] = true;
        if (!isset($robots['nofollow'])) {
            $robots['follow'] = true;
        }
    }

    return $robots;
}
add_filter('wp_robots', 'tp_storefront_robots');

function tp_sitemap_post_query_args($args, $post_type) {
    $args['has_password'] = false;
    if ('page' !== $post_type) {
        return $args;
    }

    $excluded = array_merge((array) ($args['post__not_in'] ?? []), tp_service_page_ids());
    if ($excluded) {
        $args['post__not_in'] = array_unique($excluded);
    }

    return $args;
}
add_filter('wp_sitemaps_posts_query_args', 'tp_sitemap_post_query_args', 10, 2);

require_once __DIR__ . '/storefront-setup.php';
require_once __DIR__ . '/storefront-seo.php';

function tp_normalize_catalog_filters() {
    if (!isset($_GET['atelier_filters'])) {
        return;
    }

    foreach (['filter_material', 'filter_length', 'filter_color', 'min_price', 'max_price'] as $key) {
        if (isset($_GET[$key]) && (!is_string($_GET[$key]) || '' === trim($_GET[$key]))) {
            unset($_GET[$key]);
        }
    }
}
add_action('parse_request', 'tp_normalize_catalog_filters', 1);

function tp_product_care_guide() {
    $url = tp_published_page_url('wig-care');
    if ($url) {
        printf('<p class="atelier-care-link"><a href="%s">%s</a></p>', esc_url($url), esc_html__('Как ухаживать за париком', 'top-pariks'));
    }
}
add_action('woocommerce_single_product_summary', 'tp_product_care_guide', 45);
