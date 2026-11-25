</main>
<?php if (is_front_page()) : ?>
    <footer class="footer footer-atelier">
        <div class="wrap footer-inner">
            <div>
                <p class="footer-brand">TOP-PARIKS Atelier</p>
                <p>© <?php echo esc_html(wp_date('Y')); ?> TOP-PARIKS</p>
            </div>
            <nav aria-label="Навигация в подвале">
                <?php tp_fallback_menu(); ?>
                <?php if ($returns_url = tp_published_page_url('returns')) : ?>
                    <a href="<?php echo esc_url($returns_url); ?>"><?php esc_html_e('Возврат', 'top-pariks'); ?></a>
                <?php endif; ?>
                <?php if ($privacy_url = get_privacy_policy_url()) : ?>
                    <a href="<?php echo esc_url($privacy_url); ?>">Политика конфиденциальности</a>
                <?php endif; ?>
            </nav>
        </div>
    </footer>
<?php else : ?>
    <footer class="footer"><div class="wrap footer-inner"><p>🚚 Доставка по всей России</p><p>♢ Гарантия качества</p><p>☎ Поддержка и консультация</p><p>© <?php echo esc_html(date('Y')); ?> TOP-PARIKS<?php if ($privacy_url = get_privacy_policy_url()) : ?> · <a href="<?php echo esc_url($privacy_url); ?>">Политика конфиденциальности</a><?php endif; ?></p></div></footer>
<?php endif; ?>
<?php wp_footer(); ?>
</body>
</html>
