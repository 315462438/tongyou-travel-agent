#if DEBUG
import SwiftUI

/// Explicit test-only entry; avoids real account state and never writes to Photos.
struct ShareExportTestView: View {
    @State private var preview = false
    @State private var members = false
    @State private var result = "正在检查导出"
    private let short = """
    # 合肥情侣自然风光2日游
    ## Day 1 · 环巢湖线
    | 时间 | 行程安排 | 交通/费用 | 备注 |
    | --- | --- | --- | --- |
    | 09:00 | 合肥滨湖国家森林公园 | 自驾 | 慢慢散步 |
    | 12:00 | 湖畔午餐 | 待定 | |
    | 14:00 | 环巢湖大道自驾观景 | 自驾 | |
    | 16:30 | 红石咀公园 | 自驾 | |
    | 19:00 | 长临河古镇景区 | 自驾 | |
    ## Day 2 · 城市慢游
    - 09:00 蜀山森林公园
    - 11:30 半边街
    - 13:30 合肥植物园
    ## 旅行贴士
    完整攻略最后一条提示。
    """
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Text(result).accessibilityIdentifier("shareExportProbe")
                Button("预览简版") { preview = true }
                Button("邀请页") { members = true }
            }.padding().navigationTitle("分享验收")
                .sheet(isPresented: $preview) { GuideSharePreview(title: "合肥情侣自然风光2日游", markdown: short) }
                .sheet(isPresented: $members) {
                    MembersSheet(trip: TripDetail(id: "t1", title: "合肥情侣自然风光2日游", destination: "合肥", days: 2, members: [.init(username: "demo", role: "owner", online: false)], stops: []), isOwner: true) {}
                }
                .task { probe() }
        }
    }
    @MainActor private func probe() {
        do {
            let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("share-qa")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            var long = "# 七日完整行程\n"
            for day in 1...7 {
                long += "## Day \(day) · 城市散步\n| 时间 | 地点 |\n| --- | --- |\n"
                for stop in 1...6 { long += "| \(8 + stop):00 | 第\(day)天地点\(stop) |\n" }
            }
            var metrics: [[String: Any]] = []
            for (name, markdown) in [("short", short), ("long", long)] {
                let summary = GuideShareSummary.parse(title: name == "short" ? "合肥情侣自然风光2日游" : "七日完整行程", markdown: markdown)
                let images = GuideCardRenderer.images(summary)
                for (index, image) in images.enumerated() {
                    try image.pngData()?.write(to: dir.appendingPathComponent("\(name)-\(index).png"))
                    metrics.append(["name":name,"page":index,"width":image.cgImage!.width,"height":image.cgImage!.height])
                }
                if name == "long" {
                    let flattened = summary.pages().flatMap { $0 }.flatMap(\.stops).map(\.name)
                    guard flattened.count == 42, flattened.last == "第7天地点6" else { result = "失败：地点缺失"; return }
                }
            }
            try JSONSerialization.data(withJSONObject: metrics, options: .prettyPrinted).write(to: dir.appendingPathComponent("metrics.json"))
            result = "导出校验通过"
        } catch { result = "失败：\(error.localizedDescription)" }
    }
}
#endif
