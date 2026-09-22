import tempfile
import unittest
from pathlib import Path

import track_prices


class TrackerTests(unittest.TestCase):
    def test_extract_price_from_html(self):
        html = "<div>Beras Medium / kg</div><strong>Rp12.500</strong>"
        self.assertEqual(track_prices.extract_price(track_prices.clean_html(html), "Beras Medium / kg"), 12500)

    def test_extract_missing_price(self):
        self.assertIsNone(track_prices.extract_price("Beras Medium / kg belum tersedia", "Beras Medium / kg"))

    def test_merge_history_replaces_same_market_day(self):
        old = [
            {
                "date": "2026-09-21",
                "area": "gresik",
                "marketId": "45",
                "location": "Pasar Baru",
                "sourceType": "pasar rakyat",
                "commodityKey": "gula",
                "commodity": "Gula",
                "unit": "kg",
                "price": 17000,
                "address": "",
                "sourceUrl": "",
            }
        ]
        new = [dict(old[0], price=17500)]
        result = track_prices.merge_history(old, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price"], 17500)

    def test_trend_warning_after_rising_days(self):
        history = []
        for date, price in [
            ("2026-09-18", 60000),
            ("2026-09-19", 61000),
            ("2026-09-20", 62000),
        ]:
            history.append(
                {
                    "date": date,
                    "area": "gresik",
                    "marketId": "45",
                    "location": "Pasar Baru",
                    "sourceType": "pasar rakyat",
                    "commodityKey": "cabai-rawit",
                    "commodity": "Cabai rawit merah",
                    "unit": "kg",
                    "price": price,
                    "address": "",
                    "sourceUrl": "",
                }
            )
        current = [dict(history[-1], date="2026-09-21", price=63000)]
        signal = track_prices.trend_signal(
            history,
            "2026-09-21",
            "gresik",
            track_prices.COMMODITY_BY_KEY["cabai-rawit"],
            current,
        )
        self.assertEqual(signal["signal"], "WASPADA NAIK")

    def test_csv_round_trip(self):
        record = {
            "date": "2026-09-21",
            "area": "lamongan",
            "marketId": "retail:1",
            "location": "Koperasi",
            "sourceType": "koperasi",
            "commodityKey": "gula",
            "commodity": "Gula kristal putih",
            "brand": "Gulaku",
            "productName": "Gula Premium",
            "size": "1 kg",
            "unit": "kg",
            "price": 17000,
            "priceType": "promo",
            "stockStatus": "tersedia",
            "confidence": "input-manual",
            "observedAt": "2026-09-21 08:00",
            "address": "Jalan A, Lamongan",
            "sourceUrl": "https://example.com",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv"
            track_prices.write_csv_records(path, [record])
            self.assertEqual(track_prices.read_csv_records(path)[0], record)

    def test_telegram_messages_are_sorted_and_include_brand_location(self):
        records = [
            {
                "area": "gresik",
                "commodity": "Gula",
                "productName": "Gula Premium",
                "brand": "Gulaku",
                "price": 17000,
                "unit": "kg",
                "location": "Koperasi Contoh",
                "sourceType": "koperasi",
                "address": "Jalan A, Gresik",
            },
            {
                "area": "lamongan",
                "commodity": "Beras",
                "productName": "Beras Medium",
                "brand": "Merk Hemat",
                "price": 12500,
                "unit": "kg",
                "location": "Toko Contoh",
                "sourceType": "toko",
                "address": "Jalan B, Lamongan",
            },
        ]

        message = track_prices.build_telegram_messages(records, "2026-09-21")[0]

        self.assertLess(message.index("Beras Medium"), message.index("Gula Premium"))
        self.assertIn("Merk Hemat", message)
        self.assertIn("Toko Contoh (toko)", message)


if __name__ == "__main__":
    unittest.main()