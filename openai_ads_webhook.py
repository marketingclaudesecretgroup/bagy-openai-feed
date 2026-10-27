"""Shopify orders/paid -> OpenAI Ads Conversions API bridge.

Run with Python 3.10+; no third-party dependencies.
"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, HTTPServer

MAX_BODY = 1024 * 1024
DB_PATH = os.getenv("CONVERSIONS_DB", "conversions.sqlite3")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))


def verify_shopify(body, provided_hmac, secret):
    if not provided_hmac or not secret:
        return False
    expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, provided_hmac)


def prepare_event(order, source_url):
    if not isinstance(order, dict) or not order.get("id"):
        raise ValueError("Missing Shopify order id")
    currency = str(order.get("currency", "")).upper()
    if currency != "BRL":
        raise ValueError("Only BRL orders are supported")
    try:
        total = Decimal(str(order["total_price"]))
        if not total.is_finite() or total < 0:
            raise ValueError("Invalid order amount")
        cents = int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (KeyError, InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid total_price") from exc

    occurred = order.get("processed_at") or order.get("updated_at") or order.get("created_at")
    if not occurred:
        raise ValueError("Missing order timestamp")
    try:
        dt = datetime.fromisoformat(str(occurred).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Timestamp needs timezone")
        timestamp_ms = int(dt.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid timestamp") from exc

    return {
        "id": "shopify_order_" + str(order["id"]),
        "type": "order_created",
        "timestamp_ms": timestamp_ms,
        "action_source": "web",
        "source_url": source_url,
        "data": {"type": "contents", "amount": cents, "currency": currency},
    }


def send_conversion(event, pixel_id, api_key, validate_only=False):
    payload = {"events": [event], "integration_source": "secret-outlet-shopify"}
    if validate_only:
        payload["validate_only"] = True
    url = "https://bzr.openai.com/v1/events?pid=" + urllib.parse.quote(pixel_id, safe="")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status


def init_database(db):
    db.execute("CREATE TABLE IF NOT EXISTS delivered (event_id TEXT PRIMARY KEY, delivered_at TEXT NOT NULL)")
    db.commit()


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, message):
        payload = json.dumps({"status": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, "ok")
        return self.respond(404, "not_found")

    def do_POST(self):
        if self.path != "/webhooks/shopify/orders-paid":
            return self.respond(404, "not_found")
        if self.headers.get("X-Shopify-Topic") != "orders/paid":
            return self.respond(400, "wrong_topic")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, "bad_content_length")
        if not (0 < length <= MAX_BODY):
            return self.respond(413, "invalid_payload_size")
        body = self.rfile.read(length)
        if not verify_shopify(body, self.headers.get("X-Shopify-Hmac-Sha256"), os.environ["SHOPIFY_WEBHOOK_SECRET"]):
            return self.respond(401, "invalid_signature")
        try:
            order = json.loads(body)
            event = prepare_event(order, os.environ["OPENAI_CONVERSION_SOURCE_URL"])
            # OpenAI accepts timestamps from the previous 7 days, max 10 minutes in the future.
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            if not (now_ms - 7 * 86400000 <= event["timestamp_ms"] <= now_ms + 600000):
                return self.respond(422, "timestamp_out_of_range")
            db = self.server.database
            if db.execute("SELECT 1 FROM delivered WHERE event_id=?", (event["id"],)).fetchone():
                return self.respond(200, "already_delivered")
            send_conversion(event, os.environ["OPENAI_PIXEL_ID"], os.environ["OPENAI_CONVERSIONS_API_KEY"])
            db.execute("INSERT INTO delivered (event_id, delivered_at) VALUES (?, ?)",
                       (event["id"], datetime.now(timezone.utc).isoformat()))
            db.commit()
            return self.respond(200, "delivered")
        except (ValueError, KeyError, json.JSONDecodeError):
            return self.respond(422, "invalid_order")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print("Delivery failed:", type(exc).__name__, flush=True)
            return self.respond(503, "retry_later")


def main():
    for name in ("SHOPIFY_WEBHOOK_SECRET", "OPENAI_PIXEL_ID", "OPENAI_CONVERSIONS_API_KEY", "OPENAI_CONVERSION_SOURCE_URL"):
        if not os.getenv(name):
            raise RuntimeError("Required environment variable missing: " + name)
    db = sqlite3.connect(DB_PATH)
    init_database(db)
    server = HTTPServer((HOST, PORT), Handler)
    server.database = db
    print("Conversion webhook listening on port", PORT, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        db.close()


if __name__ == "__main__":
    main()
