import SwiftUI

struct TripStopThumbnail: View {
    let tripID: String
    let stop: TripDetail.Stop
    let index: Int
    @State private var path: String?
    private struct Preview: Decodable { var photos: [Photo]; struct Photo: Decodable { var url: String } }
    var body: some View {
        Group {
            if let path { RemoteImage(path: path) }
            else { Image(systemName: "mappin.and.ellipse").font(.title3).foregroundStyle(Palette.sky.opacity(0.6)).frame(maxWidth: .infinity, maxHeight: .infinity).background(Palette.sky.opacity(0.07)) }
        }
        .frame(width: 54, height: 54).clipShape(.rect(cornerRadius: 15))
        .overlay(alignment: .topLeading) {
            Text("\(index)").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                .frame(width: 19, height: 19).background(.regularMaterial, in: .circle).offset(x: -3, y: -3)
        }
        .accessibilityHidden(true)
        .task(id: stop.name + (stop.location ?? "")) {
            path = nil
            if let data = try? await API.shared.get("trips/\(tripID)/stops/\(stop.id)/details", as: Preview.self), !Task.isCancelled { path = data.photos.first?.url }
        }
    }
}
