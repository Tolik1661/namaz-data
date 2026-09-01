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
import os
import pathlib
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Все районы Турции (842, сгенерировано из GetRegList Диянета + центроиды
# границ OSM). Их СТРАНИЦЫ парсятся только в еженедельном прогоне
# (env DIYANET_DISTRICTS=1) — данные у Диянета на год вперёд, чаще не нужно.
# В index.json районы попадают ВСЕГДА (чтобы приложение их находило).
DISTRICTS_FILE = pathlib.Path(__file__).resolve().parent / "diyanet_districts.json"
PARSE_DISTRICTS = os.environ.get("DIYANET_DISTRICTS") == "1"
DISTRICT_MONTHS_HORIZON = 3   # хранить только текущий + 2 следующих месяца


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
    # Турция — курорты и крупные города (IlceID разрезолвлены через GetRegList)
    _city(9224,  "tr/alanya",     "Аланья",     "TR", 36.5437, 31.9998, "Europe/Istanbul"),
    _city(9236,  "tr/manavgat",   "Манавгат (Сиде)", "TR", 36.7869, 31.4429, "Europe/Istanbul"),
    _city(9237,  "tr/serik",      "Серик (Белек)",   "TR", 36.9170, 31.0994, "Europe/Istanbul"),
    _city(9233,  "tr/kemer",      "Кемер",      "TR", 36.6023, 30.5606, "Europe/Istanbul"),
    _city(9232,  "tr/kas",        "Каш",        "TR", 36.2020, 29.6414, "Europe/Istanbul"),
    _city(9741,  "tr/bodrum",     "Бодрум",     "TR", 37.0344, 27.4305, "Europe/Istanbul"),
    _city(17883, "tr/marmaris",   "Мармарис",   "TR", 36.8550, 28.2741, "Europe/Istanbul"),
    _city(9744,  "tr/fethiye",    "Фетхие",     "TR", 36.6217, 29.1164, "Europe/Istanbul"),
    _city(9146,  "tr/adana",      "Адана",      "TR", 37.0000, 35.3213, "Europe/Istanbul"),
    _city(9479,  "tr/gaziantep",  "Газиантеп",  "TR", 37.0662, 37.3833, "Europe/Istanbul"),
    _city(9620,  "tr/kayseri",    "Кайсери",    "TR", 38.7312, 35.4787, "Europe/Istanbul"),
    _city(9737,  "tr/mersin",     "Мерсин",     "TR", 36.8000, 34.6333, "Europe/Istanbul"),
    _city(9905,  "tr/trabzon",    "Трабзон",    "TR", 41.0015, 39.7178, "Europe/Istanbul"),
    _city(9819,  "tr/samsun",     "Самсун",     "TR", 41.2867, 36.3300, "Europe/Istanbul"),
    _city(9470,  "tr/eskisehir",  "Эскишехир",  "TR", 39.7767, 30.5206, "Europe/Istanbul"),
    _city(9392,  "tr/denizli",    "Денизли",    "TR", 37.7765, 29.0864, "Europe/Istanbul"),
    _city(9402,  "tr/diyarbakir", "Диярбакыр",  "TR", 37.9144, 40.2306, "Europe/Istanbul"),
    _city(9451,  "tr/erzurum",    "Эрзурум",    "TR", 39.9043, 41.2679, "Europe/Istanbul"),
    _city(9930,  "tr/van",        "Ван",        "TR", 38.4891, 43.4089, "Europe/Istanbul"),
    _city(9799,  "tr/rize",       "Ризе",       "TR", 41.0201, 40.5234, "Europe/Istanbul"),
    _city(9868,  "tr/sivas",      "Сивас",      "TR", 39.7477, 37.0179, "Europe/Istanbul"),
    _city(9703,  "tr/malatya",    "Малатья",    "TR", 38.3552, 38.3095, "Europe/Istanbul"),
    _city(9831,  "tr/sanliurfa",  "Шанлыурфа",  "TR", 37.1591, 38.7969, "Europe/Istanbul"),
    _city(9654,  "tr/kocaeli",    "Коджаэли (Измит)", "TR", 40.7654, 29.9408, "Europe/Istanbul"),
    _city(9807,  "tr/sakarya",    "Сакарья",    "TR", 40.7569, 30.3783, "Europe/Istanbul"),
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
    # Азербайджан (Diyanet, суннитская методика)
    _city(11631, "az/baku",       "Баку",        "AZ", 40.4093, 49.8671, "Asia/Baku"),
    _city(11634, "az/gence",      "Гянджа",      "AZ", 40.6828, 46.3606, "Asia/Baku"),
    _city(11641, "az/sumqayit",   "Сумгаит",     "AZ", 40.5897, 49.6686, "Asia/Baku"),
    _city(11625, "az/mingacevir", "Мингечевир",  "AZ", 40.7703, 47.0496, "Asia/Baku"),
    _city(11645, "az/lenkeran",   "Ленкорань",   "AZ", 38.7529, 48.8475, "Asia/Baku"),
    _city(11635, "az/seki",       "Шеки",        "AZ", 41.1919, 47.1706, "Asia/Baku"),
    _city(11637, "az/nahcivan",   "Нахичевань",  "AZ", 39.2089, 45.4122, "Asia/Baku"),
    _city(11632, "az/quba",       "Губа",        "AZ", 41.3611, 48.5125, "Asia/Baku"),
    _city(11643, "az/samaxi",     "Шемаха",      "AZ", 40.6319, 48.6414, "Asia/Baku"),
    _city(11638, "az/yevlax",     "Евлах",       "AZ", 40.6172, 47.1500, "Asia/Baku"),
    _city(11624, "az/salyan",     "Сальян",      "AZ", 39.5942, 48.9787, "Asia/Baku"),
    _city(11642, "az/astara",     "Астара",      "AZ", 38.4561, 48.8786, "Asia/Baku"),
    _city(11626, "az/tovuz",      "Товуз",       "AZ", 40.9922, 45.6289, "Asia/Baku"),
    _city(11649, "az/zaqatala",   "Закаталы",    "AZ", 41.6336, 46.6433, "Asia/Baku"),
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


def merge_months(city, days, months_horizon=None):
    """Слить дни скользящего окна в файлы месяцев (существующие дни обновляются)"""
    by_month = {}
    for date, d in days.items():
        by_month.setdefault(date[:7], {})[date] = d

    # Для районов храним только ближайшие месяцы (иначе репозиторий распухнет)
    if months_horizon:
        keep = sorted(by_month)[:months_horizon]
        by_month = {k: v for k, v in by_month.items() if k in keep}

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


def district_cities():
    """Районы Турции как city-структуры (кроме уже курируемых IlceID)"""
    if not DISTRICTS_FILE.exists():
        return []
    curated = {c["ilce"] for c in CITIES}
    out = []
    for d in json.loads(DISTRICTS_FILE.read_text(encoding="utf-8")):
        if int(d["ilce"]) in curated:
            continue
        out.append({
            "ilce": int(d["ilce"]),
            "slug": f"tr/{d['ilce']}",
            "name": d["name"].title(),
            "country": "TR",
            "lat": d["lat"], "lon": d["lon"],
            "timezone": "Europe/Istanbul",
            "madhab": "shafi",
        })
    return out


def collect(index, failures):
    districts = district_cities()

    # Районы всегда в индексе (приложение находит их по координатам);
    # страницы районов парсим только в еженедельном прогоне
    for d in districts:
        index.append({
            "slug": d["slug"], "name": d["name"], "country": d["country"],
            "lat": d["lat"], "lon": d["lon"], "timezone": d["timezone"],
            "madhab": d["madhab"],
            "source": "Diyanet (namazvakitleri.diyanet.gov.tr)",
        })

    if PARSE_DISTRICTS:
        done = 0
        for d in districts:
            try:
                days = parse_city(d)
                merge_months(d, days, months_horizon=DISTRICT_MONTHS_HORIZON)
                done += 1
                if done % 50 == 0:
                    print(f"[districts] {done}/{len(districts)}")
            except Exception as e:                                # noqa: BLE001
                print(f"[ERROR] {d['slug']}: {e}", file=sys.stderr)
                failures.append(d["slug"])
            time.sleep(0.5)
        print(f"[OK] районы Турции: {done}/{len(districts)}")

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
