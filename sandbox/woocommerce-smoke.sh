#!/usr/bin/env bash
set -euo pipefail

base="http://localhost:${TOP_PARIKS_PORT:-8080}"
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
touch "$scratch/cookies"

fetch() {
    local path="$1" output="$2"
    curl --fail --silent --show-error --location --max-redirs 5 --max-time 30 \
        --noproxy '*' --resolve "localhost:${TOP_PARIKS_PORT:-8080}:127.0.0.1" \
        --cookie "$scratch/cookies" --cookie-jar "$scratch/cookies" \
        --output "$scratch/$output" "$base$path"
}

fetch /shop/ catalog
grep -F 'ТЕСТ — модель Atelier' "$scratch/catalog" >/dev/null
grep -F 'ТЕСТ — модель Studio' "$scratch/catalog" >/dev/null

fetch /product/topqa-natural/ product
product_id="$(sed -nE 's/.*name="add-to-cart" value="([0-9]+)".*/\1/p' "$scratch/product")"
if [[ ! "$product_id" =~ ^[1-9][0-9]*$ ]]; then
    echo 'Could not find the test product add-to-cart button.' >&2
    exit 1
fi

fetch "/?add-to-cart=$product_id" add-to-cart
fetch /cart/ cart
grep -F 'ТЕСТ — модель Atelier' "$scratch/cart" >/dev/null
grep -F '19.00' "$scratch/cart" >/dev/null

fetch /checkout/ checkout
grep -F 'payment_method_cod' "$scratch/checkout" >/dev/null
grep -F 'Test only — offline payment' "$scratch/checkout" >/dev/null
echo 'Test products, cart and offline checkout are available.'
