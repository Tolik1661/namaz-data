#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер расписаний намазов Узбекистана: namozvaqti.uz — времена по данным
Управления мусульман Узбекистана (ханафитский мазхаб).
Месячная страница: /ru/oylik/<месяц>/<город> (год берём из <title>).
Загружаем текущий и следующий месяцы.
"""

import json
import pathlib
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _city(slug, name, lat, lon):
    return {"site_slug": slug, "slug": f"uz/{slug}", "name": name,
            "country": "UZ", "lat": lat, "lon": lon,
            "timezone": "Asia/Tashkent", "madhab": "hanafi"}


# Главные города Узбекистана (слаги проверены по списку сайта)
CITIES = [
    _city("toshkent",   "Ташкент",    41.2995, 69.2401),
    _city("samarqand",  "Самарканд",  39.6270, 66.9750),
    _city("buxoro",     "Бухара",     39.7747, 64.4286),
    _city("andijon",    "Андижан",    40.7821, 72.3442),
    _city("namangan",   "Наманган",   40.9983, 71.6726),
    _city("fargona",    "Фергана",    40.3864, 71.7864),
    _city("qarshi",     "Карши",      38.8600, 65.7890),
    _city("nukus",      "Нукус",      42.4600, 59.6200),
    _city("urganch",    "Ургенч",     41.5500, 60.6333),
    _city("xiva",       "Хива",       41.3783, 60.3639),
    _city("termiz",     "Термез",     37.2242, 67.2783),
    _city("jizzax",     "Джизак",     40.1158, 67.8422),
    _city("guliston",   "Гулистан",   40.4897, 68.7842),
    _city("navoiy",     "Навои",      40.0844, 65.3792),
    _city("qoqon",      "Коканд",     40.5286, 70.9425),
    _city("margilon",   "Маргилан",   40.4712, 71.7246),
    _city("olmaliq",    "Алмалык",    40.8442, 69.5983),
    _city("angren",     "Ангрен",     41.0167, 70.1436),
    _city("shahrisabz", "Шахрисабз",  39.0578, 66.8342),
    _city("zarafshon",  "Зарафшан",   41.5847, 64.2000),
]

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
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def parse_month(city, month_no):
    url = f"https://namozvaqti.uz/ru/oylik/{month_no}/{city['site_slug']}"
    html = fetch(url)

    title = re.search(r"<title>([^<]+)</title>", html)
    if not title:
        raise ValueError(f"{city['slug']}: нет <title>")
    ym = re.search(r"[А-Яа-я]+-(\d{4})", title.group(1))
    if not ym:
        raise ValueError(f"{city['slug']}: нет года в title: {title.group(1)!r}")
    year = int(ym.group(1))

    days = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        tds = [strip_tags(td) for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(tds) < 7:
            continue
        dm = re.match(r"(\d{1,2})\b", tds[0])
        if not dm:
            continue
        times = tds[1:7]
        if not all(re.fullmatch(r"\d{1,2}:\d{2}", t) for t in times):
            raise ValueError(f"{city['slug']}: битые времена {tds!r}")
        days.append({
            "date": f"{year:04d}-{month_no:02d}-{int(dm.group(1)):02d}",
            "fajr": times[0], "sunrise": times[1], "dhuhr": times[2],
            "asr": times[3], "maghrib": times[4], "isha": times[5],
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

    return year, days


def collect(index, failures):
    now = datetime.now()
    months = [now.month, now.month % 12 + 1]   # текущий + следующий

    for city in CITIES:
        ok_any = False
        for m in months:
            try:
                year, days = parse_month(city, m)
            except Exception as e:                                # noqa: BLE001
                print(f"[ERROR] {city['slug']} м{m}: {e}", file=sys.stderr)
                failures.append(f"{city['slug']}:{m}")
                continue
            out_dir = ROOT / "timetables" / city["slug"]
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{year:04d}-{m:02d}.json").write_text(json.dumps({
                "city": city["name"], "slug": city["slug"], "country": city["country"],
                "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
                "madhab": city["madhab"],
                "source": "namozvaqti.uz (Управление мусульман Узбекистана, ханафитский мазхаб)",
                "source_url": f"https://namozvaqti.uz/ru/oylik/{m}/{city['site_slug']}",
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "year": year, "month": m, "days": days,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            ok_any = True
            time.sleep(0.6)
        if ok_any:
            print(f"[OK] {city['slug']}")
            index.append({
                "slug": city["slug"], "name": city["name"], "country": city["country"],
                "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
                "madhab": city["madhab"],
                "source": "namozvaqti.uz (Управление мусульман Узбекистана)",
            })


if __name__ == "__main__":
    idx, fails = [], []
    collect(idx, fails)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
