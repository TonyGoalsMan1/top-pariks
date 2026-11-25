</main>
    <footer class="footer footer-atelier">
        <div class="wrap footer-inner">
            <div>
                <p class="footer-brand">TOP-PARIKS Atelier</p>
                <p>© <?php echo esc_html(wp_date('Y')); ?> TOP-PARIKS</p>
            </div>
            <nav aria-label="Навигация в подвале">
                <?php tp_fallback_menu(); ?>
                <?php foreach (['wig-guide' => 'Как выбрать парик', 'wig-care' => 'Уход за париком', 'faq' => 'Вопросы и ответы'] as $slug => $label) : ?>
                    <?php if ($page_url = tp_published_page_url($slug)) : ?>
                        <a href="<?php echo esc_url($page_url); ?>"><?php echo esc_html($label); ?></a>
                    <?php endif; ?>
                <?php endforeach; ?>
                <?php if ($returns_url = tp_published_page_url('returns')) : ?>
                    <a href="<?php echo esc_url($returns_url); ?>"><?php esc_html_e('Возврат', 'top-pariks'); ?></a>
                <?php endif; ?>
                <?php if ($privacy_url = get_privacy_policy_url()) : ?>
                    <a href="<?php echo esc_url($privacy_url); ?>">Политика конфиденциальности</a>
                <?php endif; ?>
            </nav>
        </div>
    </footer>
<?php wp_footer(); ?>
</body>
</html>
