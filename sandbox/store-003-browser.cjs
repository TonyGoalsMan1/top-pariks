const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { mkdirSync } = require('node:fs');
const { chromium, webkit } = require('playwright-core');

const origin = process.env.TOP_PARIKS_URL || 'http://localhost:8080';
const samples = 'store-003-screenshots';
mkdirSync(samples, { recursive: true });

function wp(...args) {
    return execFileSync('docker', ['compose', 'exec', '-T', '--user', 'www-data', 'wordpress',
        'php', '/tmp/top-pariks-wp-cli.phar', '--url=' + origin, ...args], { encoding: 'utf8' }).trim();
}

async function open(page, path, status = 200) {
    const response = await page.goto(new URL(path, origin).href);
    assert.equal(response.status(), status, path);
    assert.equal(new URL(page.url()).origin, origin);
    assert.match(await page.locator('html').getAttribute('lang'), /^ru/);
}

async function noOverflow(page, route, width) {
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, route + ' at ' + width);
}

async function catalog(page) {
    await open(page, '/shop/');
    const cards = page.locator('ul.products > li.product');
    assert.equal(await cards.count(), 3);
    assert.equal(await cards.filter({hasText:'Studio'}).locator('img.woocommerce-placeholder').count(), 1);
    const showFilters = async () => {
        const toggle = page.locator('.atelier-filter-toggle');
        if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') === 'false') {
            await toggle.click();
        }
    };
    const filters = page.getByRole('form', {name:'Фильтры каталога'});
    for (const [field, value] of [['filter_material','natural'],['filter_length','long'],['filter_color','chestnut']]) {
        await showFilters();
        await filters.locator('[name=' + field + ']').selectOption(value);
        await filters.getByRole('button', {name:'Применить'}).click();
        await page.waitForURL(url => url.searchParams.get(field) === value);
        assert.match(await cards.first().innerText(), /Atelier/);
    }
    assert.equal(await cards.count(), 1);
    const chips = page.getByRole('list', {name:'Выбранные фильтры'});
    if (await chips.count()) {
        await chips.getByRole('link', {name:/Удалить фильтр Цвет/}).click();
        assert.match(await chips.innerText(), /Материал/);
        await chips.getByRole('link', {name:'Сбросить все'}).click();
    } else {
        await showFilters();
        await filters.getByRole('link', {name:'Сбросить'}).click();
    }
    await showFilters();
    await filters.locator('[name=min_price]').fill('20');
    await filters.getByRole('button', {name:'Применить'}).click();
    await page.waitForURL(url => url.searchParams.get('min_price') === '20');
    assert.match(await cards.first().innerText(), /выбором цвета/);
    assert.equal(await cards.count(), 1);

    await open(page, '/shop/?orderby=price');
    assert.match(await cards.first().innerText(), /Studio/);
    await open(page, '/?s=Atelier&post_type=product');
    assert.match(await page.locator('main').innerText(), /Atelier/);
    await open(page, '/product/topqa-choice/');
    const select = page.locator('select[name=attribute_pa_color]');
    await select.selectOption('chestnut');
    await page.waitForFunction(() => Number(document.querySelector('input.variation_id').value) > 0);
    await page.locator('.single_variation').filter({hasText:/24[,.]00/}).waitFor();
    if (!(await select.locator('option[value=blond]:disabled').count())) {
        await select.selectOption('blond');
        await page.locator('.single_add_to_cart_button.wc-variation-is-unavailable').waitFor();
    }
    await select.selectOption('chestnut');
    await page.locator('.single_add_to_cart_button:not(.disabled)').click();
    await open(page, '/cart/');
    await page.getByText('Тестовая доставка', {exact:true}).waitFor();
    await page.locator('.cart_item a.remove').click();
    await page.locator('.cart-empty').waitFor();
    console.log('Catalog, search, sorting, three attributes, price, variation and test shipping passed.');
}

async function addProduct(page) {
    await open(page, '/product/topqa-natural/');
    assert.ok(await page.locator('.woocommerce-product-gallery__image').count() >= 2);
    await page.locator('.single_add_to_cart_button').click();
    await open(page, '/cart/');
    assert.match(await page.locator('.cart_item').innerText(), /Atelier/);
}

const address = {first_name: 'Анна', last_name: 'Тестова', address_1: '123 Test Street',
    city: 'San Francisco', postcode: '94105', phone: '+14155550100'};
async function fillAddress(page, prefix, email) {
    for (const [field, value] of [['country', 'US'], ['state', 'CA']]) {
        const select = page.locator('#' + prefix + '_' + field + ' option[value=' + value + ']');
        if (await select.count()) {
            await page.locator('#' + prefix + '_' + field).selectOption(value);
        }
    }
    for (const [field, value] of Object.entries(address)) {
        const input = page.locator('#' + prefix + '_' + field);
        if (await input.count()) {
            await input.fill(value);
        }
    }
    if (email) {
        await page.locator('#billing_email').fill(email);
    }
}

async function checkout(page, email, validate = false) {
    await addProduct(page);
    if (validate) {
        await page.locator('.cart_item input.qty').fill('2');
        await page.locator('.cart_item input.qty').press('Tab');
        await page.locator('[name=update_cart]').click();
        await page.waitForFunction(() => /38[.,]00/.test(document.querySelector('.order-total')?.textContent || ''));
        await page.locator('.cart_item a.remove').click();
        await page.locator('.cart-empty').waitFor();
        await addProduct(page);
    }
    await open(page, '/checkout/');
    assert.match(await page.locator('h1').innerText(), /Оформление заказа/);
    if (validate) {
        for (const width of [320, 375, 390, 430, 768, 1024, 1440]) {
            await page.setViewportSize({width, height: 900});
            await noOverflow(page, '/checkout/', width);
            if (width === 390) {
                await page.screenshot({path:samples + '/checkout-390.png', fullPage:true});
            }
        }
    }
    if (validate) {
        await page.locator('#place_order').click();
        await page.locator('.woocommerce-error').waitFor();
    }
    await fillAddress(page, 'billing', email);
    await page.locator('#payment_method_cod').waitFor({state:'attached'});
    assert.match(await page.locator('#payment').innerText(), /Тестовая оплата без списания/);
    assert.equal(await page.locator('#payment input[name=payment_method]').count(), 1);
    const submit = page.locator('#place_order');
    await submit.click();
    await page.waitForURL(/order-received\/\d+/, {timeout:25000});
    const order = Number(page.url().match(/order-received\/(\d+)/)[1]);
    assert.ok(order > 0);
    await page.locator('.woocommerce-thankyou-order-received').waitFor();
    return order;
}

async function account(page, email, password) {
    await open(page, '/my-account/');
    const registration = page.locator('form.register');
    const usernameField = registration.locator('#reg_username');
    if (await usernameField.count()) {
        await usernameField.fill(email.split('@')[0]);
    }
    await registration.locator('#reg_email').fill(email);
    const passwordInput = registration.locator('#reg_password');
    await passwordInput.pressSequentially(password);
    await passwordInput.press('Tab');
    assert.deepEqual(await registration.locator(':invalid[name]').evaluateAll(fields => fields.map(field => field.name)), []);
    await registration.locator('button[name=register]:enabled').click();
    const navigation = page.locator('.woocommerce-MyAccount-navigation');
    const notice = page.locator('.woocommerce-error');
    await navigation.or(notice).first().waitFor();
    assert.equal(await notice.count(), 0, await notice.allTextContents());

    await open(page, '/my-account/edit-account/');
    await page.locator('#account_first_name').fill('Анна');
    await page.locator('#account_last_name').fill('Тестова');
    await page.locator('#account_display_name').fill('Анна Тестова');
    await page.locator('#account_email').fill('updated-' + email);
    await page.locator('#password_current').fill(password);
    await page.locator('#password_1').pressSequentially(password + '9!');
    await page.locator('#password_2').fill(password + '9!');
    await page.locator('[name=save_account_details]').click();
    await page.locator('.woocommerce-message').waitFor();

    await open(page, '/my-account/edit-address/');
    await page.locator('a[href*="/edit-address/shipping/"]').click();
    await page.locator('#shipping_first_name').waitFor();
    await fillAddress(page, 'shipping');
    await page.locator('[name=save_address]').click();
    await page.locator('.woocommerce-message').waitFor();
}

async function verifyStore004Admin(admin) {
    const natural = wp('eval', "echo wc_get_product_id_by_sku('TOPQA-NATURAL');");
    await open(admin, '/wp-admin/post.php?post=' + natural + '&action=edit');
    await admin.locator('#_regular_price').fill('22');
    await admin.locator('.inventory_tab a').click();
    await admin.locator('#_stock').fill('45');
    await Promise.all([admin.waitForEvent('framenavigated'), admin.locator('#publish').click()]);
    assert.deepEqual(JSON.parse(wp('eval', "$p=wc_get_product(" + natural + ");echo wp_json_encode([(float)$p->get_regular_price(),$p->get_stock_quantity()]);")), [22, 45]);

    const parent = wp('eval', "echo wc_get_product_id_by_sku('TOPQA-CHOICE');");
    const variant = wp('eval', "echo wc_get_product_id_by_sku('TOPQA-CHOICE-CHESTNUT');");
    await open(admin, '/wp-admin/post.php?post=' + parent + '&action=edit');
    await admin.locator('.variations_tab a').click();
    const panel = admin.locator('.woocommerce_variation').filter({has: admin.locator('.variable_post_id[value="' + variant + '"]')});
    await panel.locator('.edit_variation').click();
    const variantPrice = panel.locator('input[name^=variable_regular_price]');
    await variantPrice.fill('29');
    await variantPrice.press('Tab');
    const saved = admin.waitForResponse(response => (response.request().postData() || '').includes('action=woocommerce_save_variations'));
    await admin.locator('.save-variation-changes').click();
    assert.equal((await saved).ok(), true);
    assert.equal(Number(wp('eval', 'echo wc_get_product(' + variant + ')->get_regular_price();')), 29);

    await open(admin, '/wp-admin/media-new.php?browser-uploader');
    await admin.locator('#async-upload').setInputFiles('theme/top-pariks/assets/images/product-4.webp');
    await admin.locator('#html-upload').click();
    await admin.waitForURL(/upload\.php/);
    assert.ok(wp('post', 'list', '--post_type=attachment', '--post_status=inherit', '--name=product-4', '--field=ID'));

    await open(admin, '/wp-admin/edit-tags.php?taxonomy=product_cat&post_type=product');
    await admin.locator('#tag-name').fill('ТЕСТ — категория администратора');
    await admin.locator('#tag-slug').fill('store004-admin-category');
    await admin.locator('#submit').click();
    await admin.locator('#the-list .row-title').filter({hasText:'ТЕСТ — категория администратора'}).waitFor();
    assert.ok(wp('term', 'list', 'product_cat', '--slug=store004-admin-category', '--field=term_id'));
    await open(admin, '/wp-admin/edit.php?post_type=page');
    const faq = admin.locator('tr').filter({has: admin.locator('a.row-title').filter({hasText:'Часто задаваемые вопросы'})});
    await faq.hover();
    await faq.locator('button.editinline').click();
    const quickEdit = admin.locator('tr.inline-editor');
    await quickEdit.locator('input[name=post_title]').fill('Часто задаваемые вопросы — проверка');
    await quickEdit.locator('button.save').click();
    await admin.locator('a.row-title').filter({hasText:'Часто задаваемые вопросы — проверка'}).waitFor();
    assert.equal(wp('eval', "echo get_page_by_path('faq')->post_title;"), 'Часто задаваемые вопросы — проверка');
    console.log('STORE-004: price, stock, variation, media, category and information page editing passed in wp-admin.');
}

async function login(page, username, password) {
    await open(page, '/my-account/');
    await page.locator('#username').fill(username);
    await page.locator('#password').fill(password);
    await page.locator('[name=login]').click();
    await page.locator('.woocommerce-MyAccount-navigation').waitFor();
}

async function resetPassword(page, email, password) {
    await open(page, '/my-account/lost-password/');
    await page.locator('#user_login').fill(email);
    await page.locator('form.lost_reset_password button[type=submit]').click();
    await page.waitForURL(/reset-link-sent/);
    const encoded = wp('eval', "echo wp_json_encode(get_transient('topqa_mail_' . hash('sha256', '" + email + "')));");
    const message = JSON.parse(encoded);
    assert.match(message.subject, /[А-Яа-я]/);
    const link = await page.evaluate(message => {
        const document = new DOMParser().parseFromString(message, 'text/html');
        const links = [...document.querySelectorAll('a[href]')].map(anchor => anchor.href);
        links.push(...(document.body.textContent.match(/https?:\/\/[^\s<>]+/g) || []));
        return links.find(href => {
            const url = new URL(href, location.href);
            return url.origin === location.origin && url.searchParams.has('key')
                && (url.searchParams.has('id') || url.searchParams.has('login'));
        });
    }, message.message);
    assert.ok(link, 'Password reset URL was captured');
    await open(page, link);
    assert.equal(new URL(page.url()).searchParams.get('show-reset-form'), 'true');
    await page.locator('#password_1').pressSequentially(password);
    await page.locator('#password_2').fill(password);
    await page.locator('form.lost_reset_password button[type=submit]').click();
    await page.waitForURL(url => url.searchParams.get('password-reset') === 'true');
    await page.locator('.woocommerce-MyAccount-navigation').waitFor();
    await page.locator('.woocommerce-MyAccount-navigation-link--customer-logout a').click();
    await login(page, email, password);
    console.log('Password reset by intercepted email and fresh login passed.');
}

async function checkWebkit() {
    if (process.env.TOP_PARIKS_TEST_WEBKIT === 'yes') {
        const browser = await webkit.launch();
        try {
            const page = await browser.newPage({viewport:{width:390,height:844}, isMobile:true, hasTouch:true});
            await catalog(page);
            await open(page, '/my-account/');
            await noOverflow(page, '/my-account/', 390);
            await page.screenshot({path:samples + '/webkit-account-390.png', fullPage:true});
        } finally {
            await browser.close();
        }
    }
}

(async () => {
    await checkWebkit();
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('response', response => {
            if (response.status() >= 500 && response.url().startsWith(origin)) {
                errors.push(response.status() + ' ' + response.url());
            }
        });
        await catalog(page);
        const routes = ['/', '/shop/', '/product/topqa-natural/', '/my-account/'];
        for (const width of [320, 375, 390, 430, 768, 1024, 1440]) {
            await page.setViewportSize({width, height: 900});
            for (const route of routes) {
                await open(page, route);
                await noOverflow(page, route, width);
                if ([390, 1440].includes(width)) {
                    await page.screenshot({path: samples + '/' + (route.replaceAll('/', '-') || 'home') + width + '.png', fullPage: true});
                }
            }
        }
        for (const path of ['/about/', '/delivery/', '/contacts/', '/returns/', '/cart/',
            '/product-category/natural-wigs/', '/product-category/synthetic-wigs/', '/product-category/short-wigs/', '/product-category/long-wigs/']) {
            await open(page, path);
        }
        await open(page, '/product-category/short-wigs/');
        await page.getByRole('navigation', {name:'Подкатегории товаров'}).getByRole('link', {name:/пикси/i}).click();
        assert.match(await page.locator('ul.products').innerText(), /выбором цвета/);
        const privacyUrl = await page.locator('footer a').filter({hasText:'Политика конфиденциальности'}).getAttribute('href');
        await open(page, privacyUrl);
        if (process.env.TOP_PARIKS_STORE004 === 'yes') {
            for (const path of ['/about/', '/contacts/', '/delivery/', '/returns/', '/wig-guide/', '/wig-care/', '/faq/', privacyUrl, '/cart/', '/product/topqa-choice/']) {
                await open(page, path);
                await page.setViewportSize({width:390,height:844});
                await noOverflow(page, path, 390);
                const slug = new URL(path, origin).pathname.replaceAll('/', '-');
                await page.screenshot({path:samples + '/' + slug + '390.png', fullPage:true});
            }
        }
        if (process.env.TOP_PARIKS_STORE004 === 'yes') {
            await page.setViewportSize({width:320,height:844});
            await open(page, '/shop/');
            const title = page.locator('.woocommerce-loop-product__title').first();
            await title.evaluate(element => { element.textContent = 'Демонстрационная модель парика с длинным названием '.repeat(4); });
            assert.ok(await title.evaluate(element => element.scrollWidth <= element.clientWidth));
            await noOverflow(page, '/shop/ long title', 320);
            await open(page, '/?s=store004-no-such-item&post_type=product');
            await page.locator('.atelier-search-help a').waitFor();
        }
        await open(page, '/topqa-missing-page/', 404);
        await open(page, '/shop/?filter_material=natural');
        assert.match(await page.locator('meta[name=robots]').getAttribute('content'), /noindex/);
        assert.deepEqual(errors, []);

        const email = 'store003-' + randomBytes(5).toString('hex') + '@example.test';
        const password = 'TopQa!Z9-' + randomBytes(20).toString('hex');
        const guest = await browser.newPage();
        const guestOrder = await checkout(guest, 'guest-' + email, true);
        const customer = await browser.newPage({ viewport: {width: 390, height: 844} });
        await account(customer, email, password);
        const updatedEmail = 'updated-' + email;
        const customerOrder = await checkout(customer, updatedEmail);
        await open(customer, '/my-account/orders/');
        await noOverflow(customer, '/my-account/orders/', 390);
        await customer.screenshot({path:samples + '/orders-390.png', fullPage:true});
        assert.match(await customer.locator('main').innerText(), new RegExp(String(customerOrder)));
        await open(customer, '/my-account/view-order/' + customerOrder + '/');
        assert.match(await customer.locator('main').innerText(), /Atelier/);
        assert.match(await customer.locator('mark.order-status').innerText(), /[А-Яа-яЁё]/);
        await open(customer, '/my-account/view-order/' + guestOrder + '/');
        assert.equal(await customer.locator('.woocommerce-order-details').count(), 0);
        await customer.locator('.woocommerce-MyAccount-navigation-link--customer-logout a').click();
        await customer.locator('#username').waitFor();
        await login(customer, updatedEmail, password + '9!');
        await customer.locator('.woocommerce-MyAccount-navigation-link--customer-logout a').click();
        await resetPassword(customer, updatedEmail, password + '8!');

        const adminPassword = 'TopQa!Z9-' + randomBytes(20).toString('hex');
        wp('user', 'update', 'topqa', '--user_pass=' + adminPassword);
        const admin = await browser.newPage();
        await login(admin, 'topqa', adminPassword);
        const orderUrl = wp('eval', 'echo wc_get_order(' + customerOrder + ')->get_edit_order_url();');
        await open(admin, orderUrl);
        await admin.locator('#order_status').selectOption('wc-completed');
        await Promise.all([admin.waitForEvent('framenavigated'), admin.locator('button.save_order').click()]);
        await admin.waitForLoadState();
        assert.equal(wp('eval', 'echo wc_get_order(' + customerOrder + ')->get_status();'), 'completed');
        assert.equal(wp('eval', 'echo wc_get_order(' + guestOrder + ')->get_customer_id();'), '0');
        assert.equal(wp('eval', 'echo wc_get_order(' + customerOrder + ')->get_payment_method();'), 'cod');
        const outsiderEmail = 'other-' + email;
        wp('user', 'create', outsiderEmail.split('@')[0], outsiderEmail, '--role=customer', '--user_pass=' + password);
        const outsider = await browser.newPage();
        await login(outsider, outsiderEmail, password);
        await open(outsider, '/my-account/view-order/' + customerOrder + '/');
        assert.equal(await outsider.locator('.woocommerce-order-details').count(), 0);
        await open(customer, '/my-account/view-order/' + customerOrder + '/');
        const repeat = customer.locator('a[href*="order_again="]');
        await repeat.click();
        await open(customer, '/cart/');
        assert.match(await customer.locator('.cart_item').innerText(), /Atelier/);
        await open(admin, '/wp-admin/post-new.php?post_type=product');
        await admin.locator('#title').fill('ТЕСТ — черновик администратора');
        await admin.locator('#save-post').click();
        await admin.waitForURL(/post=\d+/);
        await admin.locator('#title').fill('ТЕСТ — правка черновика администратора');
        await admin.locator('#save-post').click();
        await admin.waitForLoadState();
        assert.ok(wp('post', 'list', '--post_type=product', '--post_status=draft', '--s=правка черновика', '--field=ID'));
        console.log('Guest and customer orders, account isolation, password reset, status and product administration passed.');
        if (process.env.TOP_PARIKS_STORE004 === 'yes') {
            await verifyStore004Admin(admin);
        }
    } finally {
        await browser.close();
    }

})().catch(error => { console.error(error); process.exitCode = 1; });
