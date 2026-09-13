// Проверка совместимости данных namaz-data со ВЫШЕДШИМИ версиями приложения.
// Структуры скопированы один в один из PrayerTimesKBR (OfficialTimetables.swift, v1.3)
// и виджета (WidgetPrayerData.swift). Индекс декодируется целиком: одна битая запись
// лишает старое приложение официальных таблиц для ВСЕХ городов.
// Запуск: swift scripts/compat/check_app_decoding.swift <путь к namaz-data>
import Foundation

struct IndexCity: Codable {
    let slug: String, name: String, country: String
    let lat: Double, lon: Double
    let timezone: String, madhab: String, source: String
}
struct Index: Codable { let updated: String; let cities: [IndexCity] }
struct MonthDay: Codable {
    let date: String, fajr: String, sunrise: String, dhuhr: String,
        asr: String, maghrib: String, isha: String
}
struct MonthFile: Codable { let slug: String; let days: [MonthDay] }
struct WidgetOfficialMonth: Decodable {
    struct Day: Decodable { let date, fajr, sunrise, dhuhr, asr, maghrib, isha: String }
    let days: [Day]
}

let root = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ".")
var errors: [String] = []
let decoder = JSONDecoder()
let hhmm = try! NSRegularExpression(pattern: "^\\d{1,2}:\\d{2}$")
func isTime(_ s: String) -> Bool { hhmm.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil }

// 1. Индекс
let indexData = try Data(contentsOf: root.appendingPathComponent("index.json"))
guard let index = try? decoder.decode(Index.self, from: indexData) else {
    do { _ = try decoder.decode(Index.self, from: indexData) } catch { print("❌ index.json НЕ декодируется: \(error)") }
    exit(1)
}
print("✓ index.json декодируется структурой приложения: \(index.cities.count) городов")
let slugs = Set(index.cities.map(\.slug))
if slugs.count != index.cities.count { errors.append("в индексе повторяются slug") }
for c in index.cities {
    if !(-90...90).contains(c.lat) || !(-180...180).contains(c.lon) { errors.append("\(c.slug): координаты вне диапазона") }
    if TimeZone(identifier: c.timezone) == nil { errors.append("\(c.slug): неизвестный часовой пояс \(c.timezone)") }
    if !["hanafi", "shafi"].contains(c.madhab) { errors.append("\(c.slug): madhab «\(c.madhab)»") }
    if c.source.split(separator: " ").first == nil { errors.append("\(c.slug): пустой source") }
}

// 2. Месяцы: декодирование приложением и виджетом, формат времени, дата внутри файла
var files = 0, days = 0
let fm = FileManager.default
let timetables = root.appendingPathComponent("timetables")
let enumerator = fm.enumerator(at: timetables, includingPropertiesForKeys: nil)!
for case let url as URL in enumerator where url.pathExtension == "json" {
    files += 1
    let data = try Data(contentsOf: url)
    guard let month = try? decoder.decode(MonthFile.self, from: data) else {
        errors.append("\(url.path): не декодируется приложением"); continue
    }
    if (try? decoder.decode(WidgetOfficialMonth.self, from: data)) == nil {
        errors.append("\(url.path): не декодируется виджетом")
    }
    let ym = url.deletingPathExtension().lastPathComponent
    let rel = url.deletingLastPathComponent().path.replacingOccurrences(of: timetables.path + "/", with: "")
    if month.slug != rel { errors.append("\(url.path): slug «\(month.slug)» не совпадает с папкой «\(rel)»") }
    for d in month.days {
        days += 1
        if !d.date.hasPrefix(ym) { errors.append("\(url.path): день \(d.date) не из месяца \(ym)") }
        for t in [d.fajr, d.sunrise, d.dhuhr, d.asr, d.maghrib, d.isha] where !isTime(t) {
            errors.append("\(url.path): \(d.date) время «\(t)»")
        }
    }
    if !slugs.contains(month.slug) { errors.append("\(month.slug): файлы есть, а в индексе города нет") }
}
print("✓ проверено файлов месяцев: \(files), дней: \(days)")

// 3. У каждого города индекса есть данные на сегодня (иначе старое приложение молча уйдёт в расчёт)
let today = { () -> String in let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC"); return f.string(from: Date()) }()
var missingToday = 0
for c in index.cities {
    let url = timetables.appendingPathComponent(c.slug).appendingPathComponent("\(today.prefix(7)).json")
    guard let data = try? Data(contentsOf: url), let m = try? decoder.decode(MonthFile.self, from: data),
          m.days.contains(where: { $0.date == today }) else { missingToday += 1; errors.append("\(c.slug): нет данных на \(today)"); continue }
}
print(missingToday == 0 ? "✓ у всех \(index.cities.count) городов есть данные на \(today)" : "❌ без данных на сегодня: \(missingToday)")

if errors.isEmpty { print("✅ совместимо с вышедшими версиями приложения"); exit(0) }
print("❌ ошибок: \(errors.count)"); errors.prefix(30).forEach { print("  " + $0) }
exit(1)
