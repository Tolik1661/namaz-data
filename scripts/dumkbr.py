#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Духовное управление мусульман Кабардино-Балкарской Республики (ДУМ КБР):
годовой «График намазов по КБР» — одна таблица на всю республику.

Таблица выходит раз в год (обычно в декабре) PDF-файлом на cloud.mail.ru,
ссылка — на главной kbrdum.ru. Проверенные таблицы лежат снимками в
scripts/data/dumkbr/<год>.json (2026 сверен с PDF: 365 дней). Если на раннере
есть pypdf, скрипт сам скачивает PDF и подхватывает таблицу нового года.

Формулой таблица не воспроизводится (Фаджр = восход − 90…109 мин, Иша =
Магриб + 100…110 мин по сезонам), поэтому резервного расчёта нет: где таблицы
нет, приложение считает само. Мазхаб таблицы — ханафитский (решение владельца).
"""

import calendar as cal
import json
import pathlib
import re
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from local_authorities import http, horizon, validate_day      # noqa: E402
from official_feeds import entry, write_horizon                # noqa: E402

DATA = pathlib.Path(__file__).resolve().parent / "data" / "dumkbr"
KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
OFFICIAL = ("kbrdum.ru (Духовное управление мусульман КБР — официальная таблица по республике)",
            "https://kbrdum.ru")

# Таблица «по КБР» действует для всей республики
CITIES = [
    {"slug": "ru/nalchik", "name": "Нальчик", "lat": 43.4846, "lon": 43.6071},
    {"slug": "ru/baksan", "name": "Баксан", "lat": 43.6819, "lon": 43.5345},
    {"slug": "ru/prokhladny", "name": "Прохладный", "lat": 43.7575, "lon": 44.0297},
    {"slug": "ru/tyrnyauz", "name": "Тырныауз", "lat": 43.3981, "lon": 42.9214},
    {"slug": "ru/nartkala", "name": "Нарткала", "lat": 43.5578, "lon": 43.8575},
    {"slug": "ru/terek", "name": "Терек", "lat": 43.4839, "lon": 44.1402},
    {"slug": "ru/mayskiy", "name": "Майский", "lat": 43.6281, "lon": 44.0517},
    {"slug": "ru/chegem", "name": "Чегем", "lat": 43.5667, "lon": 43.5833},
    {"slug": "ru/zalukokoazhe", "name": "Залукокоаже", "lat": 43.9000, "lon": 43.2167},
    {"slug": "ru/kashkhatau", "name": "Кашхатау", "lat": 43.3181, "lon": 43.6069},
]
for _c in CITIES:
    _c.update(country="RU", timezone="Europe/Moscow")

MONTHS = ["ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ", "АВГУСТ",
          "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"]


def hhmm(t):
    h, m = t.replace(".", ":").split(":")
    return f"{int(h):02d}:{m}"


def check_year(year, table):
    n = 366 if cal.isleap(year) else 365
    if len(table) != n:
        raise ValueError(f"ДУМ КБР {year}: {len(table)} дней вместо {n}")
    for ds, times in table.items():
        validate_day(f"ДУМ КБР {ds}", dict(zip(KEYS, times), date=ds))


def parse_pdf(data):
    """Текст PDF: страница на месяц, строки «день  Дн  HH:MM ×6»; кириллица как /uniXXXX."""
    import io
    import pypdf                                                      # есть не на всех раннерах
    year, table = None, {}
    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        text = re.sub(r"/uni([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), page.extract_text())
        head = re.search(r"НА\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", text.upper())
        if not head:
            continue
        month, year = MONTHS.index(head.group(1)) + 1, int(head.group(2))
        t = r"(\d{1,2}[:.]\d{2})"
        for row in re.findall(r"(?m)^\s*(\d{1,2})\s+\S{2}\s+" + r"\s+".join([t] * 6), text):
            table[f"{year:04d}-{month:02d}-{int(row[0]):02d}"] = [hhmm(x) for x in row[1:]]
    check_year(year, table)
    return year, table


def fetch_online():
    """Все PDF «график намазов» по ссылкам cloud.mail.ru с главной kbrdum.ru."""
    page = http("https://kbrdum.ru/").decode("utf-8", "replace")
    found = {}
    for link in sorted(set(re.findall(r"https://cloud\.mail\.ru/public/[\w/]+", page))):
        public = link.split("/public/", 1)[1]
        html = http(link).decode("utf-8", "replace")
        name = re.search(r'"name":"(\d{4})kbr\.pdf"', html)
        server = re.search(r'weblink_get[^}]*?"url":\s*"([^"]+)"', html)
        if not (name and server):
            continue
        data = http(f"{server.group(1)}/{public}", headers={"Referer": link})
        year, table = parse_pdf(data)
        found[year] = table
    return found


def tables(today):
    known = {int(f.stem): json.loads(f.read_text(encoding="utf-8")) for f in DATA.glob("*.json")}
    for year, table in known.items():
        check_year(year, table)
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("[WARN] ДУМ КБР: pypdf не установлен — используются только снимки таблиц", file=sys.stderr)
        return known
    try:
        for year, table in fetch_online().items():
            if year not in known:
                print(f"[OK] ДУМ КБР: новая таблица на {year} год — сохраните снимок scripts/data/dumkbr/{year}.json")
                (DATA / f"{year}.json").write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")),
                                                   encoding="utf-8")
                known[year] = table
            elif table != known[year]:
                print(f"[WARN] ДУМ КБР: таблица {year} на сайте изменилась — снимок обновлён", file=sys.stderr)
                (DATA / f"{year}.json").write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")),
                                                   encoding="utf-8")
                known[year] = table
    except Exception as e:                                            # noqa: BLE001
        print(f"[WARN] ДУМ КБР: PDF с kbrdum.ru не получен, используются снимки: {e}", file=sys.stderr)
    return known


def collect(index, failures, today=None):
    today = today or datetime.now(timezone.utc).date()
    known = tables(today)
    if today.year not in known:
        print(f"[ERROR] ДУМ КБР: нет таблицы на {today.year} год", file=sys.stderr)
        failures.append("ru/nalchik")
    if today.month == 12 and today.year + 1 not in known:
        print(f"[WARN] ДУМ КБР: таблица на {today.year + 1} год ещё не опубликована", file=sys.stderr)
    days = {}
    for table in known.values():
        for ds, times in table.items():
            days[ds] = {"date": ds, **dict(zip(KEYS, times))}
    for city in CITIES:
        # Таблица «по КБР» — как есть для всех городов республики (решение владельца)
        written = write_horizon(city, today, days, *OFFICIAL, None, None, "hanafi")
        print(f"[OK] {city['slug']}: {' '.join(written) or 'нет данных'}")
        current = f"{today.year}-{today.month:02d}"
        if any(w.startswith(current) for w in written):
            index.append(entry(city, "hanafi", OFFICIAL[0], "official"))


if __name__ == "__main__":
    idx, fails = [], []
    collect(idx, fails)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
