const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');

const origin = new URL(process.env.TOP_PARIKS_URL || 'http://localhost:8080').origin;
(async () => {
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage();
        async function open(path) {
            const response = await page.goto(new URL(path, origin).href);
            assert.equal(response.status(), 200, path);
            assert.match(response.headers()['x-robots-tag'] || '', /noindex/);
            assert.match(await page.locator('meta[name=robots]').getAttribute('content'), /noindex/);
            assert.equal(await page.locator('main h1').count(), 1, path);
            assert.ok(await page.title(), path);
        }
        await open('/');
        assert.ok(await page.locator('meta[name=description]').getAttribute('content'));
        assert.ok(await page.locator('meta[property="og:image"]').getAttribute('content'));
        assert.equal(await page.locator('link[rel=canonical]').count(), 1);
        await open('/shop/?filter_material=natural&atelier_filters=1&utm_source=test');
        const filteredCanonical = new URL(await page.locator('link[rel=canonical]').getAttribute('href'));
        assert.equal(filteredCanonical.pathname, '/shop/');
        assert.equal(filteredCanonical.searchParams.get('filter_material'), 'natural');
        assert.equal(filteredCanonical.searchParams.has('utm_source'), false);
        assert.equal(filteredCanonical.searchParams.has('atelier_filters'), false);
        await open('/product-category/natural-wigs/');
        assert.equal(await page.locator('meta[property="og:type"]').getAttribute('content'), 'website');
        await open('/product/topqa-natural/');
        assert.equal(await page.locator('meta[property="og:type"]').getAttribute('content'), 'product');
        assert.equal(await page.locator('meta[property="og:url"]').getAttribute('content'), origin + '/product/topqa-natural/');
        assert.ok(await page.locator('.woocommerce-product-gallery img').first().getAttribute('alt'));
        await page.getByRole('navigation', {name:'Хлебные крошки'}).waitFor();
        const types = await page.locator('script[type="application/ld+json"]').evaluateAll(elements => {
            const nodes = elements.flatMap(element => {
                const data = JSON.parse(element.textContent);
                return data['@graph'] || [data];
            });
            return nodes.flatMap(node => node['@type'] || []);
        });
        assert.ok(types.includes('Product') && types.includes('BreadcrumbList'), types.join(', '));
        await open('/my-account/');
        assert.equal(await page.locator('meta[property^="og:"]').count(), 0);
        const sitemap = await page.request.get(origin + '/wp-sitemap.xml');
        assert.equal(sitemap.status(), 404);
        const robots = await page.request.get(origin + '/robots.txt');
        assert.equal(robots.status(), 200);
        assert.match(await robots.text(), /User-agent:\s*\*/i);
        console.log('SEO checks passed: headings, meta, canonical, Open Graph, Product/BreadcrumbList and non-indexed demo.');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
