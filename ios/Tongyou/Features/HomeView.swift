import SwiftUI

@MainActor @Observable
final class AppRouter {
    enum TabID: Hashable { case home, ledger, me }
    var tab: TabID = .home
    var travelDetailOpen = false
    var aiOpen = false
    var aiPrompt = ""
    var socialDestination: String?
    var openTripID: String?
    var openLedgerID: String?
    var ledgerLinks = LedgerLinkInbox()
    var historyVersion = 0
    var petToolsOpen = false
    var keyboardOpen = false
    var petTask = PetTask()
    var petCelebration = 0
    /// 问 AI 衔接动画：停靠处与 AI 标题栏小游游的全局位置，及起跳/落地触发器。
    var petDockFrame = CGRect.zero
    var petBadgeFrame = CGRect.zero
    var petFlight = 0
    var petFlying = false
    var petLanded = 0
    /// 指引一次 App 会话只说一句。
    var petTipShown = false
    var petPreferences = PetPreferences() {
        didSet {
            if let petUsername, let data = try? JSONEncoder().encode(petPreferences) { UserDefaults.standard.set(data, forKey: "travelPet.v1.\(petUsername)") }
        }
    }
    private var petUsername: String?
    private var petLiveTurn: (conversation: String?, turn: String)?
    /// 游游跟着的那个对话：气泡点进去直达它；离开对话页后由 followPet 接着拉进度。
    private(set) var petChat: PetChatRoute?
    /// AssistantView 消费：把这个对话推到 AI 面板最上层。
    var petChatRequest: PetChatRoute?
    /// 正在显示的对话页（栈），已在最上层就不重复推。
    private(set) var chatsShown: [String] = []
    private var petFollow: Task<Void, Never>?
    private var petFollowing: String?

    func chatShown(_ id: String?) { if let id { chatsShown.append(id) } }
    func chatHidden(_ id: String?) { if let id, let i = chatsShown.lastIndex(of: id) { chatsShown.remove(at: i) } }

    /// 打开 AI 面板；带 chat 时直达游游正在跟的对话。
    func openPetChat() {
        if let petChat, chatsShown.last != petChat.id { petChatRequest = petChat }
    }

    /// 对话页关掉时本轮还没完，就由这里接着轮询，完成提醒照常出现。
    func followPet(conversation id: String, title: String) {
        petFollow?.cancel()
        petFollowing = id
        let store = ChatStore(conversationID: id)
        petFollow = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled, let self, self.petLiveTurn?.conversation == id else { return }
                guard let running = await store.refresh() else { continue }
                guard !Task.isCancelled, self.petFollowing == id else { return }
                self.applyPet(store.petTask, conversation: id, title: title)
                if !running {
                    if store.petTask.phase == .ready { UINotificationFeedbackGenerator().notificationOccurred(.success) }
                    self.historyVersion += 1
                    self.petFollowing = nil
                    return
                }
            }
        }
    }

    func configurePet(username: String?) {
        guard username != petUsername else { return }
        petUsername = username
        #if DEBUG
        if JourneyUITestProtocol.enabled && ProcessInfo.processInfo.arguments.contains("--pet-reset"), let username { UserDefaults.standard.removeObject(forKey: "travelPet.v1.\(username)") }
        #endif
        petPreferences = PetPreferences.read(username.flatMap { UserDefaults.standard.data(forKey: "travelPet.v1.\($0)") })
        petTask = PetTask(); petLiveTurn = nil; petCelebration = 0; petToolsOpen = false
        petFollow?.cancel(); petFollowing = nil; petChat = nil
    }

    /// 对话页上报：页面回来了就由它自己轮询，停掉后台跟进。
    func updatePet(_ task: PetTask, conversation: String?, title: String) {
        if let conversation, conversation == petFollowing { petFollow?.cancel(); petFollowing = nil }
        applyPet(task, conversation: conversation, title: title)
    }

    private func applyPet(_ task: PetTask, conversation: String?, title: String) {
        guard TravelPetLogic.accepts(task, from: conversation, live: petLiveTurn) else { return }
        if let conversation, task.phase != .idle { petChat = PetChatRoute(id: conversation, title: title) }
        if task.phase == .working || task.phase == .waiting { petLiveTurn = (conversation, task.turn) }
        else {
            if task.phase == .ready, let live = petLiveTurn, live.conversation == conversation, live.turn == task.turn { petCelebration += 1 }
            petLiveTurn = nil
        }
        petTask = task
    }
}

struct PetChatRoute: Hashable {
    var id: String
    var title: String
}

struct ChatLaunch: Hashable {
    var id = UUID()
    var text: String
    var deep: Bool
}

struct AssistantView: View {
    @Environment(AppRouter.self) private var router
    @State private var path = NavigationPath()
    @State private var draft = ""
    @State private var deep = false
    /// Same setting as the chat composer's web search toggle.
    @AppStorage("webSearch") private var webSearch = ChatPreferences.defaultWebSearch
    @State private var showHistory = false
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    hero
                    composer
                    assistantTasks
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 30)
            }
            .scrollDismissesKeyboard(.interactively)
            .screenBackground()
            .navigationTitle("同游 AI")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) { if router.petPreferences.visible { PetStatusBadge() } }
                ToolbarItem(placement: .topBarLeading) {
                    Button { focused = false; router.aiOpen = false } label: { Label("收起", systemImage: "chevron.down") }
                        .accessibilityIdentifier("closeAI")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("历史") { showHistory = true }
                }
            }
            .navigationDestination(for: ChatLaunch.self) { launch in
                ChatView(conversationID: nil, title: String(launch.text.prefix(16)), initialText: launch.text,
                         sendOnAppear: true, deep: launch.deep) { router.historyVersion += 1 }
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("收起") { router.aiOpen = false }.accessibilityIdentifier("closeAI")
                        }
                    }
            }
            .navigationDestination(for: PetChatRoute.self) { route in
                ChatView(conversationID: route.id, title: route.title) { router.historyVersion += 1 }
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("收起") { router.aiOpen = false }.accessibilityIdentifier("closeAI")
                        }
                    }
            }
            .onChange(of: router.petChatRequest) { _, route in
                guard let route else { return }
                showHistory = false
                var next = NavigationPath(); next.append(route)
                path = next
                router.petChatRequest = nil
            }
            .sheet(isPresented: $showHistory) { HistoryView() }
            .onChange(of: router.aiPrompt) { _, prompt in
                guard !prompt.isEmpty else { return }
                path = NavigationPath()
                draft = prompt
                router.aiPrompt = ""
            }

        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("旅行里的小事，交给我").font(.subheadline.weight(.semibold)).foregroundStyle(Palette.sky)
            Text("想去哪儿，\n一起想想。").font(.largeTitle.weight(.bold)).lineSpacing(4)
            Text("说一个目的地、贴一篇攻略，或者直接问旅行问题。").font(.subheadline).foregroundStyle(.secondary)
        }
        .padding(.top, 12)
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("输入目的地、粘贴攻略链接，或者问“第一次去日本怎么准备？”", text: $draft, axis: .vertical)
                .accessibilityIdentifier("assistantDraft")
                .lineLimit(3...8)
                .focused($focused)
                .font(.body)
            HStack(spacing: 10) {
                Button {
                    deep.toggle()
                } label: {
                    Label("深度推理", systemImage: deep ? "brain.fill" : "brain")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(deep ? Palette.sky : .secondary)
                }
                .buttonStyle(.glass)
                Button {
                    webSearch.toggle()
                } label: {
                    Label("联网搜索", systemImage: "globe")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(webSearch ? Palette.sky : .secondary)
                }
                .buttonStyle(.glass)
                Spacer()
                Button {
                    start(draft, deep: deep)
                } label: {
                    Label("开始", systemImage: "arrow.up").font(.subheadline.weight(.semibold)).padding(.horizontal, 6)
                }
                .buttonStyle(.glassProminent)
                .tint(Palette.sky)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(18)
        .glassCard(cornerRadius: 28)
    }

    private var assistantTasks: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            ForEach(["规划旅行", "找美食", "整理攻略", "检查路线"], id: \.self) { title in
                Button {
                    draft = ["规划旅行": "帮我规划一次旅行，目的地是", "找美食": "帮我推荐当地值得体验的美食，目的地是", "整理攻略": "帮我把这篇攻略整理成行程：", "检查路线": "帮我检查这份行程的路线和时间安排："][title] ?? ""
                    focused = true
                } label: {
                    HStack { Text(title); Spacer(); Image(systemName: "arrow.up.right") }.font(.subheadline)
                        .padding(14).frame(maxWidth: .infinity).glassCard(cornerRadius: 22)
                }.buttonStyle(TravelPressStyle())
            }
        }
    }

    private func start(_ text: String, deep: Bool) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        focused = false
        draft = ""
        path.append(ChatLaunch(text: trimmed, deep: deep))
    }

}
