import Foundation

/// A local, deterministic reading copy. Times are copied from the guide, never inferred.
struct GuideShareSummary: Equatable {
    struct Stop: Equatable {
        var name: String
        var time: String
    }
    struct Day: Equatable {
        var title: String
        var stops: [Stop]
    }
    var title: String
    var days: [Day]
    var isItinerary: Bool

    static func plain(_ value: String) -> String {
        var text = value.replacingOccurrences(of: #"!\[[^\]]*\]\([^)]*\)"#, with: "", options: .regularExpression)
        text = text.replacingOccurrences(of: #"\[([^\]]+)\]\([^)]*\)"#, with: "$1", options: .regularExpression)
        text = text.replacingOccurrences(of: #"https?://\S+"#, with: "", options: .regularExpression)
        text = text.replacingOccurrences(of: #"[*_`#]"#, with: "", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func parse(title: String, markdown: String) -> Self {
        let lines = markdown.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var days: [Day] = []
        var current: Day?
        var header: [String] = []
        var fallback: [Stop] = []
        var skippingCode = false
        // Guides write "今日路线：A → B", then a timed table, then a few tips — the same places three times.
        // Keep one source per day, most reliable first: table > timed lines > route line > other lines.
        enum Source { case table, route, line }
        var buckets: [Source: [Stop]] = [:]
        func flush() {
            if var day = current {
                let table = buckets[.table] ?? [], route = buckets[.route] ?? [], other = buckets[.line] ?? []
                day.stops = !table.isEmpty ? table : other.contains { !$0.time.isEmpty } ? other : !route.isEmpty ? route : other
                days.append(day)
            }
            current = nil; buckets = [:]
        }
        func add(_ value: String, time: String = "", source: Source = .line) {
            let name = plain(value)
            guard !name.isEmpty else { return }
            let stop = Stop(name: name, time: plain(time))
            if current != nil {
                if buckets[source]?.last != stop { buckets[source, default: []].append(stop) }
            } else { fallback.append(stop) }
        }
        for raw in lines {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("```") { skippingCode.toggle(); continue }
            if skippingCode || line.isEmpty || line.hasPrefix("![") || line.hasPrefix("[[img:") { continue }
            let text = plain(line)
            let heading = line.hasPrefix("#") || (line.hasPrefix("**") && line.hasSuffix("**"))
            let dayPattern = #"(?i)(?:^|[\s·｜|])(?:day\s*\d+|第[一二三四五六七八九十\d]+[天日])"#
            let datePattern = #"^\d{1,2}[月./]\d{1,2}(?:日|\s|[｜|·：:]|$)"#
            if !line.hasPrefix("|") && !line.hasPrefix("-") && !line.hasPrefix("* ") && !line.hasPrefix("•") && (heading || text.count < 95) && (text.range(of: dayPattern, options: .regularExpression) != nil || text.range(of: datePattern, options: .regularExpression) != nil) {
                flush(); current = Day(title: text, stops: []); header = []; continue
            }
            // A new non-day section (budget, tips, restaurants, etc.) ends the current itinerary.
            if heading {
                if text.range(of: "预算|费用|住宿推荐|酒店推荐|美食推荐|注意事项|旅行贴士|行前|行李|总结|参考来源", options: .regularExpression) != nil { flush() }
                header = []
                if current == nil && text != plain(title) { fallback.append(Stop(name: text, time: "")) }
                continue
            }
            if line.hasPrefix("|") {
                let cells = line.trimmingCharacters(in: CharacterSet(charactersIn: "| ")).components(separatedBy: "|").map(plain)
                if cells.allSatisfy({ $0.allSatisfy { "-: ".contains($0) } }) { continue }
                if header.isEmpty { header = cells; continue }
                let placeIndex = header.firstIndex { $0.range(of: "地点|景点|安排|活动|行程|项目|去哪里", options: .regularExpression) != nil }
                let timeIndex = header.firstIndex { $0.contains("时间") || $0.contains("时段") }
                if let i = placeIndex, i < cells.count {
                    add(cells[i], time: timeIndex.flatMap { $0 < cells.count ? cells[$0] : nil } ?? "", source: .table)
                } else if current != nil {
                    add(cells.enumerated().filter { $0.offset != timeIndex }.map(\.element).joined(separator: " · "),
                        time: timeIndex.flatMap { $0 < cells.count ? cells[$0] : nil } ?? "", source: .table)
                }
                continue
            }
            header = []
            if ["---", "***", "___"].contains(line) || line.hasPrefix(">") { continue }
            let stripped = text.replacingOccurrences(of: #"^(?:[-+•]\s*|\d+[.、)]\s*)"#, with: "", options: .regularExpression)
            if current != nil {
                if stripped.contains("→") {
                    // "今日路线：" and similar labels are not places.
                    let route = stripped.replacingOccurrences(of: #"^[^→：:]{1,8}[：:]\s*"#, with: "", options: .regularExpression)
                    for part in route.components(separatedBy: "→") { add(part, source: .route) }
                } else if let range = stripped.range(of: #"^(?:[0-2]?\d[:：][0-5]\d(?:\s*[-–—~～至]\s*[0-2]?\d[:：][0-5]\d)?|上午|中午|下午|傍晚|晚上|早餐|午餐|晚餐)"#, options: .regularExpression) {
                    let name = String(stripped[range.upperBound...]).trimmingCharacters(in: CharacterSet(charactersIn: " ：:·｜|-–—"))
                    add(name.isEmpty ? stripped : name, time: String(stripped[range]))
                } else if line.hasPrefix("-") || line.hasPrefix("*") || line.hasPrefix("•") || stripped != text {
                    add(stripped)
                } else if !stripped.contains("：") && !stripped.contains("。") && stripped.count < 65 {
                    add(stripped)
                }
            } else if !stripped.isEmpty { fallback.append(Stop(name: stripped, time: "")) }
        }
        flush()
        let itinerary = days.contains { !$0.stops.isEmpty }
        if !itinerary { days = [Day(title: "旅行笔记", stops: fallback.isEmpty ? [Stop(name: plain(markdown).isEmpty ? "暂无可分享的内容" : plain(markdown), time: "")] : fallback)] }
        return Self(title: plain(title).isEmpty ? "我的旅行计划" : plain(title), days: days, isItinerary: itinerary)
    }

    /// Bounded cards, with continuation headings. Every extracted stop is included exactly once.
    func pages(maxUnits: Int = 24) -> [[Day]] {
        var pages: [[Day]] = [], page: [Day] = []
        var units = 0
        func flush() { if !page.isEmpty { pages.append(page) }; page = []; units = 0 }
        for day in days {
            var continuation = false
            let rows = day.stops.flatMap { stop -> [Stop] in
                let chars = Array(stop.name)
                return stride(from: 0, to: max(chars.count, 1), by: 100).map { offset in
                    Stop(name: String(chars.dropFirst(offset).prefix(100)), time: offset == 0 ? stop.time : "续")
                }
            }
            if rows.isEmpty {
                if units + 3 > maxUnits { flush() }
                page.append(Day(title: day.title, stops: [])); units += 3
            }
            for stop in rows {
                let cost = max(1, Int(ceil(Double(stop.name.count) / 19))) + 1
                if units + cost + (page.last?.title == day.title ? 0 : 2) > maxUnits { flush(); continuation = true }
                let label = day.title + (continuation ? " · 续" : "")
                if page.last?.title != label { page.append(Day(title: label, stops: [])); units += 2 }
                page[page.count - 1].stops.append(stop); units += cost
            }
        }
        flush()
        return pages
    }
}
