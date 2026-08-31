#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер расписаний намазов с islamdag.ru («Ислам в Дагестане», ресурс
Муфтията Республики Дагестан). Шафиитский мазхаб.
Страница отдаёт таблицу текущего месяца: Число|Фаджр|Восход|Зухр|Аср|Магриб|Иша.
"""

import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _city(slug, name, lat, lon):
    return {
        "site_slug": slug,
        "slug": f"ru/{slug}",
        "name": name, "country": "RU",
        "lat": lat, "lon": lon,
        "timezone": "Europe/Moscow",
        "madhab": "shafi",   # Дагестан — шафиитский мазхаб
    }


# Крупнейшие города Дагестана со страниц islamdag.ru/vremya-namaza/<slug>
CITIES = [
    _city("mahachkala", "Махачкала", 42.9849, 47.5047),
    _city("kaspiysk",   "Каспийск",  42.8916, 47.6367),
    _city("derbent",    "Дербент",   42.0578, 48.2899),
    _city("hasavyurt",  "Хасавюрт",  43.2465, 46.5901),
    _city("buynaksk",   "Буйнакск",  42.8213, 47.1166),
    _city("izberbash",  "Избербаш",  42.5624, 47.8712),
    _city("kizlyar",    "Кизляр",    43.8484, 46.7231),
    _city("kizilurt",   "Кизилюрт",  43.2044, 46.8729),
    _city("dagogni",    "Дагестанские Огни", 42.1149, 48.1942),
    _city("suhokumsk",  "Южно-Сухокумск",    44.6600, 45.6500),
]

RU_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "NamazZamanBot/1.0 (+https://github.com/Tolik1661/namaz-data)"
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def parse_city(city):
    url = f"https://islamdag.ru/vremya-namaza/{city['site_slug']}"
    html = fetch(url)

    # Город в title — защита от чужой/битой страницы
    title = re.search(r"<title>([^<]+)</title>", html)
    if not title:
        raise ValueError(f"{city['slug']}: нет <title>")
    stem = city["name"].split()[0].lower()[:6]   # «Махачкала» → «махачк» (падежи)
    if stem not in title.group(1).lower():
        raise ValueError(f"{city['slug']}: в title другой город: {title.group(1)!r}")

    # Месяц и год — «сентябрь 2026» в тексте страницы
    m = re.search(r"(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*\s+(\d{4})",
                  html.lower())
    if not m:
        raise ValueError(f"{city['slug']}: не найден месяц/год на странице")
    stem_month = m.group(1)[:2] if m.group(1).startswith("ма") else m.group(1)
    month = next((v for k, v in RU_MONTHS.items() if stem_month.startswith(k) or k.startswith(stem_month)), None)
    year = int(m.group(2))
    if not month:
        raise ValueError(f"{city['slug']}: неизвестный месяц {m.group(1)!r}")

    days = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        tds = [strip_tags(td) for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(tds) < 7:
            continue
        dm = re.match(r"(\d{1,2})$", tds[0])
        if not dm:
            continue
        times = tds[1:7]
        if not all(re.fullmatch(r"\d{1,2}:\d{2}", t) for t in times):
            raise ValueError(f"{city['slug']}: битые времена {tds!r}")
        days.append({
            "date": f"{year:04d}-{month:02d}-{int(dm.group(1)):02d}",
            "fajr": times[0], "sunrise": times[1], "dhuhr": times[2],
            "asr": times[3], "maghrib": times[4], "isha": times[5],
        })

    if len(days) < 28:
        raise ValueError(f"{city['slug']}: мало дней: {len(days)}")
    nums = [int(d["date"][-2:]) for d in days]
    if nums != list(range(1, len(days) + 1)):
        raise ValueError(f"{city['slug']}: дни не по порядку")

    def minutes(t):
        h, mm = t.split(":")
        return int(h) * 60 + int(mm)

    for d in days:
        seq = [minutes(d[k]) for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")]
        if seq != sorted(seq):
            raise ValueError(f"{city['slug']}: немонотонные времена {d}")

    return {
        "city": city["name"], "slug": city["slug"], "country": city["country"],
        "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
        "madhab": city["madhab"],
        "source": "islamdag.ru (Муфтият Республики Дагестан, шафиитский мазхаб)",
        "source_url": url,
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
