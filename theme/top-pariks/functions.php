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
function tp_fallback_menu(){echo '<a href="'.esc_url(home_url('/')).'">Главная</a><a href="'.esc_url(tp_catalog_url()).'">Каталог</a><a href="'.esc_url(home_url('/about/')).'">О компании</a><a href="'.esc_url(home_url('/delivery/')).'">Доставка и оплата</a><a href="'.esc_url(home_url('/contacts/')).'">Контакты</a>';}
