<?php defined('ABSPATH') || exit; ?>
<!doctype html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo('charset'); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<a class="skip-link" href="#content">К содержанию</a>
<header class="site-header">
    <div class="topbar">
        <div class="wrap">
            <span>Доставка по всей России</span>
            <a href="<?php echo esc_url(function_exists('wc_get_page_permalink') ? wc_get_page_permalink('myaccount') : wp_login_url()); ?>">Войти</a>
        </div>
    </div>
    <div class="mast">
        <div class="wrap mast-inner">
            <a class="brand" href="<?php echo esc_url(home_url('/')); ?>">
                TOP-PARIKS<small>Интернет-магазин париков</small>
            </a>
            <form class="product-search" action="<?php echo esc_url(home_url('/')); ?>" method="get" role="search">
                <label class="screen-reader-text" for="tp-search">Поиск товаров</label>
                <input id="tp-search" name="s" type="search" value="<?php echo esc_attr(is_search() ? get_search_query(false) : ''); ?>" placeholder="Поиск по каталогу">
                <input type="hidden" name="post_type" value="product">
                <button type="submit">Найти</button>
            </form>
            <div class="header-actions">
                <?php if ($wishlist_url = tp_published_page_url('wishlist')) : ?>
                    <a class="wishlist" href="<?php echo esc_url($wishlist_url); ?>" aria-label="Избранное"><span aria-hidden="true">♡</span></a>
                <?php endif; ?>
                <a class="cart-link" href="<?php echo esc_url(tp_cart_url()); ?>">Корзина<?php if (class_exists('WooCommerce') && WC()->cart) : ?>
                    <span class="cart-count"><?php echo (int) WC()->cart->get_cart_contents_count(); ?></span>
                <?php endif; ?></a>
                <button class="menu-toggle" type="button" aria-controls="tp-navigation" aria-expanded="false" hidden>Меню</button>
            </div>
        </div>
    </div>
    <nav class="nav" id="tp-navigation" aria-label="Основная навигация">
        <div class="wrap">
            <?php
            if (has_nav_menu('primary')) {
                wp_nav_menu(['theme_location' => 'primary', 'container' => false, 'depth' => 1]);
            } else {
                tp_fallback_menu();
            }
            ?>
        </div>
    </nav>
</header>
<main class="site-main" id="content" tabindex="-1">
