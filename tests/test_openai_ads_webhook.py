import unittest
from openai_ads_webhook import prepare_event, verify_shopify

class ConversionTests(unittest.TestCase):
    def test_invalid_signature(self):
        self.assertFalse(verify_shopify(b'{}', 'incorrect', 'test'))

    def test_conversion(self):
        event = prepare_event({'id': 42, 'total_price': '399.90', 'currency': 'BRL', 'processed_at': '2026-10-27T11:00:00-03:00'}, 'https://www.secretoutlet.com.br/')
        self.assertEqual(event['type'], 'order_created')
        self.assertEqual(event['data']['amount'], 39990)

    def test_missing_id(self):
        with self.assertRaises(ValueError):
            prepare_event({'currency': 'BRL'}, 'https://www.secretoutlet.com.br/')
