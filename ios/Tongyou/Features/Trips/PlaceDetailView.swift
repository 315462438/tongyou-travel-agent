import SwiftUI

private struct PlaceDetails: Decodable {
    var status: String
    var description: String
    var descriptionSource: String
    var guideExcerpt: String
    var photos: [Photo]
    var facts: [Fact]
    var sourceUrl: String?
    struct Photo: Decodable, Hashable { var url: String; var source: String }
    struct Fact: Decodable, Hashable { var label: String; var value: String; var source: String }
}

struct PlaceDetailView: View {
    let tripID: String
    let stop: TripDetail.Stop
    let onEdit: () -> Void
    @State private var details: PlaceDetails?
    @State private var loading = true
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text(stop.name).font(.title.bold()).fixedSize(horizontal: false, vertical: true)
                    HStack { Chip(text: "Day \(stop.day)", symbol: "calendar"); if let time = stop.startTime, !time.isEmpty { Chip(text: time, symbol: "clock") } }
                    if loading {
                        ProgressView("正在整理地点资料…").frame(maxWidth: .infinity).frame(height: 180)
                    } else if let photos = details?.photos, !photos.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 12) {
                                ForEach(photos, id: \.self) { photo in
                                    VStack(alignment: .leading, spacing: 5) {
                                        RemoteImage(path: photo.url).frame(width: 270, height: 200).clipShape(.rect(cornerRadius: 24)).accessibilityLabel(stop.name + "实景照片")
                                        Text(photo.source).font(.caption2).foregroundStyle(.secondary)
                                    }.scrollTargetLayout()
                                }
                            }
                        }.scrollTargetBehavior(.viewAligned).accessibilityIdentifier("placePhotos")
                    } else {
                        Label("暂无可靠实景照片", systemImage: "photo").font(.subheadline).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity).frame(height: 150).background(Palette.sky.opacity(0.07), in: .rect(cornerRadius: 22))
                    }
                    if let error { retry(error) }
                    else if details?.status == "temporary_error" { retry("地图资料暂时不可用，原行程已保留") }
                    VStack(alignment: .leading, spacing: 10) {
                        HStack { Text("行程介绍").font(.title3.bold()); Text(details?.descriptionSource ?? "行程说明").font(.caption).foregroundStyle(.secondary) }
                        let note = details?.description ?? stop.note ?? ""
                        if note.isEmpty { Text("还没有地点介绍，可以编辑补充你的安排。").foregroundStyle(.secondary).font(.subheadline) }
                        else { MarkdownView(note) }
                    }
                    if let excerpt = details?.guideExcerpt, !excerpt.isEmpty, excerpt != details?.description {
                        VStack(alignment: .leading, spacing: 10) { Text("原攻略节选").font(.title3.bold()); MarkdownView(excerpt) }
                    }
                    if let facts = details?.facts, !facts.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack { Text("地点信息").font(.title3.bold()); Text("高德地图").font(.caption).foregroundStyle(.secondary) }
                            ForEach(facts, id: \.self) { fact in
                                HStack(alignment: .top, spacing: 14) { Text(fact.label).foregroundStyle(.secondary).frame(width: 72, alignment: .leading); Text(fact.value); Spacer(minLength: 0) }.font(.subheadline)
                            }
                        }.padding(16).background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 20))
                    }
                    if let price = stop.ticketPrice { Text("行程记录的参考费用：¥\(Int(price))，以现场信息为准。").font(.caption).foregroundStyle(.secondary) }
                    if let source = details?.sourceUrl, let url = URL(string: source) { Link("在高德地图查看资料 ↗", destination: url).font(.caption) }
                }.padding(20)
            }
            .safeAreaInset(edge: .bottom) {
                HStack(spacing: 12) {
                    if let url = stop.navigationURL { Button { openURL(url) } label: { Label("导航", systemImage: "location.north").frame(minHeight: 30) }.buttonStyle(.glassProminent) }
                    else { Text("位置待补充").font(.caption).foregroundStyle(.secondary) }
                    Button { dismiss(); onEdit() } label: { Label("编辑安排", systemImage: "pencil").frame(minHeight: 30) }.buttonStyle(.glass)
                    Spacer()
                }.padding(.horizontal, 20).padding(.vertical, 10).background(.regularMaterial)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("关闭", systemImage: "xmark") { dismiss() }.accessibilityIdentifier("closePlaceDetail") } }
            .screenBackground()
            .task(id: stop.id) { await load() }
        }.presentationDetents([.large]).presentationDragIndicator(.visible).accessibilityIdentifier("placeDetail")
    }
    private func retry(_ message: String) -> some View {
        HStack { Text(message).font(.caption).foregroundStyle(.secondary); Spacer(); Button("重试") { Task { await load() } } }
    }
    private func load() async {
        loading = true; error = nil
        defer { loading = false }
        do { details = try await API.shared.get("trips/\(tripID)/stops/\(stop.id)/details", as: PlaceDetails.self) }
        catch { self.error = error.localizedDescription }
    }
}
