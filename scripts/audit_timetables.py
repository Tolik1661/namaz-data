#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Аудит официальных расписаний: проверяет КАЖДЫЙ город и КАЖДЫЙ сохранённый день
независимой астрономией (алгоритм NOAA), без доверия к источнику.

Что ловит:
  • целостность — все 6 времён, формат (строго 0–23 ч, 00–59 мин), порядок, дубли,
    пропуски дней;
  • восход / Зухр / Магриб против расчётных восхода, истинного полдня и заката
    (не зависят от метода и мазхаба) — выдают неверные координаты, часовой пояс,
    летнее время, сдвиг дат в парсере. Медиана города и КАЖДЫЙ день по отдельности:
    опечатка в часе одного дня (05:43 вместо 04:43) медиану не сдвигает;
  • фактические углы Фаджра и Иши, по которым считал источник, — выбросы
    внутри одного источника указывают на ошибку данных; угол дня, резко
    отличный от соседних дней того же города, — предупреждение;
  • запас вперёд — сколько дней от сегодня лежит в данных.

Запуск: python3 scripts/audit_timetables.py [--json отчёт.json]
Код выхода 1, если есть ошибки уровня ERROR.
"""

import argparse
import collections
import json
import math
import pathlib
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from local_authorities import RAMADAN_UQ  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
# Строго 0–23 ч и 00–59 мин, только ASCII-цифры (\d в Python — любые Unicode-цифры)
TIME = re.compile(r"^(?:[01]?[0-9]|2[0-3]):[0-5][0-9]$", re.ASCII)
# Восход / Зухр / Магриб КАЖДОГО дня против астрономии: ERROR при расхождении больше порога.
# 25 мин с запасом: на данных 23.09.2026 максимум 18,0 мин (bg/byala, восход), ДУМ КБР Зухр 13,6
DAY_LIMIT_MIN = 25
# Фаджр / Иша: угол дня против медианы соседних ±3 дней того же города — только WARN.
# На данных 23.09.2026 максимум 2,6° (Казань 08–09.08, сезонная смена правила ДУМ РТ);
# опечатка в часе даёт 8° и больше
NEIGHBOR_DAYS = 3
NEIGHBOR_ANGLE_LIMIT = 3.0
# В Рамадан у SA/QA Иша на 30 мин позже (120 мин после Магриба вместо 90) — скачок угла не ошибка
RAMADAN_COUNTRIES = {"SA", "QA"}
# Источники, у которых Магриб по методике наступает по углу Солнца под горизонтом
# (QMİ: 3,5°, ≈15 мин после заката) — для них абсолютный порог Магриба не применяем.
ANGLE_MAGHRIB_SOURCES = {"QMİ"}
# Одна таблица на всю республику (ДУМ КБР): в восточных городах Зухр дальше от
# астрономического полудня — ихтият +10 мин плюс до ±3 мин разницы долгот
REPUBLIC_TABLE_SOURCES = {"kbrdum.ru"}


# ── Астрономия (NOAA) ──────────────────────────────────────────────────────

def _julian_day(dt_utc):
    y, m = dt_utc.year, dt_utc.month
    d = dt_utc.day + (dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def _sun(jd):
    """Склонение Солнца (°) и уравнение времени (мин)."""
    t = (jd - 2451545.0) / 36525
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * m) * (0.019993 - 0.000101 * t) + math.sin(3 * m) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eqt = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(m)
                           + 4 * e * y * math.sin(m) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * m))
    return decl, eqt


def solar_events(day, lat, lon, tz):
    """Истинный полдень, восход и закат (минуты местного времени) для даты."""
    noon_utc = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc) - timedelta(minutes=4 * lon)
    offset = ZoneInfo(tz).utcoffset(noon_utc.replace(tzinfo=None)).total_seconds() / 60
    decl, eqt = _sun(_julian_day(noon_utc))
    noon = 720 - 4 * lon - eqt + offset
    phi = math.radians(lat)
    events = {"noon": noon}
    for name, sign in (("sunrise", -1), ("sunset", 1)):
        # уточняем склонение на момент события
        guess = noon + sign * 360
        for _ in range(2):
            t_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(minutes=guess - offset)
            decl, eqt = _sun(_julian_day(t_utc))
            cos_h = ((math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(decl))
                     / (math.cos(phi) * math.cos(decl)))
            if abs(cos_h) > 1:
                events[name] = None
                break
            guess = 720 - 4 * lon - eqt + offset + sign * 4 * math.degrees(math.acos(cos_h))
        else:
            events[name] = guess
    return events, offset


def sun_altitude(day, minutes_local, lat, lon, offset):
    t_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(minutes=minutes_local - offset)
    decl, eqt = _sun(_julian_day(t_utc))
    solar_time = minutes_local - offset + eqt + 4 * lon          # минуты солнечного времени (UTC-база)
    hour_angle = math.radians((solar_time / 4) - 180)
    phi = math.radians(lat)
    return math.degrees(math.asin(math.sin(phi) * math.sin(decl)
                                  + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)))


# ── Проверки ───────────────────────────────────────────────────────────────

def to_min(hhmm):
    if not isinstance(hhmm, str) or not TIME.fullmatch(hhmm):
        raise ValueError(f"время {hhmm!r}")
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def ramadan_dates(pad=2):
    """Даты Рамадана по Умм-аль-Кура с запасом ±pad дней (в Катаре начало может отличаться на день)."""
    days = set()
    for start, end in RAMADAN_UQ.values():
        d, last = date.fromisoformat(start) - timedelta(pad), date.fromisoformat(end) + timedelta(pad)
        while d <= last:
            days.add(d.isoformat())
            d += timedelta(1)
    return frozenset(days)


def neighbor_angle_issues(angles, skip=frozenset()):
    """Дни, где угол Фаджра или Иши отличается от медианы соседних ±NEIGHBOR_DAYS дней
    больше чем на NEIGHBOR_ANGLE_LIMIT. angles: {дата: (угол Фаджра, угол Иши)}.
    Возвращает [(дата, "fajr"|"isha", угол дня, медиана соседей)]."""
    out = []
    for ds in sorted(angles):
        if ds in skip:
            continue
        day = date.fromisoformat(ds)
        for j, name in enumerate(("fajr", "isha")):
            around = []
            for k in range(-NEIGHBOR_DAYS, NEIGHBOR_DAYS + 1):
                other = (day + timedelta(k)).isoformat()
                if k and other in angles and other not in skip:
                    around.append(angles[other][j])
            if len(around) < 2:
                continue
            med = statistics.median(around)
            if abs(angles[ds][j] - med) > NEIGHBOR_ANGLE_LIMIT:
                out.append((ds, name, angles[ds][j], med))
    return out


def audit(today):
    index = json.loads((ROOT / "index.json").read_text())
    issues = []                                  # (уровень, источник, slug, текст)
    per_source = collections.defaultdict(lambda: collections.defaultdict(list))
    per_city = {}
    ramadan = ramadan_dates()

    for city in index["cities"]:
        slug, lat, lon, tz = city["slug"], city["lat"], city["lon"], city["timezone"]
        # Норма считается по паре «источник · страна»: один сайт может вести разные
        # страны по разным методикам (umma.ru: Россия 18°, Казахстан 15°)
        source = f'{city["source"].split(" (")[0]} · {city["country"]}'
        folder = ROOT / "timetables" / slug
        files = sorted(folder.glob("*.json"))
        if not files:
            issues.append(("ERROR", source, slug, "нет файлов расписания"))
            continue
        days = {}
        for f in files:
            data = json.loads(f.read_text())
            for d in data.get("days", []):
                if d["date"] in days:
                    issues.append(("WARN", source, slug, f"дубль даты {d['date']}"))
                days[d["date"]] = d

        deltas = collections.defaultdict(list)
        angles = {}                               # дата → (угол Фаджра, угол Иши)
        angle_maghrib = source.split(" · ")[0] in ANGLE_MAGHRIB_SOURCES
        for ds in sorted(days):
            d = days[ds]
            try:
                day = date.fromisoformat(ds)
                t = {k: to_min(d[k]) for k in KEYS}
            except (KeyError, ValueError, AttributeError, TypeError):
                issues.append(("ERROR", source, slug, f"{ds}: битый формат {d}"))
                continue
            seq = [t[k] for k in KEYS]
            if seq != sorted(seq):
                issues.append(("ERROR", source, slug, f"{ds}: порядок времён нарушен {d}"))
                continue
            ev, offset = solar_events(day, lat, lon, tz)
            if ev["sunrise"] is None or ev["sunset"] is None:
                continue                          # полярный день/ночь — сверять нечего
            day_delta = {"sunrise": t["sunrise"] - ev["sunrise"], "dhuhr": t["dhuhr"] - ev["noon"],
                         "maghrib": t["maghrib"] - ev["sunset"]}
            for k, v in day_delta.items():
                deltas[k].append(v)
                if k == "maghrib" and angle_maghrib:
                    continue                      # Магриб по углу Солнца — абсолютный порог не применим
                if abs(v) > DAY_LIMIT_MIN:
                    issues.append(("ERROR", source, slug,
                                   f"{ds}: {k} {d[k]} — расхождение с астрономией {v:+.0f} мин"))
            fajr_angle = -sun_altitude(day, t["fajr"], lat, lon, offset)
            isha_angle = -sun_altitude(day, t["isha"], lat, lon, offset)
            deltas["fajr_angle"].append(fajr_angle)
            deltas["isha_angle"].append(isha_angle)
            angles[ds] = (fajr_angle, isha_angle)

        skip = ramadan if city["country"] in RAMADAN_COUNTRIES else frozenset()
        for ds, name, value, med in neighbor_angle_issues(angles, skip):
            issues.append(("WARN", source, slug,
                           f"{ds}: {name} {days[ds][name]} — угол {value:.1f}° при {med:.1f}° у соседних дней"))

        # пропуски дней внутри диапазона
        all_dates = sorted(days)
        if all_dates:
            first, last = date.fromisoformat(all_dates[0]), date.fromisoformat(all_dates[-1])
            gaps = [(first + timedelta(i)).isoformat() for i in range((last - first).days + 1)
                    if (first + timedelta(i)).isoformat() not in days]
            ahead = sum(1 for x in all_dates if x >= today.isoformat())
            contiguous_ahead = 0
            cur = today
            while cur.isoformat() in days:
                contiguous_ahead += 1
                cur += timedelta(1)
            if contiguous_ahead == 0:
                issues.append(("ERROR", source, slug, "нет данных на сегодня"))
            elif contiguous_ahead < 20:
                # Предупреждение, а не ошибка: многие источники публикуют только текущий месяц
                issues.append(("WARN", source, slug, f"сплошной запас вперёд всего {contiguous_ahead} дн."))
        else:
            gaps, contiguous_ahead = [], 0

        summary = {k: (statistics.median(v) if v else None) for k, v in deltas.items()}
        spread = {k: (max(v) - min(v) if v else None) for k, v in deltas.items()}
        per_city[slug] = {"source": source, "name": city["name"], "days": len(days),
                          "ahead": contiguous_ahead, "gaps": len(gaps), "median": summary,
                          "spread": spread}
        for k, v in summary.items():
            if v is not None:
                per_source[source][k].append(v)

    # Выбросы внутри источника: медиана города далеко от медианы источника
    tolerance = {"sunrise": 4, "dhuhr": 4, "maghrib": 4, "fajr_angle": 1.5, "isha_angle": 1.5}
    absolute = {"sunrise": 12, "dhuhr": 12, "maghrib": 12}
    source_norm = {s: {k: statistics.median(v) for k, v in ks.items()} for s, ks in per_source.items()}
    for slug, info in per_city.items():
        norm = source_norm.get(info["source"], {})
        for k, tol in tolerance.items():
            v = info["median"].get(k)
            if v is None or k not in norm:
                continue
            if abs(v - norm[k]) > tol:
                unit = "°" if "angle" in k else " мин"
                issues.append(("ERROR" if abs(v - norm[k]) > 2 * tol else "WARN", info["source"], slug,
                               f"{k}: {v:+.1f}{unit} при норме источника {norm[k]:+.1f}{unit}"))
        for k, lim in absolute.items():
            if k == "maghrib" and info["source"].split(" · ")[0] in ANGLE_MAGHRIB_SOURCES:
                continue
            if info["source"].split(" · ")[0] in REPUBLIC_TABLE_SOURCES:
                lim += 4
            v = info["median"].get(k)
            if v is not None and abs(v) > lim:
                issues.append(("ERROR", info["source"], slug, f"{k}: расхождение с астрономией {v:+.1f} мин"))
        if info["gaps"]:
            issues.append(("WARN", info["source"], slug, f"пропущено дней внутри диапазона: {info['gaps']}"))
    return index, per_city, source_norm, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="сохранить подробный отчёт")
    ap.add_argument("--today", help="YYYY-MM-DD (по умолчанию сегодня)")
    args = ap.parse_args()
    # «Сегодня» по UTC — как в build_all и check_schema
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()

    index, per_city, norm, issues = audit(today)

    print(f"Городов: {len(index['cities'])}, сверено дней: {sum(c['days'] for c in per_city.values())}\n")
    print("Норма по источникам (медианы по городам): расхождение с астрономией и фактические углы")
    for s, n in sorted(norm.items()):
        cnt = sum(1 for c in per_city.values() if c["source"] == s)
        print(f"  {s:15} {cnt:4} гор. │ восход {n['sunrise']:+5.1f} │ Зухр {n['dhuhr']:+5.1f} │ "
              f"Магриб {n['maghrib']:+5.1f} мин │ Фаджр {n['fajr_angle']:5.2f}° │ Иша {n['isha_angle']:5.2f}°")
    by_level = collections.Counter(i[0] for i in issues)
    print(f"\nЗамечаний: ERROR {by_level['ERROR']}, WARN {by_level['WARN']}")
    for level in ("ERROR", "WARN"):
        rows = [i for i in issues if i[0] == level]
        for lvl, src, slug, text in rows[:60]:
            print(f"  [{lvl}] {src:15} {slug:28} {text}")
        if len(rows) > 60:
            print(f"  … и ещё {len(rows) - 60}")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(
            {"today": today.isoformat(), "norm": norm, "cities": per_city,
             "issues": [dict(zip(("level", "source", "slug", "text"), i)) for i in issues]},
            ensure_ascii=False, indent=1))
    return 1 if by_level["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
