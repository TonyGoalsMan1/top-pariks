<?php
defined('ABSPATH') || exit;

// Keep checkout email and payment integrations inside the test environment.
add_filter('pre_wp_mail', '__return_true');
add_filter('woocommerce_available_payment_gateways', static function ($gateways) {
    return array_intersect_key($gateways, ['cod' => true]);
});
