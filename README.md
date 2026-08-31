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
| Махачкала, Каспийск, Дербент, Хасавюрт, Буйнакск, Избербаш, Кизляр, Кизилюрт, Даг. Огни, Ю.-Сухокумск | [islamdag.ru](https://islamdag.ru/vremya-namaza/mahachkala) (Муфтият РД) | шафии |
| Куала-Лумпур, Шах-Алам, Джохор-Бару, Джорджтаун, Ипох, Кота-Бару, Кучинг, Кота-Кинабалу | [JAKIM e-Solat](https://api.waktusolat.app) | шафии |
| Турция: Стамбул, Анкара, Измир, Бурса, Анталья, Конья | [Diyanet](https://namazvakitleri.diyanet.gov.tr) | аср по джумхуру |
| Европа: Берлин, Гамбург, Мюнхен, Кёльн, Франкфурт, Париж, Лион, Амстердам, Роттердам, Вена, Лондон, Бирмингем, Манчестер | [Diyanet](https://namazvakitleri.diyanet.gov.tr) | аср по джумхуру |

Итого: **47 городов, 9 стран**. Diyanet отдаёт таблицы на год вперёд.
Планируется: муфтияты Чечни, КЧР.
Проверено и НЕ работает: API ДУМ Казахстана (namaz.muftyat.kz/api — success:false
на все годы, включая пример из их документации) — Казахстан через umma.ru.

## Доступ из приложения

```
https://raw.githubusercontent.com/Tolik1661/namaz-data/main/index.json
https://raw.githubusercontent.com/Tolik1661/namaz-data/main/timetables/ru/moscow/2026-08.json
```

Атрибуция: данные принадлежат соответствующим источникам, используются
с указанием источника внутри приложения. Парсер ходит на источники не чаще
одного раза в сутки.
