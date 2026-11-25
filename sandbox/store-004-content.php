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
        // Keep the original demonstration text and append the editable outline.
        $content = $existing->post_content . "\n\n" . $outline($intro, $sections);
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
