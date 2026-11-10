import SwiftUI

/// 回答里提到的店/景点：图、导航、加入行程。把「聊到的地方」接到行程里，不用另外搜、另外记。
struct PlaceCardsRow: View {
    let places: [ChatMessage.Place]
    @Environment(\.openURL) private var openURL
    @State private var picking: ChatMessage.Place?
    @State private var added: Set<String> = []

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 10) {
                ForEach(places, id: \.self) { place in
                    VStack(alignment: .leading, spacing: 0) {
                        Color.clear.frame(width: 208, height: 112)
                            .overlay {
                                if place.photo.isEmpty {
                                    Image(systemName: "mappin.and.ellipse").font(.title2).foregroundStyle(.secondary)
                                } else {
                                    RemoteImage(path: place.photo)
                                }
                            }
                            .background(.quaternary)
                            .clipped()
                        VStack(alignment: .leading, spacing: 4) {
                            Text(place.name).font(.subheadline.weight(.semibold)).lineLimit(1)
                            if !place.address.isEmpty {
                                Text(place.address).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                            HStack(spacing: 8) {
                                if let url = place.navURL {
                                    Button { openURL(url) } label: { Text("导航").frame(maxWidth: .infinity) }
                                        .buttonStyle(.glassProminent)
                                }
                                Button { picking = place } label: {
                                    Text(added.contains(place.name) ? "已加入" : "加入行程").frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.glass)
                                .disabled(added.contains(place.name))
                            }
                            .font(.footnote.weight(.medium))
                            .padding(.top, 6)
                        }
                        .padding(.horizontal, 12).padding(.vertical, 10)
                    }
                    .frame(width: 208)
                    .glassCard(cornerRadius: 18)
                    .clipShape(.rect(cornerRadius: 18))
                }
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
        .sheet(item: $picking) { place in
            AddPlaceSheet(place: place) { added.insert(place.name) }
                .presentationDetents([.medium, .large])
        }
    }
}

private struct AddPlaceSheet: View {
    let place: ChatMessage.Place
    let onAdded: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var trips: [TripSummary]?
    @State private var working = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if let trips {
                    ForEach(trips.filter { $0.role != "viewer" }) { trip in
                        Button { add(to: trip.id) } label: { Label(trip.title, systemImage: "map") }
                    }
                    Button { add(to: nil) } label: { Label("新建一个行程", systemImage: "plus") }
                } else {
                    ProgressView().frame(maxWidth: .infinity)
                }
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            }
            .disabled(working)
            .navigationTitle("把「\(place.name)」加入")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
            .task {
                trips = (try? await API.shared.get("trips", as: [TripSummary].self)) ?? []
            }
        }
    }

    private struct Created: Decodable { var id: String }

    private func add(to tripID: String?) {
        working = true
        error = nil
        Task {
            do {
                var id = tripID
                if id == nil {
                    id = try await API.shared.post("trips", body: ["title": "\(place.name)之行", "destination": "", "days": 1],
                                                   as: Created.self).id
                }
                _ = try await API.shared.request("POST", "trips/\(id!)/stops",
                                                 body: ["day": 1, "name": place.name, "location": place.location, "note": place.address])
                Haptics.success()
                onAdded()
                dismiss()
            } catch {
                Haptics.error()
                self.error = "加入行程失败，请重试。"
            }
            working = false
        }
    }
}

/// 回答末尾的追问：点一下就发出去，不用打字。只在最后一条回答下面出现。
struct SuggestionChips: View {
    let items: [String]
    let onPick: (String) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(items, id: \.self) { text in
                    Button { onPick(text) } label: {
                        Text(text).font(.subheadline).padding(.horizontal, 14).padding(.vertical, 9)
                    }
                    .buttonStyle(TravelPressStyle())
                    .foregroundStyle(Palette.sky)
                    .glassPill()
                }
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }
}
