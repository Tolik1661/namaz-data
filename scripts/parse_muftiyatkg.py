#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер расписаний Кыргызстана: официальный API ДУМ Кыргызстана
(muftiyat.kg/ru/api/v1/calendar/?lat=&lng=&start=&end=). Ханафитский мазхаб.
Загружаем текущий и следующий месяцы по координатам городов.
"""

import calendar as cal
import json
import pathlib
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _city(slug, name, lat, lon):
    return {"slug": f"kg/{slug}", "name": name, "country": "KG",
            "lat": lat, "lon": lon, "timezone": "Asia/Bishkek", "madhab": "hanafi"}


CITIES = [
    _city("bishkek",     "Бишкек",      42.8746, 74.5698),
    _city("osh",         "Ош",          40.5140, 72.8161),
    _city("jalal-abad",  "Джалал-Абад", 40.9333, 72.9833),
    _city("karakol",     "Каракол",     42.4907, 78.3936),
    _city("tokmok",      "Токмок",      42.8421, 75.3010),
    _city("naryn",       "Нарын",       41.4287, 75.9911),
    _city("talas",       "Талас",       42.5228, 72.2427),
    _city("batken",      "Баткен",      40.0553, 70.8180),
    _city("kara-balta",  "Кара-Балта",  42.8144, 73.8485),
    _city("balykchy",    "Балыкчы",     42.4600, 76.1870),
    _city("cholpon-ata", "Чолпон-Ата",  42.6489, 77.0827),
    _city("kyzyl-kiya",  "Кызыл-Кия",   40.2570, 72.1279),
    _city("uzgen",       "Узген",       40.7697, 73.3009),
]

HEADERS = {"User-Agent": "NamazZamanBot/1.0 (+https://github.com/Tolik1661/namaz-data)"}


def fetch_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception:                                        # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3)


def parse_month(city, year, month):
    last = cal.monthrange(year, month)[1]
    url = (f"https://muftiyat.kg/ru/api/v1/calendar/"
           f"?lat={city['lat']}&lng={city['lon']}"
           f"&start=01-{month:02d}-{year}&end={last:02d}-{month:02d}-{year}")
    data = fetch_json(url)
    days = []
    for p in data.get("prayertimes", []):
        dd, mm, yy = p["date"].split("-")
        days.append({
            "date": f"{yy}-{mm}-{dd}",
            "fajr": p["fajr"], "sunrise": p["sunrise"], "dhuhr": p["dhuhr"],
            "asr": p["asr"], "maghrib": p["maghrib"], "isha": p["isha"],
        })

    if len(days) < 28:
        raise ValueError(f"{city['slug']}: мало дней: {len(days)}")

    def minutes(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    for d in days:
        seq = [minutes(d[k]) for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")]
        if seq != sorted(seq):
            raise ValueError(f"{city['slug']}: немонотонные времена {d}")
    return days


def collect(index, failures):
    now = datetime.now()
    months = [(now.year, now.month)]
    ny, nm = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    months.append((ny, nm))

    for city in CITIES:
        ok_any = False
        for year, month in months:
            try:
                days = parse_month(city, year, month)
            except Exception as e:                                # noqa: BLE001
                print(f"[ERROR] {city['slug']} {year}-{month:02d}: {e}", file=sys.stderr)
                failures.append(f"{city['slug']}:{month}")
                continue
            out_dir = ROOT / "timetables" / city["slug"]
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{year:04d}-{month:02d}.json").write_text(json.dumps({
                "city": city["name"], "slug": city["slug"], "country": city["country"],
                "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
                "madhab": city["madhab"],
                "source": "muftiyat.kg (ДУМ Кыргызстана, официальный API, ханафитский мазхаб)",
                "source_url": "https://muftiyat.kg/ru/calendar/",
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "year": year, "month": month, "days": days,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            ok_any = True
            time.sleep(0.6)
        if ok_any:
            print(f"[OK] {city['slug']}")
            index.append({
                "slug": city["slug"], "name": city["name"], "country": city["country"],
                "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
                "madhab": city["madhab"],
                "source": "muftiyat.kg (ДУМ Кыргызстана)",
            })


if __name__ == "__main__":
    idx, fails = [], []
    collect(idx, fails)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
