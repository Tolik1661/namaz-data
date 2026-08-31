#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер расписаний намазов Малайзии: api.waktusolat.app — официальные данные
JAKIM (Jabatan Kemajuan Islam Malaysia, e-Solat). Шафиитский мазхаб.
API отдаёт весь текущий месяц unix-таймстампами; конвертируем в HH:mm
малайзийского времени (вся страна UTC+8).
"""

import json
import pathlib
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
MYT = timezone(timedelta(hours=8))   # Malaysia Time, UTC+8


def _city(zone, slug, name, lat, lon):
    return {
        "zone": zone, "slug": f"my/{slug}", "name": name,
        "country": "MY", "lat": lat, "lon": lon,
        "timezone": "Asia/Kuala_Lumpur", "madhab": "shafi",
    }


# Зоны JAKIM для крупных городов (коды проверены по /zones)
CITIES = [
    _city("WLY01", "kuala-lumpur", "Куала-Лумпур", 3.1390, 101.6869),
    _city("SGR01", "shah-alam",    "Шах-Алам",     3.0733, 101.5185),
    _city("JHR02", "johor-bahru",  "Джохор-Бару",  1.4927, 103.7414),
    _city("PNG01", "george-town",  "Джорджтаун (Пенанг)", 5.4141, 100.3288),
    _city("PRK02", "ipoh",         "Ипох",         4.5975, 101.0901),
    _city("KTN01", "kota-bharu",   "Кота-Бару",    6.1254, 102.2381),
    _city("SWK08", "kuching",      "Кучинг",       1.5533, 110.3592),
    _city("SBH07", "kota-kinabalu","Кота-Кинабалу", 5.9804, 116.0735),
]

HEADERS = {"User-Agent": "NamazZamanBot/1.0 (+https://github.com/Tolik1661/namaz-data)"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def hhmm(ts):
    return datetime.fromtimestamp(ts, MYT).strftime("%H:%M")


def parse_city(city):
    data = fetch_json(f"https://api.waktusolat.app/v2/solat/{city['zone']}")
    year, month = int(data["year"]), int(data["month_number"])
    if data.get("zone") != city["zone"]:
        raise ValueError(f"{city['slug']}: ответ для другой зоны {data.get('zone')!r}")

    days = []
    for p in data["prayers"]:
        days.append({
            "date": f"{year:04d}-{month:02d}-{int(p['day']):02d}",
            "fajr": hhmm(p["fajr"]), "sunrise": hhmm(p["syuruk"]),
            "dhuhr": hhmm(p["dhuhr"]), "asr": hhmm(p["asr"]),
            "maghrib": hhmm(p["maghrib"]), "isha": hhmm(p["isha"]),
        })

    if len(days) < 28:
        raise ValueError(f"{city['slug']}: мало дней: {len(days)}")
    nums = [int(d["date"][-2:]) for d in days]
    if nums != list(range(1, len(days) + 1)):
        raise ValueError(f"{city['slug']}: дни не по порядку")

    def minutes(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    for d in days:
        seq = [minutes(d[k]) for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")]
        if seq != sorted(seq):
            raise ValueError(f"{city['slug']}: немонотонные времена {d}")

    return {
        "city": city["name"], "slug": city["slug"], "country": city["country"],
        "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
        "madhab": city["madhab"],
        "source": "JAKIM e-Solat (api.waktusolat.app, шафиитский мазхаб)",
        "source_url": f"https://api.waktusolat.app/v2/solat/{city['zone']}",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "year": year, "month": month, "days": days,
    }


def collect(index, failures):
    for city in CITIES:
        try:
            data = parse_city(city)
        except Exception as e:                                    # noqa: BLE001
            print(f"[ERROR] {city['slug']}: {e}", file=sys.stderr)
            failures.append(city["slug"])
            continue
        out_dir = ROOT / "timetables" / data["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{data['year']:04d}-{data['month']:02d}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] {data['slug']} — {len(data['days'])} дней")
        index.append({
            "slug": data["slug"], "name": data["city"], "country": data["country"],
            "lat": data["lat"], "lon": data["lon"], "timezone": data["timezone"],
            "madhab": data["madhab"], "source": data["source"],
        })


if __name__ == "__main__":
    idx, fails = [], []
    collect(idx, fails)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
