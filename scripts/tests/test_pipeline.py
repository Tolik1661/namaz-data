#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Юнит-тесты конвейера данных: строгий формат времени, аудит по дням, запись файлов
только при изменении, очистка индекса в build_all, ранние алерты о таблицах
следующего года. Без сети; файлы пишутся только во временные каталоги.

Запуск: python3 -m unittest discover -s scripts/tests
"""

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "compat"))

import audit_timetables                              # noqa: E402
import build_all                                     # noqa: E402
import check_schema                                  # noqa: E402
import dumkbr                                        # noqa: E402
import official_feeds                                # noqa: E402
from calc_engine import Profile, month_schedule      # noqa: E402
from local_authorities import validate_day, write_json_if_changed  # noqa: E402

GOOD_DAY = {"date": "2026-10-10", "fajr": "04:43", "sunrise": "06:13", "dhuhr": "12:03",
            "asr": "15:06", "maghrib": "17:34", "isha": "19:14"}


class StrictTimeFormat(unittest.TestCase):
    BAD = ["25:00", "24:00", "12:75", "99:99", "٠٤:٣٠", "04:30\n", "4:3", "", "04.30", " 04:30"]

    def test_validate_day_accepts_two_digit_24h(self):
        validate_day("t", GOOD_DAY)
        validate_day("t", {**GOOD_DAY, "fajr": "00:00", "isha": "23:59"})

    def test_validate_day_rejects_bad_times(self):
        for bad in self.BAD + ["4:30", None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_day("t", {**GOOD_DAY, "isha": bad})

    def test_file_level_regex_allows_one_digit_hour_only(self):
        # umma.ru и islamdag.ru хранят «2:11» — это допустимо и в приложении
        for ok in ("2:11", "02:11", "0:00", "23:59"):
            self.assertTrue(check_schema.TIME.fullmatch(ok), ok)
            self.assertTrue(audit_timetables.TIME.fullmatch(ok), ok)
        for bad in self.BAD:
            with self.subTest(bad=bad):
                self.assertIsNone(check_schema.TIME.fullmatch(bad))
                self.assertIsNone(audit_timetables.TIME.fullmatch(bad))
                with self.assertRaises(ValueError):
                    audit_timetables.to_min(bad)


class WriteIfChanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "ru" / "x" / "2026-10.json"
        self.data = {"city": "X", "slug": "ru/x", "lat": 43.4846, "lon": 43.6071, "source": "s",
                     "updated": "2026-09-01T00:00:00Z", "year": 2026, "month": 10, "days": [GOOD_DAY]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_updated_changed_is_not_rewritten(self):
        self.assertTrue(write_json_if_changed(self.path, self.data))
        before = self.path.read_text(encoding="utf-8")
        self.assertFalse(write_json_if_changed(self.path, {**self.data, "updated": "2026-09-23T00:00:00Z"}))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_changed_days_or_metadata_are_written(self):
        write_json_if_changed(self.path, self.data)
        self.assertTrue(write_json_if_changed(self.path, {**self.data, "days": [{**GOOD_DAY, "isha": "19:15"}]}))
        self.assertTrue(write_json_if_changed(self.path, {**self.data, "lat": 43.5}))
        self.assertTrue(write_json_if_changed(self.path, {**self.data, "source": "другой"}))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["source"], "другой")

    def test_broken_file_is_rewritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{битый", encoding="utf-8")
        self.assertTrue(write_json_if_changed(self.path, self.data))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["days"], [GOOD_DAY])


def index_entry(slug="ru/x", **over):
    e = {"slug": slug, "name": "X", "country": "RU", "lat": 43.48, "lon": 43.6, "timezone": "Europe/Moscow",
         "madhab": "hanafi", "source": "src (подпись)"}
    e.update(over)
    return e


class BuildAllIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.today = date(2026, 10, 10)

    def tearDown(self):
        self.tmp.cleanup()

    def put_month(self, slug, day):
        f = self.root / "timetables" / slug / f"{day:%Y-%m}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"slug": slug, "days": [{**GOOD_DAY, "date": day.isoformat()}]}), encoding="utf-8")

    def test_entry_problem(self):
        self.assertIsNone(build_all.entry_problem(index_entry()))
        self.assertIsNone(build_all.entry_problem(index_entry(lat=43)))           # int — тоже число
        e = index_entry()
        del e["timezone"]
        broken = [e, index_entry(lat="43.48"), index_entry(lon=True), index_entry(madhab="maliki"),
                  index_entry(timezone="Mars/Olympus"), index_entry(source=""), index_entry(lat=95.0),
                  index_entry(lat=float("nan")), "не объект", index_entry(name=None)]
        for b in broken:
            with self.subTest(entry=b):
                self.assertIsNotNone(build_all.entry_problem(b))

    def test_sanitize_drops_cities_without_today_and_broken(self):
        for slug in ("ru/a", "ru/b", "ru/dup"):
            self.put_month(slug, self.today)
        self.put_month("ru/stale", date(2026, 9, 30))       # данные только за прошлый месяц
        index = [index_entry("ru/a"), index_entry("ru/stale"), index_entry("ru/b", lat="x"),
                 index_entry("ru/dup"), index_entry("ru/dup", name="Дубль"), index_entry("ru/nofiles")]
        failures = []
        with contextlib.redirect_stderr(io.StringIO()):
            clean = build_all.sanitize_index(index, failures, self.today, self.root)
        self.assertEqual([e["slug"] for e in clean], ["ru/a", "ru/dup"])
        self.assertEqual(clean[1]["name"], "X")                   # остаётся первая запись slug
        self.assertEqual(sorted(failures), ["ru/b", "ru/dup", "ru/nofiles", "ru/stale"])

    def test_has_day(self):
        self.put_month("ru/a", self.today)
        self.assertTrue(build_all.has_day("ru/a", self.today, self.root))
        self.assertFalse(build_all.has_day("ru/a", date(2026, 10, 11), self.root))
        self.assertFalse(build_all.has_day("ru/none", self.today, self.root))


class AuditPerDay(unittest.TestCase):
    """Аудит на синтетическом городе: времена из calc_engine близки к астрономии,
    затем портим отдельные дни."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.slug = "kw/test"
        profile = Profile("test", fajr_angle=18, isha_angle=17.5)
        self.days = month_schedule(profile, 2026, 10, 29.3759, 47.9774, "Asia/Kuwait")
        (self.root / "index.json").write_text(json.dumps({"updated": "x", "cities": [
            {"slug": self.slug, "name": "T", "country": "KW", "lat": 29.3759, "lon": 47.9774,
             "timezone": "Asia/Kuwait", "madhab": "shafi", "source": "Test (расчёт)"}]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_audit(self):
        f = self.root / "timetables" / self.slug / "2026-10.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"slug": self.slug, "days": self.days}), encoding="utf-8")
        with mock.patch.object(audit_timetables, "ROOT", self.root):
            _, _, _, issues = audit_timetables.audit(date(2026, 10, 5))
        return [i for i in issues if "запас вперёд" not in i[3]]

    @staticmethod
    def shift(t, minutes):
        h, m = map(int, t.split(":"))
        v = h * 60 + m + minutes
        return f"{v // 60:02d}:{v % 60:02d}"

    def test_clean_month_has_no_issues(self):
        self.assertEqual(self.run_audit(), [])

    def test_single_day_maghrib_shift_is_error(self):
        self.days[10]["maghrib"] = self.shift(self.days[10]["maghrib"], 59)
        self.days[10]["isha"] = self.shift(self.days[10]["isha"], 59)          # порядок времён цел
        issues = self.run_audit()
        errors = [i for i in issues if i[0] == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("2026-10-11: maghrib", errors[0][3])

    def test_bad_format_is_error(self):
        self.days[3]["dhuhr"] = "11:75"
        errors = [i for i in self.run_audit() if i[0] == "ERROR"]
        self.assertTrue(any("2026-10-04: битый формат" in e[3] for e in errors))

    def test_fajr_hour_typo_is_warning_only(self):
        self.days[20]["fajr"] = self.shift(self.days[20]["fajr"], -60)
        issues = self.run_audit()
        self.assertEqual([i for i in issues if i[0] == "ERROR"], [])
        warns = [i for i in issues if i[0] == "WARN"]
        self.assertEqual(len(warns), 1)
        self.assertIn("2026-10-21: fajr", warns[0][3])

    def test_neighbor_angles_skip_ramadan(self):
        angles = {f"2027-02-{d:02d}": (18.0, 17.0) for d in range(1, 15)}
        for d in range(8, 15):                          # Иша +30 мин в Рамадан: у Мекки ≈ +6,5°
            angles[f"2027-02-{d:02d}"] = (18.0, 24.0)
        self.assertTrue(audit_timetables.neighbor_angle_issues(angles))
        skip = audit_timetables.ramadan_dates()
        self.assertIn("2027-02-06", skip)                                     # запас ±2 дня
        self.assertEqual(audit_timetables.neighbor_angle_issues(angles, skip), [])


class NextYearAlerts(unittest.TestCase):
    def run_dumkbr(self, today, years):
        table = {f"{y}-01-01": ["06:00", "07:30", "12:10", "14:40", "16:40", "18:20"] for y in years}
        known = {y: {k: v for k, v in table.items() if k.startswith(str(y))} for y in years}
        failures, index = [], []
        with mock.patch.object(dumkbr, "tables", return_value=known), \
                mock.patch.object(dumkbr, "write_horizon", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            dumkbr.collect(index, failures, today)
        return failures

    def test_dumkbr_alert_from_december_15(self):
        self.assertEqual(self.run_dumkbr(date(2026, 12, 10), [2026]), [])
        self.assertEqual(self.run_dumkbr(date(2026, 12, 15), [2026]), ["ru/nalchik"])
        self.assertEqual(self.run_dumkbr(date(2026, 12, 20), [2026, 2027]), [])
        self.assertEqual(self.run_dumkbr(date(2027, 1, 1), [2026]), ["ru/nalchik"])   # без дубля

    def test_rt_next_year_missing(self):
        dec = {"2026-12-31": {}}
        self.assertFalse(official_feeds.rt_next_year_missing(dec, date(2026, 12, 14)))
        self.assertTrue(official_feeds.rt_next_year_missing(dec, date(2026, 12, 15)))
        self.assertFalse(official_feeds.rt_next_year_missing({**dec, "2027-01-01": {}}, date(2026, 12, 20)))
        self.assertTrue(official_feeds.rt_next_year_missing({}, date(2026, 12, 20)))

    def test_fetch_online_skips_broken_link(self):
        page = b"https://cloud.mail.ru/public/aaa/1 https://cloud.mail.ru/public/bbb/2"
        good = b'"name":"2027kbr.pdf" weblink_get {"url": "https://srv"}'

        def fake_http(url, **kw):
            if url == "https://kbrdum.ru/":
                return page
            if url.endswith("aaa/1"):
                raise OSError("404")                                          # старая ссылка мертва
            return good if "cloud.mail.ru" in url else b"%PDF"
        with mock.patch.object(dumkbr, "http", side_effect=fake_http), \
                mock.patch.object(dumkbr, "parse_pdf", return_value=(2027, {"2027-01-01": []})), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(dumkbr.fetch_online(), {2027: {"2027-01-01": []}})
        self.assertIn("aaa/1", err.getvalue())


if __name__ == "__main__":
    unittest.main()
