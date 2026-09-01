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

import parse_diyanet    # noqa: E402
import parse_islamdag   # noqa: E402
import parse_jakim      # noqa: E402
import parse_muftiyatkg # noqa: E402
import parse_namozvaqti # noqa: E402
import parse_umma       # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    index, failures = [], []

    parse_umma.collect(index, failures)
    parse_islamdag.collect(index, failures)
    parse_jakim.collect(index, failures)
    parse_namozvaqti.collect(index, failures)
    parse_muftiyatkg.collect(index, failures)
    parse_diyanet.collect(index, failures)

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
