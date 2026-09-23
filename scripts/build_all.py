#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оркестратор: запускает все парсеры и собирает единый index.json.
Частичный сбой одного источника не мешает остальным, но помечает прогон
кодом 1 — GitHub Actions пришлёт алерт.

Перед записью индекса из него убираются записи, которые сломали бы проверки
перед публикацией: битые (приложение декодирует индекс целиком — одна такая
запись отключает официальные таблицы у всех новых пользователей), повторы slug
и города без данных на сегодня. Они попадают в failures: job красный, но
остальные города публикуются, а не встают все из-за одного источника.
"""

import json
import math
import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import dumkbr           # noqa: E402
import local_authorities  # noqa: E402
import official_feeds   # noqa: E402
import parse_diyanet    # noqa: E402
import parse_islamdag   # noqa: E402
import parse_jakim      # noqa: E402
import parse_muftiyatkg # noqa: E402
import parse_umma       # noqa: E402
import regional_feeds   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Обязательные поля записи индекса и их типы — контракт IndexCity в приложениях
# (iOS OfficialTimetables.swift, Android OfficialTimetables.kt, scripts/compat)
INDEX_FIELDS = {"slug": str, "name": str, "country": str, "lat": (int, float), "lon": (int, float),
                "timezone": str, "madhab": str, "source": str}


def entry_problem(entry):
    """Почему запись индекса не декодируется приложением (или None, если всё в порядке)."""
    if not isinstance(entry, dict):
        return "запись не объект"
    for key, typ in INDEX_FIELDS.items():
        value = entry.get(key)
        # bool — подкласс int в Python, но Double из true/false в Swift не декодируется
        if not isinstance(value, typ) or isinstance(value, bool):
            return f"поле {key} отсутствует или неверного типа ({value!r})"
        if isinstance(value, str) and not value.strip():
            return f"пустое поле {key}"
    if not (math.isfinite(entry["lat"]) and math.isfinite(entry["lon"])
            and -90 <= entry["lat"] <= 90 and -180 <= entry["lon"] <= 180):
        return f"координаты вне диапазона ({entry['lat']!r}, {entry['lon']!r})"
    if entry["madhab"] not in ("hanafi", "shafi"):
        return f"madhab {entry['madhab']!r}"
    try:
        ZoneInfo(entry["timezone"])
    except Exception:                                                 # noqa: BLE001
        return f"часовой пояс {entry['timezone']!r}"
    return None


def has_day(slug, day, root=ROOT):
    """Есть ли у города данные на этот день (файл месяца и сам день в нём)."""
    month_file = root / "timetables" / slug / f"{day:%Y-%m}.json"
    try:
        days = json.loads(month_file.read_text(encoding="utf-8")).get("days", [])
    except (OSError, ValueError, AttributeError):
        return False
    return any(isinstance(d, dict) and d.get("date") == day.isoformat() for d in days)


def sanitize_index(index, failures, today, root=ROOT):
    """Оставляет в индексе только записи, которые пройдут проверки перед публикацией;
    остальные убирает и добавляет в failures."""
    clean, seen = [], set()
    for entry in index:
        slug = entry.get("slug") if isinstance(entry, dict) else None
        problem = entry_problem(entry)
        if problem is None and slug in seen:
            problem = "повтор slug"
        if problem is None and not has_day(slug, today, root):
            problem = f"нет данных на {today.isoformat()}"
        if problem:
            print(f"[ERROR] {slug or '?'}: убран из индекса — {problem}", file=sys.stderr)
            failures.append(slug if isinstance(slug, str) and slug else "index.json")
            continue
        seen.add(slug)
        clean.append(entry)
    return clean


def main() -> int:
    index, failures = [], []
    index_file = ROOT / "index.json"
    previous = (json.loads(index_file.read_text(encoding="utf-8"))["cities"]
                if index_file.exists() else [])

    parse_umma.collect(index, failures)
    parse_islamdag.collect(index, failures)
    parse_jakim.collect(index, failures)
    # Узбекистан: официальный API Управления мусульман (official_feeds) вместо namozvaqti.uz
    parse_muftiyatkg.collect(index, failures)
    parse_diyanet.collect(index, failures)
    local_authorities.collect(index, failures)
    official_feeds.collect(index, failures)
    regional_feeds.collect(index, failures)
    dumkbr.collect(index, failures)

    # Сбой источника не должен выкидывать город из индекса: иначе приложение
    # молча перейдёт на собственный расчёт с другой методикой. Оставляем город,
    # если на сегодня у него лежат данные; алерт всё равно придёт через failures.
    got = {c.get("slug") for c in index if isinstance(c, dict)}
    today = datetime.now(timezone.utc).date()
    kept = []
    for entry in previous:
        if not isinstance(entry, dict) or entry.get("slug") in got:
            continue
        if isinstance(entry.get("slug"), str) and has_day(entry["slug"], today):
            index.append(entry)
            kept.append(entry["slug"])
    if kept:
        print(f"[WARN] город(а) оставлены в индексе после сбоя источника: {kept}", file=sys.stderr)

    # Города без данных на сегодня и битые записи — вон из индекса и в failures
    index = sanitize_index(index, failures, today)

    if index:
        (ROOT / "index.json").write_text(
            json.dumps({
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "cities": index,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] index.json — городов: {len(index)}")

    if failures:
        # Районы Турции без еженедельного прогона дают сотни slug — печатаем коротко
        shown = failures if len(failures) <= 40 else failures[:40] + [f"… и ещё {len(failures) - 40}"]
        print(f"[FAIL] источники с ошибками ({len(failures)}): {shown}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
