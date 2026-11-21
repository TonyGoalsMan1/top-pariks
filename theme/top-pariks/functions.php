<?php
if (!defined('ABSPATH')) exit;
function tp_setup(){add_theme_support('title-tag');add_theme_support('post-thumbnails');add_theme_support('custom-logo');add_theme_support('woocommerce');add_theme_support('wc-product-gallery-zoom');add_theme_support('wc-product-gallery-lightbox');add_theme_support('wc-product-gallery-slider');register_nav_menus(['primary'=>__('Основное меню','top-pariks')]);}
add_action('after_setup_theme','tp_setup');
function tp_assets(){wp_enqueue_style('tp-style',get_stylesheet_uri(),[],wp_get_theme()->get('Version'));wp_enqueue_script('tp-script',get_template_directory_uri().'/assets/site.js',[],wp_get_theme()->get('Version'),true);}
add_action('wp_enqueue_scripts','tp_assets');
function tp_image($name){return esc_url(get_template_directory_uri().'/assets/images/'.$name.'.webp');}
function tp_catalog_url(){return class_exists('WooCommerce')?wc_get_page_permalink('shop'):home_url('/');}
function tp_cart_url(){return class_exists('WooCommerce')?wc_get_cart_url():home_url('/');}
function tp_products(){if(!class_exists('WooCommerce'))return [];return wc_get_products(['limit'=>4,'status'=>'publish','orderby'=>'date','order'=>'DESC']);}
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

function tp_meta_description() {
    if (is_404() || is_search() || tp_is_service_page() || (is_singular() && post_password_required(get_queried_object()))) {
        return;
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
            $description = $post->post_excerpt;
            if ('' === trim($description)) {
                $description = wp_trim_words(strip_shortcodes(str_replace(['</p>', '</li>'], ' ', $post->post_content)), 30, '…');
            }
        }
    } elseif (function_exists('is_product_taxonomy') && is_product_taxonomy() && !is_paged() && !tp_has_catalog_parameters()) {
        $description = term_description();
    }

    $description = wp_strip_all_tags(strip_shortcodes($description), true);
    $description = trim(preg_replace('/\s+/u', ' ', $description) ?? $description);
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
    } elseif (function_exists('is_shop') && !is_search() && (is_shop() || is_product_taxonomy())) {
        $url = get_pagenum_link(max(1, (int) get_query_var('paged')), false);
        $tracking = array_intersect_key($_GET, array_flip(['utm_source', 'utm_medium', 'utm_campaign', 'utm_id', 'utm_term', 'utm_content', 'gclid', 'fbclid']));
        $url = remove_query_arg(array_keys($tracking), $url);
    } else {
        return;
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
