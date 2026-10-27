"""Bagy -> OpenAI Ads paid-order converter. Dry-run by default.

Does NOT assume that order creation means payment. Works from the Bagy API
/orders result and requires explicit confirmed payment indicators.
"""
import argparse
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

def confirmed(order):
    value = order.get("has_payment")
    return value is True or value == 1 or value == "1"

def convert(order, now=None):
    if not confirmed(order):
        return None
    ident = str(order.get("id") or "").strip()
    if not ident:
        return None
    value = order.get("total") or order.get("total_price")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            return None
    except (ValueError, TypeError, ArithmeticError):
        return None
    paid_at = order.get("payment_date") or order.get("paid_at")
    if not paid_at:
        return None  # never guess the payment date
    try:
        timestamp = dt.datetime.fromisoformat(str(paid_at).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
    except ValueError:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    seconds = (now - timestamp).total_seconds()
    if seconds < -600 or seconds > 7 * 86400:
        return None
    event = {
        "id": "bagy_order_" + ident,
        "type": "order_created",
        "timestamp_ms": int(timestamp.timestamp() * 1000),
        "action_source": "web",
        "source_url": os.getenv("OPENAI_CONVERSION_SOURCE_URL", "https://www.secretoutlet.com.br/"),
        "data": {
            "type": "contents",
            "amount": int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "currency": "BRL",
        },
    }
    if isinstance(order.get("oppref"), str) and order["oppref"].strip():
        event["oppref"] = order["oppref"].strip()
    return event

def fetch_orders(base_url, token, page=1):
    if not base_url.startswith("https://"):
        raise ValueError("BAGY_API_BASE_URL must be HTTPS")
    url = base_url.rstrip("/") + "/orders?" + urllib.parse.urlencode({
        "access_token": token, "page": page, "limit": 50
    })
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)

def extract_orders(payload):
    if isinstance(payload, dict) and isinstance(payload.get("Orders"), list):
        return [v.get("Order", v) for v in payload["Orders"] if isinstance(v, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("orders"), list):
        return [v.get("Order", v) for v in payload["orders"] if isinstance(v, dict)]
    raise ValueError("Unknown Bagy orders response structure; do not send events")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--send", action="store_true", help="Explicitly send validated events to OpenAI")
    args = p.parse_args()
    token = os.environ["BAGY_API_TOKEN"]
    base_url = os.environ["BAGY_API_BASE_URL"]
    orders = extract_orders(fetch_orders(base_url, token, args.page))
    events = [event for order in orders if (event := convert(order))]
    print("Orders checked:", len(orders), "confirmed eligible:", len(events))
    if not args.send:
        print(json.dumps({"events": events}, ensure_ascii=False, indent=2))
        return
    pixel_id = os.environ["OPENAI_PIXEL_ID"]
    api_key = os.environ["OPENAI_CONVERSIONS_API_KEY"]
    for event in events:
        body = json.dumps({"events": [event], "integration_source": "secret_outlet_bagy"}).encode()
        endpoint = "https://bzr.openai.com/v1/events?pid=" + urllib.parse.quote(pixel_id, safe="")
        req = urllib.request.Request(endpoint, data=body,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as response:
            print("Sent:", event["id"], response.status)

if __name__ == "__main__":
    main()
