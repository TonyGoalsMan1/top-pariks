const assert = require('node:assert/strict');
const { chromium, devices } = require('playwright-core');

const base = new URL(process.env.TOP_PARIKS_URL || 'http://localhost:8080');
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(base.hostname), 'Use the local test stand');
assert.equal(base.protocol, 'http:', 'Use the local HTTP sandbox');

async function restrictToSandbox(context) {
    await context.route('**/*', route => {
        return new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort();
    });
}
const label = /ТЕСТ — модель Atelier/;

async function checkLayout(page, step) {
    const dimensions = await page.evaluate(() => ({
        visible: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth
    }));
    assert.ok(dimensions.content <= dimensions.visible, `${step}: ${JSON.stringify(dimensions)}`);
}

async function open(page, path) {
    const response = await page.goto(new URL(path, base).href);
    assert.equal(response?.headers()['x-top-pariks-sandbox'], 'local', 'Missing sandbox marker');
    assert.ok(response?.ok(), `${path}: ${response?.status()}`);
}

async function checkShop(page, mobile) {
    const nav = page.getByRole('navigation', { name: 'Основная навигация' });
    await open(page, '/');
    assert.ok(await page.title().then(title => title.includes('TOP-PARIKS TEST')));
    await checkLayout(page, 'home');

    if (mobile) {
        const menu = page.getByRole('button', { name: 'Меню' });
        assert.equal(await menu.getAttribute('aria-expanded'), 'false');
        await menu.click();
        await nav.getByRole('link', { name: 'Каталог', exact: true }).focus();
        await page.keyboard.press('Escape');
        assert.equal(await menu.getAttribute('aria-expanded'), 'false');
        assert.equal(await menu.evaluate(button => button === document.activeElement), true);
        await menu.click();
        assert.equal(await menu.getAttribute('aria-expanded'), 'true');
        await nav.getByRole('link', { name: 'Каталог', exact: true }).click();
        await page.waitForURL('**/shop/');
        assert.equal(await menu.getAttribute('aria-expanded'), 'false');
        await open(page, '/');
    } else {
        await nav.getByRole('link', { name: 'Каталог', exact: true }).waitFor();
    }

    await page.getByRole('link', { name: /Перейти в каталог/ }).click();
    await page.waitForURL('**/shop/');
    const products = page.locator('ul.products > li.product');
    assert.equal(await products.count(), 2);
    const positions = await products.evaluateAll(cards => cards.map(card => {
        const { x, y, width } = card.getBoundingClientRect();
        const track = parseFloat(getComputedStyle(card.parentElement).gridTemplateColumns);
        return { x, y, width, track };
    }));
    assert.ok(positions[1].x > positions[0].x && positions[0].y === positions[1].y);
    assert.ok(positions.every(({ width, track }) => Math.abs(width - track) < 1));
    await page.getByRole('combobox', { name: 'Shop order' }).selectOption('price');
    await page.waitForURL(url => url.pathname === '/shop/' && url.searchParams.get('orderby') === 'price');
    assert.match(await products.first().innerText(), /Studio/);
    await checkLayout(page, 'catalog');

    const categories = page.getByRole('navigation', { name: 'Категории товаров' });
    const natural = categories.getByRole('link', { name: 'ТЕСТ — натуральные парики' });
    await natural.click();
    await page.waitForURL('**/product-category/natural-wigs/');
    assert.equal(await natural.getAttribute('aria-current'), 'page');
    assert.equal(await products.count(), 1);
    await checkLayout(page, 'category');

    const search = page.getByRole('searchbox', { name: 'Поиск товаров' });
    await search.fill('ТЕСТ');
    await page.getByRole('button', { name: 'Найти' }).click();
    await page.waitForURL(url => url.searchParams.get('s') === 'ТЕСТ' && url.searchParams.get('post_type') === 'product');
    assert.equal(await search.inputValue(), 'ТЕСТ');
    assert.equal(await products.count(), 2);
    await checkLayout(page, 'search');
    await search.fill('несуществующий-парик');
    await search.press('Enter');
    await page.waitForURL(url => url.searchParams.get('s') === 'несуществующий-парик');
    assert.equal(await products.count(), 0);
    await checkLayout(page, 'empty search');

    await open(page, '/shop/');
    await products.getByRole('link', { name: label }).click();
    await page.waitForURL('**/product/topqa-natural/');
    await checkLayout(page, 'product');
    await page.getByRole('button', { name: 'Add to cart' }).click();
    await page.getByRole('link', { name: 'View cart' }).click();
    await page.waitForURL('**/cart/');
    assert.match(await page.locator('.cart_item').innerText(), label);
    assert.equal(await page.locator('.cart_item input.qty').inputValue(), '1');
    assert.match(await page.locator('.order-total').innerText(), /\$19\.00/);
    await checkLayout(page, 'cart');
    if (mobile) {
        await page.setViewportSize({ width: 320, height: 844 });
        await checkLayout(page, 'cart at 320px');
    }

    await page.getByRole('link', { name: 'Proceed to checkout' }).click();
    await page.waitForURL('**/checkout/');
    const fields = {
        first_name: 'Test',
        last_name: 'Customer',
        address_1: '123 Test Street',
        city: 'San Francisco',
        postcode: '94105',
        phone: '+1 415 555 0100',
        email: 'shopper@example.test'
    };
    for (const [field, value] of Object.entries(fields)) {
        await page.locator(`#billing_${field}`).fill(value);
    }
    assert.equal(await page.locator('#billing_country').inputValue(), 'US');
    assert.equal(await page.locator('#billing_state').inputValue(), 'CA');
    await page.getByText('Test only — offline payment', { exact: true }).waitFor();
    await checkLayout(page, 'checkout');
    if (mobile) {
        await page.setViewportSize({ width: 390, height: 844 });
        await checkLayout(page, 'checkout at 390px');
    }
    await page.locator('#place_order').click();
    await page.waitForURL('**/checkout/order-received/**');
    const confirmation = page.locator('.woocommerce-order-overview');
    await confirmation.waitFor();
    assert.match(await confirmation.innerText(), /\$19\.00/);
    assert.match(await confirmation.innerText(), /Test only — offline payment/);
    await checkLayout(page, 'order confirmation');
    return (await confirmation.locator('.order strong').innerText()).trim();
}

async function checkAjaxCount(page) {
    await open(page, '/shop/');
    const add = page.locator('ul.products > li.product .ajax_add_to_cart').first();
    const count = page.locator('.site-header .cart-count');
    for (const quantity of [1, 2]) {
        const response = page.waitForResponse(res => res.url().includes('wc-ajax=add_to_cart'));
        await add.click();
        assert.ok((await response).ok());
        await count.filter({ hasText: new RegExp(`^${quantity}$`) }).waitFor();
    }
    await open(page, '/cart/');
    await page.locator('.cart_item input.qty').fill('3');
    await page.locator('[name=update_cart]').click();
    await count.filter({ hasText: /^3$/ }).waitFor();
    await page.locator('.cart_item a.remove').click();
    await count.filter({ hasText: /^0$/ }).waitFor();
}

async function checkAccount(page) {
    await checkAjaxCount(page);
    await open(page, '/my-account/');
    const email = 'store-002@example.test';
    const username = page.locator('#reg_username');
    if (await username.isVisible()) {
        await username.fill('store-002');
    }
    await page.locator('#reg_email').fill(email);
    const password = page.locator('#reg_password');
    await password.pressSequentially('Q7!gRv23xK@fP9vD6u!2');
    await password.press('Tab');
    const register = page.locator('form.woocommerce-form-register');
    const invalidFields = await register.locator(':invalid[name]').evaluateAll(fields => fields.map(field => field.name));
    assert.deepEqual(invalidFields, [], 'Registration form has invalid fields');
    await register.locator('button[name=register]').click();
    await page.locator('.woocommerce-MyAccount-navigation').waitFor();
    await checkAjaxCount(page);
    const order = await checkShop(page, false);
    await open(page, '/my-account/orders/');
    const number = page.locator('.woocommerce-orders-table__cell-order-number a').filter({ hasText: `#${order}` });
    await number.waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await checkLayout(page, 'mobile order history');
    await number.click();
    await page.waitForURL('**/my-account/view-order/**');
    await page.locator('.woocommerce-order-details').waitFor();
    console.log('STORE-002: registration, order history and AJAX cart count for guest and customer');
}

async function main() {
    const browser = await chromium.launch({
        executablePath: process.env.CHROMIUM_PATH,
        args: ['--no-sandbox']
    });
    try {
        if (process.argv.includes('--account')) {
            const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
            await restrictToSandbox(page.context());
            page.setDefaultTimeout(15000);
            await checkAccount(page);
            return;
        }
        const viewports = [
            ['mobile', devices['iPhone 13']],
            ['desktop', { viewport: { width: 1440, height: 900 } }]
        ];
        for (const [name, options] of viewports) {
            const context = await browser.newContext(options);
            await restrictToSandbox(context);
            const page = await context.newPage();
            page.setDefaultTimeout(10000);
            const order = await checkShop(page, name === 'mobile');
            console.log(`${name}: navigation, search, catalog, cart, checkout, order #${order}`);
            await context.close();
        }
        const page = await browser.newPage({ javaScriptEnabled: false });
        await restrictToSandbox(page.context());
        for (const width of [320, 360, 390, 768, 820, 821, 1024, 1440]) {
            await page.setViewportSize({ width, height: 900 });
            for (const path of ['/', '/shop/', '/product/topqa-natural/']) {
                await open(page, path);
                await checkLayout(page, `${width}px ${path}`);
                await page.getByRole('navigation', { name: 'Основная навигация' })
                    .getByRole('link', { name: 'Каталог', exact: true }).waitFor();
            }
        }
        console.log('320–1440px: no document overflow and navigation available without JavaScript');
    } finally {
        await browser.close();
    }
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
