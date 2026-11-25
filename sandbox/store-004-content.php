<?php
defined('ABSPATH') || exit;

if (!get_option('top_pariks_store003_seeded') || ('local' !== wp_get_environment_type() && !defined('TOP_PARIKS_STORE003_SANDBOX'))) {
    throw new RuntimeException('STORE-004 content is for the isolated demonstration only.');
}

$outline = static function ($intro, $sections) {
    $content = '<p>' . esc_html($intro) . '</p>';
    foreach ($sections as $heading => $paragraph) {
        $content .= '<h2>' . esc_html($heading) . '</h2><p>' . esc_html($paragraph) . '</p>';
    }
    return $content;
};

$awaiting = 'Данные для этого раздела ожидают подтверждения владельца магазина.';
$pages = [
    'about' => ['О компании', $awaiting, ['О магазине' => 'Нужны утверждённое описание и сведения о продавце.', 'Ассортимент' => 'Нужны подтверждённые сведения о моделях и брендах.']],
    'contacts' => ['Контакты', $awaiting, ['Связь с магазином' => 'Нужны телефон, электронная почта и часы работы.', 'Адрес' => 'Нужен подтверждённый адрес, если покупатели могут посетить магазин.']],
    'delivery' => ['Доставка и оплата', $awaiting, ['Доставка' => 'Нужны регионы, способы, сроки и тарифы.', 'Оплата' => 'Нужен перечень доступных покупателям способов оплаты.']],
    'returns' => ['Возврат', $awaiting, ['Условия' => 'Нужны утверждённые условия и порядок обращения.', 'Куда обратиться' => 'Нужен подтверждённый контакт для вопросов о возврате.']],
    'wig-guide' => ['Как выбрать парик', 'Начните с задач, для которых вы выбираете парик.', ['Сравните модели' => 'Проверьте материал, оттенок, длину и конструкцию по карточке модели.', 'Проверьте размер' => 'Пользуйтесь таблицей производителя выбранной модели, если она опубликована.']],
    'wig-care' => ['Как ухаживать за париком', 'Порядок ухода зависит от материала и конструкции модели.', ['Перед уходом' => 'Сверьте инструкции изготовителя. Если инструкции нет, уточните уход у продавца.', 'Укладка и хранение' => 'Проверяйте ограничения для нагрева, очищения и хранения в инструкции к конкретной модели.']],
    'faq' => ['Часто задаваемые вопросы', 'Ответы о выборе модели и работе витрины.', ['Где посмотреть характеристики?' => 'Откройте карточку и проверьте раздел с характеристиками. Набор сведений зависит от модели.', 'Где узнать условия доставки и возврата?' => 'Для этих условий предусмотрены отдельные страницы. В демонстрации указано, какие сведения ещё требуются.']],
    'privacy-policy' => ['Политика конфиденциальности', $awaiting, ['Обработка данных' => 'Нужен утверждённый текст для рабочих форм, личного кабинета и заказов.', 'Контакт по вопросам данных' => 'Нужен подтверждённый способ связи с ответственным лицом.']],
];

foreach ($pages as $slug => [$title, $intro, $sections]) {
    $existing = get_page_by_path($slug);
    if ('privacy-policy' === $slug && get_option('wp_page_for_privacy_policy')) {
        $existing = get_post((int) get_option('wp_page_for_privacy_policy'));
    }
    if ($existing && 'publish' === $existing->post_status) {
        if (get_post_meta($existing->ID, '_top_pariks_store004_outline', true)) {
            continue;
        }
        // Replace only the known generated seed claim. Preserve custom content.
        $previous = $existing->post_content;
        if ('delivery' === $slug && 'Мы доставляем заказы по России. Доступные способы доставки и оплаты отображаются при оформлении заказа.' === $previous) {
            $previous = '';
        }
        $content = trim($previous . "\n\n" . $outline($intro, $sections));
        $id = wp_update_post(['ID' => $existing->ID, 'post_content' => $content], true);
    } elseif (!$existing) {
        $id = wp_insert_post(['post_type' => 'page', 'post_status' => 'publish', 'post_name' => $slug,
            'post_title' => $title, 'post_content' => $outline($intro, $sections)], true);
    } else {
        continue;
    }
    if (is_wp_error($id)) {
        throw new RuntimeException($id->get_error_message());
    }
    update_post_meta($id, '_top_pariks_store004_outline', true);
}

// Use separate display media for the demo. Keep the original attachments intact.
$crop_media = static function ($id) {
    $slug = 'atelier-demo-portrait-' . $id;
    $existing = get_page_by_path($slug, OBJECT, 'attachment');
    if ($existing) {
        return (int) $existing->ID;
    }

    require_once ABSPATH . 'wp-admin/includes/image.php';
    $uploads = wp_get_upload_dir();
    $filename = wp_unique_filename($uploads['path'], $slug . '.webp');
    $editor = wp_get_image_editor(get_attached_file($id));
    if (is_wp_error($editor) || $uploads['error']) {
        throw new RuntimeException('The demo needs WordPress WebP image support.');
    }
    $size = $editor->get_size();
    $top = (int) ceil($size['height'] * 0.15);
    $crop = $editor->crop(0, $top, $size['width'], $size['height'] - $top);
    if (is_wp_error($crop)) {
        throw new RuntimeException($crop->get_error_message());
    }
    $file = $editor->save($uploads['path'] . '/' . $filename, 'image/webp');
    if (is_wp_error($file)) {
        throw new RuntimeException($file->get_error_message());
    }
    $media_id = wp_insert_attachment([
        'post_name' => $slug,
        'post_title' => 'ТЕСТ — портрет для демонстрации',
        'post_mime_type' => $file['mime-type'],
        'post_status' => 'inherit',
    ], $file['path'], 0, true);
    if (is_wp_error($media_id)) {
        throw new RuntimeException($media_id->get_error_message());
    }
    wp_update_attachment_metadata($media_id, wp_generate_attachment_metadata($media_id, $file['path']));
    update_post_meta($media_id, '_wp_attachment_image_alt', 'Демонстрационная фотография парика');
    return $media_id;
};

if (!get_option('top_pariks_store004_demo_media')) {
    foreach (['TOPQA-NATURAL', 'TOPQA-CHOICE'] as $sku) {
        $product = wc_get_product(wc_get_product_id_by_sku($sku));
        $product->set_image_id($crop_media($product->get_image_id()));
        $product->set_gallery_image_ids(array_map($crop_media, $product->get_gallery_image_ids()));
        $product->save();
    }
    update_option('top_pariks_store004_demo_media', '1');
}
