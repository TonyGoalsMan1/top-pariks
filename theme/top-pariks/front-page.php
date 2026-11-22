<?php get_header(); ?>
<section class="hero wrap">
    <div class="hero-inner">
        <div class="hero-copy">
            <h1>Парики для вашего образа</h1>
            <p>Натуральные и искусственные модели на каждый день и для особых случаев.</p>
            <a class="btn" href="<?php echo esc_url(tp_catalog_url()); ?>">Перейти в каталог <span aria-hidden="true">→</span></a>
        </div>
        <div class="hero-media">
            <img class="hero-image" src="<?php echo tp_image('hero'); ?>" alt="Модель с объёмными волнистыми волосами" width="395" height="368" fetchpriority="high">
        </div>
    </div>
</section>
<section class="section wrap"><div class="section-head"><h2>Категории</h2><a href="<?php echo esc_url(tp_catalog_url()); ?>">Весь каталог →</a></div><div class="categories">
<?php $cats=[['category-natural','Парики из натуральных волос','natural-wigs'],['category-synthetic','Парики из искусственных волос','synthetic-wigs'],['category-short','Короткие парики','short-wigs'],['category-long','Длинные парики','long-wigs']];foreach($cats as $c):$term=get_term_by('slug',$c[2],'product_cat');$link=$term?get_term_link($term):tp_catalog_url();if(is_wp_error($link))$link=tp_catalog_url(); ?><a class="category" href="<?php echo esc_url($link); ?>"><img loading="lazy" src="<?php echo tp_image($c[0]); ?>" alt=""><span><?php echo esc_html($c[1]); ?> →</span></a><?php endforeach; ?></div></section>
<?php $items = tp_products(); ?>
<section class="section wrap"><div class="section-head"><h2>Модели из каталога</h2><a href="<?php echo esc_url(tp_catalog_url()); ?>">Смотреть все товары →</a></div>
<?php if ($items) : ?>
<div class="products">
<?php foreach($items as $p):$url=get_permalink($p->get_id()); ?><article class="product"><a class="product-img" href="<?php echo esc_url($url); ?>" aria-label="<?php echo esc_attr($p->get_name()); ?>"><?php echo $p->get_image('woocommerce_thumbnail',['loading'=>'lazy']); ?></a><div class="product-body"><h3><a href="<?php echo esc_url($url); ?>"><?php echo esc_html($p->get_name()); ?></a></h3><div class="price"><?php echo wp_kses_post($p->get_price_html()); ?></div><a class="btn" href="<?php echo esc_url($url); ?>">Подробнее →</a></div></article><?php endforeach; ?>
</div>
<?php else : ?>
    <p class="notice">В каталоге пока нет товаров.</p>
<?php endif; ?>
</section>
<section class="wrap"><div class="promo"><div class="promo-copy"><h2>Красота и уверенность<br>в каждом образе</h2><p>Найдите модель, которая подходит именно вам.</p><a class="btn" href="<?php echo esc_url(tp_catalog_url()); ?>">Выбрать парик →</a></div><img loading="lazy" src="<?php echo tp_image('promo'); ?>" alt="Модель с длинными светлыми волосами"></div></section>
<section class="wrap seo-copy"><h2>Парики и накладные волосы TOP-PARIKS</h2><p>В нашем каталоге вы сможете подобрать парики из натуральных и искусственных волос, короткие и длинные модели, шиньоны и накладные волосы. Выбирайте подходящий оттенок, длину и стиль. Перед покупкой уточняйте наличие и характеристики товара.</p></section>
<?php get_footer(); ?>
