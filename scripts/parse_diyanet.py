#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер расписаний Diyanet (Управление по делам религии Турции):
namazvakitleri.diyanet.gov.tr — Турция + города Европы (диаспора).
Аср у Диянета — по джумхуру (тень=1, как в шафиитском мазхабе).

Страница отдаёт таблицу «30 дней от сегодня» (может пересекать границу
месяца) — поэтому дни МЕРДЖАТСЯ в существующие файлы месяцев.
"""

import json
import pathlib
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _city(ilce, slug, name, country, lat, lon, tz):
    return {"ilce": ilce, "slug": slug, "name": name, "country": country,
            "lat": lat, "lon": lon, "timezone": tz, "madhab": "shafi"}


CITIES = [
    # Турция
    _city(9541,  "tr/istanbul",  "Стамбул",   "TR", 41.0082, 28.9784, "Europe/Istanbul"),
    _city(9206,  "tr/ankara",    "Анкара",    "TR", 39.9334, 32.8597, "Europe/Istanbul"),
    _city(9560,  "tr/izmir",     "Измир",     "TR", 38.4237, 27.1428, "Europe/Istanbul"),
    _city(9335,  "tr/bursa",     "Бурса",     "TR", 40.1885, 29.0610, "Europe/Istanbul"),
    _city(9225,  "tr/antalya",   "Анталья",   "TR", 36.8969, 30.7133, "Europe/Istanbul"),
    _city(9676,  "tr/konya",     "Конья",     "TR", 37.8746, 32.4932, "Europe/Istanbul"),
    # Германия
    _city(11002, "de/berlin",    "Берлин",    "DE", 52.5200, 13.4050, "Europe/Berlin"),
    _city(11012, "de/hamburg",   "Гамбург",   "DE", 53.5511,  9.9937, "Europe/Berlin"),
    _city(11022, "de/munchen",   "Мюнхен",    "DE", 48.1351, 11.5820, "Europe/Berlin"),
    _city(11019, "de/koln",      "Кёльн",     "DE", 50.9375,  6.9603, "Europe/Berlin"),
    _city(11010, "de/frankfurt", "Франкфурт", "DE", 50.1109,  8.6821, "Europe/Berlin"),
    # Франция
    _city(13382, "fr/paris",     "Париж",     "FR", 48.8566,  2.3522, "Europe/Paris"),
    _city(13381, "fr/lyon",      "Лион",      "FR", 45.7640,  4.8357, "Europe/Paris"),
    # Нидерланды
    _city(13976, "nl/amsterdam", "Амстердам", "NL", 52.3676,  4.9041, "Europe/Amsterdam"),
    _city(13980, "nl/rotterdam", "Роттердам", "NL", 51.9244,  4.4777, "Europe/Amsterdam"),
    # Австрия
    _city(11618, "at/vienna",    "Вена",      "AT", 48.2082, 16.3738, "Europe/Vienna"),
    # Великобритания
    _city(14096, "gb/london",     "Лондон",     "GB", 51.5074, -0.1278, "Europe/London"),
    _city(14105, "gb/birmingham", "Бирмингем",  "GB", 52.4862, -1.8904, "Europe/London"),
    _city(14098, "gb/manchester", "Манчестер",  "GB", 53.4808, -2.2426, "Europe/London"),
]

TR_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

HEADERS = {"User-Agent": "Mozilla/5.0 NamazZamanBot/1.0 (+https://github.com/Tolik1661/namaz-data)"}


def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:                                        # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3)


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&#252;", "ü").replace("&#220;", "Ü").replace("&#231;", "ç") \
         .replace("&#199;", "Ç").replace("&#246;", "ö").replace("&#214;", "Ö") \
         .replace("&#305;", "ı").replace("&#304;", "İ").replace("&#351;", "ş") \
         .replace("&#350;", "Ş").replace("&#287;", "ğ").replace("&#286;", "Ğ")
    return re.sub(r"\s+", " ", s).strip()


def parse_city(city):
    url = f"https://namazvakitleri.diyanet.gov.tr/tr-TR/{city['ilce']}/vakitler"
    html = fetch(url)

    # Дни из всех таблиц: [«01 Eylül 2026 Salı», хиджра, imsak, güneş, öğle, ikindi, akşam, yatsı]
    days = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        tds = [strip_tags(td) for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(tds) < 8:
            continue
        dm = re.match(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})", tds[0])
        if not dm:
            continue
        month = TR_MONTHS.get(dm.group(2).lower())
        if not month:
            continue
        times = tds[2:8]
        if not all(re.fullmatch(r"\d{1,2}:\d{2}", t) for t in times):
            continue
        date = f"{int(dm.group(3)):04d}-{month:02d}-{int(dm.group(1)):02d}"
        days[date] = {
            "date": date,
            "fajr": times[0], "sunrise": times[1], "dhuhr": times[2],
            "asr": times[3], "maghrib": times[4], "isha": times[5],
        }

    if len(days) < 25:
        raise ValueError(f"{city['slug']}: слишком мало дней: {len(days)}")

    def minutes(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    for d in days.values():
        seq = [minutes(d[k]) for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")]
        if seq != sorted(seq):
            raise ValueError(f"{city['slug']}: немонотонные времена {d}")

    return days


def merge_months(city, days):
    """Слить дни скользящего окна в файлы месяцев (существующие дни обновляются)"""
    by_month = {}
    for date, d in days.items():
        by_month.setdefault(date[:7], {})[date] = d

    written = []
    for ym, month_days in by_month.items():
        out_dir = ROOT / "timetables" / city["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{ym}.json"

        existing = {}
        if out_file.exists():
            try:
                for d in json.loads(out_file.read_text(encoding="utf-8"))["days"]:
                    existing[d["date"]] = d
            except Exception:                                    # noqa: BLE001
                pass
        existing.update(month_days)
        merged = sorted(existing.values(), key=lambda d: d["date"])

        out_file.write_text(json.dumps({
            "city": city["name"], "slug": city["slug"], "country": city["country"],
            "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
            "madhab": city["madhab"],
            "source": "Diyanet (namazvakitleri.diyanet.gov.tr)",
            "source_url": f"https://namazvakitleri.diyanet.gov.tr/tr-TR/{city['ilce']}/vakitler",
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "year": int(ym[:4]), "month": int(ym[5:7]),
            "days": merged,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(f"{ym}({len(merged)}д)")
    return written


def collect(index, failures):
    for city in CITIES:
        try:
            days = parse_city(city)
            written = merge_months(city, days)
        except Exception as e:                                    # noqa: BLE001
            print(f"[ERROR] {city['slug']}: {e}", file=sys.stderr)
            failures.append(city["slug"])
            continue
        print(f"[OK] {city['slug']} — {', '.join(written)}")
        index.append({
            "slug": city["slug"], "name": city["name"], "country": city["country"],
            "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
            "madhab": city["madhab"],
            "source": "Diyanet (namazvakitleri.diyanet.gov.tr)",
        })
        time.sleep(1.5)   # вежливая пауза между городами


if __name__ == "__main__":
    idx, fails = [], []
    collect(idx, fails)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
