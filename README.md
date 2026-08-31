# namaz-data

Официальные расписания намазов для приложения **Namaz Zaman**.

Данные собираются автоматически (GitHub Actions, ежедневно в 03:00 UTC) из
официальных источников и публикуются как статические JSON. Приложение
использует их с приоритетом над астрономическим расчётом.

## Структура

```
index.json                        — список городов с официальными таблицами
timetables/<страна>/<город>/<YYYY-MM>.json — помесячные расписания
scripts/parse_umma.py             — парсер umma.ru
.github/workflows/update.yml      — ежедневное автообновление
```

## Схема файла месяца

```json
{
  "city": "Москва",
  "slug": "ru/moscow",
  "country": "RU",
  "lat": 55.7558, "lon": 37.6173,
  "timezone": "Europe/Moscow",
  "madhab": "hanafi",
  "source": "umma.ru (официальная таблица, ханафитский мазхаб)",
  "source_url": "https://umma.ru/raspisanie-namaza/moscow",
  "updated": "2026-08-31T20:00:00Z",
  "year": 2026, "month": 8,
  "days": [
    { "date": "2026-08-01", "fajr": "2:11", "sunrise": "4:30",
      "dhuhr": "12:41", "asr": "16:51", "maghrib": "20:41", "isha": "22:38" }
  ]
}
```

Поля дня совпадают со схемой `prayer_schedule.json` приложения.

## Источники

| Города | Источник | Мазхаб |
|---|---|---|
| Москва, Казань | [umma.ru](https://umma.ru/raspisanie-namaza/moscow) | ханафи |
| Алматы, Астана, Шымкент, Караганда, Актау, Атырау, Уральск, Костанай | [umma.ru](https://umma.ru/raspisanie-namaza/almaty) | ханафи |

Планируется: муфтияты Дагестана, Чечни, КЧР; Турция (Diyanet), Малайзия (JAKIM).

## Доступ из приложения

```
https://raw.githubusercontent.com/Tolik1661/namaz-data/main/index.json
https://raw.githubusercontent.com/Tolik1661/namaz-data/main/timetables/ru/moscow/2026-08.json
```

Атрибуция: данные принадлежат соответствующим источникам, используются
с указанием источника внутри приложения. Парсер ходит на источники не чаще
одного раза в сутки.
