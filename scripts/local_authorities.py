#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Времена намаза от МЕСТНЫХ духовных управлений — для стран, которые раньше
ошибочно брались из турецкого Diyanet (у Diyanet другая методика: в Мекке Иша
выходила на 18–20 минут раньше Умм-аль-Кура, в Азербайджане Аср на 49 минут
раньше, в Лондоне Фаджр на 22–28 минут раньше).

Официальные потоки (данные самого ведомства):
  SA — календарь Умм-аль-Кура, KACST: umqserv.kacst.gov.sa, год по координатам
  QA — Министерство вакфов Катара: islam.gov.qa, по дням
  OM — Министерство вакфов и религиозных дел Омана: mara.gov.om, по месяцам

Расчёт по опубликованной методике ведомства (машиночитаемого потока нет):
  AE — Awqaf ОАЭ, KW — Минвакф Кувейта, BH — Высший совет по исламским делам,
  EG — Египетская служба геодезии, AZ — Управление мусульман Кавказа (QMİ),
  GB — Moonsighting Committee с поправками единого расписания Лондона (LUPT).
Параметры подобраны и сверены с официальными таблицами (см. calc_engine.py).

Если официальный поток недоступен, недостающие месяцы дописываются расчётом
по профилю страны, уже сохранённые официальные дни не затираются.
"""

import calendar as cal
import json
import pathlib
import re
import ssl
import sys
import time
import urllib.parse
import zlib
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from calc_engine import KEYS, Profile, month_schedule   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 NamazZamanBot/1.0 (+https://github.com/Tolik1661/namaz-data)"

# Сервер mara.gov.om отдаёт только конечный сертификат без промежуточного.
# Проверку не отключаем: докладываем промежуточный DigiCert (скачан с cacerts.digicert.com,
# SHA-256 C8:02:5F:9F:…:25:A9, действует до 2031-03-29) к системным корневым.
CERTS = pathlib.Path(__file__).resolve().parent / "certs"


def ssl_context_with_intermediate():
    ctx = ssl.create_default_context()
    try:
        import certifi                              # локально на macOS; в Actions хватает системных
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    ctx.load_verify_locations(str(CERTS / "digicert-global-g2-tls-rsa-sha256-2020-ca1.pem"))
    return ctx


HORIZON_MONTHS = 13          # текущий месяц + 12 вперёд

# ── Профили расчёта ────────────────────────────────────────────────────────
# Поправки — минуты к Фаджру/восходу/Зухру/Асру/Магрибу/Ише.

PROFILES = {
    # Резервные профили SA/QA/OM подогнаны по официальным данным ведомств
    # (SA — 1975 дней по 5 городам, QA — 61, OM — 91): 99–100% дней в пределах ±1 мин.
    # Календарь Умм-аль-Кура: 18,5°, Иша через 90 мин (в Рамадан 120)
    "SA": Profile("Умм-аль-Кура (KACST)", fajr_angle=18.5, isha_angle=None, isha_minutes=90,
                  isha_minutes_ramadan=120, adjust={"dhuhr": 1, "asr": 1, "maghrib": 1, "isha": 1}),
    # Катар: 18°, Магриб = закат + 2, Иша через 90 мин круглый год
    "QA": Profile("Минвакф Катара", fajr_angle=18, isha_angle=None, isha_minutes=90,
                  maghrib_minutes=2, adjust={"fajr": -1, "sunrise": -1, "maghrib": 1, "isha": 1}),
    # Оман: 18°/18°, Магриб = закат + 5
    "OM": Profile("Минвакф Омана", fajr_angle=18, isha_angle=18, maghrib_minutes=5,
                  adjust={"fajr": 1, "dhuhr": 6, "asr": 6, "maghrib": 1, "isha": 1}),
    # ОАЭ (Awqaf): 18,2°/18,2°, восход −4, Зухр и Магриб +3
    "AE": Profile("Awqaf ОАЭ", fajr_angle=18.2, isha_angle=18.2,
                  adjust={"sunrise": -4, "dhuhr": 3, "maghrib": 3}),
    # Кувейт: 18°/17,5°
    "KW": Profile("Минвакф Кувейта", fajr_angle=18, isha_angle=17.5),
    # Бахрейн: 18,5°/18°, сверено с годовым календарём 1448 г.х. (355 из 355 дней ±1)
    "BH": Profile("Высший совет по исламским делам Бахрейна", fajr_angle=18.5, isha_angle=18,
                  adjust={"fajr": 1, "sunrise": -1, "dhuhr": 1, "maghrib": 1, "isha": -1}),
    # Египет: 19,5°/17,5°
    "EG": Profile("Египетская служба геодезии", fajr_angle=19.5, isha_angle=17.5),
    # Азербайджан (QMİ): 15,8°/15°, Магриб — Солнце 3,5° под горизонтом, ханафитский Аср
    "AZ": Profile("Управление мусульман Кавказа (QMİ)", fajr_angle=15.8, isha_angle=15,
                  maghrib_angle=3.5, asr_factor=2, madhab="hanafi"),
    # Великобритания: сезонные сумерки Moonsighting Committee + поправки LUPT
    "GB": Profile("Moonsighting Committee", fajr_angle=18,
                  isha_angle=18, moonsighting=True, adjust={"sunrise": -3, "dhuhr": 5, "maghrib": 3}),
    # Лондон: мечети следуют единому расписанию LUPT, построенному на наблюдениях, — формулой
    # его Фаджр и Ишу не воспроизвести (лучшая модель — 29% дней ±1). До подключения фида LUPT
    # Иша сдвинута на безопасную сторону: раньше LUPT в 3% дней против 87% без сдвига.
    "GB-LON": Profile("Moonsighting Committee (поправки к единому расписанию Лондона)", fajr_angle=18,
                      isha_angle=18, moonsighting=True,
                      adjust={"sunrise": -3, "dhuhr": 5, "maghrib": 3, "isha": 8}),
}

# Рамадан по календарю Умм-аль-Кура (для резервного расчёта SA; официальный поток KACST
# уже учитывает Рамадан). Даты — из ответов KACST, 1 рамадана … 29/30 рамадана.
RAMADAN_UQ = {
    1447: ("2026-02-18", "2026-03-19"),
    1448: ("2027-02-08", "2027-03-08"),
    1449: ("2028-01-28", "2028-02-25"),
    1450: ("2029-01-16", "2029-02-13"),
}

# ── Города (slug и координаты прежние — их знают вышедшие версии приложения) ──

def _c(slug, name, country, lat, lon, tz, **extra):
    return {"slug": slug, "name": name, "country": country, "lat": lat, "lon": lon, "timezone": tz, **extra}


CITIES = [
    _c("sa/mekke", "Мекка", "SA", 21.4225, 39.8262, "Asia/Riyadh"),
    _c("sa/medine", "Медина", "SA", 24.5247, 39.5692, "Asia/Riyadh"),
    _c("sa/riyadh", "Эр-Рияд", "SA", 24.7136, 46.6753, "Asia/Riyadh"),
    _c("sa/jeddah", "Джидда", "SA", 21.4858, 39.1925, "Asia/Riyadh"),
    _c("sa/dammam", "Даммам", "SA", 26.4207, 50.0888, "Asia/Riyadh"),
    _c("qa/doha", "Доха", "QA", 25.2854, 51.5310, "Asia/Qatar"),
    _c("om/muscat", "Маскат", "OM", 23.5880, 58.3829, "Asia/Muscat", mara_city=0),
    _c("ae/dubai", "Дубай", "AE", 25.2048, 55.2708, "Asia/Dubai"),
    _c("ae/abu-dhabi", "Абу-Даби", "AE", 24.4539, 54.3773, "Asia/Dubai"),
    _c("ae/sharjah", "Шарджа", "AE", 25.3463, 55.4209, "Asia/Dubai"),
    _c("kw/kuwait", "Эль-Кувейт", "KW", 29.3759, 47.9774, "Asia/Kuwait"),
    _c("bh/manama", "Манама", "BH", 26.2285, 50.5860, "Asia/Bahrain"),
    _c("eg/cairo", "Каир", "EG", 30.0444, 31.2357, "Africa/Cairo"),
    _c("eg/alexandria", "Александрия", "EG", 31.2001, 29.9187, "Africa/Cairo"),
    _c("az/baku", "Баку", "AZ", 40.4093, 49.8671, "Asia/Baku"),
    _c("az/gence", "Гянджа", "AZ", 40.6828, 46.3606, "Asia/Baku"),
    _c("az/sumqayit", "Сумгаит", "AZ", 40.5897, 49.6686, "Asia/Baku"),
    _c("az/mingacevir", "Мингечевир", "AZ", 40.7703, 47.0496, "Asia/Baku"),
    _c("az/lenkeran", "Ленкорань", "AZ", 38.7529, 48.8475, "Asia/Baku"),
    _c("az/seki", "Шеки", "AZ", 41.1919, 47.1706, "Asia/Baku"),
    _c("az/nahcivan", "Нахичевань", "AZ", 39.2089, 45.4122, "Asia/Baku"),
    _c("az/quba", "Губа", "AZ", 41.3611, 48.5125, "Asia/Baku"),
    _c("az/samaxi", "Шемаха", "AZ", 40.6319, 48.6414, "Asia/Baku"),
    _c("az/yevlax", "Евлах", "AZ", 40.6172, 47.1500, "Asia/Baku"),
    _c("az/salyan", "Сальян", "AZ", 39.5942, 48.9787, "Asia/Baku"),
    _c("az/astara", "Астара", "AZ", 38.4561, 48.8786, "Asia/Baku"),
    _c("az/tovuz", "Товуз", "AZ", 40.9922, 45.6289, "Asia/Baku"),
    _c("az/zaqatala", "Закаталы", "AZ", 41.6336, 46.6433, "Asia/Baku"),
    _c("gb/london", "Лондон", "GB", 51.5074, -0.1278, "Europe/London", profile="GB-LON"),
    _c("gb/birmingham", "Бирмингем", "GB", 52.4862, -1.8904, "Europe/London"),
    _c("gb/manchester", "Манчестер", "GB", 53.4808, -2.2426, "Europe/London"),
]

# Первое слово подписи — короткое имя источника: вышедшие версии приложения показывают
# «официальная таблица (<первое слово>)». Поле kind в index.json различает официальные
# таблицы и расчёт по методике (новые версии приложения подписывают их по-разному).
def sa_kacst_cities():
    """Города календаря Умм-аль-Кура (снимок ummulqura.org.sa/assets/data/cities.json).
    Пропускаем точки в 10 км от уже известных городов и дубли ближе 2 км."""
    import math
    raw = json.loads((pathlib.Path(__file__).resolve().parent / "data" / "sa_cities_kacst.json").read_text(encoding="utf-8"))
    known = [(c["lat"], c["lon"]) for c in CITIES if c["country"] == "SA"]

    def km(a, b):
        return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))
    out, used = [], {c["slug"] for c in CITIES}
    for c in raw:
        p = (c["latitude"], c["longitude"])
        if any(km(p, k) < 10 for k in known) or any(km(p, (o["lat"], o["lon"])) < 2 for o in out):
            continue
        slug = "sa/" + (re.sub(r"[^a-z0-9]+", "-", c["name_en"].lower()).strip("-") or str(c["id"]))
        while slug in used:
            slug += "-2"
        used.add(slug)
        out.append(_c(slug, c["name_en"], "SA", c["latitude"], c["longitude"], "Asia/Riyadh"))
    return out


CITIES += sa_kacst_cities()

OFFICIAL_SOURCE = {
    "SA": ("KACST (календарь Умм-аль-Кура — официальная таблица Саудовской Аравии)",
           "https://www.ummulqura.org.sa/en/prayer-times"),
    "QA": ("islam.gov.qa (Министерство вакфов и исламских дел Катара — официальная таблица)",
           "https://www.islam.gov.qa"),
    "OM": ("mara.gov.om (Министерство вакфов и религиозных дел Омана — официальная таблица)",
           "https://www.mara.gov.om"),
}
CALC_SOURCE = {
    "SA": "KACST (расчёт по методике календаря Умм-аль-Кура)",
    "QA": "islam.gov.qa (расчёт по методике Министерства вакфов Катара)",
    "OM": "mara.gov.om (расчёт по методике Министерства вакфов Омана)",
    "AE": "Awqaf (расчёт по методике Awqaf ОАЭ)",
    "KW": "Awqaf (расчёт по методике Министерства вакфов Кувейта)",
    "BH": "almajles.gov.bh (расчёт по методике Высшего совета по исламским делам Бахрейна)",
    "EG": "ESA (расчёт по методике Египетской службы геодезии)",
    "AZ": "QMİ (расчёт по методике Управления мусульман Кавказа)",
    "GB": "Moonsighting (расчёт по методике Moonsighting Committee)",
    "GB-LON": "Moonsighting (расчёт Moonsighting Committee с поправками к единому расписанию Лондона)",
}
CALC_URL = "https://github.com/Tolik1661/namaz-data/blob/main/scripts/local_authorities.py"


# ── Общие помощники ────────────────────────────────────────────────────────

def http(url, data=None, tries=3, timeout=40, headers=None, context=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    hdrs = {"User-Agent": UA, **(headers or {})}
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
                return r.read()
        except Exception:                                             # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def due_today(slug, today):
    """Годовые источники обновляем раз в неделю; дни недели разнесены по городам."""
    return zlib.crc32(slug.encode()) % 7 == today.toordinal() % 7


def minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def validate_day(slug, d):
    for k in KEYS:
        if not re.fullmatch(r"\d{2}:\d{2}", d.get(k) or ""):
            raise ValueError(f"{slug}: битое время {k} в {d}")
    seq = [minutes(d[k]) for k in KEYS]
    if seq != sorted(seq):
        raise ValueError(f"{slug}: немонотонные времена {d}")


def horizon(today):
    y, m = today.year, today.month
    for _ in range(HORIZON_MONTHS):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def ramadan_days():
    days = set()
    for start, end in RAMADAN_UQ.values():
        d, last = date.fromisoformat(start), date.fromisoformat(end)
        while d <= last:
            days.add(d.isoformat())
            d += timedelta(1)
    return frozenset(days)


def stored_month(city, y, m):
    f = ROOT / "timetables" / city["slug"] / f"{y:04d}-{m:02d}.json"
    return json.loads(f.read_text()) if f.exists() else None


def write_month(city, y, m, days, source, source_url, madhab):
    out = ROOT / "timetables" / city["slug"]
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{y:04d}-{m:02d}.json").write_text(json.dumps({
        "city": city["name"], "slug": city["slug"], "country": city["country"],
        "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
        "madhab": madhab, "source": source, "source_url": source_url,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "year": y, "month": m, "days": days,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


# ── Официальные потоки ─────────────────────────────────────────────────────

def fetch_kacst_year(city, year):
    """Календарь Умм-аль-Кура: весь год по координатам города."""
    url = ("https://umqserv.kacst.gov.sa/api/v1/Prayer/GetPrayerByYear"
           f"?lang=en&format=24&yg={year}&lat={city['lat']}&lon={city['lon']}&zone=3")
    data = json.loads(http(url))
    out = {}
    for item in data:
        g, p = item["gregorianDate"], item["prayerTimes"]
        ds = f"{g['year']:04d}-{g['month']:02d}-{g['day']:02d}"
        d = {"date": ds, "fajr": p["fajr"], "sunrise": p["sunrise"], "dhuhr": p["dhuhr"],
             "asr": p["asr"], "maghrib": p["maghrib"], "isha": p["isha"]}
        validate_day(city["slug"], d)
        out[ds] = d
    if len(out) < 360:
        raise ValueError(f"{city['slug']}: KACST вернул {len(out)} дней за {year}")
    return out


def fetch_qatar_day(day):
    """Минвакф Катара: один день (по пятницам вместо Dhuhr приходит Jummah)."""
    url = ("https://meiaservicesext.islam.gov.qa/ServicesBrokerGatewayAPI/api/PrayerTimes"
           f"?date={day.day:02d}-{day.month:02d}-{day.year}")
    data = json.loads(http(url))
    g = data["gregorianDate"]
    if (g["year"], g["month"], g["day"]) != (day.year, day.month, day.day):
        raise ValueError(f"qa/doha: запрошен {day}, пришёл {g['date']}")
    names = {"fajr": "fajr", "sunrise": "sunrise", "dhuhr": "dhuhr", "jummah": "dhuhr",
             "asr": "asr", "maghrib": "maghrib", "isha": "isha"}
    d = {"date": day.isoformat()}
    for t in data["times"]:
        key = names.get(t["prayerTimeName"].strip().lower())
        if key:
            d[key] = f"{int(t['time']['hour']):02d}:{int(t['time']['minutes']):02d}"
    # Часы у ведомства 12-часовые в timeFormat, но hour — 24-часовой; проверяем порядок
    validate_day("qa/doha", d)
    return d


def fetch_oman_month(city, year, month):
    """Минвакф Омана: месяц HTML-таблицей, Аср/Магриб/Иша в 12-часовом формате."""
    raw = http("https://www.mara.gov.om/arabic/calendar_page2.asp",
               data={"year": year, "month": month, "CityID": city["mara_city"], "B1": "x"},
               headers={"User-Agent": "Mozilla/5.0 (compatible; NamazZamanBot/1.0)"},
               context=ssl_context_with_intermediate())
    html = raw.decode("utf-8", errors="replace")
    days = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [re.sub(r"<[^>]+>|&nbsp;", " ", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if len(cells) < 7:
            continue
        dm = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cells[0])
        if not dm or (int(dm.group(2)), int(dm.group(3))) != (month, year):
            continue
        t = cells[1:7]
        if not all(re.fullmatch(r"\d{1,2}:\d{2}", x) for x in t):
            continue

        def h24(x, pm):
            hh, mm = map(int, x.split(":"))
            if pm and hh < 12:
                hh += 12
            return f"{hh:02d}:{mm:02d}"
        dhuhr_h = int(t[2].split(":")[0])
        d = {"date": f"{year:04d}-{month:02d}-{int(dm.group(1)):02d}",
             "fajr": h24(t[0], False), "sunrise": h24(t[1], False),
             "dhuhr": h24(t[2], dhuhr_h < 11),           # 12:xx — полдень, 01:xx — после полудня
             "asr": h24(t[3], True), "maghrib": h24(t[4], True), "isha": h24(t[5], True)}
        validate_day(city["slug"], d)
        days[d["date"]] = d
    if len(days) < cal.monthrange(year, month)[1]:
        raise ValueError(f"{city['slug']}: Оман вернул {len(days)} дней за {year}-{month:02d}")
    return days


# ── Сборка города ──────────────────────────────────────────────────────────

def build_city(city, today, failures, reset=False):
    country = city["country"]
    profile = PROFILES[city.get("profile", country)]
    folder = ROOT / "timetables" / city["slug"]
    if reset and folder.exists():
        for f in folder.glob("*.json"):
            f.unlink()                     # прежние месяцы Diyanet не должны остаться

    calc_source = CALC_SOURCE[city.get("profile", country)]
    ramadan = ramadan_days() if country == "SA" else frozenset()
    official = {}

    try:
        if country == "SA":
            months = list(horizon(today))
            have_all = all((stored_month(city, y, m) or {}).get("source") == OFFICIAL_SOURCE["SA"][0]
                           for y, m in months[:2])
            if not have_all or due_today(city["slug"], today):
                for y in sorted({y for y, _ in months}):
                    official.update(fetch_kacst_year(city, y))
                    time.sleep(0.5)
        elif country == "QA":
            # Текущий и следующий месяц: только дни, которых ещё нет в официальных файлах
            for y, m in list(horizon(today))[:2]:
                have = stored_month(city, y, m)
                have_days = {d["date"]: d for d in (have or {}).get("days", [])} \
                    if have and have["source"] == OFFICIAL_SOURCE["QA"][0] else {}
                for dd in range(1, cal.monthrange(y, m)[1] + 1):
                    ds = f"{y:04d}-{m:02d}-{dd:02d}"
                    if ds in have_days:
                        official[ds] = have_days[ds]
                        continue
                    official[ds] = fetch_qatar_day(date(y, m, dd))
                    time.sleep(0.3)
        elif country == "OM":
            for y, m in list(horizon(today))[:3]:
                official.update(fetch_oman_month(city, y, m))
                time.sleep(1)
    except Exception as e:                                              # noqa: BLE001
        print(f"[ERROR] {city['slug']}: официальный поток: {e}", file=sys.stderr)
        failures.append(city["slug"])

    written = []
    for y, m in horizon(today):
        n = cal.monthrange(y, m)[1]
        month_official = [official.get(f"{y:04d}-{m:02d}-{d:02d}") for d in range(1, n + 1)]
        if country in OFFICIAL_SOURCE and all(month_official):
            src, url = OFFICIAL_SOURCE[country]
            write_month(city, y, m, month_official, src, url, profile.madhab)
            written.append(f"{y}-{m:02d}✓")
            continue
        existing = stored_month(city, y, m)
        if existing and country in OFFICIAL_SOURCE and existing["source"] == OFFICIAL_SOURCE[country][0]:
            written.append(f"{y}-{m:02d}=")        # официальный месяц уже лежит — не затираем расчётом
            continue
        days = month_schedule(profile, y, m, city["lat"], city["lon"], city["timezone"], ramadan)
        for d in days:
            validate_day(city["slug"], d)
        write_month(city, y, m, days, calc_source, CALC_URL, profile.madhab)
        written.append(f"{y}-{m:02d}")

    # Официальный — если данные ведомства получены сегодня или текущий месяц уже лежит официальным
    # (годовые источники вроде KACST опрашиваются раз в неделю)
    current = stored_month(city, today.year, today.month) or {}
    is_official = country in OFFICIAL_SOURCE and (bool(official) or current.get("source") == OFFICIAL_SOURCE[country][0])
    primary = OFFICIAL_SOURCE[country][0] if is_official else calc_source
    print(f"[OK] {city['slug']}: {' '.join(written)}")
    return {"slug": city["slug"], "name": city["name"], "country": country,
            "lat": city["lat"], "lon": city["lon"], "timezone": city["timezone"],
            "madhab": profile.madhab, "source": primary,
            "kind": "official" if is_official else "calculated"}


def collect(index, failures, today=None, reset=False):
    today = today or datetime.now(timezone.utc).date()
    for city in CITIES:
        try:
            index.append(build_city(city, today, failures, reset=reset))
        except Exception as e:                                          # noqa: BLE001
            print(f"[ERROR] {city['slug']}: {e}", file=sys.stderr)
            failures.append(city["slug"])


if __name__ == "__main__":
    idx, fails = [], []
    collect(idx, fails, reset="--reset" in sys.argv)
    print(f"городов: {len(idx)}, ошибок: {len(fails)}")
    sys.exit(1 if fails else 0)
