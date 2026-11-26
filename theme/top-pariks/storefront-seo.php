<?php
defined('ABSPATH') || exit;

function tp_product_seo_title($parts) {
    if (is_singular('product') && !post_password_required()) {
        $title = trim(wp_strip_all_tags((string) get_post_meta(get_queried_object_id(), 'atelier_seo_title', true), true));
        if ($title !== '') {
            $parts['title'] = $title;
        }
    }
    return $parts;
}
add_filter('document_title_parts', 'tp_product_seo_title');

function tp_catalog_canonical_url() {
    if (!function_exists('is_shop') || is_search() || !(is_shop() || is_product_taxonomy())) {
        return '';
    }

    $remove = [];
    foreach (array_keys($_GET) as $key) {
        if (preg_match('/^(?:utm_.+|gclid|fbclid|atelier_filters|add-to-cart)$/D', (string) $key)) {
            $remove[] = $key;
        }
    }
    return remove_query_arg($remove, get_pagenum_link(max(1, (int) get_query_var('paged')), false));
}

function tp_open_graph() {
    if (is_404() || is_search() || tp_is_service_page() || is_preview()
        || (is_singular() && post_password_required())
        || (tp_catalog_canonical_url() && tp_has_catalog_parameters())
        || !apply_filters('tp_emit_open_graph', true)) {
        return;
    }

    $url = is_singular() ? wp_get_canonical_url() : tp_catalog_canonical_url();
    if (!$url && is_front_page() && !is_paged()) {
        $url = home_url('/');
    }
    if (!$url) {
        return;
    }

    $image_id = is_singular() ? get_post_thumbnail_id() : 0;
    if (is_front_page() && get_theme_mod('tp_hero_image')) {
        $image_id = (int) get_theme_mod('tp_hero_image');
    }
    if (!$image_id && function_exists('is_product_category') && is_product_category()) {
        $image_id = (int) get_term_meta(get_queried_object_id(), 'thumbnail_id', true);
    }
    $meta = [
        'og:title' => wp_get_document_title(),
        'og:type' => is_singular('product') ? 'product' : 'website',
        'og:url' => $url,
        'og:site_name' => get_bloginfo('name'),
        'og:locale' => get_locale(),
        'og:description' => tp_storefront_description(),
        'og:image' => $image_id ? wp_get_attachment_image_url($image_id, 'large') : (is_front_page() ? tp_image('hero') : ''),
        'og:image:alt' => $image_id ? get_post_meta($image_id, '_wp_attachment_image_alt', true) : '',
    ];
    foreach ($meta as $property => $value) {
        if (is_string($value) && $value !== '') {
            $content = in_array($property, ['og:url', 'og:image'], true) ? esc_url($value) : esc_attr($value);
            printf("<meta property=\"%s\" content=\"%s\" />\n", esc_attr($property), $content);
        }
    }
}
add_action('wp_head', 'tp_open_graph', 12);

function tp_demo_robots_header($headers) {
    if ('0' === get_option('blog_public')) {
        $headers['X-Robots-Tag'] = 'noindex, nofollow';
    }
    return $headers;
}
add_filter('wp_headers', 'tp_demo_robots_header');

function tp_sitemap_catalog_terms($args, $taxonomy) {
    if ('product_cat' === $taxonomy) {
        $args['hide_empty'] = true;
    }
    return $args;
}
add_filter('wp_sitemaps_taxonomies_query_args', 'tp_sitemap_catalog_terms', 10, 2);
