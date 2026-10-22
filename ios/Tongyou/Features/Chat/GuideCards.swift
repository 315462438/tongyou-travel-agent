import SwiftUI

/// Compact entry for a 手账 poster; the full poster opens as a sheet.
struct PosterCard: View {
    let poster: JSONValue
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: 0) {
                RemoteImage(path: poster["overall_map"]?.string ?? poster["days"]?.array?.first?["map"]?.string)
                    .frame(height: 160).frame(maxWidth: .infinity).clipped()
                VStack(alignment: .leading, spacing: 6) {
                    Text(poster["title"]?.string ?? "旅行手账").font(.title3.bold())
                    if let subtitle = poster["subtitle"]?.string { Text(subtitle).font(.subheadline).foregroundStyle(.secondary) }
                    HStack {
                        Chip(text: "\(poster["days"]?.array?.count ?? 0) 天", symbol: "calendar")
                        Chip(text: "\(poster["foods"]?.array?.count ?? 0) 美食", symbol: "fork.knife")
                        Spacer()
                        Text("查看手账").font(.subheadline.weight(.semibold)).foregroundStyle(Palette.sky)
                    }
                    .padding(.top, 4)
                }
                .padding(16)
            }
            .clipShape(.rect(cornerRadius: 24))
            .glassCard(cornerRadius: 24, interactive: true)
        }
        .buttonStyle(TravelPressStyle())
    }
}

struct PosterSheet: View {
    let poster: JSONValue
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(poster["destination"]?.string ?? "").font(.subheadline.weight(.semibold)).foregroundStyle(Palette.sky)
                        Text(poster["title"]?.string ?? "旅行手账").font(.largeTitle.bold())
                        if let subtitle = poster["subtitle"]?.string { Text(subtitle).foregroundStyle(.secondary) }
                    }
                    ForEach(Array((poster["days"]?.array ?? []).enumerated()), id: \.offset) { _, day in
                        VStack(alignment: .leading, spacing: 12) {
                            HStack(alignment: .firstTextBaseline) {
                                Text("Day \(day["day"]?.string ?? "")").font(.headline).foregroundStyle(Palette.sky)
                                Text(day["title"]?.string ?? "").font(.headline)
                            }
                            if let map = day["map"]?.string {
                                RemoteImage(path: map).frame(height: 170).frame(maxWidth: .infinity).clipShape(.rect(cornerRadius: 16))
                            }
                            ForEach(Array((day["stops"]?.array ?? []).enumerated()), id: \.offset) { index, stop in
                                HStack(alignment: .top, spacing: 12) {
                                    if let photo = stop["photo"]?.string, !photo.isEmpty {
                                        RemoteImage(path: photo).frame(width: 64, height: 64).clipShape(.rect(cornerRadius: 12))
                                    } else {
                                        Text("\(index + 1)").font(.headline).frame(width: 64, height: 64).glassCard(cornerRadius: 12)
                                    }
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(stop["name"]?.string ?? "").font(.subheadline.weight(.semibold))
                                        if let note = stop["note"]?.string { Text(note).font(.caption).foregroundStyle(.secondary) }
                                    }
                                }
                            }
                        }
                        .padding(16).glassCard(cornerRadius: 22)
                    }
                    section("住宿", items: poster["hotels"]?.array ?? []) { "\($0["area"]?.string ?? "") \($0["price"]?.string ?? "")" }
                    section("美食", items: poster["foods"]?.array ?? []) { $0["note"]?.string ?? "" }
                    if let tips = poster["tips"]?.array, !tips.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("小贴士").font(.title3.bold())
                            ForEach(Array(tips.enumerated()), id: \.offset) { _, tip in
                                Label(tip.string ?? "", systemImage: "lightbulb").font(.subheadline)
                            }
                        }
                    }
                }
                .padding(20)
            }
            .screenBackground()
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }

    @ViewBuilder private func section(_ title: String, items: [JSONValue], detail: @escaping (JSONValue) -> String) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text(title).font(.title3.bold())
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                            VStack(alignment: .leading, spacing: 6) {
                                RemoteImage(path: item["photo"]?.string).frame(width: 170, height: 110).clipShape(.rect(cornerRadius: 14))
                                Text(item["name"]?.string ?? "").font(.subheadline.weight(.semibold)).lineLimit(1)
                                Text(detail(item)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                            .frame(width: 170)
                            .padding(10).glassCard(cornerRadius: 18)
                        }
                    }
                }
                .scrollClipDisabled()
            }
        }
    }
}

struct BudgetCard: View {
    let budget: JSONValue

    private func yuan(_ value: JSONValue?) -> String {
        guard let amount = value?.double else { return "—" }
        return "¥" + Int(amount.rounded()).formatted()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Label("预算明细", systemImage: "yensign.circle").font(.headline)
                Spacer()
                Text("人均 " + yuan(budget["total"])).font(.title3.bold()).monospacedDigit()
            }
            if let headcount = budget["headcount"]?.int, headcount > 1 {
                Text("\(headcount) 人合计 \(yuan(budget["group_total"]))").font(.subheadline).foregroundStyle(.secondary)
            }
            ForEach(Array((budget["by_category"]?.array ?? []).enumerated()), id: \.offset) { _, row in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(row["category"]?.string ?? "").font(.subheadline)
                        Spacer()
                        Text(yuan(row["amount"])).font(.subheadline.weight(.medium)).monospacedDigit()
                    }
                    GeometryReader { geo in
                        Capsule().fill(Palette.sky.opacity(0.15))
                            .overlay(alignment: .leading) {
                                Capsule().fill(Palette.sky).frame(width: geo.size.width * min(1, (row["pct"]?.double ?? 0) / 100))
                            }
                    }
                    .frame(height: 6)
                }
            }
            if let notes = budget["notes"]?.array, !notes.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(notes.enumerated()), id: \.offset) { _, note in
                        Text("· " + (note.string ?? "")).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(18)
        .glassCard(cornerRadius: 24)
    }
}
