import PhotosUI
import SwiftUI

struct TripRef: Hashable { var id: String }

struct ChatView: View {
    @State private var store: ChatStore
    @State private var draft: String
    private let title: String
    private let sendOnAppear: Bool
    var onConversationChanged: (() -> Void)?

    init(conversationID: String?, title: String = "新对话", initialText: String = "", sendOnAppear: Bool = false,
         deep: Bool = false, onConversationChanged: (() -> Void)? = nil) {
        let store = ChatStore(conversationID: conversationID)
        store.deepReasoning = deep
        store.title = title
        _store = State(initialValue: store)
        _draft = State(initialValue: initialText)
        self.title = title
        self.sendOnAppear = sendOnAppear
        self.onConversationChanged = onConversationChanged
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                // Not lazy: guides are very tall rows, and a lazy stack's height estimates left the
                // view parked in blank space after jumping to the bottom of a long conversation.
                VStack(alignment: .leading, spacing: 18) {
                    if !store.loaded { ProgressView().frame(maxWidth: .infinity).padding(.top, 80) }
                    ForEach(store.visible) { message in
                        MessageRow(message: message, store: store, isLast: message.id == store.visible.last?.id)
                            .id(message.id)
                    }
                    if store.running { ThinkingPanel(store: store).id("thinking") }
                    if let error = store.error {
                        Label(error, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.red)
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .defaultScrollAnchor(.bottom)
            .onChange(of: store.messages.count) { old, _ in
                if old == 0, !store.running, let lastAsk = store.visible.last(where: { $0.role == "user" }) {
                    // Opening a past conversation: start at the latest question so its answer reads top-down.
                    Task { @MainActor in proxy.scrollTo(lastAsk.id, anchor: .top) }
                } else {
                    withAnimation(.snappy) { proxy.scrollTo("bottom", anchor: .bottom) }
                }
            }
            .onChange(of: store.running) { withAnimation(.snappy) { proxy.scrollTo("bottom", anchor: .bottom) } }
        }
        .safeAreaInset(edge: .bottom) {
            Composer(text: $draft, deep: $store.deepReasoning, webSearch: $store.webSearch, running: store.running,
                     onSend: { text, images in Task { await store.send(text, images: images) } },
                     onStop: store.stop)
                .padding(.horizontal, 12)
                .padding(.bottom, 6)
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .screenBackground()
        .task {
            store.onTurnFinished = onConversationChanged
            await store.load()
            if sendOnAppear, !draft.isEmpty {
                let text = draft
                draft = ""
                await store.send(text)
            }
        }
        .onDisappear { store.stopPolling() }
    }
}

// MARK: Rows

private struct MessageRow: View {
    let message: ChatMessage
    let store: ChatStore
    let isLast: Bool

    var body: some View {
        switch message.role {
        case "user": UserBubble(message: message)
        case "progress": ProgressRow(message: message, store: store, isLast: isLast)
        default: AssistantRow(message: message, store: store)
        }
    }
}

private struct UserBubble: View {
    let message: ChatMessage
    var body: some View {
        VStack(alignment: .trailing, spacing: 8) {
            if !message.images.isEmpty {
                HStack(spacing: 6) {
                    ForEach(message.images, id: \.self) { id in
                        RemoteImage(path: API.upload(id)).frame(width: 84, height: 84).clipShape(.rect(cornerRadius: 14))
                    }
                }
            }
            if !message.content.isEmpty {
                Text(message.content)
                    .textSelection(.enabled)
                    .padding(.horizontal, 15).padding(.vertical, 11)
                    .foregroundStyle(.white)
                    .glassEffect(.regular.tint(Palette.sky.opacity(0.85)), in: .rect(cornerRadius: 22))
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.leading, 48)
    }
}

private struct ProgressRow: View {
    let message: ChatMessage
    let store: ChatStore
    let isLast: Bool

    var body: some View {
        if let confirm = message.meta?["confirm"], let id = confirm["id"]?.string {
            ConfirmCard(question: confirm["question"]?.string ?? message.content, source: confirm["source"]?["title"]?.string,
                        reply: store.confirmReply(for: id), active: isLast && store.running) { store.confirm(id, choice: $0) }
        } else if let handoff = message.meta?["handoff"] {
            HandoffCard(handoff: handoff, text: message.content, conversationID: store.conversationID, active: isLast && store.running)
        } else if message.meta?["hint"]?.string == "deep_reasoning" {
            VStack(alignment: .leading, spacing: 12) {
                Label(message.content, systemImage: "brain").font(.subheadline)
                if let prompt = message.meta?["hint_prompt"]?.string, !store.running {
                    Button("用深度模式重新回答（约 2-6 分钟）") { Task { await store.send(prompt, deep: true) } }
                        .buttonStyle(.glass)
                } else if !store.deepReasoning {
                    Button("打开深度推理") { store.deepReasoning = true }.buttonStyle(.glass)
                } else {
                    Text("已开启深度推理，重新发送问题即可").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 20)
        } else if !message.content.isEmpty {
            Label(message.content, systemImage: "info.circle").font(.footnote).foregroundStyle(.secondary)
        }
    }
}

private struct ConfirmCard: View {
    let question: String
    let source: String?
    let reply: String?
    let active: Bool
    let choose: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("需要登录的来源", systemImage: "person.badge.key").font(.subheadline.weight(.semibold))
            Text(question).font(.subheadline)
            if let source { Text(source).font(.caption).foregroundStyle(.secondary) }
            if let reply {
                Text("已选择：\(reply == "login" ? "登录读取" : "跳过")").font(.footnote).foregroundStyle(.secondary)
            } else if active {
                GlassEffectContainer {
                    HStack {
                        Button("登录读取") { choose("login") }.buttonStyle(.glassProminent).tint(Palette.sky)
                        Button("跳过") { choose("skip") }.buttonStyle(.glass)
                    }
                }
            } else {
                Text("已超时自动跳过").font(.footnote).foregroundStyle(.secondary)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 20)
    }
}

private struct HandoffCard: View {
    let handoff: JSONValue
    let text: String
    let conversationID: String?
    let active: Bool
    @State private var tick = 0

    var body: some View {
        let site = handoff["site_name"]?.string ?? "网站"
        let remote = handoff["mode"]?.string == "remote"
        VStack(alignment: .leading, spacing: 10) {
            Label(remote ? "用 \(site) App 扫码登录" : "请在浏览器中登录\(site)", systemImage: "qrcode.viewfinder")
                .font(.subheadline.weight(.semibold))
            Text(text).font(.subheadline).foregroundStyle(.secondary)
            if remote, handoff["screenshot"]?.bool == true, active, let conversationID {
                RemoteImage(path: "/travel/api/chat/\(conversationID)/handoff-screenshot?t=\(tick)")
                    .frame(maxWidth: .infinity).frame(height: 300).clipShape(.rect(cornerRadius: 14))
                    .task(id: tick) {
                        try? await Task.sleep(nanoseconds: 4_000_000_000)
                        tick += 1
                    }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 20)
    }
}

private struct AssistantRow: View {
    let message: ChatMessage
    let store: ChatStore
    @State private var showReasoning = false
    @State private var showSources = false
    @State private var importing = false
    @State private var openTrip: TripRef?
    @State private var showPoster = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !message.candidates.isEmpty {
                candidates
            } else if let poster = message.meta?["poster"], !poster.isNull {
                PosterCard(poster: poster) { showPoster = true }
                    .sheet(isPresented: $showPoster) { PosterSheet(poster: poster) }
            } else if let budget = message.meta?["budget"], !budget.isNull {
                BudgetCard(budget: budget)
            } else {
                answer
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .navigationDestination(item: $openTrip) { TripDetailView(tripID: $0.id) }
    }

    private var candidates: some View {
        VStack(alignment: .leading, spacing: 10) {
            MarkdownView(message.content)
            ForEach(message.candidates, id: \.self) { candidate in
                Button { Task { await store.send("去\(candidate.name)") } } label: {
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(candidate.name).font(.headline)
                                if !candidate.tag.isEmpty { Chip(text: candidate.tag) }
                            }
                            Text(candidate.reason).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                        }
                        Spacer()
                        Image(systemName: "arrow.up.right").foregroundStyle(Palette.sky)
                    }
                    .padding(14).glassCard(cornerRadius: 18, interactive: true)
                }
                .buttonStyle(TravelPressStyle())
                .disabled(store.running)
            }
            Text("都不合适？直接说个地名，或者让我来定。").font(.footnote).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private var answer: some View {
        if message.preliminary {
            Label("初步判断 · 正在查证实时资料，完整分析稍后送到", systemImage: "lightbulb")
                .font(.caption.weight(.medium)).foregroundStyle(.orange)
        }
        if let reasoning = message.reasoning, !reasoning.isEmpty {
            DisclosureGroup(isExpanded: $showReasoning) {
                Text(reasoning).font(.footnote).foregroundStyle(.secondary).textSelection(.enabled).padding(.top, 6)
            } label: {
                Label("思考过程", systemImage: "sparkles").font(.footnote.weight(.medium)).foregroundStyle(.secondary)
            }
            .tint(.secondary)
        }
        if message.content.isEmpty && message.streaming {
            Label("正在生成…", systemImage: "ellipsis").font(.subheadline).foregroundStyle(.secondary).symbolEffect(.variableColor.iterative)
        } else {
            TypewriterMarkdown(message.content, active: message.streaming)
        }
        if message.streaming && !message.content.isEmpty {
            Text("已生成 \(message.content.count) 字").font(.caption).foregroundStyle(.secondary)
        }
        if !message.sources.isEmpty {
            DisclosureGroup(isExpanded: $showSources) {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(message.sources, id: \.self) { source in
                        if let url = URL(string: source.url) {
                            Link(destination: url) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(source.title).font(.subheadline).lineLimit(2).multilineTextAlignment(.leading)
                                    Text(source.host).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                .padding(.top, 8)
            } label: {
                Label("参考了 \(message.sources.count) 个网站 · \(message.sources.prefix(3).map(\.host).joined(separator: "、"))", systemImage: "globe")
                    .font(.footnote.weight(.medium)).foregroundStyle(.secondary).lineLimit(1)
            }
            .tint(.secondary)
            .padding(12).glassCard(cornerRadius: 16)
        }
        if let saved = message.meta?["memories_saved"]?.array?.filter({ $0["op"]?.string != "delete" }), !saved.isEmpty {
            Label("已记住：" + saved.compactMap { $0["content"]?.string ?? $0["key"]?.string }.joined(separator: "；"), systemImage: "brain.head.profile")
                .font(.caption).foregroundStyle(.secondary)
        }
        if !message.streaming && message.isGuide { actions }
    }

    private var actions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: 8) {
                HStack(spacing: 8) {
                    GuideShareButton(markdown: message.content, fallbackTitle: store.title)
                    Button { store.requestExtra("budget", messageID: message.id) } label: { Label("预算明细", systemImage: "yensign.circle") }
                        .disabled(store.running)
                    Button { store.requestExtra("poster", messageID: message.id) } label: { Label("手账海报", systemImage: "photo.on.rectangle.angled") }
                        .disabled(store.running)
                    Button {
                        if let id = message.importedTripID { openTrip = TripRef(id: id); return }
                        importing = true
                        Task {
                            if let id = await store.importTrip(messageID: message.id) { openTrip = TripRef(id: id) }
                            importing = false
                        }
                    } label: {
                        Label(message.importedTripID == nil ? "转成协同行程" : "打开协同行程", systemImage: "map")
                    }
                    .disabled(importing)
                }
                .font(.footnote.weight(.medium))
                .buttonStyle(.glass)
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }
}

// MARK: Thinking

private struct ThinkingPanel: View {
    let store: ChatStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: "sparkles").foregroundStyle(Palette.sky).symbolEffect(.pulse)
                Text(store.thinkingStatus).font(.subheadline.weight(.medium)).contentTransition(.opacity)
                Spacer(minLength: 0)
            }
            let earlier = store.thinkingTrail.dropLast()
            if !earlier.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(Array(earlier.enumerated()), id: \.offset) { _, line in
                        Label(line, systemImage: "checkmark").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
            }
            if !store.subagents.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(store.subagents.enumerated()), id: \.offset) { _, run in
                        HStack(spacing: 8) {
                            switch run["status"]?.string {
                            case "done": Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                            case "failed": Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
                            default: ProgressView().controlSize(.mini)
                            }
                            Text(run["title"]?.string ?? run["name"]?.string ?? "子任务").font(.caption).lineLimit(1)
                            Spacer()
                            if let elapsed = run["elapsed_s"]?.double { Text("\(Int(elapsed))s").font(.caption2).foregroundStyle(.secondary).monospacedDigit() }
                        }
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 22)
        .animation(.snappy, value: store.thinkingStatus)
    }
}

// MARK: Composer

struct Composer: View {
    @Binding var text: String
    @Binding var deep: Bool
    @Binding var webSearch: Bool
    var running: Bool
    var placeholder = "继续问，或补充预算和节奏…"
    var onSend: (String, [String]) -> Void
    var onStop: () -> Void
    @State private var picks: [PhotosPickerItem] = []
    @State private var uploads: [UploadedImage] = []
    @State private var uploading = false
    @State private var uploadError: String?
    @FocusState private var focused: Bool

    struct UploadedImage: Identifiable { var id: String; var preview: UIImage }

    private var canSend: Bool {
        !running && !uploading && (!text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !uploads.isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !uploads.isEmpty || uploading || uploadError != nil {
                HStack(spacing: 8) {
                    ForEach(uploads) { image in
                        Image(uiImage: image.preview).resizable().scaledToFill().frame(width: 52, height: 52)
                            .clipShape(.rect(cornerRadius: 12))
                            .overlay(alignment: .topTrailing) {
                                Button { uploads.removeAll { $0.id == image.id } } label: {
                                    Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette).foregroundStyle(.white, .black.opacity(0.6))
                                }
                                .offset(x: 5, y: -5)
                            }
                    }
                    if uploading { ProgressView().frame(width: 52, height: 52) }
                    if let uploadError { Text(uploadError).font(.caption).foregroundStyle(.red) }
                }
                .padding(.horizontal, 6)
            }
            GlassEffectContainer(spacing: 10) {
                HStack(alignment: .bottom, spacing: 10) {
                    Menu {
                        Toggle(isOn: $webSearch) { Label("联网搜索（查最新信息）", systemImage: "globe") }
                        Toggle(isOn: $deep) { Label("深度推理（更慢更全面）", systemImage: "brain") }
                    } label: {
                        Image(systemName: deep ? "brain.fill" : webSearch ? "globe" : "slider.horizontal.3")
                            .font(.system(size: 17, weight: .medium))
                            .foregroundStyle(deep || webSearch ? Palette.sky : .primary)
                            .frame(width: 44, height: 44)
                    }
                    .glassEffect(.regular.interactive(), in: .circle)

                    HStack(alignment: .bottom, spacing: 6) {
                        PhotosPicker(selection: $picks, maxSelectionCount: max(1, 4 - uploads.count), matching: .images) {
                            Image(systemName: "photo").font(.system(size: 17)).foregroundStyle(.secondary).frame(width: 30, height: 36)
                        }
                        .disabled(uploads.count >= 4)
                        TextField(placeholder, text: $text, axis: .vertical)
                            .lineLimit(1...6)
                            .focused($focused)
                            .padding(.vertical, 9)
                    }
                    .padding(.leading, 10).padding(.trailing, 14)
                    .frame(minHeight: 44)
                    .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22))

                    Button {
                        if running { onStop(); return }
                        guard canSend else { return }
                        onSend(text, uploads.map(\.id))
                        text = ""
                        uploads = []
                    } label: {
                        Image(systemName: running ? "stop.fill" : "arrow.up")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .glassEffect(.regular.tint((running || canSend) ? Palette.sky : .gray.opacity(0.5)).interactive(), in: .circle)
                    .disabled(!running && !canSend)
                }
            }
        }
        .onChange(of: picks) { _, items in
            guard !items.isEmpty else { return }
            picks = []
            Task { await upload(items) }
        }
    }

    private func upload(_ items: [PhotosPickerItem]) async {
        uploading = true
        uploadError = nil
        for item in items.prefix(4 - uploads.count) {
            guard let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data),
                  let jpeg = ImageCompressor.jpeg(image) else { uploadError = "图片读取失败"; continue }
            do {
                struct Uploaded: Decodable { var id: String }
                let reply = try API.shared.decode(Uploaded.self, try await API.shared.upload("uploads", field: "file", fileName: "image.jpg", mime: "image/jpeg", data: jpeg))
                uploads.append(UploadedImage(id: reply.id, preview: image))
            } catch {
                uploadError = error.localizedDescription
            }
        }
        uploading = false
    }
}

enum ImageCompressor {
    /// The server accepts up to 5 MB; 2048 px JPEG keeps screenshots legible well under that.
    static func jpeg(_ image: UIImage) -> Data? {
        let longest = max(image.size.width, image.size.height)
        let scale = min(1, 2048 / max(longest, 1))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        var quality: CGFloat = 0.82
        var data = resized.jpegData(compressionQuality: quality)
        while let current = data, current.count > 4_800_000, quality > 0.3 {
            quality -= 0.15
            data = resized.jpegData(compressionQuality: quality)
        }
        return data
    }
}
