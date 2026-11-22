# LANG-001 — зависимости интеграции

Ветка создана от `integration/arch-003` (`6cfab371910566bf7026c522f39499e797f6ce9f`). [CI для этого коммита](https://github.com/TonyGoalsMan1/top-pariks/actions/runs/44945613928) прошёл.

- [STORE-002 (#9)](https://github.com/TonyGoalsMan1/top-pariks/pull/9) содержит исправления личного кабинета и AJAX-счётчика корзины. Ветка PR также включает Preview.
- [ARCH-008 (#10)](https://github.com/TonyGoalsMan1/top-pariks/pull/10) переносит STORE-002 без Preview. В PR указан порядок интеграции #7 → #8 → #10.

На момент подготовки ветки оба изменения отсутствуют в `integration/arch-003`. После интеграции ARCH-008 нужно обновить ветку LANG-001 от проверенной базы, сверить пересечения файлов и повторить проверки личного кабинета, корзины и оформления заказа WooCommerce.
