import SwiftUI

/// Drag only the handle so map gestures and itinerary scrolling remain independent.
struct TripMapPanel<MapContent: View, Content: View>: View {
    @ViewBuilder let map: (CGFloat) -> MapContent
    @ViewBuilder let content: () -> Content
    @State private var level = 1
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        GeometryReader { geometry in
            let landscape = geometry.size.width > geometry.size.height * 1.3
            let heights = [min(240.0, geometry.size.height * 0.6), max(300.0, geometry.size.height * 0.58), geometry.size.height * 0.83]
            let height = min(heights[level], geometry.size.height - 70)
            if landscape {
                HStack(spacing: 0) { map(0); content().padding(12).frame(width: geometry.size.width * 0.48).background(.regularMaterial) }
            } else {
                ZStack(alignment: .bottom) {
                    map(height).ignoresSafeArea(edges: .bottom)
                    VStack(spacing: 8) {
                        HStack {
                            Text("当天行程").font(.caption2).foregroundStyle(.secondary)
                            Spacer()
                            Button { change(level == 2 ? 0 : level + 1) } label: {
                                Image(systemName: level == 2 ? "chevron.down" : "chevron.up").frame(width: 44, height: 30)
                            }.accessibilityLabel(level == 2 ? "收起行程面板" : "展开行程面板")
                        }
                        .overlay(alignment: .top) { Capsule().fill(.secondary.opacity(0.35)).frame(width: 36, height: 4).padding(.top, 4).allowsHitTesting(false) }
                        .contentShape(.rect)
                        .gesture(DragGesture(minimumDistance: 12).onEnded { value in
                            if abs(value.translation.height) > 24 { change(level + (value.translation.height < 0 ? 1 : -1)) }
                        })
                        .accessibilityIdentifier("tripPanelHandle")
                        content()
                    }
                    .padding(.horizontal, 16).padding(.top, 8)
                    .frame(height: height)
                    .background { UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28).fill(.regularMaterial).ignoresSafeArea(edges: .bottom) }
                    .overlay(alignment: .top) { UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28).stroke(.white.opacity(0.18), lineWidth: 0.5).allowsHitTesting(false) }
                    .shadow(color: .black.opacity(0.08), radius: 16, y: -4)
                    .accessibilityIdentifier("tripRoutePanel")
                }
            }
        }
    }
    private func change(_ value: Int) {
        withAnimation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.86)) { level = min(2, max(0, value)) }
    }
}
