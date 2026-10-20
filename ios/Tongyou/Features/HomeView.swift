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
