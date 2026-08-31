#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер расписаний намазов с umma.ru (официальные таблицы по ханафитскому мазхабу).
Страница отдаёт ВЕСЬ текущий месяц — запускаясь ежедневно (GitHub Actions),
парсер сохраняет/обновляет файл timetables/<slug>/<YYYY-MM>.json.

Схема JSON совместима с prayer_schedule.json приложения Namaz Zaman:
поля дня — fajr, sunrise, dhuhr, asr, maghrib, isha (строки "H:MM").
"""

import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Города umma.ru: slug в URL → наши метаданные.
# lat/lon нужны приложению для сопоставления выбранного города с таблицей.
def _city(umma_slug, country, name, lat, lon, tz):
    return {
        "umma_slug": umma_slug,
        "slug": f"{country.lower()}/{umma_slug}",
        "name": name, "country": country,
        "lat": lat, "lon": lon, "timezone": tz,
        "madhab": "hanafi",   # umma.ru публикует по ханафитскому мазхабу
    }

# Рабочие города umma.ru (проверены по title; часть слагов из sitemap
# мертва — отдаёт Москву, защита в parse_city это ловит).
# ВАЖНО: неизвестный slug сайт молча отдаёт как Москву — поэтому парсер
# сверяет имя города в <title> (см. parse_city).
CITIES = [
    # Россия
    _city("moscow",          "RU", "Москва",          55.7558, 37.6173, "Europe/Moscow"),
    _city("kazan",           "RU", "Казань",          55.7963, 49.1088, "Europe/Moscow"),
    # Казахстан
    _city("almaty",          "KZ", "Алматы",          43.2380, 76.9452, "Asia/Almaty"),
    _city("astana",          "KZ", "Астана",          51.1605, 71.4704, "Asia/Almaty"),
    _city("shymkent",        "KZ", "Шымкент",         42.3417, 69.5901, "Asia/Almaty"),
    _city("karaganda",       "KZ", "Караганда",       49.8047, 73.1094, "Asia/Almaty"),
    _city("aktau",           "KZ", "Актау",           43.6410, 51.1985, "Asia/Aqtau"),
    _city("atyrau",          "KZ", "Атырау",          47.1164, 51.8830, "Asia/Atyrau"),
    _city("uralsk",          "KZ", "Уральск",         51.2333, 51.3667, "Asia/Oral"),
    _city("kostanay",        "KZ", "Костанай",        53.2198, 63.6354, "Asia/Qostanay"),
]

RU_MONTHS = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "NamazZamanBot/1.0 (+https://github.com/Tolik1661/namaz-data)"
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def parse_city(city: dict) -> dict:
    url = f"https://umma.ru/raspisanie-namaza/{city['umma_slug']}"
    html = fetch(url)

    # Месяц и год из <title>: «Время намаза на Август 2026 для Москва»
    title = re.search(r"<title>([^<]+)</title>", html)
    if not title:
        raise ValueError(f"{city['slug']}: нет <title>")
    m = re.search(r"на\s+([А-Яа-яЁё]+)\s+(\d{4})", title.group(1))
    if not m:
        raise ValueError(f"{city['slug']}: не распознан месяц в title: {title.group(1)!r}")
    month = RU_MONTHS.get(m.group(1).lower())
    year = int(m.group(2))
    if not month:
        raise ValueError(f"{city['slug']}: неизвестный месяц {m.group(1)!r}")

    # Защита от молчаливого фолбэка: umma.ru отдаёт МОСКВУ для неизвестных
    # слагов. Убеждаемся, что в title именно наш город.
    if city["name"].split()[0].lower() not in title.group(1).lower():
        raise ValueError(
            f"{city['slug']}: в title другой город: {title.group(1)!r} — "
            f"вероятно, slug не существует и сайт вернул Москву")

    days = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        tds = [strip_tags(td) for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        # Ряд дня: [«1 Сб», фаджр, шурук, зухр, аср, магриб, иша, хиджра]
        if len(tds) < 7:
            continue
        day_match = re.match(r"(\d{1,2})\b", tds[0])
        if not day_match:
            continue  # строка заголовка
        times = tds[1:7]
        if not all(re.fullmatch(r"\d{1,2}:\d{2}", t) for t in times):
            raise ValueError(f"{city['slug']}: битые времена в ряду {tds!r}")
        day = int(day_match.group(1))
        days.append({
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "fajr": times[0], "sunrise": times[1], "dhuhr": times[2],
            "asr": times[3], "maghrib": times[4], "isha": times[5],
        })

    # Валидация: полный месяц, дни подряд, времена в порядке возрастания
    if len(days) < 28:
        raise ValueError(f"{city['slug']}: слишком мало дней: {len(days)}")
    day_nums = [int(d["date"][-2:]) for d in days]
    if day_nums != list(range(1, len(days) + 1)):
        raise ValueError(f"{city['slug']}: дни не по порядку: {day_nums}")

    def minutes(t):
        h, mm = t.split(":")
        return int(h) * 60 + int(mm)

    for d in days:
        seq = [minutes(d[k]) for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")]
        if seq != sorted(seq):
            raise ValueError(f"{city['slug']}: немонотонные времена {d}")

    return {
        "city": city["name"],
        "slug": city["slug"],
        "country": city["country"],
        "lat": city["lat"],
        "lon": city["lon"],
        "timezone": city["timezone"],
        "madhab": city["madhab"],
        "source": "umma.ru (официальная таблица, ханафитский мазхаб)",
        "source_url": url,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "year": year,
        "month": month,
        "days": days,
    }


def main() -> int:
    index = []
    failures = []

    for city in CITIES:
        try:
            data = parse_city(city)
        except Exception as e:                                    # noqa: BLE001
            print(f"[ERROR] {city['slug']}: {e}", file=sys.stderr)
            failures.append(city["slug"])
            continue

        out_dir = ROOT / "timetables" / data["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{data['year']:04d}-{data['month']:02d}.json"
        out_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] {out_file.relative_to(ROOT)} — {len(data['days'])} дней")

        index.append({
            "slug": data["slug"], "name": data["city"], "country": data["country"],
            "lat": data["lat"], "lon": data["lon"], "timezone": data["timezone"],
            "madhab": data["madhab"], "source": data["source"],
        })

    if index:
        # index.json — список городов с официальными таблицами
        # (приложение сопоставляет выбранный город по координатам)
        (ROOT / "index.json").write_text(
            json.dumps({
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "cities": index,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] index.json — городов: {len(index)}")

    # Частичный сбой не валит весь прогон, но помечает его failed,
    # чтобы GitHub прислал алерт
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
