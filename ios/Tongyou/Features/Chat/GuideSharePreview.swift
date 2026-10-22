import SwiftUI
import Photos

struct GuideSharePreview: View {
    let title: String
    let markdown: String
    @Environment(\.dismiss) private var dismiss
    @State private var images: [UIImage] = []
    @State private var saving = false
    @State private var saved = false
    @State private var sharing = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    Text(images.count > 1 ? "共 \(images.count) 张，全部日期都在。可一次分享或保存。" : "一张轻便的计划单，带上就出发。")
                        .font(.subheadline).foregroundStyle(.secondary)
                    ForEach(images.indices, id: \.self) { index in
                        Image(uiImage: images[index]).resizable().scaledToFit()
                            .clipShape(.rect(cornerRadius: 24))
                            .shadow(color: .black.opacity(0.06), radius: 14, y: 6)
                            .accessibilityLabel("\(title)，第 \(index + 1) 张，共 \(images.count) 张")
                    }
                    Text("简版只保留行程安排，详细说明可在分享菜单导出完整 PDF。")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(20)
            }
            .screenBackground()
            .navigationTitle("分享计划单")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.accessibilityIdentifier("closeGuidePreview") } }
            .safeAreaInset(edge: .bottom) {
                HStack(spacing: 12) {
                    Button { save() } label: {
                        Label(saving ? "保存中…" : saved ? "已保存" : "保存到相册", systemImage: saved ? "checkmark" : "arrow.down.to.line")
                            .frame(maxWidth: .infinity).padding(.vertical, 9)
                    }.buttonStyle(.glass).disabled(images.isEmpty || saving)
                    Button { sharing = true } label: {
                        Label("分享图片", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity).padding(.vertical, 9)
                    }.buttonStyle(.glassProminent).disabled(images.isEmpty)
                }.padding(.horizontal, 20).padding(.vertical, 12).background(.regularMaterial)
            }
            .task { images = GuideExporter.longImages(title: title, markdown: markdown) }
            .sheet(isPresented: $sharing) { GuideActivitySheet(items: images) }
            .alert("暂时无法保存", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
                Button("好") { error = nil }
            } message: { Text(error ?? "") }
        }
    }

    private func save() {
        guard !saving else { return }
        saving = true
        Task { @MainActor in
            defer { saving = false }
            let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
            guard status == .authorized || status == .limited else {
                error = "请在系统设置中允许 17同游添加照片，也可以使用“分享图片”保存。"; return
            }
            do {
                let copies = images
                try await PHPhotoLibrary.shared().performChanges {
                    for image in copies { PHAssetChangeRequest.creationRequestForAsset(from: image) }
                }
                saved = true
            } catch { self.error = "保存失败：" + error.localizedDescription }
        }
    }
}

struct GuideActivitySheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
