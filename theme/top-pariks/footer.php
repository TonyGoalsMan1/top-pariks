</main>
<footer class="footer footer-atelier">
    <div class="wrap footer-inner">
        <div>
            <p class="footer-brand">TOP-PARIKS Atelier</p>
            <p>© <?php echo esc_html(wp_date('Y')); ?> TOP-PARIKS</p>
        </div>
        <nav aria-label="Навигация в подвале">
            <?php tp_fallback_menu(); ?>
            <?php if ($privacy_url = get_privacy_policy_url()) : ?>
                <a href="<?php echo esc_url($privacy_url); ?>">Политика конфиденциальности</a>
            <?php endif; ?>
        </nav>
    </div>
</footer>
<?php wp_footer(); ?>
</body>
</html>
