#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Официальные потоки духовных управлений, третья очередь:

  BA/RS/ME — Исламская община Боснии и Герцеговины (vaktija.ba): вечная таблица
       на 118 мест (Босния, Санджак в Сербии и Черногории). База — Сараево плюс
       помесячные поправки для каждого места; сайт отдаёт её целиком в своём JS.
       Формулой не воспроизводится (сдвиги мест не астрономические, ±8 мин),
       поэтому считаем по базе ровно так, как сайт, и сверяем с api.vaktija.ba.
  SG — Majlis Ugama Islam Singapura (MUIS), открытые данные data.gov.sg
       (Singapore Open Data Licence): годовая таблица на страну.
  BG — Главное муфтийство Болгарии (grandmufti.bg): 48 городов, помесячно.
       Сайт отдаёт таблицу текущего года; месяцы следующего года до январского
       обновления — резервный расчёт по методике муфтийства.
"""

import calendar as cal
import json
import pathlib
import random
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from calc_engine import Profile                              # noqa: E402
from local_authorities import due_today, http, horizon, validate_day  # noqa: E402
from official_feeds import entry, official_month_present, write_horizon  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parent / "data"
CALC_URL = "https://github.com/Tolik1661/namaz-data/blob/main/scripts/regional_feeds.py"
KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def latin_slug(text):
    s = unicodedata.normalize("NFKD", text.replace("đ", "dj").replace("Đ", "Dj"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def hhmm(t):
    h, m = t.strip().split(":")[:2]
    return f"{int(h):02d}:{int(m):02d}"


# ── Босния и Герцеговина, Санджак: vaktija.ba ──────────────────────────────

VAKTIJA_OFFICIAL = ("vaktija.ba (Islamska zajednica u Bosni i Hercegovini — официальная таблица)",
                    "https://vaktija.ba")
VAKTIJA_TZ = {"BA": "Europe/Sarajevo", "RS": "Europe/Belgrade", "ME": "Europe/Podgorica"}


def vaktija_db():
    """База с сайта (актуальная); при сбое — снимок в scripts/data."""
    snapshot = json.loads((DATA / "vaktija_db.json").read_text(encoding="utf-8"))
    try:
        page = http("https://vaktija.ba/").decode("utf-8", "replace")
        js_path = re.search(r'src="(/static/js/main\.[0-9a-f]+\.chunk\.js)"', page).group(1)
        js = http("https://vaktija.ba" + js_path).decode("utf-8", "replace")
        start = js.index("JSON.parse('") + len("JSON.parse('")
        live = json.loads(js[start:js.index("')", start)].replace("\\'", "'"))
        if len(live["locations"]) != len(live["differences"]) or len(live["vaktija"]["months"]) != 12:
            raise ValueError("неожиданная структура базы")
        if live["locations"] != snapshot["locations"]:
            raise ValueError("список мест изменился — обновите scripts/data/vaktija_locations.json")
        if live["vaktija"] != snapshot["vaktija"] or live["differences"] != snapshot["differences"]:
            print("[WARN] vaktija.ba: база на сайте изменилась — обновите снимок scripts/data/vaktija_db.json",
                  file=sys.stderr)
        return live
    except Exception as e:                                            # noqa: BLE001
        print(f"[WARN] vaktija.ba: база с сайта не получена, используется снимок: {e}", file=sys.stderr)
        return snapshot


def vaktija_day(db, loc_id, day, tz):
    """Как на сайте: база Сараева + поправка места за месяц, +1 час летом."""
    base = db["vaktija"]["months"][day.month - 1]["days"][day.day - 1]["vakat"]
    diff = db["differences"][loc_id]["months"][day.month - 1]["vakat"]
    at3 = datetime(day.year, day.month, day.day, 3, tzinfo=ZoneInfo(tz))
    dst = 3600 if at3.dst() else 0
    out = {"date": day.isoformat()}
    for k, b, d in zip(KEYS, base, diff):
        s = b + d + dst
        out[k] = f"{s // 3600:02d}:{s % 3600 // 60:02d}"
    return out


def vaktija_cities():
    cities = []
    for loc in json.loads((DATA / "vaktija_locations.json").read_text(encoding="utf-8")):
        cities.append({"slug": f"{loc['country'].lower()}/{latin_slug(loc['name'])}", "name": loc["name"],
                       "country": loc["country"], "lat": loc["lat"], "lon": loc["lon"],
                       "timezone": VAKTIJA_TZ[loc["country"]], "vaktija_id": loc["id"],
                       "vaktija_name": loc["vaktija"]})
    return cities


def vaktija_check(db, cities, today):
    """Сверка расчёта по базе с API на двух местах; расхождение — ошибка потока."""
    sample = [c for c in cities if c["vaktija_id"] == 77]
    sample += random.Random(today.toordinal()).sample([c for c in cities if c["vaktija_id"] != 77], 1)
    checked = 0
    for city in sample:
        try:
            api = json.loads(http(f"https://api.vaktija.ba/vaktija/v1/{city['vaktija_id']}/{today.year}/{today.month}"))
        except Exception as e:                                        # noqa: BLE001
            print(f"[WARN] api.vaktija.ba недоступен, сверка пропущена: {e}", file=sys.stderr)
            continue
        if api.get("lokacija") != city["vaktija_name"]:
            raise ValueError(f"API вернул {api.get('lokacija')!r} вместо {city['vaktija_name']!r}")
        for i, d in enumerate(api["dan"]):
            ours = vaktija_day(db, city["vaktija_id"], date(today.year, today.month, i + 1), city["timezone"])
            theirs = [hhmm(t) for t in d["vakat"]]
            if [ours[k] for k in KEYS] != theirs:
                raise ValueError(f"{city['slug']} {ours['date']}: расчёт по базе {ours} ≠ API {theirs}")
        checked += 1
        time.sleep(1)
    return checked


def collect_vaktija(index, failures, today):
    db = vaktija_db()
    cities = vaktija_cities()
    try:
        checked = vaktija_check(db, cities, today)
        print(f"[OK] vaktija.ba: база сверена с API на {checked} местах")
    except Exception as e:                                            # noqa: BLE001
        print(f"[ERROR] vaktija.ba: {e}", file=sys.stderr)
        failures.append("vaktija.ba")
        return
    for city in cities:
        official = {}
        for y, m in horizon(today):
            for d in range(1, cal.monthrange(y, m)[1] + 1):
                day = vaktija_day(db, city["vaktija_id"], date(y, m, d), city["timezone"])
                validate_day(city["slug"], day)
                official[day["date"]] = day
        written = write_horizon(city, today, official, *VAKTIJA_OFFICIAL, None, None, "shafi")
        print(f"[OK] {city['slug']}: {' '.join(written)}")
        index.append(entry(city, "shafi", VAKTIJA_OFFICIAL[0], "official"))


# ── Сингапур: MUIS, data.gov.sg ────────────────────────────────────────────

SG_OFFICIAL = ("MUIS (Majlis Ugama Islam Singapura — официальная таблица, data.gov.sg)",
               "https://data.gov.sg/collections/2312/view")
SG_CALC = "MUIS (расчёт по методике Majlis Ugama Islam Singapura)"
SG_CITY = {"slug": "sg/singapore", "name": "Singapore", "country": "SG",
           "lat": 1.2897, "lon": 103.8501, "timezone": "Asia/Singapore"}
# Сверено с таблицей MUIS 2026: 100% дней в пределах минуты
SG_PROFILE = Profile("MUIS", fajr_angle=20, isha_angle=18, adjust={"sunrise": 1, "dhuhr": 1}, rounding="up")


def sg_datasets():
    meta = json.loads(http("https://api-production.data.gov.sg/v2/public/api/collections/2312/metadata"))
    years = {}
    for ds in meta["data"]["collectionMetadata"]["childDatasets"]:
        info = json.loads(http(f"https://api-production.data.gov.sg/v2/public/api/datasets/{ds}/metadata"))
        m = re.fullmatch(r"Muslim Prayer Timetable (\d{4})", info["data"]["name"].strip())
        if m:
            years[int(m.group(1))] = ds
        time.sleep(1)
    return years


def fetch_sg_year(dataset):
    data = json.loads(http(f"https://data.gov.sg/api/action/datastore_search?resource_id={dataset}&limit=400"))
    out = {}
    for r in data["result"]["records"]:
        ds = r["Date"][:10]
        d = {"date": ds, "fajr": hhmm(r["Subuh"]), "sunrise": hhmm(r["Syuruk"]), "dhuhr": hhmm(r["Zohor"]),
             "asr": hhmm(r["Asar"]), "maghrib": hhmm(r["Maghrib"]), "isha": hhmm(r["Isyak"])}
        # в некоторых годах время дня записано в 12-часовом формате
        for k in ("dhuhr", "asr", "maghrib", "isha"):
            if int(d[k][:2]) < 11:
                d[k] = f"{int(d[k][:2]) + 12:02d}{d[k][2:]}"
        validate_day(SG_CITY["slug"], d)
        out[ds] = d
    return out


def collect_sg(index, failures, today):
    official = {}
    try:
        years = sg_datasets()
        for y in sorted({y for y, _ in horizon(today)}):
            if y in years:
                got = fetch_sg_year(years[y])
                if len(got) < 365:
                    raise ValueError(f"MUIS {y}: {len(got)} дней")
                official.update(got)
    except Exception as e:                                            # noqa: BLE001
        print(f"[ERROR] sg/singapore: MUIS: {e}", file=sys.stderr)
        failures.append("sg/singapore")
    written = write_horizon(SG_CITY, today, official, *SG_OFFICIAL, SG_PROFILE, SG_CALC, "shafi")
    kind = "official" if written and written[0].endswith(("✓", "=")) else "calculated"
    print(f"[OK] sg/singapore: {' '.join(written)}")
    index.append(entry(SG_CITY, "shafi", SG_OFFICIAL[0] if kind == "official" else SG_CALC, kind))


# ── Болгария: Главное муфтийство ───────────────────────────────────────────

BG_OFFICIAL = ("grandmufti.bg (Главное муфтийство Болгарии — официальная таблица)",
               "https://grandmufti.bg/bg/home/vremena-za-namaz.html")
BG_CALC = "grandmufti.bg (расчёт по методике Главного муфтийства Болгарии)"
# Сверено по Софии за сентябрь (±1); в другие месяцы таблица муфтийства расходится с формулой до 6 мин
BG_PROFILE = Profile("Главное муфтийство", fajr_angle=18, isha_angle=17, maghrib_minutes=9,
                     adjust={"fajr": -2, "sunrise": -8, "dhuhr": 5, "asr": 5, "isha": 3})


def bg_cities():
    return [{"slug": f"bg/{t['town']}", "name": t["name"], "country": "BG", "lat": t["lat"], "lon": t["lon"],
             "timezone": "Europe/Sofia", "town": t["town"]}
            for t in json.loads((DATA / "bg_grandmufti_towns.json").read_text(encoding="utf-8"))]


def fetch_bg_month(city, year, month):
    html = http("https://grandmufti.bg/bg/home/vremena-za-namaz.html",
                data={"option": "com_sv_prayer_times", "task": "month", "month": month, "town": city["town"]}
                ).decode("utf-8", "replace")
    rows = [re.sub(r"<[^>]+>", " ", r).split() for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)]
    rows = [r for r in rows if len(r) >= 7 and r[0].isdigit()]
    if len(rows) != cal.monthrange(year, month)[1]:
        raise ValueError(f"{city['slug']} {year}-{month:02d}: {len(rows)} строк")
    out = {}
    for r in rows:
        d = {"date": f"{year:04d}-{month:02d}-{int(r[0]):02d}", **{k: hhmm(v) for k, v in zip(KEYS, r[1:7])}}
        validate_day(city["slug"], d)
        out[d["date"]] = d
    return out


def collect_bg(index, failures, today):
    for city in bg_cities():
        official = {}
        # сайт отдаёт только текущий год: число дней в феврале совпадает с ним
        months = [(y, m) for y, m in horizon(today) if y == today.year]
        need = not official_month_present(city, today.year, today.month, BG_OFFICIAL[0])
        if need or due_today(city["slug"], today):
            try:
                for y, m in months:
                    official.update(fetch_bg_month(city, y, m))
                    time.sleep(0.5)
            except Exception as e:                                    # noqa: BLE001
                print(f"[ERROR] {city['slug']}: grandmufti.bg: {e}", file=sys.stderr)
                failures.append(city["slug"])
        written = write_horizon(city, today, official, *BG_OFFICIAL, BG_PROFILE, BG_CALC, "shafi")
        kind = "official" if written and written[0].endswith(("✓", "=")) else "calculated"
        print(f"[OK] {city['slug']}: {' '.join(written)}")
        index.append(entry(city, "shafi", BG_OFFICIAL[0] if kind == "official" else BG_CALC, kind))


def collect(index, failures, today=None):
    today = today or datetime.now(timezone.utc).date()
    collect_vaktija(index, failures, today)
    collect_sg(index, failures, today)
    collect_bg(index, failures, today)


if __name__ == "__main__":
    idx, fails = [], []
    only = sys.argv[1] if len(sys.argv) > 1 else None
    t = datetime.now(timezone.utc).date()
    {"ba": collect_vaktija, "sg": collect_sg, "bg": collect_bg}.get(only, lambda i, f, d: collect(i, f, d))(idx, fails, t)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
