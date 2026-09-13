#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Движок расчёта времён намаза для стран, где у духовного управления нет
машиночитаемого потока. Порт алгоритма PrayTimes (та же математика, что у
Aladhan API) — профили стран подобраны и сверены именно по нему.

Возможности профиля:
  • угол Фаджра; Иша углом или интервалом после Магриба (+ отдельный интервал в Рамадан);
  • Магриб = закат, закат + N минут или угол Солнца под горизонтом;
  • Аср с тенью ×1 (джумхур) или ×2 (ханафитский);
  • правила высоких широт (середина ночи, 1/7 ночи, по углу);
  • сезонные сумерки Moonsighting Committee (Халид Шаукат) для Фаджра и Иши;
  • поправки в минутах по каждому намазу; ограничения «не раньше/не позже»;
  • округление к ближайшей минуте (как Aladhan) или вверх (как Kemenag).

Только стандартная библиотека: работает в GitHub Actions без pip.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


# ── Тригонометрия в градусах ───────────────────────────────────────────────

def _sin(d): return math.sin(math.radians(d))
def _cos(d): return math.cos(math.radians(d))
def _tan(d): return math.tan(math.radians(d))
def _asin(x): return math.degrees(math.asin(x))
def _acos(x): return math.degrees(math.acos(x))
def _atan2(y, x): return math.degrees(math.atan2(y, x))
def _acot(x): return math.degrees(math.atan(1 / x))
def _fix(a, b): a = a - b * math.floor(a / b); return a + b if a < 0 else a


# ── Профиль ────────────────────────────────────────────────────────────────

@dataclass
class Profile:
    name: str                               # «Умм-аль-Кура (KACST)»
    fajr_angle: float = 18.0
    isha_angle: float | None = 17.0         # None → isha_minutes
    isha_minutes: int | None = None         # интервал после Магриба
    isha_minutes_ramadan: int | None = None
    maghrib_angle: float | None = None      # угол Солнца под горизонтом
    maghrib_minutes: float = 0.0            # закат + N минут (если угол не задан)
    asr_factor: int = 1                     # 1 — джумхур, 2 — ханафитский
    high_lat: str = "angle"                 # angle | middle | seventh | none
    moonsighting: bool = False              # сезонные сумерки MCW
    shafaq: str = "general"                 # general | ahmer | abyad (для MCW)
    adjust: dict = field(default_factory=dict)   # {намаз: минуты}
    clamp: dict = field(default_factory=dict)    # {"fajr_min": "03:30", "isha_max": "23:30"}
    rounding: str = "nearest"               # nearest | up
    madhab: str = "shafi"                   # для index.json

    def adjustment(self, key):
        return self.adjust.get(key, 0)


# ── Солнце (PrayTimes) ─────────────────────────────────────────────────────

def _julian(y, m, d):
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _sun_position(jd):
    d = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * d, 360)
    q = _fix(280.459 + 0.98564736 * d, 360)
    l = _fix(q + 1.915 * _sin(g) + 0.020 * _sin(2 * g), 360)
    e = 23.439 - 0.00000036 * d
    ra = _atan2(_cos(e) * _sin(l), _cos(l)) / 15
    eqt = q / 15 - _fix(ra, 24)
    decl = _asin(_sin(e) * _sin(l))
    return decl, eqt


class _Day:
    def __init__(self, day, lat, lon, tz):
        self.day, self.lat, self.lon = day, lat, lon
        noon = datetime(day.year, day.month, day.day, 12)
        self.tz_hours = ZoneInfo(tz).utcoffset(noon).total_seconds() / 3600
        self.jdate = _julian(day.year, day.month, day.day) - lon / (15 * 24)

    def mid_day(self, t):
        _, eqt = _sun_position(self.jdate + t)
        return _fix(12 - eqt, 24)

    def sun_angle_time(self, angle, t, ccw=False):
        decl, _ = _sun_position(self.jdate + t)
        noon = self.mid_day(t)
        x = (-_sin(angle) - _sin(decl) * _sin(self.lat)) / (_cos(decl) * _cos(self.lat))
        if x < -1 or x > 1:
            return float("nan")
        h = _acos(x) / 15
        return noon - h if ccw else noon + h

    def asr_time(self, factor, t):
        decl, _ = _sun_position(self.jdate + t)
        angle = -_acot(factor + _tan(abs(self.lat - decl)))
        return self.sun_angle_time(angle, t)


# ── Сезонные сумерки Moonsighting Committee ────────────────────────────────

def _days_since_solstice(day, lat):
    doy = day.timetuple().tm_yday
    leap = day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)
    days_in_year = 366 if leap else 365
    if lat >= 0:
        d = doy + 10
        if d >= days_in_year:
            d -= days_in_year
    else:
        d = doy - (173 if leap else 172)
        if d < 0:
            d += days_in_year
    return d


def _seasonal(dyy, a, b, c, d):
    if dyy < 91:
        return a + (b - a) / 91.0 * dyy
    if dyy < 137:
        return b + (c - b) / 46.0 * (dyy - 91)
    if dyy < 183:
        return c + (d - c) / 46.0 * (dyy - 137)
    if dyy < 229:
        return d + (c - d) / 46.0 * (dyy - 183)
    if dyy < 275:
        return c + (b - c) / 46.0 * (dyy - 229)
    return b + (a - b) / 91.0 * (dyy - 275)


def _mcw_morning(day, lat):
    """Минуты до восхода, когда наступает Фаджр."""
    la = abs(lat)
    return _seasonal(_days_since_solstice(day, lat),
                     75 + 28.65 / 55.0 * la, 75 + 19.44 / 55.0 * la,
                     75 + 32.74 / 55.0 * la, 75 + 48.10 / 55.0 * la)


def _mcw_evening(day, lat, shafaq):
    """Минуты после заката, когда наступает Иша."""
    la = abs(lat)
    if shafaq == "ahmer":
        abcd = (62 + 17.40 / 55.0 * la, 62 - 7.16 / 55.0 * la, 62 + 5.12 / 55.0 * la, 62 + 19.44 / 55.0 * la)
    elif shafaq == "abyad":
        abcd = (75 + 25.60 / 55.0 * la, 75 + 7.16 / 55.0 * la, 75 + 36.84 / 55.0 * la, 75 + 81.84 / 55.0 * la)
    else:
        abcd = (75 + 25.60 / 55.0 * la, 75 + 2.050 / 55.0 * la, 75 - 9.210 / 55.0 * la, 75 + 6.140 / 55.0 * la)
    return _seasonal(_days_since_solstice(day, lat), *abcd)


# ── Расчёт дня ─────────────────────────────────────────────────────────────

RISE_SET_ANGLE = 0.833


def _hhmm_to_hours(s):
    h, m = s.split(":")
    return int(h) + int(m) / 60


def compute_day(profile, day, lat, lon, tz, ramadan=False):
    """Времена дня в часах местного времени (float), до округления."""
    sd = _Day(day, lat, lon, tz)

    # PrayTimes: одна итерация уточнения от стартовых приближений (часы / 24)
    t0 = {"fajr": 5, "sunrise": 6, "dhuhr": 12, "asr": 13, "sunset": 18, "maghrib": 18, "isha": 18}
    p = {k: v / 24 for k, v in t0.items()}
    raw = {
        "fajr": sd.sun_angle_time(profile.fajr_angle, p["fajr"], ccw=True),
        "sunrise": sd.sun_angle_time(RISE_SET_ANGLE, p["sunrise"], ccw=True),
        "dhuhr": sd.mid_day(p["dhuhr"]),
        "asr": sd.asr_time(profile.asr_factor, p["asr"]),
        "sunset": sd.sun_angle_time(RISE_SET_ANGLE, p["sunset"]),
        "maghrib": sd.sun_angle_time(profile.maghrib_angle, p["maghrib"])
                   if profile.maghrib_angle is not None else float("nan"),
        "isha": sd.sun_angle_time(profile.isha_angle, p["isha"])
                if profile.isha_angle is not None else float("nan"),
    }

    # Переход к местному времени
    shift = sd.tz_hours - lon / 15
    t = {k: v + shift for k, v in raw.items()}

    night = _fix(t["sunrise"] - t["sunset"], 24)

    if profile.moonsighting:
        # Фаджр — не раньше сезонных сумерек, Иша — не позже (как в Adhan/Aladhan)
        safe_fajr = t["sunrise"] - _mcw_morning(day, lat) / 60
        if math.isnan(t["fajr"]) or safe_fajr > t["fajr"]:
            t["fajr"] = safe_fajr
        if profile.isha_angle is not None:
            safe_isha = t["sunset"] + _mcw_evening(day, lat, profile.shafaq) / 60
            if math.isnan(t["isha"]) or safe_isha < t["isha"]:
                t["isha"] = safe_isha
    elif profile.high_lat != "none":
        def portion(angle):
            if profile.high_lat == "middle":
                return night / 2
            if profile.high_lat == "seventh":
                return night / 7
            return night * angle / 60

        fp = portion(profile.fajr_angle)
        if math.isnan(t["fajr"]) or _fix(t["sunrise"] - t["fajr"], 24) > fp:
            t["fajr"] = t["sunrise"] - fp
        if profile.isha_angle is not None:
            ip = portion(profile.isha_angle)
            if math.isnan(t["isha"]) or _fix(t["isha"] - t["sunset"], 24) > ip:
                t["isha"] = t["sunset"] + ip
        if profile.maghrib_angle is not None:
            mp = portion(profile.maghrib_angle)
            if math.isnan(t["maghrib"]) or _fix(t["maghrib"] - t["sunset"], 24) > mp:
                t["maghrib"] = t["sunset"] + mp

    if profile.maghrib_angle is None:
        t["maghrib"] = t["sunset"] + profile.maghrib_minutes / 60

    if profile.isha_angle is None:
        minutes = profile.isha_minutes_ramadan if (ramadan and profile.isha_minutes_ramadan) else profile.isha_minutes
        t["isha"] = t["maghrib"] + minutes / 60

    out = {k: t[k] + profile.adjustment(k) / 60 for k in KEYS}

    if "fajr_min" in profile.clamp:
        out["fajr"] = max(out["fajr"], _hhmm_to_hours(profile.clamp["fajr_min"]))
    if "isha_max" in profile.clamp:
        out["isha"] = min(out["isha"], _hhmm_to_hours(profile.clamp["isha_max"]))
    return out


def format_time(hours, rounding="nearest"):
    if math.isnan(hours):
        return None
    hours = _fix(hours, 24)
    total = hours * 60
    minutes = math.ceil(total - 1e-9) if rounding == "up" else math.floor(total + 0.5)
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def day_schedule(profile, day, lat, lon, tz, ramadan=False):
    t = compute_day(profile, day, lat, lon, tz, ramadan)
    out = {"date": day.isoformat()}
    for k in KEYS:
        # Восход при округлении вверх — вниз (безопасная сторона, как у Kemenag)
        rounding = "nearest" if (k == "sunrise" and profile.rounding == "up") else profile.rounding
        if k == "sunrise" and profile.rounding == "up":
            out[k] = format_time(t[k] - 0.5 / 60, "nearest")
        else:
            out[k] = format_time(t[k], rounding)
    return out


def month_schedule(profile, year, month, lat, lon, tz, ramadan_days=frozenset()):
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    days = []
    d = first
    while d < nxt:
        days.append(day_schedule(profile, d, lat, lon, tz, d.isoformat() in ramadan_days))
        d += timedelta(1)
    return days
