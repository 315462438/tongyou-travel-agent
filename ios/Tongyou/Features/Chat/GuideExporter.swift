import SwiftUI
import UIKit

extension EnvironmentValues {
    /// True while a guide is rendered off-screen for sharing: no scroll views, glass or async images.
    @Entry var markdownExporting = false
}

/// WeChat's share extension rejects long plain text; it accepts images and files. Guides are therefore
/// shared as a long image (chats and Moments) or a PDF (file transfer), both rendered natively.
@MainActor
enum GuideExporter {
    static let width: CGFloat = 390

    static func longImages(title: String, markdown: String) -> [UIImage] {
        GuideCardRenderer.images(.parse(title: title, markdown: markdown))
    }

    static func pdf(title: String, markdown: String) -> URL? {
        let url = DownloadFile.freshURL(name: fileName(title) + ".pdf")
        return GuideCardRenderer.pdf(title: title, markdown: markdown, url: url) ? url : nil
    }

    /// A readable file name from the guide's first heading or the conversation title.
    static func title(for markdown: String, fallback: String) -> String {
        for line in markdown.split(separator: "\n").prefix(8) {
            let text = line.trimmingCharacters(in: .whitespaces)
            if text.hasPrefix("#") { return text.trimmingCharacters(in: CharacterSet(charactersIn: "# ")) }
        }
        return fallback.isEmpty ? "旅行攻略" : fallback
    }

    private static func fileName(_ title: String) -> String {
        let cleaned = title.components(separatedBy: CharacterSet(charactersIn: "/\\:*?\"<>|")).joined(separator: "_")
        return String(cleaned.prefix(40))
    }

    static func share(_ items: [Any]) {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              var top = scene.keyWindow?.rootViewController else { return }
        while let presented = top.presentedViewController, !presented.isBeingDismissed { top = presented }
        let sheet = UIActivityViewController(activityItems: items, applicationActivities: nil)
        sheet.popoverPresentationController?.sourceView = top.view
        top.present(sheet, animated: true)
    }
}

/// Share menu for a finished answer.
struct GuideShareMenu: View {
    let markdown: String
    let fallbackTitle: String
    @State private var working = false
    @State private var preview = false
    @State private var error: String?

    var body: some View {
        Menu {
            Button("分享简版行程", systemImage: "photo") { preview = true }
            Button("导出完整 PDF（文字版）", systemImage: "doc.richtext") { exportPDF() }
            Button("复制文字", systemImage: "doc.on.doc") { UIPasteboard.general.string = markdown }
        } label: {
            if working { ProgressView() } else { Label("分享", systemImage: "square.and.arrow.up") }
        }
        .disabled(working)
        .sheet(isPresented: $preview) { GuideSharePreview(title: GuideExporter.title(for: markdown, fallback: fallbackTitle), markdown: markdown) }
        .alert("导出未完成", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) { Button("好") { error = nil } } message: { Text(error ?? "") }
    }

    private func exportPDF() {
        working = true
        let title = GuideExporter.title(for: markdown, fallback: fallbackTitle)
        // Let the menu close before the (synchronous) render so the spinner shows.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 150_000_000)
            if let url = GuideExporter.pdf(title: title, markdown: markdown) {
                GuideExporter.share([url])
            } else { error = "PDF 生成失败，请重试。" }
            working = false
        }
    }
}
