#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Официальные потоки духовных управлений, вторая очередь:

  KZ — Духовное управление мусульман Казахстана (ДУМК): api.muftyat.kz,
       год одним запросом по координатам; 89 городов («қаласы»).
       Раньше 8 городов брались с umma.ru — данные совпадают минута в минуту.
  UZ — Управление мусульман Узбекистана, Фатво маркази: api.fatvo.uz, по дням.
       Раньше — namozvaqti.uz (частный сайт): Магриб там на 3 мин раньше официального.
  RU — Духовное управление мусульман Республики Татарстан: CSV-таблица Казани.
       Раньше — umma.ru (копия той же таблицы).

Каждый поток имеет резервный расчёт по методике ведомства (calc_engine): если
источник недоступен, недостающие месяцы дописываются расчётом, уже сохранённые
официальные месяцы не затираются. Запросы к годовым API разнесены по дням недели.
"""

import calendar as cal
import json
import pathlib
import re
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from calc_engine import Profile, month_schedule            # noqa: E402
from local_authorities import (due_today, http, horizon,  # noqa: E402
                               stored_month, validate_day, write_month)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = pathlib.Path(__file__).resolve().parent / "data"
CALC_URL = "https://github.com/Tolik1661/namaz-data/blob/main/scripts/official_feeds.py"

# ── Транслитерация для slug новых городов ──────────────────────────────────

_TR = {
    "а": "a", "ә": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "қ": "k", "л": "l", "м": "m", "н": "n",
    "ң": "n", "о": "o", "ө": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ұ": "u",
    "ү": "u", "ф": "f", "х": "kh", "һ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "і": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text):
    s = "".join(_TR.get(ch, ch) for ch in text.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "city"


def official_month_present(city, y, m, label):
    have = stored_month(city, y, m)
    return bool(have) and have.get("source") == label and len(have.get("days", [])) == cal.monthrange(y, m)[1]


def write_horizon(city, today, official_days, official_label, official_url, calc_profile, calc_label, madhab):
    """Пишет месяцы горизонта: официальные, где месяц полон; иначе — сохранённый
    официальный, если он есть; иначе — резервный расчёт."""
    written = []
    for y, m in horizon(today):
        n = cal.monthrange(y, m)[1]
        month = [official_days.get(f"{y:04d}-{m:02d}-{d:02d}") for d in range(1, n + 1)]
        if all(month):
            write_month(city, y, m, month, official_label, official_url, madhab)
            written.append(f"{y}-{m:02d}✓")
        elif official_month_present(city, y, m, official_label):
            written.append(f"{y}-{m:02d}=")
        elif calc_profile is not None:
            days = month_schedule(calc_profile, y, m, city["lat"], city["lon"], city["timezone"])
            for d in days:
                validate_day(city["slug"], d)
            write_month(city, y, m, days, calc_label, CALC_URL, madhab)
            written.append(f"{y}-{m:02d}")
    return written


def entry(city, madhab, source, kind):
    return {"slug": city["slug"], "name": city["name"], "country": city["country"],
            "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
            "madhab": madhab, "source": source, "kind": kind}


# ── Казахстан: ДУМК ────────────────────────────────────────────────────────

KZ_OFFICIAL = ("muftyat.kz (Духовное управление мусульман Казахстана — официальная таблица)",
               "https://www.muftyat.kz/ru/namaz_times/")
KZ_CALC = "muftyat.kz (расчёт по методике Духовного управления мусульман Казахстана)"
# Прежние slug (umma.ru) — их знают вышедшие версии приложения
KZ_KEEP = {"kz/almaty": (43.2380, 76.9452, "Asia/Almaty"), "kz/astana": (51.1605, 71.4704, "Asia/Almaty"),
           "kz/shymkent": (42.3417, 69.5901, "Asia/Almaty"), "kz/karaganda": (49.8047, 73.1094, "Asia/Almaty"),
           "kz/aktau": (43.6410, 51.1985, "Asia/Aqtau"), "kz/atyrau": (47.1164, 51.8830, "Asia/Atyrau"),
           "kz/uralsk": (51.2333, 51.3667, "Asia/Oral"), "kz/kostanay": (53.2198, 63.6354, "Asia/Qostanay")}


def kz_profile(lat):
    # Методика из JS muftyat.kz: 15°/15°, ханафитский Аср, AngleBased; ихтият зависит от широты
    extra = 3 if lat < 48 else 5
    return Profile("ДУМК", fajr_angle=15, isha_angle=15, asr_factor=2, high_lat="angle", madhab="hanafi",
                   adjust={"sunrise": -extra, "dhuhr": extra, "asr": extra, "maghrib": extra})


def kz_cities():
    raw = json.loads((DATA / "kz_cities_muftyat.json").read_text(encoding="utf-8"))["results"]
    # Прежний slug получает только ближайший к нему город ДУМК (рядом бывают города-спутники:
    # Тобыл в 5 км от Костаная)
    def dist(c, k):
        return (float(c["lat"]) - k[0]) ** 2 + (float(c["lng"]) - k[1]) ** 2
    keep_for = {}
    for keep, k in KZ_KEEP.items():
        best = min(raw, key=lambda c: dist(c, k))
        if dist(best, k) < 0.15 ** 2:
            keep_for[best["id"]] = keep
    cities, used = [], set()
    for c in raw:
        lat, lon = float(c["lat"]), float(c["lng"])
        name = c["title"].replace(" қаласы", "").strip()
        slug, tz = None, "Asia/Almaty"
        if c["id"] in keep_for:
            slug = keep_for[c["id"]]
            klat, klon, tz = KZ_KEEP[slug]
            lat, lon = klat, klon            # прежние координаты — сопоставление в приложении не меняется
        if slug is None:
            slug = f"kz/{slugify(name)}"
        while slug in used:
            slug += "-2"
        used.add(slug)
        cities.append({"slug": slug, "name": name, "country": "KZ", "lat": lat, "lon": lon, "timezone": tz,
                       "api_lat": c["lat"], "api_lng": c["lng"]})
    return cities


def fetch_kz_year(city, year):
    data = json.loads(http(f"https://api.muftyat.kz/prayer-times/{year}/{city['api_lat']}/{city['api_lng']}"))
    out = {}
    for r in data.get("result", []):
        ds = r["Date"][:10]
        d = {"date": ds, **{k: r[k][:5].zfill(5) for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")}}
        validate_day(city["slug"], d)
        out[ds] = d
    if out and len(out) < 360:
        raise ValueError(f"{city['slug']}: ДУМК вернул {len(out)} дней за {year}")
    return out


def collect_kz(index, failures, today):
    for city in kz_cities():
        official = {}
        months = list(horizon(today))
        need = not all(official_month_present(city, y, m, KZ_OFFICIAL[0]) for y, m in months[:2])
        if need or due_today(city["slug"], today):
            try:
                for y in sorted({y for y, _ in months}):
                    official.update(fetch_kz_year(city, y))
                    time.sleep(0.3)
            except Exception as e:                                    # noqa: BLE001
                # Ошибка — только если город раньше получал официальные данные; города, для которых
                # сервер ДУМК никогда не отвечал (HTTP 500 на их координатах), идут на резервном расчёте
                if need and not any(official_month_present(city, y, m, KZ_OFFICIAL[0]) for y, m in months):
                    print(f"[WARN] {city['slug']}: ДУМК недоступен, резервный расчёт: {e}", file=sys.stderr)
                else:
                    print(f"[ERROR] {city['slug']}: ДУМК: {e}", file=sys.stderr)
                    failures.append(city["slug"])
        written = write_horizon(city, today, official, *KZ_OFFICIAL, kz_profile(city["lat"]), KZ_CALC, "hanafi")
        kind = "official" if written and written[0].endswith(("✓", "=")) else "calculated"
        print(f"[OK] {city['slug']}: {' '.join(written)}")
        index.append(entry(city, "hanafi", KZ_OFFICIAL[0] if kind == "official" else KZ_CALC, kind))


# ── Узбекистан: УМУ, Фатво маркази ─────────────────────────────────────────

UZ_OFFICIAL = ("fatvo.uz (Управление мусульман Узбекистана — официальная таблица)", "https://fatvo.uz")
UZ_CALC = "fatvo.uz (расчёт по методике Управления мусульман Узбекистана)"
UZ_PROFILE = Profile("УМУ", fajr_angle=15.5, isha_angle=15.5, maghrib_minutes=4, asr_factor=2, madhab="hanafi")
UZ_MONTHS_AHEAD = 2           # текущий + следующий (API отдаёт по дню)
UZ_REQUESTS_PER_RUN = 600     # после ~1000 запросов подряд API отвечает 429 — остальное догрузим завтра


def uz_cities():
    import parse_namozvaqti                  # те же slug и координаты
    return [{k: c[k] for k in ("slug", "name", "country", "lat", "lon", "timezone")} for c in parse_namozvaqti.CITIES]


def fetch_uz_day(city, day):
    import urllib.error
    url = (f"https://api.fatvo.uz/v1/prayer-times?lat={city['lat']}&lon={city['lon']}"
           f"&date={day.day:02d}-{day.month:02d}-{day.year}&tz_offset=5&lang=uz")
    for attempt in range(3):
        try:
            r = json.loads(http(url, tries=1))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(30 * (attempt + 1))      # лимит запросов — ждём и повторяем
    if r.get("date") != f"{day.day:02d}-{day.month:02d}-{day.year}":
        raise ValueError(f"{city['slug']}: запрошен {day}, пришёл {r.get('date')}")
    d = {"date": day.isoformat(), **{k: r[k] for k in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")}}
    validate_day(city["slug"], d)
    return d


def collect_uz(index, failures, today):
    budget = UZ_REQUESTS_PER_RUN
    for city in uz_cities():
        official, broken = {}, False
        for y, m in list(horizon(today))[:UZ_MONTHS_AHEAD]:
            have = stored_month(city, y, m)
            have_days = ({d["date"]: d for d in have["days"]}
                         if have and have.get("source") == UZ_OFFICIAL[0] else {})
            for dd in range(1, cal.monthrange(y, m)[1] + 1):
                ds = f"{y:04d}-{m:02d}-{dd:02d}"
                if ds in have_days:
                    official[ds] = have_days[ds]
                    continue
                if broken or budget <= 0:
                    continue
                try:
                    budget -= 1
                    official[ds] = fetch_uz_day(city, date(y, m, dd))
                    time.sleep(0.25)
                except Exception as e:                                # noqa: BLE001
                    if getattr(e, "code", None) == 429:
                        # Лимит запросов УМУ: ожидаемо, недостающие дни догрузятся в следующих прогонах
                        print(f"[WARN] {city['slug']} {ds}: УМУ ограничил запросы (429), догрузим позже", file=sys.stderr)
                        budget = 0
                    else:
                        print(f"[ERROR] {city['slug']} {ds}: УМУ: {e}", file=sys.stderr)
                        failures.append(city["slug"])
                    broken = True
        written = write_horizon(city, today, official, *UZ_OFFICIAL, UZ_PROFILE, UZ_CALC, "hanafi")
        kind = "official" if written and written[0].endswith(("✓", "=")) else "calculated"
        print(f"[OK] {city['slug']}: {' '.join(written)}")
        index.append(entry(city, "hanafi", UZ_OFFICIAL[0] if kind == "official" else UZ_CALC, kind))


# ── Татарстан: ДУМ РТ ─────────────────────────────────────────────────────

RT_OFFICIAL = ("dumrt.ru (Духовное управление мусульман Республики Татарстан — официальная таблица)",
               "https://dumrt.ru/help-info/prayertime/")
RT_CITIES = [
    {"slug": "ru/kazan", "name": "Казань", "country": "RU", "lat": 55.7963, "lon": 49.1088,
     "timezone": "Europe/Moscow", "csv": "https://dumrt.ru/netcat_files/482/640/Kazan.csv"},
]


def fetch_rt_csv(city, today):
    """Колонки: дата; Фаджр; Фаджр в мечетях; восход; зәвәл (Зухр); 12:00; Аср; Магриб; Иша[; кыйбла]."""
    text = http(city["csv"]).decode("utf-8-sig")
    first = date(today.year, today.month, 1).isoformat()
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(";")]
        if len(cells) < 9 or not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", cells[0]):
            continue
        dd, mm, yy = cells[0].split(".")

        def t(x):
            h, mi = x.split(":")
            return f"{int(h):02d}:{int(mi):02d}"
        d = {"date": f"{yy}-{mm}-{dd}", "fajr": t(cells[1]), "sunrise": t(cells[3]), "dhuhr": t(cells[4]),
             "asr": t(cells[6]), "maghrib": t(cells[7]), "isha": t(cells[8])}
        if d["date"] < first:
            continue                                  # прошлые месяцы не публикуем
        if d["fajr"] > d["sunrise"]:
            # Белые ночи: рассвет приходится на вечер предыдущего дня (напр. 23:54) — модель дня
            # приложения это не выражает. Берём время Фаджра в мечетях из той же таблицы (восход − 1:31).
            d["fajr"] = t(cells[2])
        validate_day(city["slug"], d)
        out[d["date"]] = d
    if len(out) < 28:
        raise ValueError(f"{city['slug']}: в CSV ДУМ РТ всего {len(out)} дней")
    return out


def collect_rt(index, failures, today):
    for city in RT_CITIES:
        official = {}
        try:
            official = fetch_rt_csv(city, today)
        except Exception as e:                                        # noqa: BLE001
            print(f"[ERROR] {city['slug']}: ДУМ РТ: {e}", file=sys.stderr)
            failures.append(city["slug"])
        # Резервного расчёта нет: летом у ДУМ РТ особые правила (шафак не исчезает) —
        # формулой не воспроизвести; без таблицы месяц не пишем, приложение считает само.
        written = write_horizon(city, today, official, *RT_OFFICIAL, None, None, "hanafi")
        print(f"[OK] {city['slug']}: {' '.join(written) or 'нет данных'}")
        if written:
            index.append(entry({k: city[k] for k in ("slug", "name", "country", "lat", "lon", "timezone")},
                               "hanafi", RT_OFFICIAL[0], "official"))


def collect(index, failures, today=None):
    today = today or datetime.now(timezone.utc).date()
    collect_kz(index, failures, today)
    collect_uz(index, failures, today)
    collect_rt(index, failures, today)


if __name__ == "__main__":
    idx, fails = [], []
    only = sys.argv[1] if len(sys.argv) > 1 else None
    t = datetime.now(timezone.utc).date()
    {"kz": collect_kz, "uz": collect_uz, "rt": collect_rt}.get(only, lambda i, f, d: collect(i, f, d))(idx, fails, t)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
