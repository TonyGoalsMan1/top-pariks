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
    const filters = page.getByRole('form', {name:'Фильтры каталога'});
    for (const [field, value] of [['filter_material','natural'],['filter_length','long'],['filter_color','chestnut']]) {
        await filters.locator('[name=' + field + ']').selectOption(value);
        await filters.getByRole('button', {name:'Применить'}).click();
        await page.waitForURL(url => url.searchParams.get(field) === value);
        assert.match(await cards.first().innerText(), /Atelier/);
    }
    assert.equal(await cards.count(), 1);
    await filters.getByRole('link', {name:'Сбросить'}).click();
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
    assert.match(await page.locator('.single_variation').innerText(), /24[,.]00/);
    if (!(await select.locator('option[value=blond]:disabled').count())) {
        await select.selectOption('blond');
        await page.locator('.single_add_to_cart_button.wc-variation-is-unavailable').waitFor();
    }
    console.log('Catalog, search, sorting, three attributes, price and variation passed.');
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
        await page.locator('[name=update_cart]').click();
        await page.waitForFunction(() => /38[.,]00/.test(document.querySelector('.order-total')?.textContent || ''));
        await page.locator('.cart_item a.remove').click();
        await page.locator('.cart-empty').waitFor();
        await addProduct(page);
    }
    await open(page, '/checkout/');
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
    await registration.locator('#reg_password').fill(password);
    await registration.locator('[name=register]').click();
    await page.locator('.woocommerce-MyAccount-navigation').waitFor();

    await open(page, '/my-account/edit-account/');
    await page.locator('#account_first_name').fill('Анна');
    await page.locator('#account_last_name').fill('Тестова');
    await page.locator('#account_display_name').fill('Анна Тестова');
    await page.locator('#password_current').fill(password);
    await page.locator('#password_1').fill(password + '9!');
    await page.locator('#password_2').fill(password + '9!');
    await page.locator('[name=save_account_details]').click();
    await page.locator('.woocommerce-message').waitFor();

    await open(page, '/my-account/edit-address/shipping/');
    await fillAddress(page, 'shipping');
    await page.locator('[name=save_address]').click();
    await page.locator('.woocommerce-message').waitFor();
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
    const link = message.message.match(/https?:\/\/[^\s<>]+[?&]key=[^\s<>]+/);
    assert.ok(link, 'Password reset URL was captured');
    await open(page, link[0].replaceAll('&amp;', '&'));
    await page.locator('#password_1').fill(password);
    await page.locator('#password_2').fill(password);
    await page.locator('form.lost_reset_password button[type=submit]').click();
    await page.locator('#username').waitFor();
    await login(page, email, password);
}

(async () => {
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
        const privacyUrl = await page.locator('footer a').filter({hasText:'Политика конфиденциальности'}).getAttribute('href');
        await open(page, privacyUrl);
        await open(page, '/topqa-missing-page/', 404);
        await open(page, '/shop/?filter_material=natural');
        assert.match(await page.locator('meta[name=robots]').getAttribute('content'), /noindex/);
        assert.deepEqual(errors, []);

        const email = 'store003-' + randomBytes(5).toString('hex') + '@example.test';
        const password = 'TopQa-' + randomBytes(20).toString('hex');
        const guest = await browser.newPage();
        const guestOrder = await checkout(guest, 'guest-' + email, true);
        const customer = await browser.newPage({ viewport: {width: 390, height: 844} });
        await account(customer, email, password);
        const customerOrder = await checkout(customer, email);
        await open(customer, '/my-account/orders/');
        await noOverflow(customer, '/my-account/orders/', 390);
        await customer.screenshot({path:samples + '/orders-390.png', fullPage:true});
        assert.match(await customer.locator('main').innerText(), new RegExp(String(customerOrder)));
        await open(customer, '/my-account/view-order/' + customerOrder + '/');
        assert.match(await customer.locator('main').innerText(), /Atelier/);
        await open(customer, '/my-account/view-order/' + guestOrder + '/');
        assert.equal(await customer.locator('.woocommerce-order-details').count(), 0);
        await customer.locator('.woocommerce-MyAccount-navigation-link--customer-logout a').click();
        await customer.locator('#username').waitFor();
        await login(customer, email, password + '9!');
        await customer.locator('.woocommerce-MyAccount-navigation-link--customer-logout a').click();
        await resetPassword(customer, email, password + '8!');

        const adminPassword = 'TopQa-' + randomBytes(20).toString('hex');
        wp('user', 'update', 'topqa', '--user_pass=' + adminPassword);
        const admin = await browser.newPage();
        await login(admin, 'topqa', adminPassword);
        const orderUrl = wp('eval', 'echo wc_get_order(' + customerOrder + ')->get_edit_order_url();');
        await open(admin, orderUrl);
        await admin.locator('#order_status').selectOption('wc-completed');
        await admin.locator('button.save_order').click();
        await admin.waitForLoadState();
        assert.equal(wp('eval', 'echo wc_get_order(' + customerOrder + ')->get_status();'), 'completed');
        assert.equal(wp('eval', 'echo wc_get_order(' + guestOrder + ')->get_customer_id();'), '0');
        assert.equal(wp('eval', 'echo wc_get_order(' + customerOrder + ')->get_payment_method();'), 'cod');
        await open(admin, '/wp-admin/post-new.php?post_type=product');
        await admin.locator('#title').fill('ТЕСТ — черновик администратора');
        await admin.locator('#save-post').click();
        await admin.waitForURL(/post=\d+/);
        await admin.locator('#title').fill('ТЕСТ — правка черновика администратора');
        await admin.locator('#save-post').click();
        await admin.waitForLoadState();
        assert.ok(wp('post', 'list', '--post_type=product', '--post_status=draft', '--s=правка черновика', '--field=ID'));
        console.log('Guest and customer orders, account isolation, password reset, status and product administration passed.');
    } finally {
        await browser.close();
    }

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
})().catch(error => { console.error(error); process.exitCode = 1; });
