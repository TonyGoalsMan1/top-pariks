const assert = require('node:assert/strict');
const { mkdirSync } = require('node:fs');
const { chromium } = require('playwright-core');

const side = process.argv[2];
assert.ok(['before', 'after'].includes(side));
const origin = process.env.TOP_PARIKS_URL || 'http://localhost:8080';
const widths = [320, 375, 390, 430, 768, 1024, 1440];
const routes = {
    home: '/', catalog: '/shop/', category: '/product-category/natural-wigs/',
    product: '/product/topqa-choice/', search: '/?s=Atelier&post_type=product',
    'search-empty': '/?s=design002-no-result&post_type=product',
    cart: '/cart/', checkout: '/checkout/', account: '/my-account/',
    about: '/about/', contacts: '/contacts/', delivery: '/delivery/', returns: '/returns/',
    guide: '/wig-guide/', care: '/wig-care/', faq: '/faq/', privacy: '/privacy-policy/',
};

async function open(page, route) {
    const response = await page.goto(new URL(route, origin).href);
    assert.equal(response?.status(), 200, route);
    await page.locator('h1').first().waitFor();
}

async function run() {
    const output = 'design-002-screenshots/' + side;
    mkdirSync(output, { recursive: true });
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage();
        await open(page, '/product/topqa-natural/');
        await page.locator('.single_add_to_cart_button').click();
        await page.waitForLoadState('load');
        await open(page, '/cart/');
        await page.locator('.woocommerce-cart-form .cart_item').first().waitFor();

        for (const [name, route] of Object.entries(routes)) {
            await page.setViewportSize({ width: 390, height: 870 });
            await open(page, route);
            assert.match(await page.locator('html').getAttribute('lang'), /^ru/i, name);
            if (name === 'checkout') await page.locator('#place_order').waitFor();
            if (name === 'product') {
                await page.locator('.woocommerce-product-gallery__image img').first().waitFor();
                await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('.woocommerce-product-gallery')).opacity) > 0.95);
            }
            const untranslated = await page.getByText(/^(?:Add to cart|View cart|Proceed to checkout|Place order|My account|Log in|Register|Lost your password\\?|Billing details|Your order|Search results|No products were found matching your selection\\.)$/i).all();
            if (side === 'after') {
                for (const item of untranslated) assert.equal(await item.isVisible(), false, name + ': ' + await item.textContent());
            }
            for (const width of widths) {
                await page.setViewportSize({ width, height: 870 });
                await page.evaluate(() => document.fonts.ready.then(() => undefined));
                const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
                if (side === 'after') assert.ok(overflow <= 0, name + ' @ ' + width + ': overflow ' + overflow);
                else if (overflow > 0) console.log(name, width, 'baseline overflow', overflow);
                if (width === 390 || width === 1440) {
                    await page.screenshot({ path: output + '/' + name + '-' + width + '.png', fullPage: true, animations: 'disabled' });
                }
            }
            console.log(side, name, widths.join(', '));
        }
    } finally {
        await browser.close();
    }
}

run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});