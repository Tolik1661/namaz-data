#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Страховка для вышедших версий приложения: данные должны декодироваться теми же
структурами Codable, что в PrayerTimesKBR (OfficialTimetables.swift) и в виджете.
Индекс декодируется целиком — одна запись без обязательного поля или с неверным
типом лишает старое приложение официальных таблиц для ВСЕХ городов.

Повторяет контракт Swift строго (обязательные ключи, типы, без null) и дополнительно
проверяет формат времени, соответствие slug папке и наличие данных на сегодня.
Та же проверка настоящим JSONDecoder: scripts/compat/check_app_decoding.swift.

Запуск: python3 scripts/compat/check_schema.py   (код выхода 1 при ошибках)
"""

import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TIME = re.compile(r"^\d{1,2}:\d{2}$")
INDEX_FIELDS = {"slug": str, "name": str, "country": str, "lat": (int, float), "lon": (int, float),
                "timezone": str, "madhab": str, "source": str}
DAY_FIELDS = ("date", "fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def is_type(value, expected):
    # bool — подкласс int в Python, но Swift Double из true/false не декодирует
    return isinstance(value, expected) and not isinstance(value, bool)


def main():
    errors = []
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    if not is_type(index.get("updated"), str) or not isinstance(index.get("cities"), list):
        print("❌ index.json: нет updated (строка) или cities (массив)")
        return 1
    slugs = set()
    for i, c in enumerate(index["cities"]):
        where = c.get("slug", f"#{i}") if isinstance(c, dict) else f"#{i}"
        if not isinstance(c, dict):
            errors.append(f"{where}: запись не объект")
            continue
        for key, typ in INDEX_FIELDS.items():
            if not is_type(c.get(key), typ):
                errors.append(f"{where}: поле {key} отсутствует или неверного типа ({c.get(key)!r})")
        if c.get("slug") in slugs:
            errors.append(f"{where}: повтор slug")
        slugs.add(c.get("slug"))
        if c.get("madhab") not in ("hanafi", "shafi"):
            errors.append(f"{where}: madhab {c.get('madhab')!r}")
        try:
            ZoneInfo(c.get("timezone", ""))
        except Exception:                                              # noqa: BLE001
            errors.append(f"{where}: часовой пояс {c.get('timezone')!r}")

    files = days = 0
    for f in (ROOT / "timetables").rglob("*.json"):
        files += 1
        rel = "/".join(f.parent.relative_to(ROOT / "timetables").parts)
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:                                         # noqa: BLE001
            errors.append(f"{rel}/{f.name}: не JSON: {e}")
            continue
        if not is_type(data.get("slug"), str) or not isinstance(data.get("days"), list):
            errors.append(f"{rel}/{f.name}: нет slug (строка) или days (массив)")
            continue
        if data["slug"] != rel:
            errors.append(f"{rel}/{f.name}: slug {data['slug']!r} не совпадает с папкой")
        if rel not in slugs:
            errors.append(f"{rel}: файлы есть, а города нет в индексе")
        for d in data["days"]:
            days += 1
            if not isinstance(d, dict) or any(not is_type(d.get(k), str) for k in DAY_FIELDS):
                errors.append(f"{rel}/{f.name}: день без обязательных строковых полей: {d!r}")
                continue
            if not d["date"].startswith(f.stem):
                errors.append(f"{rel}/{f.name}: день {d['date']} не из месяца")
            for k in DAY_FIELDS[1:]:
                if not TIME.match(d[k]):
                    errors.append(f"{rel}/{f.name}: {d['date']} {k}={d[k]!r}")

    today = datetime.now(timezone.utc).date().isoformat()
    for slug in slugs:
        month = ROOT / "timetables" / slug / f"{today[:7]}.json"
        ok = month.exists() and any(d.get("date") == today for d in json.loads(month.read_text(encoding="utf-8")).get("days", []))
        if not ok:
            errors.append(f"{slug}: нет данных на {today}")

    print(f"Индекс: {len(index['cities'])} городов; файлов месяцев: {files}; дней: {days}")
    if errors:
        print(f"❌ ошибок совместимости: {len(errors)}")
        for e in errors[:40]:
            print("  " + e)
        return 1
    print("✅ данные совместимы с вышедшими версиями приложения")
    return 0


if __name__ == "__main__":
    sys.exit(main())
