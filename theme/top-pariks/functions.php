<?php
if (!defined('ABSPATH')) exit;
function tp_setup(){add_theme_support('title-tag');add_theme_support('post-thumbnails');add_theme_support('custom-logo');add_theme_support('woocommerce');add_theme_support('wc-product-gallery-zoom');add_theme_support('wc-product-gallery-lightbox');add_theme_support('wc-product-gallery-slider');register_nav_menus(['primary'=>__('Основное меню','top-pariks')]);}
add_action('after_setup_theme','tp_setup');
function tp_assets(){wp_enqueue_style('tp-style',get_stylesheet_uri(),[],wp_get_theme()->get('Version'));wp_enqueue_script('tp-script',get_template_directory_uri().'/assets/site.js',[],wp_get_theme()->get('Version'),true);}
add_action('wp_enqueue_scripts','tp_assets');
function tp_image($name){return esc_url(get_template_directory_uri().'/assets/images/'.$name.'.webp');}
function tp_catalog_url(){return class_exists('WooCommerce')?wc_get_page_permalink('shop'):home_url('/?post_type=product');}
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

function tp_storefront_robots($robots) {
    if (isset($robots['noindex'])) {
        return $robots;
    }

    $is_catalog = function_exists('is_shop') && (is_shop() || is_product_taxonomy());
    $has_catalog_parameters = isset($_GET['orderby']) || isset($_GET['min_price']) || isset($_GET['max_price']);
    if (($is_catalog && $has_catalog_parameters) || is_page('wishlist')) {
        $robots['noindex'] = true;
        $robots['follow'] = true;
    }

    return $robots;
}
add_filter('wp_robots', 'tp_storefront_robots');

function tp_sitemap_page_query_args($args, $post_type) {
    if ('page' !== $post_type) {
        return $args;
    }

    $excluded = (array) ($args['post__not_in'] ?? []);
    if (function_exists('wc_get_page_id')) {
        foreach (['cart', 'checkout', 'myaccount'] as $page) {
            $page_id = wc_get_page_id($page);
            if ($page_id > 0) {
                $excluded[] = $page_id;
            }
        }
    }
    $wishlist = get_page_by_path('wishlist', OBJECT, ['page']);
    if ($wishlist) {
        $excluded[] = $wishlist->ID;
    }
    if ($excluded) {
        $args['post__not_in'] = array_unique($excluded);
    }

    return $args;
}
add_filter('wp_sitemaps_posts_query_args', 'tp_sitemap_page_query_args', 10, 2);
