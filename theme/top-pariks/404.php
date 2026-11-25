<?php get_header(); ?>
<div class="wrap page-content">
    <h1><?php esc_html_e('Страница не найдена', 'top-pariks'); ?></h1>
    <p><?php esc_html_e('Проверьте адрес или вернитесь в каталог.', 'top-pariks'); ?></p>
    <a class="btn" href="<?php echo esc_url(tp_catalog_url()); ?>"><?php esc_html_e('Перейти в каталог', 'top-pariks'); ?></a>
</div>
<?php get_footer(); ?>
