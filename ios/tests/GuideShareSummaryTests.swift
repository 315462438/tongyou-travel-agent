import Foundation

@main struct GuideShareSummaryTests {
    static func main() {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ message: String) { precondition(condition(), message); checks += 1 }
        let markdown = """
        # 周末旅行
        ## Day 1 · 老城
        ### 当天路线
        | 时间 | 行程安排 | 费用 | 备注 |
        | --- | --- | --- | --- |
        | 09:00 | **森林公园** | ¥20 | 不进入卡片 |
        | 下午 | [半边街](https://example.com) | 待定 | |
        ## Day 2
        - 08:30 湖边
        - 植物园
        ![图](https://example.com/image.png)
        ## 预算
        不作为地点。
        """
        let summary = GuideShareSummary.parse(title: "周末旅行", markdown: markdown)
        check(summary.days.count == 2, "two days retained")
        check(summary.days[0].stops.map(\.name) == ["森林公园", "半边街"], "table uses only itinerary column")
        check(summary.days[1].stops.map(\.time) == ["08:30", ""], "no invented times")
        check(summary.days.last?.stops.last?.name == "植物园", "last stop retained")
        check(!summary.days.flatMap(\.stops).contains { $0.name.contains("http") }, "image and link noise stripped")
        let chinese = GuideShareSummary.parse(title: "游记", markdown: "## 第一天\n西湖 → 灵隐寺\n## 第二天\n- 河坊街")
        check(chinese.days.count == 2 && chinese.days[0].stops.count == 2, "Chinese headings and route arrows")
        let fallback = GuideShareSummary.parse(title: "笔记", markdown: "带雨伞。\n留足休息。")
        check(!fallback.isItinerary && fallback.days[0].stops.count == 2, "unstructured notes remain readable")
        let dates = GuideShareSummary.parse(title: "游记", markdown: "## 10.24 周六\n- 09:00 森林公园\n## 10.25 周日\n- 植物园")
        check(dates.days.count == 2, "date headings")
        let all = (1...7).map { day in GuideShareSummary.Day(title: "Day \(day)", stops: (1...8).map { .init(name: "第\(day)天地点\($0)", time: "") }) }
        let pages = GuideShareSummary(title: "七天", days: all, isItinerary: true).pages()
        check(pages.count > 1, "long trip paginates")
        check(pages.flatMap { $0 }.flatMap(\.stops) == all.flatMap(\.stops), "all stops preserved in order")
        let tableMarkdown = all.map { day in "## \(day.title)\n| 时间 | 地点 |\n| --- | --- |\n" + day.stops.map { "| 09:00 | \($0.name) |" }.joined(separator: "\n") }.joined(separator: "\n")
        let tables = GuideShareSummary.parse(title: "七日行程", markdown: tableMarkdown)
        check(tables.days.count == 7 && tables.days.flatMap(\.stops).count == 56, "names containing 第N天 do not create date headings")
        check(tables.pages().flatMap { $0 }.flatMap(\.stops).last?.name == "第7天地点8", "parsed final stop retained")
        check(GuideShareSummary.parse(title: "行程", markdown: "**Day 1**\n- 西湖").days[0].stops[0].name == "西湖", "bold day headings")
        let long = GuideShareSummary(title: "长内容", days: [.init(title: "笔记", stops: [.init(name: String(repeating: "内容", count: 300), time: "")])], isItinerary: false)
        check(long.pages().flatMap { $0 }.flatMap(\.stops).map(\.name).joined() == long.days[0].stops[0].name, "huge rows split without truncation")
        print("\(checks) share summary checks passed")
    }
}
