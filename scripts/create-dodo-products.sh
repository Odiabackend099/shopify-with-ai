#!/bin/bash
# Run this ONCE after your Dodo API key has WRITE access enabled
# Usage: bash scripts/create-dodo-products.sh

DODO_KEY="${DODO_PAYMENTS_TEST_API_KEY}"
BASE_URL="https://test.dodopayments.com/v1"

echo "Creating Shopify with AI products in Dodo Payments..."

create_product() {
  local name="$1"
  local price="$2"  # in cents
  local interval="$3"  # Month or Year
  local repeat="$4"  # 1 or 12
  local trial_days="$5"  # 0 or 14
  local tier="$6"

  local body=$(cat <<EOF
{
  "name": "$name",
  "description": "AI-powered dropshipping automation",
  "price": {
    "currency": "USD",
    "price": $price,
    "type": "recurring_price",
    "interval": "$interval",
    "repeat_interval": $repeat,
    "trial_days": $trial_days
  },
  "tax_category": "saas",
  "metadata": {
    "tier": "$tier",
    "interval": "$interval"
  }
}
EOF
)

  echo "Creating: $name..."
  curl -s -X POST "$BASE_URL/products" \
    -H "Authorization: Bearer $DODO_KEY" \
    -H "Content-Type: application/json" \
    -d "$body" | python3 -c "
import sys,json
d=json.load(sys.stdin)
pid=d.get('product_id','ERROR')
print(f'  → product_id: {pid}')
print(f'  → price: \${$price/100}/$interval')
"
}

# Create products
create_product "Shopify with AI - Free Trial" 0 "Month" 1 14 "free"
create_product "Shopify with AI - Starter Monthly" 2900 "Month" 1 0 "starter"
create_product "Shopify with AI - Growth Monthly" 7900 "Month" 1 0 "growth"
create_product "Shopify with AI - Starter Annual" 27600 "Year" 1 0 "starter"
create_product "Shopify with AI - Growth Annual" 75600 "Year" 1 0 "growth"

echo ""
echo "Done! Save these product IDs in your .env and backend code."
