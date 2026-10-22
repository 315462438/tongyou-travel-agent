import SwiftUI
import UIKit

extension EnvironmentValues {
    /// True while a guide is rendered off-screen for sharing: no scroll views, glass or async images.
    @Entry var markdownExporting = false
}

/// WeChat's share extension rejects long plain text but accepts images, so guides are shared as
/// natively rendered plan cards.
@MainActor
enum GuideExporter {
    static let width: CGFloat = 390

    static func longImages(title: String, markdown: String, book: Bool = false) -> [UIImage] {
        GuideCardRenderer.images(.parse(title: title, markdown: markdown), book: book)
    }

    /// A readable file name from the guide's first heading or the conversation title.
    static func title(for markdown: String, fallback: String) -> String {
        for line in markdown.split(separator: "\n").prefix(8) {
            let text = line.trimmingCharacters(in: .whitespaces)
            if text.hasPrefix("#") { return text.trimmingCharacters(in: CharacterSet(charactersIn: "# ")) }
        }
        return fallback.isEmpty ? "旅行攻略" : fallback
    }
}

/// One tap from a finished guide to its shareable plan cards.
struct GuideShareButton: View {
    let markdown: String
    let fallbackTitle: String
    @State private var preview = false

    var body: some View {
        Button { preview = true } label: { Label("分享计划单", systemImage: "square.and.arrow.up") }
            .sheet(isPresented: $preview) { GuideSharePreview(title: GuideExporter.title(for: markdown, fallback: fallbackTitle), markdown: markdown) }
    }
}
