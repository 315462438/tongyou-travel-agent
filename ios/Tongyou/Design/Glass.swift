import SwiftUI

/// Visual language: content sits on a soft sky-to-paper backdrop; every control floats on Liquid Glass.
enum Palette {
    static let sky = Color(red: 0.145, green: 0.388, blue: 0.922)        // #2563EB, the site's brand blue
    static let dusk = Color(red: 0.42, green: 0.36, blue: 0.95)
    static let warm = Color(red: 0.98, green: 0.62, blue: 0.36)
}

struct Backdrop: View {
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        ZStack {
            (scheme == .dark ? Color(red: 0.05, green: 0.06, blue: 0.09) : Color(red: 0.95, green: 0.96, blue: 0.99))
            // Soft colour fields give the glass something to refract.
            Circle().fill(Palette.sky.opacity(scheme == .dark ? 0.35 : 0.22)).frame(width: 420).blur(radius: 90).offset(x: -150, y: -330)
            Circle().fill(Palette.dusk.opacity(scheme == .dark ? 0.28 : 0.16)).frame(width: 360).blur(radius: 90).offset(x: 170, y: -120)
            Circle().fill(Palette.warm.opacity(scheme == .dark ? 0.16 : 0.14)).frame(width: 340).blur(radius: 100).offset(x: 120, y: 360)
        }
        .ignoresSafeArea()
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = 24, interactive: Bool = false) -> some View {
        glassEffect(interactive ? .regular.interactive() : .regular, in: .rect(cornerRadius: cornerRadius))
    }

    func glassPill(tint: Color? = nil, interactive: Bool = true) -> some View {
        var glass = Glass.regular
        if let tint { glass = glass.tint(tint) }
        if interactive { glass = glass.interactive() }
        return glassEffect(glass, in: .capsule)
    }

    func screenBackground() -> some View {
        background(Backdrop())
    }
}

/// Small label chip used for metadata (days, budget, sources).
struct Chip: View {
    let text: String
    var symbol: String?
    var body: some View {
        HStack(spacing: 4) {
            if let symbol { Image(systemName: symbol).imageScale(.small) }
            Text(text)
        }
        .font(.caption.weight(.medium))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 9).padding(.vertical, 5)
        .glassEffect(.regular, in: .capsule)
    }
}

struct EmptyState: View {
    let symbol: String
    let title: String
    let message: String
    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: symbol).font(.system(size: 38, weight: .light)).foregroundStyle(.secondary)
            Text(title).font(.headline)
            Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(40)
        .frame(maxWidth: .infinity)
    }
}
