<?php
defined('ABSPATH') || exit;

function tp_homepage_defaults() {
    return [
        'tp_hero_heading' => __('Парики для вашего образа', 'top-pariks'),
        'tp_hero_description' => __('Натуральные и синтетические модели. Выберите длину, оттенок и укладку, которые вам подходят.', 'top-pariks'),
        'tp_hero_button' => __('Перейти в каталог', 'top-pariks'),
        'tp_category_heading' => __('Основные категории', 'top-pariks'),
        'tp_featured_heading' => __('Рекомендуемые модели', 'top-pariks'),
        'tp_products_heading' => __('Модели из каталога', 'top-pariks'),
    ];
}

function tp_homepage_text($setting) {
    $defaults = tp_homepage_defaults();
    $value = (string) get_theme_mod($setting, $defaults[$setting]);
    return trim($value) === '' && $setting !== 'tp_hero_description' ? $defaults[$setting] : $value;
}

function tp_sanitize_contact_phone($value) {
    return trim(preg_replace('/[^0-9+(). -]/', '', (string) $value));
}

function tp_homepage_customize($customizer) {
    $customizer->add_section('tp_homepage', [
        'title' => __('Главная страница и контакты', 'top-pariks'),
        'priority' => 35,
    ]);
    $defaults = tp_homepage_defaults();
    $fields = [
        'tp_hero_heading' => [__('Заголовок баннера', 'top-pariks'), 'text', 'sanitize_text_field'],
        'tp_hero_description' => [__('Текст баннера', 'top-pariks'), 'textarea', 'sanitize_textarea_field'],
        'tp_hero_button' => [__('Подпись кнопки каталога', 'top-pariks'), 'text', 'sanitize_text_field'],
        'tp_category_heading' => [__('Заголовок блока категорий', 'top-pariks'), 'text', 'sanitize_text_field'],
        'tp_featured_heading' => [__('Заголовок блока рекомендуемых товаров', 'top-pariks'), 'text', 'sanitize_text_field'],
        'tp_products_heading' => [__('Заголовок блока товаров из каталога', 'top-pariks'), 'text', 'sanitize_text_field'],
        'tp_contact_phone' => [__('Публичный телефон', 'top-pariks'), 'tel', 'tp_sanitize_contact_phone'],
        'tp_contact_email' => [__('Публичная почта', 'top-pariks'), 'email', 'sanitize_email'],
    ];
    foreach ($fields as $key => [$label, $type, $sanitize]) {
        $customizer->add_setting($key, ['default' => $defaults[$key] ?? '', 'sanitize_callback' => $sanitize]);
        $customizer->add_control($key, ['section' => 'tp_homepage', 'label' => $label, 'type' => $type]);
    }
    $customizer->add_setting('tp_hero_image', ['default' => 0, 'sanitize_callback' => 'absint']);
    $customizer->add_control(new WP_Customize_Media_Control($customizer, 'tp_hero_image', [
        'section' => 'tp_homepage',
        'label' => __('Изображение баннера', 'top-pariks'),
        'description' => __('Используйте своё фото и заполните альтернативный текст в медиатеке.', 'top-pariks'),
        'mime_type' => 'image',
    ]));
}
add_action('customize_register', 'tp_homepage_customize');

function tp_footer_contacts() {
    $phone = tp_sanitize_contact_phone(get_theme_mod('tp_contact_phone', ''));
    $email = sanitize_email(get_theme_mod('tp_contact_email', ''));
    if (preg_match('/[0-9]/', $phone)) {
        $dial = (str_starts_with($phone, '+') ? '+' : '') . preg_replace('/[^0-9]/', '', $phone);
        printf('<p><a href="%s">%s</a></p>', esc_url('tel:' . $dial), esc_html($phone));
    }
    if ($email !== '') {
        printf('<p><a href="%s">%s</a></p>', esc_url('mailto:' . $email), esc_html($email));
    }
}