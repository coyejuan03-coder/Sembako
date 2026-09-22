#!/usr/bin/env python3
"""Pelacak harga sembako Gresik-Lamongan.

Dependensi: Python standard library saja.
Sumber harga pasar: SISKAPERBAPO Jawa Timur.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SOURCE_BASE = "https://siskaperbapo.indagjatim.com"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DEFAULT_HISTORY = DATA_DIR / "price-history.csv"
DEFAULT_REPORT = DATA_DIR / "latest-price-report.json"
DEFAULT_RETAIL = DATA_DIR / "retail-prices.csv"

AREAS: dict[str, dict[str, str]] = {
    "gresik": {"label": "Kabupaten Gresik", "keycode": "gresikkab"},
    "lamongan": {"label": "Kabupaten Lamongan", "keycode": "lamongankab"},
}


@dataclass(frozen=True)
class Commodity:
    key: str
    label: str
    source_label: str
    unit: str


COMMODITIES = [
    Commodity("beras-premium", "Beras premium", "Beras Premium / kg", "kg"),
    Commodity("beras-medium", "Beras medium", "Beras Medium / kg", "kg"),
    Commodity("gula", "Gula kristal putih", "Gula Kristal Putih / kg", "kg"),
    Commodity("minyak-curah", "Minyak goreng curah", "Minyak Goreng Curah / kg", "kg"),
    Commodity("minyakita", "Minyakita", "Minyak Goreng MINYAKITA / liter", "liter"),
    Commodity("ayam", "Daging ayam ras", "Daging Ayam Ras / kg", "kg"),
    Commodity("telur", "Telur ayam ras", "Telur Ayam Ras / kg", "kg"),
    Commodity("sapi", "Daging sapi paha belakang", "Daging Sapi Paha Belakang / kg", "kg"),
    Commodity("cabai-keriting", "Cabai merah keriting", "Cabe Merah Keriting / kg", "kg"),
    Commodity("cabai-besar", "Cabai merah besar", "Cabe Merah Besar / kg", "kg"),
    Commodity("cabai-rawit", "Cabai rawit merah", "Cabe Rawit Merah / kg", "kg"),
    Commodity("bawang-merah", "Bawang merah", "Bawang Merah / kg", "kg"),
    Commodity("bawang-putih", "Bawang putih", "Bawang Putih / kg", "kg"),
    Commodity("lpg", "LPG 3 kg", "GAS ELPIGI 3 Kg", "tabung"),
]

COMMODITY_BY_KEY = {commodity.key: commodity for commodity in COMMODITIES}
CSV_FIELDS = [
    "date",
    "area",
    "marketId",
    "location",
    "sourceType",
    "commodityKey",
    "commodity",
    "brand",
    "productName",
    "size",
    "unit",
    "price",
    "priceType",
    "stockStatus",
    "confidence",
    "observedAt",
    "address",
    "sourceUrl",
]


def today_jakarta() -> str:
    return datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d")


def parse_csv_list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def selected_areas(value: str | None) -> list[str]:
    requested = parse_csv_list(value, ["gresik", "lamongan"])
    valid = [area for area in requested if area in AREAS]
    return valid or ["gresik", "lamongan"]


def selected_commodities(value: str | None) -> list[Commodity]:
    if not value or value.lower() == "all":
        return COMMODITIES
    keys = set(parse_csv_list(value, []))
    return [commodity for commodity in COMMODITIES if commodity.key in keys]


def project_path(value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    from_project = ROOT / candidate
    from_cwd = Path.cwd() / candidate
    if from_project.exists() or not from_cwd.exists():
        return from_project
    return from_cwd


def clean_html(source: str) -> str:
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", source, flags=re.IGNORECASE)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", html.unescape(cleaned)).strip()


def extract_price(text: str, source_label: str) -> int | None:
    start = text.lower().find(source_label.lower())
    if start < 0:
        return None
    match = re.search(r"Rp\s*([0-9][0-9.]*)", text[start : start + 240], re.IGNORECASE)
    if not match:
        return None
    price = int(match.group(1).replace(".", ""))
    return price if price > 0 else None


def fetch_text(url: str, accept: str = "text/html,application/json") -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "PelacakHargaSembako/1.0",
            "Accept": accept,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Gagal mengambil {url}: {error}") from error


def market_url(date: str, area: str, market_id: str = "") -> str:
    keycode = AREAS[area]["keycode"]
    return f"{SOURCE_BASE}/display/show/?tanggal={date}&kabkota={keycode}&pasar={market_id}"


def fetch_markets(area: str) -> list[dict[str, Any]]:
    url = f"{SOURCE_BASE}/harga/pasar.json/{AREAS[area]['keycode']}"
    data = json.loads(fetch_text(url, "application/json"))
    if not isinstance(data, list):
        raise RuntimeError(f"Format daftar pasar {AREAS[area]['label']} tidak dikenal")
    return [
        {"psr_id": int(item["psr_id"]), "psr_nama": str(item["psr_nama"])}
        for item in data
        if isinstance(item, dict) and "psr_id" in item and "psr_nama" in item
    ]


def fetch_market_prices(
    date: str,
    area: str,
    market: dict[str, Any],
    commodities: list[Commodity],
) -> list[dict[str, Any]]:
    source_url = market_url(date, area, str(market["psr_id"]))
    text = clean_html(fetch_text(source_url))
    records: list[dict[str, Any]] = []
    for commodity in commodities:
        price = extract_price(text, commodity.source_label)
        if price is None:
            continue
        records.append(
            {
                "date": date,
                "area": area,
                "marketId": str(market["psr_id"]),
                "location": market["psr_nama"],
                "sourceType": "pasar rakyat",
                "commodityKey": commodity.key,
                "commodity": commodity.label,
                "brand": "Komoditas pasar",
                "productName": commodity.label,
                "size": f"1 {commodity.unit}",
                "unit": commodity.unit,
                "price": price,
                "priceType": "survei",
                "stockStatus": "terpantau",
                "confidence": "resmi-pasar",
                "observedAt": date,
                "address": f"{market['psr_nama']}, {AREAS[area]['label']}",
                "sourceUrl": source_url,
            }
        )
    return records


def read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                area = row.get("area", "")
                price = float(row.get("price", ""))
                if not row.get("date") or area not in AREAS or not row.get("commodityKey"):
                    continue
                records.append(
                    {
                        "date": row["date"],
                        "area": area,
                        "marketId": row.get("marketId") or f"retail:{row.get('location', '')}",
                        "location": row.get("location", ""),
                        "sourceType": row.get("sourceType", "toko"),
                        "commodityKey": row["commodityKey"],
                        "commodity": row.get("commodity", row["commodityKey"]),
                        "brand": row.get("brand", ""),
                        "productName": row.get("productName", row.get("commodity", row["commodityKey"])),
                        "size": row.get("size", ""),
                        "unit": row.get("unit", ""),
                        "price": int(price),
                        "priceType": row.get("priceType", "normal"),
                        "stockStatus": row.get("stockStatus", "perlu dikonfirmasi"),
                        "confidence": row.get("confidence", "input-manual"),
                        "observedAt": row.get("observedAt", row.get("date", "")),
                        "address": row.get("address", ""),
                        "sourceUrl": row.get("sourceUrl", ""),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    return records


def write_csv_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def merge_history(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in [*existing, *incoming]:
        key = "|".join(
            [
                str(record["date"]),
                str(record["area"]),
                str(record["marketId"]),
                str(record["commodityKey"]),
                str(record["sourceType"]),
            ]
        )
        merged[key] = record
    return sorted(
        merged.values(),
        key=lambda record: (
            record["date"],
            record["area"],
            record["commodityKey"],
            record["location"],
        ),
    )


def daily_averages(
    history: list[dict[str, Any]],
    area: str,
    commodity_key: str,
    before_date: str,
) -> list[tuple[str, float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for record in history:
        if (
            record["area"] == area
            and record["commodityKey"] == commodity_key
            and record["sourceType"] == "pasar rakyat"
            and record["date"] < before_date
        ):
            grouped[record["date"]].append(float(record["price"]))
    return sorted(
        (date, sum(values) / len(values))
        for date, values in grouped.items()
        if values
    )


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def trend_signal(
    history: list[dict[str, Any]],
    date: str,
    area: str,
    commodity: Commodity,
    latest_records: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_price = average([float(record["price"]) for record in latest_records]) or 0
    previous_days = daily_averages(history, area, commodity.key, date)
    base = {
        "area": area,
        "commodityKey": commodity.key,
        "commodity": commodity.label,
        "unit": commodity.unit,
        "latestPrice": latest_price,
    }
    if len(previous_days) < 2:
        return {
            **base,
            "previousAverage": None,
            "changePercent": None,
            "signal": "BASELINE",
            "reason": "Belum ada riwayat minimal dua hari untuk membaca tren.",
        }

    recent = previous_days[-7:]
    previous_average = average([value for _, value in recent]) or 0
    change_percent = ((latest_price - previous_average) / previous_average * 100) if previous_average else 0
    last_three = [value for _, value in previous_days[-3:]]
    rising_three_days = (
        len(last_three) == 3
        and last_three[0] < last_three[1] < last_three[2] < latest_price
    )
    historical_low = min(value for _, value in previous_days)

    if rising_three_days or change_percent >= 2:
        reason = (
            "Rata-rata pasar naik setidaknya tiga hari berturut-turut."
            if rising_three_days
            else "Harga terbaru minimal 2% di atas rata-rata tujuh hari."
        )
        signal = "WASPADA NAIK"
    elif latest_price <= historical_low * 1.01:
        reason = "Harga dekat titik terendah pada riwayat yang tersimpan."
        signal = "MURAH"
    else:
        reason = "Belum ada sinyal kenaikan kuat atau titik murah baru."
        signal = "NORMAL"

    return {
        **base,
        "previousAverage": previous_average,
        "changePercent": change_percent,
        "signal": signal,
        "reason": reason,
    }


def currency(value: float) -> str:
    return f"Rp{round(value):,}".replace(",", ".")


def build_telegram_messages(
    records: list[dict[str, Any]],
    date: str,
    limit: int = 40,
) -> list[str]:
    """Build Telegram-safe messages ordered from the cheapest price."""
    if limit < 1:
        raise ValueError("Batas harga Telegram harus minimal 1")

    ordered = sorted(
        records,
        key=lambda record: (
            float(record["price"]),
            str(record.get("commodity", "")),
            str(record.get("location", "")),
        ),
    )
    selected = ordered[:limit]
    header = [
        f"HARGA SEMBAKO TERMURAH — {date}",
        f"{len(ordered)} harga terpantau | menampilkan {len(selected)} teratas",
        "",
    ]
    lines: list[str] = []
    for index, record in enumerate(selected, start=1):
        brand = record.get("brand") or "Merek belum dicatat"
        product = record.get("productName") or record.get("commodity") or "Produk"
        unit = record.get("unit") or "unit"
        source_type = record.get("sourceType") or "sumber"
        area = AREAS.get(str(record.get("area")), {}).get("label", str(record.get("area", "")))
        location = record.get("location") or "Lokasi belum dicatat"
        lines.extend(
            [
                f"{index}. {product} — {brand}",
                f"   {currency(float(record['price']))}/{unit} | {location} ({source_type})",
                f"   {area}",
            ]
        )
        if record.get("address"):
            lines.append(f"   {record['address']}")
        lines.append("")

    if not lines:
        lines = ["Belum ada harga yang dapat dikirim."]

    messages: list[str] = []
    current = "\n".join(header)
    for line in lines:
        candidate = f"{current}\n{line}"
        if len(candidate) > 3900 and current.strip():
            messages.append(current.rstrip())
            current = line
        else:
            current = candidate
    if current.strip():
        messages.append(current.rstrip())
    return messages


def send_telegram_messages(
    messages: list[str],
    token: str | None = None,
    chat_id: str | None = None,
) -> int:
    """Send one or more messages using the official Telegram Bot API."""
    bot_token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    recipient = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not recipient:
        raise RuntimeError(
            "Telegram belum dikonfigurasi. Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID."
        )
    if not messages:
        raise RuntimeError("Tidak ada pesan Telegram yang dapat dikirim.")

    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for message in messages:
        request = Request(
            endpoint,
            data=json.dumps(
                {
                    "chat_id": recipient,
                    "text": message,
                    "disable_web_page_preview": True,
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PelacakHargaSembako/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Gagal menghubungi Telegram: {error}") from error
        if not result.get("ok"):
            description = result.get("description", "Telegram menolak pesan")
            raise RuntimeError(f"Telegram menolak pesan: {description}")
    return len(messages)


def send_telegram_notification(
    records: list[dict[str, Any]],
    date: str,
    limit: int = 40,
) -> int:
    return send_telegram_messages(build_telegram_messages(records, date, limit))


def print_report(
    date: str,
    records: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    errors: list[str],
    transport: float,
) -> None:
    print(f"\nPelacak Harga Sembako — {date}")
    print("Sumber utama: SISKAPERBAPO, harga konsumen per pasar")
    market_count = len({(record["area"], record["marketId"]) for record in records})
    print(f"Pasar terbaca: {market_count}")

    print("\nHarga termurah terpantau:")
    commodity_keys = dict.fromkeys(record["commodityKey"] for record in records)
    for commodity_key in commodity_keys:
        candidates = [
            record
            for record in records
            if record["commodityKey"] == commodity_key
        ]
        if not candidates:
            continue
        cheapest = min(candidates, key=lambda record: record["price"] + transport)
        print(
            f"- {cheapest['commodity']}: {currency(cheapest['price'])}/{cheapest['unit']} "
            f"— {cheapest['location']}, {AREAS[cheapest['area']]['label']}"
        )
        if transport:
            print(f"  Estimasi dengan ongkos: {currency(cheapest['price'] + transport)}/{cheapest['unit']}")

    print("\nSinyal tren:")
    warnings = [trend for trend in trends if trend["signal"] == "WASPADA NAIK"]
    cheap = [trend for trend in trends if trend["signal"] == "MURAH"]
    if not warnings and not cheap:
        print("- Belum ada peringatan; riwayat akan semakin berguna setelah dijalankan beberapa hari.")
    for trend in warnings:
        print(
            f"- WASPADA NAIK: {trend['commodity']} ({AREAS[trend['area']]['label']}) "
            f"— {currency(trend['latestPrice'])}/{trend['unit']}; {trend['reason']}"
        )
    for trend in cheap:
        print(
            f"- MURAH: {trend['commodity']} ({AREAS[trend['area']]['label']}) "
            f"— {currency(trend['latestPrice'])}/{trend['unit']}; {trend['reason']}"
        )

    if errors:
        print("\nSumber yang gagal dibaca:")
        for error in errors:
            print(f"- {error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pelacak harga sembako Gresik-Lamongan")
    parser.add_argument("--date", default=today_jakarta(), help="Tanggal data YYYY-MM-DD")
    parser.add_argument("--areas", default="gresik,lamongan", help="Wilayah, dipisahkan koma")
    parser.add_argument("--commodities", default="all", help="Commodity key, dipisahkan koma")
    parser.add_argument("--transport", type=float, default=0, help="Ongkos perjalanan per lokasi")
    parser.add_argument("--history", help="Path riwayat CSV relatif terhadap folder proyek")
    parser.add_argument("--retail", help="Path CSV toko/koperasi/swalayan relatif terhadap folder proyek")
    parser.add_argument("--report", help="Path laporan JSON relatif terhadap folder proyek")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Kirim daftar harga termurah ke Telegram memakai environment secret",
    )
    parser.add_argument(
        "--telegram-limit",
        type=int,
        default=40,
        help="Jumlah harga teratas yang dikirim ke Telegram",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    areas = selected_areas(args.areas)
    commodities = selected_commodities(args.commodities)
    history_path = project_path(args.history, DEFAULT_HISTORY)
    retail_path = project_path(args.retail, DEFAULT_RETAIL)
    report_path = project_path(args.report, DEFAULT_REPORT)
    errors: list[str] = []
    current_records: list[dict[str, Any]] = []

    for area in areas:
        try:
            markets = fetch_markets(area)
            for market in markets:
                try:
                    current_records.extend(fetch_market_prices(args.date, area, market, commodities))
                except RuntimeError as error:
                    errors.append(f"{AREAS[area]['label']} / {market['psr_nama']}: {error}")
        except (RuntimeError, json.JSONDecodeError) as error:
            errors.append(f"{AREAS[area]['label']}: {error}")

    if not current_records:
        print("Gagal: tidak ada harga yang berhasil dibaca.", file=sys.stderr)
        return 1

    retail_records = [
        record
        for record in read_csv_records(retail_path)
        if record["date"] == args.date
        and record["area"] in areas
        and record["commodityKey"] in {commodity.key for commodity in commodities}
    ]
    previous_history = read_csv_records(history_path)
    all_current_records = [*current_records, *retail_records]
    merged_history = merge_history(previous_history, all_current_records)
    write_csv_records(history_path, merged_history)

    trends = []
    for area in areas:
        for commodity in commodities:
            trends.append(
                trend_signal(
                    merged_history,
                    args.date,
                    area,
                    commodity,
                    [
                        record
                        for record in current_records
                        if record["area"] == area and record["commodityKey"] == commodity.key
                    ],
                )
            )

    report = {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "date": args.date,
        "areas": areas,
        "source": SOURCE_BASE,
        "retailCoverage": {
            "records": len(retail_records),
            "message": (
                "Harga retail ikut dibandingkan."
                if retail_records
                else "Belum ada harga retail bermerek. Tambahkan data/retail-prices.csv."
            ),
        },
        "records": all_current_records,
        "trends": trends,
        "errors": errors,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_report(args.date, all_current_records, trends, errors, args.transport)
    print(f"\nRiwayat tersimpan: {history_path}")
    print(f"Laporan JSON: {report_path}")
    if not retail_records:
        print(f"Harga toko/koperasi/swalayan belum ada. Tambahkan data ke: {retail_path}")
    if args.telegram:
        try:
            sent_count = send_telegram_notification(
                all_current_records,
                args.date,
                args.telegram_limit,
            )
        except RuntimeError as error:
            print(f"\nGagal mengirim Telegram: {error}", file=sys.stderr)
            return 1
        print(f"Telegram: notifikasi terkirim dalam {sent_count} pesan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())