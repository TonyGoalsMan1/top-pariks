# SEO-001 · Протокол проверок

21 ноября 2026 года, изолированный Docker Compose `top-pariks-seo`, localhost:8091. WordPress 6.9.1, WooCommerce 10.5.3, WordPress core sitemap, Chromium и Playwright. Два прогона в viewport 390 × 844: штатный `blog_public=0` и имитация открытой конфигурации `blog_public=1` на loopback. Настройка возвращена в 0.

| Запрос | HTTP | Наблюдение |
| --- | --- | --- |
| `/` | 200 | H1 «Парики для безупречного образа», title TOP-PARIKS TEST, canonical отсутствует |
| `/shop/` | 200 | H1 Shop, два товара, canonical отсутствует |
| `/product-category/natural-wigs/`, `/product-category/synthetic-wigs/`, `/product-category/short-wigs/`, `/product-category/long-wigs/` | 200 | H1 и title из названия категории, по одному товару, canonical отсутствует |
| `/product/topqa-natural/`, `/product/topqa-synthetic/` | 200 | H1 и title модели, self-canonical. JSON-LD декодируется и содержит Product, Offer и вложенного продавца Organization. На Atelier отсутствует изображение в графе, описание пустое. Цена, валюта и наличие берутся из тестового товара, рейтинга нет |
| `/cart/`, `/my-account/` | 200 | Оба с self-canonical и noindex в открытой конфигурации |
| `/checkout/` при пустой корзине | 302 → 200 | WooCommerce перенаправляет на `/cart/`. С товаром пройден checkout |
| `/?s=Atelier&post_type=product` | 302 → 200 | WooCommerce перенаправляет единственный результат в карточку |
| `/?s=ТЕСТ&post_type=product` | 200 | Поисковый архив доступен в штатном тестовом режиме |
| `/shop/?orderby=price` | 200 | Порядок Studio → Atelier. В открытом режиме отсутствуют noindex и canonical |
| `/shop/?min_price=15` | 200 | Только Atelier. В открытом режиме отсутствуют noindex и canonical |
| `/shop/page/2/`, `/product-category/natural-wigs/page/2/` | 404 | Вне диапазона тестовых выборок |
| `/about/`, `/delivery/`, `/contacts/`, `/wishlist/`, `/privacy-policy/` | 404 | Адреса присутствуют в исходнике темы, стенд страницы не публикует |

Во всех 21 HTML-запросах основной выборки отсутствовал meta Description и не обнаружен `X-Robots-Tag`. Штатный режим выдавал `noindex, nofollow`. Видимые хлебные крошки и BreadcrumbList не обнаружены в проверенном HTML. На главной отдельной разметки Organization нет.

| Проверка | Результат |
| --- | --- |
| `/robots.txt` | 200 в обоих режимах. Правила WordPress и WooCommerce ограничивают служебные пути и add-to-cart, глобального запрета обхода нет. Sitemap объявлен только в открытом режиме |
| `/wp-sitemap.xml` и `/sitemap.xml` | В штатном режиме 404. В открытом режиме оба дают XML через ответ 200 после переходов, если они есть. Проверены дочерние карты страниц, товаров и категорий. Карта страниц включает Sample Page, Cart, Checkout и My account |
| WooCommerce | Гостевой заказ №14 в Chromium. Добавление одного экземпляра Atelier, корзина, классическое оформление, офлайн-оплата и подтверждение заказа |
| Статика | PHP lint девяти PHP-файлов темы и стенда, syntax check JS темы, проверка пробелов и состава diff относительно ARCH-002 |

**Ограничения проверки.** Не проверены production, фактическое индексирование в Google и Яндексе, боевые URL и редиректы, сторонний фасетный интерфейс, рабочая страница пагинации с товарами, пустые комбинации атрибутов и вывод поиска в открытом режиме при нескольких результатах. Тестовые виртуальные товары не покрывают вариации, реальную доставку, онлайн-платежи и продуктовые фотографии. Lighthouse, полевые CWV, Google Rich Results Test и Schema Markup Validator в этом прогоне не выполнялись. DESIGN-001 проверен по diff и собственному отчёту PR, без объединения веток и повторного запуска его тестов.

Для повторения запустить отдельный экземпляр по [инструкции ARCH-002](../../sandbox/README.md), сверить в Chromium HTTP-код и конечный URL каждого запроса, `document.title`, узлы `h1,h2,h3,h4,h5,h6`, description, robots, canonical и JSON-LD. Открытый режим проверять только на изолированном экземпляре и сразу восстанавливать `blog_public=0`. Гостевой заказ повторяется по инструкции ARCH-002.
