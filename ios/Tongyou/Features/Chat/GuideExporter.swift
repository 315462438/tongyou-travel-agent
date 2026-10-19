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

    static func longImage(title: String, markdown: String) -> UIImage? {
        let renderer = ImageRenderer(content: ExportPage(title: title, markdown: markdown))
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        renderer.scale = 1
        guard let probe = renderer.uiImage else { return nil }
        // Keep the bitmap under ~24k px tall so WeChat and Photos can still decode it.
        renderer.scale = max(1, min(2.5, 24_000 / max(probe.size.height, 1)))
        return renderer.uiImage
    }

    static func pdf(title: String, markdown: String) -> URL? {
        let renderer = ImageRenderer(content: ExportPage(title: title, markdown: markdown))
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        let url = DownloadFile.freshURL(name: fileName(title) + ".pdf")
        var ok = false
        renderer.render { size, draw in
            var box = CGRect(origin: .zero, size: size)
            guard let context = CGContext(url as CFURL, mediaBox: &box, nil) else { return }
            context.beginPDFPage(nil)
            draw(context)
            context.endPDFPage()
            context.closePDF()
            ok = true
        }
        return ok ? url : nil
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

private struct ExportPage: View {
    let title: String
    let markdown: String

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 10) {
                Image("LaunchMark").resizable().frame(width: 30, height: 30).clipShape(.rect(cornerRadius: 7, style: .continuous))
                Text("17同游 · 旅行攻略").font(.subheadline.weight(.semibold)).foregroundStyle(Palette.sky)
                Spacer()
            }
            MarkdownView(markdown)
            Divider()
            Text("由 17同游 生成 · 17tongyou.com").font(.caption).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
        }
        .padding(24)
        .frame(width: GuideExporter.width)
        .background(Color.white)
        .environment(\.markdownExporting, true)
        .environment(\.colorScheme, .light)
    }
}

/// Share menu for a finished answer.
struct GuideShareMenu: View {
    let markdown: String
    let fallbackTitle: String
    @State private var working = false

    var body: some View {
        Menu {
            Button("分享长图（微信好友、朋友圈）", systemImage: "photo") { export(image: true) }
            Button("导出 PDF 文件", systemImage: "doc.richtext") { export(image: false) }
            Button("复制文字", systemImage: "doc.on.doc") { UIPasteboard.general.string = markdown }
        } label: {
            if working { ProgressView() } else { Label("分享", systemImage: "square.and.arrow.up") }
        }
        .disabled(working)
    }

    private func export(image: Bool) {
        working = true
        let title = GuideExporter.title(for: markdown, fallback: fallbackTitle)
        // Let the menu close before the (synchronous) render so the spinner shows.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 150_000_000)
            if image, let rendered = GuideExporter.longImage(title: title, markdown: markdown) {
                // WeChat accepts a UIImage directly.
                GuideExporter.share([rendered])
            } else if !image, let url = GuideExporter.pdf(title: title, markdown: markdown) {
                GuideExporter.share([url])
            }
            working = false
        }
    }
}
