# OpenAI Ads Conversions - Secret Outlet

An independent Python HTTP webhook was added to this repository. The existing Bagy product feed remains unchanged.

## Configuration

Run on Python 3.10+ with the following environment variables:

- `SHOPIFY_WEBHOOK_SECRET`: Shopify orders/paid webhook signing secret.
- `OPENAI_PIXEL_ID`: web data source pixel identifier in OpenAI Ads Manager.
- `OPENAI_CONVERSIONS_API_KEY`: API key for conversion delivery.
- `OPENAI_CONVERSION_SOURCE_URL`: public source URL, such as `https://www.secretoutlet.com.br/`.
- `PORT`: listening port, defaults to 8080.
- `CONVERSIONS_DB`: persistent SQLite database filename, defaults to `conversions.sqlite3`.

Start: `python openai_ads_webhook.py`.

Expose `POST /webhooks/shopify/orders-paid` over HTTPS and register a Shopify `orders/paid` webhook that targets it. The Shopify notifications must carry `X-Shopify-Hmac-Sha256` and `X-Shopify-Topic: orders/paid`. Only paid BRL orders are forwarded.

The webhook sends OpenAI `order_created` events with total amount in cents. It records successful event IDs to avoid re-sending them. It returns a retryable 503 when event delivery fails. Store the database on persistent disk.

Run tests with `python -m unittest discover -s tests -v`.

## Important limitations

GitHub stores the code but does not host an always-on Python webhook itself. Deployment with an HTTPS URL, creation of the pixel and conversions API key, Shopify webhook registration, and Ads Manager conversion configuration remain necessary. Do not commit secrets. Confirm that the store actually uses Shopify as the order source. For attribution, a storefront integration is needed to persist OpenAI click reference `oppref` into the order metadata, when available. Without a reference, view-through matching may still work if available for your ads account, but click-through measurement will be limited.

Official docs: https://developers.openai.com/ads/conversions-api
