#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оркестратор: запускает все парсеры и собирает единый index.json.
Частичный сбой одного источника не мешает остальным, но помечает прогон
кодом 1 — GitHub Actions пришлёт алерт.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import local_authorities  # noqa: E402
import official_feeds   # noqa: E402
import parse_diyanet    # noqa: E402
import parse_islamdag   # noqa: E402
import parse_jakim      # noqa: E402
import parse_muftiyatkg # noqa: E402
import parse_umma       # noqa: E402
import regional_feeds   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


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

    # Сбой источника не должен выкидывать город из индекса: иначе приложение
    # молча перейдёт на собственный расчёт с другой методикой. Оставляем город,
    # если на сегодня у него лежат данные; алерт всё равно придёт через failures.
    got = {c["slug"] for c in index}
    today = datetime.now(timezone.utc).date()
    kept = []
    for entry in previous:
        if entry["slug"] in got:
            continue
        month_file = ROOT / "timetables" / entry["slug"] / f"{today:%Y-%m}.json"
        if month_file.exists():
            days = json.loads(month_file.read_text(encoding="utf-8")).get("days", [])
            if any(d.get("date") == today.isoformat() for d in days):
                index.append(entry)
                kept.append(entry["slug"])
    if kept:
        print(f"[WARN] город(а) оставлены в индексе после сбоя источника: {kept}", file=sys.stderr)

    if index:
        (ROOT / "index.json").write_text(
            json.dumps({
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "cities": index,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] index.json — городов: {len(index)}")

    if failures:
        print(f"[FAIL] источники с ошибками: {failures}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
