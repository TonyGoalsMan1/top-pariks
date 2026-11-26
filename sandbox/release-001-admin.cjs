const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { chromium } = require('playwright-core');

const origin = process.env.TOP_PARIKS_URL;
assert.equal(origin, 'http://localhost:8080', 'Use the isolated release store');

function wp(...args) {
    return execFileSync('docker', ['compose', 'exec', '-T', '--user', 'www-data', 'wordpress',
        'php', '/tmp/top-pariks-wp-cli.phar', '--url=' + origin, ...args], { encoding: 'utf8' }).trim();
}

async function open(page, path) {
    const response = await page.goto(new URL(path, origin).href);
    assert.equal(response?.status(), 200, path);
    assert.equal(new URL(page.url()).origin, origin);
}

async function chooseMedia(page, control, crop = false) {
    await control.locator('button.upload-button, button.select-media').first().click();
    const modal = page.locator('.media-modal:visible').last();
    await modal.waitFor();
    const library = modal.locator('#menu-item-browse');
    if (await library.isVisible()) await library.click();
    await modal.locator('.attachments .attachment').first().click();
    await modal.locator('button.media-button-select').click();
    if (crop) {
        const skip = page.locator('.media-modal:visible button.media-button-skip');
        await Promise.race([skip.waitFor(), modal.waitFor({ state: 'hidden' })]);
        if (await skip.isVisible()) await skip.click();
    }
    await modal.waitFor({ state: 'hidden' });
}

async function customize(page, storefront) {
    await open(page, '/wp-admin/customize.php');
    await page.locator('#accordion-section-tp_homepage .accordion-section-title').click();
    const settings = {
        tp_hero_heading: 'Тест — новый баннер Atelier',
        tp_hero_description: 'Тест — текст баннера из панели управления.',
        tp_hero_button: 'Тест — открыть каталог',
        tp_category_heading: 'Тест — категории Atelier',
        tp_contact_phone: '+1 (202) 555-0100',
        tp_contact_email: 'demo-qa@example.test',
    };
    for (const [key, value] of Object.entries(settings)) {
        const field = page.locator('[data-customize-setting-link="' + key + '"]').first();
        await field.fill(value);
        await field.press('Tab');
    }
    await chooseMedia(page, page.locator('#customize-control-tp_hero_image'));
    await page.locator('#sub-accordion-section-tp_homepage .customize-section-back').click();
    await page.locator('#accordion-section-title_tagline .accordion-section-title').click();
    await chooseMedia(page, page.locator('#customize-control-custom_logo'), true);
    await page.locator('#save').click();
    await page.waitForFunction(() => {
        const control = document.querySelector('#save');
        return control && control.disabled && !document.body.classList.contains('saving');
    });

    await open(storefront, '/');
    assert.equal(await storefront.locator('#atelier-title').innerText(), settings.tp_hero_heading);
    assert.equal(await storefront.locator('.hero-copy > p').last().innerText(), settings.tp_hero_description);
    assert.equal(await storefront.locator('.hero-copy .btn').innerText(), settings.tp_hero_button);
    assert.equal(await storefront.locator('#atelier-category-title').innerText(), settings.tp_category_heading);
    assert.match(await storefront.locator('.hero-image').getAttribute('src'), /\/uploads\//);
    assert.match(await storefront.locator('.custom-logo').getAttribute('src'), /\/uploads\//);
    assert.equal(await storefront.locator('footer a[href^="tel:"]').getAttribute('href'), 'tel:+12025550100');
    assert.equal(await storefront.locator('footer a[href^="mailto:"]').getAttribute('href'), 'mailto:demo-qa@example.test');
    console.log('Customizer: banner, photo, category heading, logo, phone and email persisted and rendered.');
}

async function menu(page, storefront) {
    const id = wp('eval', 'echo get_nav_menu_locations()["primary"] ?? 0;');
    assert.ok(Number(id), 'The primary menu is assigned');
    await open(page, '/wp-admin/nav-menus.php?action=edit&menu=' + id);
    const first = page.locator('#menu-to-edit .menu-item').first();
    await first.locator('.item-edit').click();
    await first.locator('input.edit-menu-item-title').fill('Тест — пункт меню Atelier');
    await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
        page.locator('#save_menu_footer').click(),
    ]);
    assert.match(wp('menu', 'item', 'list', id, '--field=title'), /Тест — пункт меню Atelier/);
    await open(storefront, '/');
    assert.match(await storefront.locator('#tp-navigation').innerText(), /Тест — пункт меню Atelier/);
    console.log('Appearance: assigned menu updated in WordPress Admin.');
}

async function commerce(page, storefront) {
    await open(page, '/wp-admin/edit.php?post_type=product&page=product_attributes');
    await page.locator('#attribute_label').fill('Тест — характеристика Atelier');
    await page.locator('#attribute_name').fill('atelier-qa');
    await page.locator('#submit').click();
    await page.locator('table').getByText('Тест — характеристика Atelier', { exact: true }).waitFor();
    assert.ok(Number(wp('eval', 'echo wc_attribute_taxonomy_id_by_name("atelier-qa");')));

    const id = wp('eval', 'echo wc_get_product_id_by_sku("TOPQA-SYNTHETIC");');
    assert.ok(Number(id));
    await open(page, '/wp-admin/post.php?post=' + id + '&action=edit');
    await page.locator('#_regular_price').fill('12.00');
    await page.locator('#_sale_price').fill('9.00');
    await page.locator('#atelier_seo_title').fill('Тест — SEO Studio');
    await page.locator('#atelier_seo_description').fill('Тестовое описание Studio из панели управления.');
    await page.locator('#publish').click();
    await page.locator('#message.updated').waitFor();
    await open(storefront, '/product/topqa-synthetic/');
    assert.equal(await storefront.locator('.summary .price ins .amount').count(), 1);
    assert.match(await storefront.locator('.summary .price ins').innerText(), /9[.,]00/);
    assert.match(await storefront.title(), /Тест — SEO Studio/);
    assert.equal(await storefront.locator('meta[name="description"]').getAttribute('content'), 'Тестовое описание Studio из панели управления.');

    await open(page, '/wp-admin/edit.php?post_type=product');
    await page.locator('#post-' + id + ' .column-featured a').click();
    await page.waitForLoadState();
    await open(storefront, '/');
    assert.match(await storefront.locator('#atelier-products-title + a').first().getAttribute('href'), /shop/);
    assert.match(await storefront.locator('.atelier-home .products').innerText(), /Studio/);

    await open(page, '/wp-admin/admin.php?page=wc-settings&tab=checkout&section=cod');
    await page.locator('#woocommerce_cod_title').fill('Тест — офлайн-оплата Atelier');
    await page.locator('button[name="save"]').click();
    await page.locator('#woocommerce_cod_title').waitFor();
    assert.equal(JSON.parse(wp('option', 'get', 'woocommerce_cod_settings', '--format=json')).title, 'Тест — офлайн-оплата Atelier');

    const flatRate = wp('eval', 'foreach (WC_Shipping_Zones::get_zones() as $zone) { foreach ($zone["shipping_methods"] as $method) { if ($method->id === "flat_rate") { echo $method->get_instance_id(); break 2; } } }');
    assert.ok(Number(flatRate));
    await open(page, '/wp-admin/admin.php?page=wc-settings&tab=shipping&instance_id=' + flatRate);
    await page.locator('#woocommerce_flat_rate_title').fill('Тест — доставка Atelier');
    await page.locator('button[name="save"]').click();
    await page.locator('#woocommerce_flat_rate_title').waitFor();
    assert.equal(JSON.parse(wp('option', 'get', 'woocommerce_flat_rate_' + flatRate + '_settings', '--format=json')).title, 'Тест — доставка Atelier');
    console.log('WooCommerce Admin: sale price, featured product, SEO fields, offline payment and flat-rate shipping persisted.');
}

async function run() {
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
        const storefront = await browser.newPage();
        const password = 'TopQa!9-' + randomBytes(20).toString('hex');
        wp('user', 'update', 'topqa', '--user_pass=' + password);
        await open(page, '/wp-login.php');
        await page.locator('#user_login').fill('topqa');
        await page.locator('#user_pass').fill(password);
        await page.locator('#wp-submit').click();
        await page.locator('#wpadminbar').waitFor();
        await customize(page, storefront);
        await menu(page, storefront);
        await commerce(page, storefront);
    } finally {
        await browser.close();
    }
}
run().catch(error => { console.error(error); process.exitCode = 1; });