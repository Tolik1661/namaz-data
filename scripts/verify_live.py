#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сверка сохранённых расписаний с живыми официальными источниками.

Для каждого источника берёт города (все или выборку), заново скачивает их
страницы/API теми же парсерами и сравнивает минуты с тем, что лежит в
timetables/. Расхождение означает: сломался парсер, источник поменял формат
или данные, либо файл не обновлялся.

Запуск: python3 scripts/verify_live.py [--turkey-sample 40]
"""

import argparse
import json
import pathlib
import random
import sys
import time
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import parse_diyanet     # noqa: E402
import parse_islamdag    # noqa: E402
import parse_jakim       # noqa: E402
import parse_muftiyatkg  # noqa: E402
import parse_namozvaqti  # noqa: E402
import parse_umma        # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def stored_days(slug):
    days = {}
    for f in (ROOT / "timetables" / slug).glob("*.json"):
        for d in json.loads(f.read_text()).get("days", []):
            days[d["date"]] = d
    return days


def as_day_map(result):
    """Приводит ответы разных парсеров к {дата: день}."""
    if isinstance(result, tuple):                     # namozvaqti: (год, дни)
        result = result[1]
    if isinstance(result, dict) and "days" in result:  # islamdag/jakim/umma: {…, "days": [...]}
        result = result["days"]
    if isinstance(result, dict):                      # diyanet: {дата: день}
        return result
    return {d["date"]: d for d in result}


def to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def compare(slug, live):
    stored = stored_days(slug)
    common = sorted(set(stored) & set(live))
    diffs = []
    for ds in common:
        for k in KEYS:
            a, b = to_min(stored[ds][k]), to_min(live[ds][k])
            if a != b:
                diffs.append((ds, k, stored[ds][k], live[ds][k]))
    return len(common), diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turkey-sample", type=int, default=40, help="сколько районов Турции проверить")
    args = ap.parse_args()
    now = datetime.now()
    next_month = now.month % 12 + 1
    next_year = now.year + (1 if now.month == 12 else 0)

    jobs = []   # (источник, slug, функция загрузки)
    for c in parse_diyanet.CITIES:
        jobs.append(("Diyanet", c["slug"], lambda c=c: parse_diyanet.parse_city(c)))
    districts = parse_diyanet.district_cities()
    random.seed(now.strftime("%Y%m%d"))
    for c in random.sample(districts, min(args.turkey_sample, len(districts))):
        jobs.append(("Diyanet · район", c["slug"], lambda c=c: parse_diyanet.parse_city(c)))
    for c in parse_islamdag.CITIES:
        jobs.append(("islamdag.ru", c["slug"], lambda c=c: parse_islamdag.parse_city(c)))
    for c in parse_jakim.CITIES:
        jobs.append(("JAKIM", c["slug"], lambda c=c: parse_jakim.parse_city(c)))
    for c in parse_umma.CITIES:
        jobs.append(("umma.ru", c["slug"], lambda c=c: parse_umma.parse_city(c)))
    for c in parse_muftiyatkg.CITIES:
        jobs.append(("muftiyat.kg", c["slug"],
                     lambda c=c: parse_muftiyatkg.parse_month(c, now.year, now.month)
                     + parse_muftiyatkg.parse_month(c, next_year, next_month)))
    for c in parse_namozvaqti.CITIES:
        jobs.append(("namozvaqti.uz", c["slug"],
                     lambda c=c: parse_namozvaqti.parse_month(c, now.month)[1]
                     + parse_namozvaqti.parse_month(c, next_month)[1]))

    totals = {}
    problems = []
    for source, slug, load in jobs:
        try:
            live = as_day_map(load())
        except Exception as e:                                        # noqa: BLE001
            problems.append((source, slug, f"не загрузилось: {e}"))
            print(f"  ✗ {source:16} {slug:22} ошибка загрузки: {e}", flush=True)
            continue
        n, diffs = compare(slug, live)
        t = totals.setdefault(source, {"cities": 0, "days": 0, "diff_cities": 0, "no_overlap": 0})
        t["cities"] += 1
        t["days"] += n
        if n == 0:
            t["no_overlap"] += 1
            problems.append((source, slug, "нет общих дней с сохранёнными данными"))
        if diffs:
            t["diff_cities"] += 1
            sample = "; ".join(f"{d} {k}: сохранено {a}, на сайте {b}" for d, k, a, b in diffs[:3])
            problems.append((source, slug, f"расхождений {len(diffs)} (из {n} дн.): {sample}"))
        mark = "✓" if n and not diffs else "✗"
        print(f"  {mark} {source:16} {slug:22} общих дней {n:3}, расхождений {len(diffs)}", flush=True)
        time.sleep(0.3)

    print("\nИтог по источникам:")
    for s, t in totals.items():
        print(f"  {s:16} городов {t['cities']:3} │ сверено дней {t['days']:5} │ "
              f"с расхождениями {t['diff_cities']} │ без пересечения {t['no_overlap']}")
    print(f"\nПроблем: {len(problems)}")
    for s, slug, text in problems:
        print(f"  {s:16} {slug:22} {text}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
