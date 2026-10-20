import SwiftUI

struct UserCard: Decodable, Hashable {
    var id: String?
    var username: String
    var displayName: String?
    var avatarUrl: String?
    var name: String { (displayName?.isEmpty == false ? displayName : nil) ?? username }
}

struct RelayPost: Decodable, Identifiable, Hashable {
    var id: String
    var destination: String
    var phase: String
    var kind: String
    var content: String
    var expired: Bool?
    var createdAt: String?
    var author: UserCard
    var mine: Bool?
    var reactions: [String: Int]
    var myReaction: String?
}

private struct Station: Decodable {
    var destination: String
    var posts: [RelayPost]
    var phaseCounts: [String: Int]?
}

enum RelayKind: String, CaseIterable, Identifiable {
    case question, condition, route
    var id: String { rawValue }
    var title: String { self == .question ? "目的地提问" : self == .condition ? "现场情报" : "路线分享" }
    var action: String { self == .question ? "问一个问题" : self == .condition ? "报个现场" : "分享路线" }
    var symbol: String { self == .question ? "questionmark.bubble" : self == .condition ? "dot.radiowaves.left.and.right" : "point.topleft.down.to.point.bottomright.curvepath" }
    /// The web derives the phase from the kind.
    var phase: String { self == .question ? "planning" : self == .condition ? "on_trip" : "returned" }
}

struct SocialView: View {
    @Environment(AppRouter.self) private var router
    @State private var destination = "天堂寨"
    @State private var cities: [String] = ["天堂寨", "平潭岛", "武功山", "杭州", "武汉"]
    @State private var phase = ""
    @State private var posts: [RelayPost] = []
    @State private var counts: [String: Int] = [:]
    @State private var loading = false
    @State private var error: String?
    @State private var composing: RelayKind?
    @State private var customCity = ""
    @State private var askingCity = false

    private let phases = [("", "全部"), ("planning", "准备去"), ("on_trip", "正在玩"), ("returned", "刚回来")]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    citySelector
                    VStack(alignment: .leading, spacing: 4) {
                        Text(destination).font(.largeTitle.bold())
                        Text("真实旅行者接力：出发前问一问，到了报现场，回来分享路线。").font(.subheadline).foregroundStyle(.secondary)
                    }
                    Picker("阶段", selection: $phase) {
                        ForEach(phases, id: \.0) { value, title in
                            let count = value.isEmpty ? nil : counts[value]
                            Text(count.map { "\(title) \($0)" } ?? title).tag(value)
                        }
                    }
                    .pickerStyle(.segmented)
                    GlassEffectContainer(spacing: 8) {
                        HStack(spacing: 8) {
                            ForEach(RelayKind.allCases) { kind in
                                Button { composing = kind } label: {
                                    Label(kind.action, systemImage: kind.symbol).font(.footnote.weight(.semibold)).frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.glass)
                            }
                        }
                    }
                    if let error { Label(error, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.red) }
                    if loading && posts.isEmpty { ProgressView().frame(maxWidth: .infinity).padding(.top, 40) }
                    if !loading && posts.isEmpty && error == nil {
                        EmptyState(symbol: "figure.hiking", title: "还没有人接力", message: "做第一个分享\(destination)现场情况的人。")
                    }
                    ForEach($posts) { $post in PostCard(post: $post) { delete(post) } }
                }
                .padding(16)
            }
            .navigationTitle("同游圈")
            .navigationBarTitleDisplayMode(.inline)
            .screenBackground()
            .refreshable { await load() }
            .task(id: "\(destination)|\(phase)") { await load() }
            .task { await loadCities() }
            .onChange(of: router.socialDestination, initial: true) { _, value in
                if let value { select(value); router.socialDestination = nil }
            }
            .sheet(item: $composing) { kind in
                PostComposer(kind: kind, destination: destination) { post in
                    posts.insert(post, at: 0)
                }
            }
            .alert("看看其他目的地", isPresented: $askingCity) {
                TextField("城市或景区", text: $customCity)
                Button("取消", role: .cancel) {}
                Button("前往") { select(customCity) }
            }
        }
    }

    private var citySelector: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: 8) {
                HStack(spacing: 8) {
                    ForEach(cities, id: \.self) { city in
                        Button(city) { select(city) }
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(city == destination ? .white : .primary)
                            .padding(.horizontal, 14).padding(.vertical, 8)
                            .glassEffect(city == destination ? .regular.tint(Palette.sky).interactive() : .regular.interactive(), in: .capsule)
                    }
                    Button { customCity = ""; askingCity = true } label: { Image(systemName: "magnifyingglass").padding(10) }
                        .glassEffect(.regular.interactive(), in: .circle)
                }
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }

    private func select(_ city: String) {
        let trimmed = city.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        if !cities.contains(trimmed) { cities.insert(trimmed, at: 0) }
        destination = trimmed
    }

    private func loadCities() async {
        struct Onboarding: Decodable { var trending: [String] }
        if let trending = try? await API.shared.get("onboarding", as: Onboarding.self).trending, !trending.isEmpty {
            var merged = [destination]
            for city in trending where !merged.contains(city) { merged.append(city) }
            cities = merged
        }
    }

    private func load() async {
        loading = true
        do {
            var query = ["destination": destination]
            if !phase.isEmpty { query["phase"] = phase }
            let station = try await API.shared.get("social/station", query: query, as: Station.self)
            posts = station.posts
            counts = station.phaseCounts ?? [:]
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
        loading = false
    }

    private func delete(_ post: RelayPost) {
        withAnimation { posts.removeAll { $0.id == post.id } }
        Task { _ = try? await API.shared.request("DELETE", "social/posts/\(post.id)") }
    }
}

private struct PostCard: View {
    @Binding var post: RelayPost
    let onDelete: () -> Void

    private var kind: RelayKind? { RelayKind(rawValue: post.kind) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Avatar(user: post.author, size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(post.author.name).font(.subheadline.weight(.semibold))
                    Text(ISODate.relative(post.createdAt)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if let kind { Chip(text: kind.title, symbol: kind.symbol) }
                if post.mine == true {
                    Menu {
                        Button("删除", systemImage: "trash", role: .destructive, action: onDelete)
                    } label: { Image(systemName: "ellipsis").padding(8) }
                }
            }
            Text(post.content).font(.body).textSelection(.enabled)
            if post.expired == true {
                Label("现场情报已过期", systemImage: "clock.badge.exclamationmark").font(.caption).foregroundStyle(.orange)
            }
            if post.mine != true {
                GlassEffectContainer(spacing: 8) {
                    HStack(spacing: 8) {
                        reaction("useful", "有用", "hand.thumbsup")
                        reaction("verified", "属实", "checkmark.seal")
                        reaction("outdated", "已失效", "clock.arrow.trianglehead.counterclockwise.rotate.90")
                    }
                }
            } else {
                Text("有用 \(post.reactions["useful"] ?? 0) · 属实 \(post.reactions["verified"] ?? 0) · 已失效 \(post.reactions["outdated"] ?? 0)")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .glassCard(cornerRadius: 22)
    }

    private func reaction(_ key: String, _ title: String, _ symbol: String) -> some View {
        let chosen = post.myReaction == key
        return Button {
            react(key)
        } label: {
            Label("\(title) \(post.reactions[key] ?? 0)", systemImage: chosen ? symbol + ".fill" : symbol)
                .font(.caption.weight(.medium))
                .foregroundStyle(chosen ? Palette.sky : .secondary)
                .padding(.horizontal, 10).padding(.vertical, 6)
        }
        .glassEffect(.regular.interactive(), in: .capsule)
    }

    private func react(_ key: String) {
        Task {
            struct Reply: Decodable { var reactions: [String: Int] }
            do {
                let reply = try await API.shared.post("social/posts/\(post.id)/react", body: ["reaction": key], as: Reply.self)
                post.reactions = reply.reactions
                post.myReaction = post.myReaction == key ? "" : key   // sending the same reaction again removes it
            } catch {}
        }
    }
}

struct Avatar: View {
    let user: UserCard
    var size: CGFloat = 32
    var body: some View {
        Group {
            if let url = user.avatarUrl, !url.isEmpty {
                RemoteImage(path: url)
            } else {
                Text(String(user.name.prefix(1))).font(.system(size: size * 0.42, weight: .bold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity).background(Palette.sky.gradient)
            }
        }
        .frame(width: size, height: size)
        .clipShape(.circle)
    }
}

private struct PostComposer: View {
    let kind: RelayKind
    let destination: String
    let onPosted: (RelayPost) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                Text(kind == .condition ? "现场情报 72 小时后自动过期。" : "\(destination) · \(kind.title)")
                    .font(.footnote).foregroundStyle(.secondary)
                TextField(kind == .question ? "比如：周末去人多吗？需要提前订票吗？" : kind == .condition ? "比如：今天雾很大，索道排队 40 分钟" : "比如：东门进，先走玻璃桥再坐索道下山",
                          text: $text, axis: .vertical)
                    .lineLimit(5...12)
                    .padding(16)
                    .glassCard(cornerRadius: 20)
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                Spacer()
            }
            .padding(18)
            .screenBackground()
            .navigationTitle(kind.action)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("发布") { post() }.disabled(busy || text.trimmingCharacters(in: .whitespacesAndNewlines).count < 2)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func post() {
        busy = true
        Task {
            do {
                let post = try await API.shared.post("social/posts", body: ["destination": destination, "phase": kind.phase,
                                                                              "kind": kind.rawValue, "content": text.trimmingCharacters(in: .whitespacesAndNewlines)],
                                                     as: RelayPost.self)
                onPosted(post)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}

struct NotificationsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppRouter.self) private var router
    @State private var items: [Item] = []
    @State private var loading = true

    struct Item: Decodable, Identifiable {
        var id: String
        var type: String?
        var title: String
        var body: String?
        var targetKind: String?
        var targetId: String?
        var meta: JSONValue?
        var read: Bool
        var createdAt: String?
    }

    var body: some View {
        NavigationStack {
            List(items) { item in
                Button { open(item) } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Circle().fill(item.read ? .clear : Palette.sky).frame(width: 8, height: 8).padding(.top, 6)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.title).font(.subheadline.weight(.semibold))
                            if let body = item.body, !body.isEmpty { Text(body).font(.footnote).foregroundStyle(.secondary) }
                            Text(ISODate.relative(item.createdAt)).font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                }
                .foregroundStyle(.primary)
                .listRowBackground(Color.clear)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .overlay {
                if loading { ProgressView() }
                else if items.isEmpty { EmptyState(symbol: "bell", title: "没有新通知", message: "好友申请、接力回应和行程消息会出现在这里。") }
            }
            .screenBackground()
            .navigationTitle("通知")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("全部已读") {
                        Task { _ = try? await API.shared.request("POST", "notifications/read-all"); await load() }
                    }
                    .disabled(items.allSatisfy(\.read))
                }
                ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
            }
            .task { await load() }
        }
    }

    private func load() async {
        struct Reply: Decodable { var notifications: [Item] }
        items = (try? await API.shared.get("notifications", query: ["limit": "40"], as: Reply.self).notifications) ?? []
        loading = false
    }

    private func open(_ item: Item) {
        Task { _ = try? await API.shared.request("POST", "notifications/\(item.id)/read") }
        switch item.targetKind {
        case "relay":
            router.socialDestination = item.meta?["destination"]?.string
            router.tab = .me
            dismiss()
        case "trip":
            router.openTripID = item.meta?["trip_id"]?.string ?? item.targetId
            router.tab = .home
            dismiss()
        default:
            router.tab = .me
            dismiss()
        }
    }
}
