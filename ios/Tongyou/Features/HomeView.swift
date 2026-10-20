import SwiftUI

@MainActor @Observable
final class AppRouter {
    enum TabID: Hashable { case home, trips, ledger, history, social }
    var tab: TabID = .home
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

private struct Onboarding: Decodable {
    var homeCity: String?
    var trending: [String]
    var hasHistory: Bool?
}

struct HomeView: View {
    @Environment(AppSession.self) private var session
    @Environment(AppRouter.self) private var router
    @State private var path = NavigationPath()
    @State private var draft = ""
    @State private var deep = false
    /// Same setting as the chat composer's web search toggle.
    @AppStorage("webSearch") private var webSearch = ChatPreferences.defaultWebSearch
    @State private var trending: [String] = []
    @State private var homeCity = ""
    @State private var covers: [String: String] = [:]
    @State private var showNotifications = false
    @State private var showMe = false
    @State private var unread = 0
    @FocusState private var focused: Bool

    private var cities: [String] { trending.isEmpty ? ["杭州", "平潭岛", "武功山", "武汉"] : trending }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    hero
                    composer
                    quickStarts
                    relayBanner
                    trendingSection
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 30)
            }
            .scrollDismissesKeyboard(.interactively)
            .screenBackground()
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showMe = true } label: {
                        if let account = session.account {
                            Avatar(user: UserCard(username: account.username, displayName: account.displayName, avatarUrl: account.avatarUrl), size: 30)
                        } else {
                            Image(systemName: "person.crop.circle")
                        }
                    }
                    .accessibilityLabel("我的")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNotifications = true } label: {
                        Image(systemName: unread > 0 ? "bell.badge" : "bell")
                    }
                    .badge(unread)
                    .accessibilityLabel("通知")
                }
            }
            .navigationDestination(for: ChatLaunch.self) { launch in
                ChatView(conversationID: nil, title: String(launch.text.prefix(16)), initialText: launch.text,
                         sendOnAppear: true, deep: launch.deep) { router.historyVersion += 1 }
            }
            .sheet(isPresented: $showNotifications, onDismiss: { Task { await loadUnread() } }) {
                NotificationsView()
            }
            .sheet(isPresented: $showMe) { MeView() }
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(greeting).font(.subheadline.weight(.semibold)).foregroundStyle(Palette.sky)
            Text("想去哪儿，\n就从这里出发").font(.largeTitle.weight(.bold)).lineSpacing(4)
            Text("说一个目的地、贴一篇攻略，或者直接问旅行问题。").font(.subheadline).foregroundStyle(.secondary)
        }
        .padding(.top, 12)
    }

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: .now)
        let name = session.account?.displayName ?? ""
        let part = hour < 11 ? "早上好" : hour < 18 ? "下午好" : "晚上好"
        return name.isEmpty ? part : "\(part)，\(name)"
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("输入目的地、粘贴攻略链接，或者问“第一次去日本怎么准备？”", text: $draft, axis: .vertical)
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

    private var quickStarts: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: 10) {
                HStack(spacing: 10) {
                    ForEach(cities.prefix(6), id: \.self) { city in
                        Button("\(city)怎么玩") {
                            start(homeCity.isEmpty ? "我想去\(city)玩3天，帮我排个行程" : "我想从\(homeCity)出发去\(city)玩3天，帮我排个行程", deep: false)
                        }
                        .font(.subheadline.weight(.medium))
                        .buttonStyle(.glass)
                    }
                }
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }

    private var relayBanner: some View {
        Button {
            router.socialDestination = "天堂寨"
            router.tab = .social
        } label: {
            HStack(spacing: 14) {
                Image(systemName: "figure.hiking").font(.title2).foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .glassEffect(.regular.tint(Palette.sky), in: .circle)
                VStack(alignment: .leading, spacing: 3) {
                    Text("真实旅行者接力").font(.caption.weight(.semibold)).foregroundStyle(Palette.sky)
                    Text("有人正在天堂寨，把现场情况留给下一位").font(.subheadline.weight(.medium)).multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").foregroundStyle(.tertiary)
            }
            .padding(14)
            .glassCard(cornerRadius: 24, interactive: true)
        }
        .buttonStyle(.plain)
    }

    private var trendingSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("最近大家都想去").font(.title3.bold())
                Text("近 30 天真实热问，选一个再补充预算和节奏").font(.caption).foregroundStyle(.secondary)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 14) {
                    ForEach(Array(cities.prefix(4).enumerated()), id: \.element) { index, city in
                        Button {
                            draft = city
                            focused = true
                        } label: {
                            ZStack(alignment: .bottomLeading) {
                                RemoteImage(path: covers[city].map(API.proxied)).frame(width: 230, height: 150).clipped()
                                LinearGradient(colors: [.clear, .black.opacity(0.55)], startPoint: .center, endPoint: .bottom)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(city).font(.headline).foregroundStyle(.white)
                                    Text("路线、美食与住宿一次排好").font(.caption).foregroundStyle(.white.opacity(0.85))
                                }
                                .padding(14)
                                Text("TOP \(index + 1)").font(.caption2.weight(.bold)).foregroundStyle(.white)
                                    .padding(.horizontal, 9).padding(.vertical, 5)
                                    .glassEffect(.regular.tint(.black.opacity(0.2)), in: .capsule)
                                    .padding(10)
                                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                            }
                            .frame(width: 230, height: 150)
                            .clipShape(.rect(cornerRadius: 22))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .scrollClipDisabled()
        }
    }

    private func start(_ text: String, deep: Bool) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        focused = false
        draft = ""
        path.append(ChatLaunch(text: trimmed, deep: deep))
    }

    private func load() async {
        async let unreadTask: Void = loadUnread()
        if let data = try? await API.shared.get("onboarding", as: Onboarding.self) {
            trending = data.trending
            homeCity = data.homeCity ?? ""
        }
        let wanted = Array(cities.prefix(4)) + ["天堂寨"]
        struct Covers: Decodable { var covers: [String: String] }
        if let data = try? await API.shared.request("GET", "onboarding/covers", items: wanted.map { URLQueryItem(name: "destinations", value: $0) }),
           let reply = try? API.shared.decode(Covers.self, data) {
            covers = reply.covers
        }
        await unreadTask
    }

    private func loadUnread() async {
        struct Count: Decodable { var unread: Int }
        let notes = (try? await API.shared.get("notifications/unread-count", as: Count.self))?.unread ?? 0
        let news = (try? await API.shared.get("announcements/unread", as: Count.self))?.unread ?? 0
        unread = notes + news
    }
}
