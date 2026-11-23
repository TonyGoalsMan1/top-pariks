<?php
defined('ABSPATH') || exit;

function tp_storefront_setup_available() {
    $staging_host = 'top-pariks-test.freehosting.dev';

    return wp_parse_url(home_url('/'), PHP_URL_HOST) === $staging_host
        && wp_parse_url(site_url('/'), PHP_URL_HOST) === $staging_host;
}

add_action('admin_menu', function () {
    if (tp_storefront_setup_available()) {
        add_management_page('Настройка витрины', 'Настройка витрины', 'manage_options', 'tp-storefront', 'tp_storefront_setup_screen');
    }
});

function tp_storefront_setup_screen() {
    if (!current_user_can('manage_options') || !tp_storefront_setup_available()) {
        wp_die('Настройка витрины доступна только администратору тестового сайта.', '', ['response' => 403]);
    }

    ?>
    <div class="wrap">
        <h1>Настройка витрины TOP-PARIKS</h1>
        <?php
        if (isset($_POST['tp_setup_storefront'])) {
            check_admin_referer('tp_setup_storefront');

            if (!add_option('tp_storefront_setup_running', '1', '', false)) {
                $result = new WP_Error('setup_running', 'Настройка уже выполняется.');
            } else {
                try {
                    $result = tp_provision_storefront();
                } finally {
                    delete_option('tp_storefront_setup_running');
                }
            }

            if (is_wp_error($result)) {
                printf('<div class="notice notice-error"><p>%s</p></div>', esc_html($result->get_error_message()));
            } else {
                echo '<div class="notice notice-success"><p>Страницы, меню и маршруты настроены.</p></div>';
            }
        }
        ?>
        <p>Будут настроены главная страница, страницы WooCommerce, основное меню и постоянные ссылки тестового магазина.</p>
        <form method="post">
            <?php wp_nonce_field('tp_setup_storefront'); ?>
            <?php submit_button('Настроить витрину', 'primary', 'tp_setup_storefront'); ?>
        </form>
    </div>
    <?php
}

function tp_provision_storefront() {
    if (!class_exists('WooCommerce')) {
        return new WP_Error('missing_woocommerce', 'Активируйте WooCommerce перед настройкой витрины.');
    }

    $pages = [
        'shop'      => ['shop', 'Каталог', '', 'woocommerce_shop_page_id'],
        'cart'      => ['cart', 'Корзина', '[woocommerce_cart]', 'woocommerce_cart_page_id', 'woocommerce/cart'],
        'checkout'  => ['checkout', 'Оформление заказа', '[woocommerce_checkout]', 'woocommerce_checkout_page_id', 'woocommerce/checkout'],
        'myaccount' => ['my-account', 'Личный кабинет', '[woocommerce_my_account]', 'woocommerce_myaccount_page_id'],
        'about'     => ['about', 'О компании', 'TOP-PARIKS — интернет-магазин натуральных и искусственных париков.'],
        'delivery'  => ['delivery', 'Доставка и оплата', 'Мы доставляем заказы по России. Доступные способы доставки и оплаты отображаются при оформлении заказа.'],
        'contacts'  => ['contacts', 'Контакты', 'Если у вас уже есть заказ, воспользуйтесь контактами из письма с его подтверждением.'],
        'home'      => ['home', 'Главная', '', 'page_on_front'],
    ];
    $slugs = array_column($pages, 0);
    $reserved = array_filter([(int) get_option('page_for_posts')]);
    $ids = [];

    // Resolve and validate existing pages before creating anything.
    foreach ($pages as $key => [$slug, $title, $content]) {
        $option = $pages[$key][3] ?? '';
        $mapped_id = $option ? (int) get_option($option) : 0;
        $mapped = $mapped_id > 0 ? get_post($mapped_id) : null;
        $page = get_page_by_path($slug, OBJECT, ['page']);
        if ($mapped && $mapped->post_type === 'page' && $mapped->post_status === 'publish'
            && (!$mapped->post_password)
            && !in_array($mapped->ID, $reserved, true)
            && ($mapped->post_name === $slug || !in_array($mapped->post_name, $slugs, true))
            && ($key === 'home' || (int) get_option('page_on_front') !== $mapped->ID || $mapped->post_name === $slug)
        ) {
            $page = $mapped;
        }

        if (!$page) {
            continue;
        }
        if ($page->post_status !== 'publish' || $page->post_password || in_array($page->ID, $reserved, true)) {
            return new WP_Error('page_conflict', sprintf('Проверьте страницу «%s» (ID %d). Нужна отдельная опубликованная страница без пароля.', $title, $page->ID));
        }
        $block = $pages[$key][4] ?? '';
        if ($option && $content && !has_shortcode($page->post_content, trim($content, '[]'))
            && (!$block || !has_block($block, $page))
        ) {
            return new WP_Error('page_content', sprintf('Добавьте на страницу «%s» (ID %d) блок WooCommerce или шорткод %s, сохранив её содержимое.', $title, $page->ID, $content));
        }
        $ids[$key] = $page->ID;
        $reserved[] = $page->ID;
    }

    foreach ($pages as $key => [$slug, $title, $content]) {
        if (!isset($ids[$key])) {
            $id = wp_insert_post([
                'post_type'    => 'page',
                'post_status'  => 'publish',
                'post_name'    => $slug,
                'post_title'   => $title,
                'post_content' => $content,
            ], true);

            if (is_wp_error($id)) {
                return $id;
            }
            $ids[$key] = $id;
        }
    }

    foreach ($ids as $key => $id) {
        if (isset($pages[$key][3])) {
            update_option($pages[$key][3], $id);
        }
    }
    update_option('show_on_front', 'page');
    if (!get_option('permalink_structure')) {
        global $wp_rewrite;
        $wp_rewrite->set_permalink_structure('/%postname%/');
    }
    flush_rewrite_rules(false);

    return tp_provision_storefront_menu($ids, $pages);
}

function tp_provision_storefront_menu($ids, $pages) {
    $locations = get_nav_menu_locations();
    $menu = wp_get_nav_menu_object($locations['primary'] ?? 0);
    if (!$menu) {
        $menu = wp_get_nav_menu_object('TOP-PARIKS');
    }
    $menu_id = $menu ? (int) $menu->term_id : wp_create_nav_menu('TOP-PARIKS');
    if (is_wp_error($menu_id)) {
        return $menu_id;
    }
    $items = wp_get_nav_menu_items($menu_id) ?: [];

    foreach (['home', 'shop', 'about', 'delivery', 'contacts'] as $key) {
        $page_id = $ids[$key];
        $title = $pages[$key][1];
        $url = $key === 'shop' ? wc_get_page_permalink('shop') : get_permalink($page_id);
        $stale_item = null;

        foreach ($items as $item) {
            if ($item->menu_item_parent) {
                continue;
            }
            if ($item->object === 'page' && (int) $item->object_id === $page_id) {
                continue 2;
            }
            if ($item->type !== 'custom') {
                continue;
            }
            if (untrailingslashit($item->url) === untrailingslashit($url)) {
                continue 2;
            }
            if ($item->title === $title || ($key === 'shop' && $item->title === 'Shop')) {
                $stale_item = $item;
            }
        }

        $result = wp_update_nav_menu_item($menu_id, $stale_item ? $stale_item->ID : 0, [
            'menu-item-type'        => 'post_type',
            'menu-item-object'      => 'page',
            'menu-item-object-id'   => $page_id,
            'menu-item-title'       => $title,
            'menu-item-status'      => 'publish',
            'menu-item-position'    => $stale_item->menu_order ?? 0,
            'menu-item-description' => $stale_item->description ?? '',
            'menu-item-attr-title'  => $stale_item->attr_title ?? '',
            'menu-item-target'     => $stale_item->target ?? '',
            'menu-item-classes'    => $stale_item ? implode(' ', $stale_item->classes) : '',
            'menu-item-xfn'        => $stale_item->xfn ?? '',
        ]);
        if (is_wp_error($result)) {
            return $result;
        }
    }

    $locations['primary'] = $menu_id;
    set_theme_mod('nav_menu_locations', $locations);

    return true;
}
