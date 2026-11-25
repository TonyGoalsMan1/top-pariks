<?php
get_header();

$catalog_url = tp_catalog_url();
$contacts_url = tp_published_page_url('contacts');
$delivery_url = tp_published_page_url('delivery');
$categories = [
    'natural-wigs'   => ['category-natural', 'Натуральные парики'],
    'synthetic-wigs' => ['category-synthetic', 'Искусственные парики'],
    'short-wigs'     => ['category-short', 'Короткие парики'],
    'long-wigs'      => ['category-long', 'Длинные парики'],
];
$category_links = [];
foreach ($categories as $slug => [$image, $label]) {
    $url = get_term_link($slug, 'product_cat');
    if (!is_wp_error($url)) {
        $category_links[] = [$url, $image, $label];
    }
}
?>
<div class="atelier-home">
    <section class="hero wrap" aria-labelledby="atelier-title">
        <div class="hero-inner">
            <div class="hero-copy">
                <p class="atelier-label">TOP-PARIKS Atelier</p>
                <h1 id="atelier-title">Парики для вашего образа</h1>
                <p>Натуральные и искусственные модели. Выберите длину, оттенок и укладку, которые вам подходят.</p>
                <div class="atelier-actions">
                    <a class="btn" href="<?php echo esc_url($catalog_url); ?>">Перейти в каталог</a>
                    <?php if ($category_links) : ?>
                        <a class="atelier-link" href="#atelier-categories">Выбрать категорию</a>
                    <?php endif; ?>
                </div>
            </div>
            <div class="hero-media">
                <img class="hero-image" src="<?php echo tp_image('hero'); ?>" alt="Модель с объёмными волнистыми волосами" width="395" height="368" fetchpriority="high">
            </div>
        </div>
    </section>

    <?php if ($category_links) : ?>
        <section class="section wrap" id="atelier-categories" aria-labelledby="atelier-category-title">
            <div class="section-head">
                <h2 id="atelier-category-title">Популярные категории</h2>
                <a href="<?php echo esc_url($catalog_url); ?>">Весь каталог</a>
            </div>
            <div class="categories">
                <?php foreach ($category_links as [$url, $image, $label]) : ?>
                    <a class="category" href="<?php echo esc_url($url); ?>">
                        <div class="atelier-category-image">
                            <img loading="lazy" src="<?php echo tp_image($image); ?>" alt="">
                        </div>
                        <span><?php echo esc_html($label); ?></span>
                    </a>
                <?php endforeach; ?>
            </div>
        </section>
    <?php endif; ?>

    <?php
    $items = tp_homepage_products(true);
    $recommended = !empty($items);
    if (!$recommended) {
        $items = tp_homepage_products();
    }
    ?>
    <section class="section wrap" aria-labelledby="atelier-products-title">
        <div class="section-head">
            <h2 id="atelier-products-title"><?php echo $recommended ? 'Рекомендуемые модели' : 'Модели из каталога'; ?></h2>
            <a href="<?php echo esc_url($catalog_url); ?>">Все модели</a>
        </div>
        <?php if ($items) : ?>
            <div class="products">
                <?php foreach ($items as $product) :
                    $url = $product->get_permalink();
                    ?>
                    <article class="product">
                        <a class="product-img" href="<?php echo esc_url($url); ?>" aria-label="<?php echo esc_attr($product->get_name()); ?>">
                            <?php echo $product->get_image('woocommerce_thumbnail', ['loading' => 'lazy']); ?>
                        </a>
                        <div class="product-body">
                            <h3><a href="<?php echo esc_url($url); ?>"><?php echo esc_html($product->get_name()); ?></a></h3>
                            <div class="price"><?php echo wp_kses_post($product->get_price_html()); ?></div>
                            <a class="btn" href="<?php echo esc_url($url); ?>">Подробнее</a>
                        </div>
                    </article>
                <?php endforeach; ?>
            </div>
        <?php else : ?>
            <p class="notice">В каталоге пока нет товаров.</p>
        <?php endif; ?>
    </section>

    <section class="section wrap" aria-labelledby="atelier-benefits-title">
        <div class="section-head"><h2 id="atelier-benefits-title">Как выбрать парик</h2></div>
        <ul class="atelier-benefits">
            <li><h3>По материалу</h3><p>Сравните модели из натуральных и искусственных волос.</p></li>
            <li><h3>По длине</h3><p>Начните с коротких или длинных моделей в каталоге.</p></li>
            <li><h3>По характеристикам</h3><p>Откройте карточку модели, чтобы увидеть фото, цену и наличие.</p></li>
        </ul>
    </section>

    <?php if ($contacts_url || $delivery_url) : ?>
        <section class="section wrap" aria-labelledby="atelier-help-title">
            <div class="atelier-help">
                <h2 id="atelier-help-title"><?php echo $contacts_url ? 'Контакты и помощь' : 'Доставка и оплата'; ?></h2>
                <div class="atelier-actions">
                    <?php if ($contacts_url) : ?>
                        <a class="btn" href="<?php echo esc_url($contacts_url); ?>">Контакты магазина</a>
                    <?php endif; ?>
                    <?php if ($delivery_url) : ?>
                        <a class="atelier-link" href="<?php echo esc_url($delivery_url); ?>">Условия доставки и оплаты</a>
                    <?php endif; ?>
                </div>
            </div>
        </section>
    <?php endif; ?>
</div>
<?php if (is_page() && have_posts() && trim(get_post_field('post_content', get_queried_object_id()))) : ?>
    <section class="wrap page-content">
        <?php the_post(); the_content(); ?>
    </section>
<?php endif; ?>
<?php get_footer(); ?>
