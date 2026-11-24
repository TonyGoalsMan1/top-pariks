"""WordPress runtime and storefront checks with an isolated cookie jar."""

import http.cookiejar
import re
import time
import urllib.error
import urllib.request

from artifacts import FactoryError


class LocalRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(self.origin + "/"):
            raise FactoryError("Storefront attempted a redirect outside the site")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def storefront(site):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), LocalRedirects(site.url),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def fetch(path, marker=None):
        try:
            with opener.open(site.url + path, timeout=10) as response:
                html = response.read().decode("utf-8", errors="replace")
                if response.status != 200 or (marker and marker not in html):
                    raise FactoryError(f"Storefront content check failed for {path}")
                return html
        except OSError as error:
            raise FactoryError(f"Storefront request failed for {path}: {error}") from error

    smoke = site.config["smoke"]
    fetch("/", smoke["home_text"])
    if not site.woocommerce:
        print("WordPress healthy: homepage")
        return
    fetch(smoke["catalog_path"], smoke["product_name"])
    product = fetch(smoke["product_path"], smoke["product_name"])
    button = re.search(r'name=["\']add-to-cart["\']\s+value=["\']([1-9][0-9]*)["\']', product)
    if not button:
        raise FactoryError("Product has no add-to-cart button")
    fetch(f"/?add-to-cart={button[1]}")
    cart = fetch(smoke["cart_path"], smoke["product_name"])
    if smoke["cart_price"] not in cart or "woocommerce-cart-form" not in cart:
        raise FactoryError("Cart contents or price check failed")
    print("Storefront healthy: homepage, catalog, product, cart")


def health(site):
    for attempt in range(20):
        try:
            with urllib.request.build_opener(
                urllib.request.ProxyHandler({}), LocalRedirects(site.url)
            ).open(site.url + "/wp-login.php", timeout=2):
                break
        except OSError as error:
            if attempt == 19:
                raise FactoryError(f"WordPress did not become ready: {error}") from error
            time.sleep(1)

    site.wp("core", "is-installed", "--skip-plugins", "--skip-themes")
    if site.woocommerce:
        site.wp("plugin", "is-active", "woocommerce", "--skip-themes")
    if site.wp("option", "get", "stylesheet", "--skip-themes", capture=True) != site.slug:
        raise FactoryError("Unexpected active theme")
    for option in ("siteurl", "home"):
        if site.wp("option", "get", option, "--skip-themes", capture=True) != site.url:
            raise FactoryError(f"Unexpected WordPress {option}")
    storefront(site)
