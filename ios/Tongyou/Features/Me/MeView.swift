import SwiftUI

/// Account tab: personal tools for everyone,
/// plus the admin console (users, invite codes, announcements, support inbox) for admins.
struct MeView: View {
    var isRoot = false
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var showHistory = false
    @State private var supportUnread = 0
    @State private var adminSupportUnread = 0

    var body: some View {
        NavigationStack {
            List {
                if let account = session.account {
                    Section {
                        HStack(spacing: 14) {
                            Avatar(user: UserCard(username: account.username, displayName: account.displayName, avatarUrl: account.avatarUrl), size: 56)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(account.displayName).font(.title3.weight(.semibold))
                                Text("@\(account.username)" + (account.isAdmin ? " · 管理员" : "")).font(.subheadline).foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 6)
                    }
                    .listRowBackground(Rectangle().fill(.clear).glassEffect(.regular, in: .rect(cornerRadius: 22)))
                }

                Section("我的") {
                    Button { showHistory = true } label: { Label("历史对话", systemImage: "clock.arrow.circlepath") }
                    DisclosureGroup("更多工具与设置") {
                    NavigationLink { MemoryView() } label: { Label("记忆", systemImage: "brain.head.profile") }
                    NavigationLink { SkillsView() } label: { Label("技能", systemImage: "puzzlepiece.extension") }
                    NavigationLink { ConnectorsView() } label: { Label("连接", systemImage: "link") }
                    }
                    NavigationLink { AnnouncementsView() } label: { Label("公告", systemImage: "megaphone") }
                    NavigationLink { SupportChatView(mode: .user) } label: {
                        Label("联系客服", systemImage: "questionmark.bubble").badge(supportUnread)
                    }
                }

                if session.account?.isAdmin == true {
                    Section("管理") {
                        NavigationLink { AdminUsersView() } label: { Label("用户管理", systemImage: "person.3") }
                        NavigationLink { InviteCodesView() } label: { Label("邀请码", systemImage: "ticket") }
                        NavigationLink { AdminAnnouncementsView() } label: { Label("发布公告", systemImage: "megaphone.fill") }
                        NavigationLink { SupportInboxView() } label: {
                            Label("客服消息", systemImage: "tray.full").badge(adminSupportUnread)
                        }
                    }
                }

                Section {
                    Button(role: .destructive) {
                        Task { await session.logout(); dismiss() }
                    } label: { Label("退出登录", systemImage: "rectangle.portrait.and.arrow.right") }
                } footer: {
                    Text("退出会同时退出你在其他设备和网页版上的登录。")
                }
            }
            .scrollContentBackground(.hidden)
            .screenBackground()
            .toolbar(.hidden, for: .tabBar)
            .navigationTitle("我的")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { if !isRoot { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } } }
            .sheet(isPresented: $showHistory) { HistoryView() }
            .task { await loadBadges() }
        }
    }

    private func loadBadges() async {
        struct Count: Decodable { var unread: Int }
        supportUnread = (try? await API.shared.get("support/unread", as: Count.self))?.unread ?? 0
        if session.account?.isAdmin == true {
            struct Threads: Decodable { var unreadTotal: Int }
            adminSupportUnread = (try? await API.shared.get("admin/support/threads", as: Threads.self))?.unreadTotal ?? 0
        }
    }
}

// MARK: Personal

struct MemoryView: View {
    struct Memory: Decodable, Identifiable { var id: String; var type: String?; var key: String?; var content: String; var explicit: Bool?; var updatedAt: String? }
    @State private var items: [Memory] = []
    @State private var loading = true
    @State private var consolidating = false
    @State private var message: String?

    var body: some View {
        List {
            if let message { Text(message).font(.footnote).foregroundStyle(.secondary) }
            ForEach(items) { memory in
                VStack(alignment: .leading, spacing: 4) {
                    Text(memory.content).font(.body)
                    HStack(spacing: 6) {
                        if let key = memory.key, !key.isEmpty { Text(key) }
                        if memory.explicit == true { Text("· 你让我记住的") }
                        Text("· " + ISODate.relative(memory.updatedAt))
                    }
                    .font(.caption).foregroundStyle(.secondary)
                }
                .swipeActions {
                    Button(role: .destructive) { delete(memory) } label: { Label("忘掉", systemImage: "trash") }
                }
            }
        }
        .overlay {
            if loading { ProgressView() }
            else if items.isEmpty { EmptyState(symbol: "brain", title: "还没有记忆", message: "聊天时说“记住我不吃辣”，我就会记下来。") }
        }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("记忆")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("整理") { consolidate() }.disabled(consolidating || items.count < 2)
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        items = (try? await API.shared.get("memory", as: [Memory].self)) ?? []
        loading = false
    }
    private func delete(_ memory: Memory) {
        items.removeAll { $0.id == memory.id }
        Task { _ = try? await API.shared.request("DELETE", "memory/\(memory.id)") }
    }
    private func consolidate() {
        consolidating = true
        message = "正在合并重复的记忆…"
        Task {
            do { _ = try await API.shared.request("POST", "memory/consolidate"); message = "已整理" }
            catch { message = error.localizedDescription }
            await load()
            consolidating = false
        }
    }
}

struct SkillsView: View {
    struct Skill: Decodable, Identifiable { var id: String; var name: String; var description: String?; var content: String; var files: [String]?; var updatedAt: String? }
    @State private var items: [Skill] = []
    @State private var loading = true
    @State private var showEditor = false
    @State private var error: String?

    var body: some View {
        List {
            Section {
                Text("技能是一份 SKILL.md 说明书，告诉 AI 在某类问题上怎么做（例如“带娃出行先查母婴室”）。")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            ForEach(items) { skill in
                NavigationLink {
                    ScrollView { MarkdownView(skill.content).padding(18) }.screenBackground().navigationTitle(skill.name)
                } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(skill.name).font(.headline)
                        if let description = skill.description { Text(description).font(.subheadline).foregroundStyle(.secondary).lineLimit(2) }
                    }
                }
                .swipeActions {
                    Button(role: .destructive) {
                        items.removeAll { $0.id == skill.id }
                        Task { _ = try? await API.shared.request("DELETE", "skills/\(skill.id)") }
                    } label: { Label("删除", systemImage: "trash") }
                }
            }
        }
        .overlay { if loading { ProgressView() } }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("技能")
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("新建", systemImage: "plus") { showEditor = true } } }
        .sheet(isPresented: $showEditor) { SkillEditor { items.insert($0, at: 0) } }
        .task {
            items = (try? await API.shared.get("skills", as: [Skill].self)) ?? []
            loading = false
        }
    }

    struct SkillEditor: View {
        let onSaved: (Skill) -> Void
        @Environment(\.dismiss) private var dismiss
        @State private var text = "---\nname: 我的技能\ndescription: 一句话说明什么时候用\n---\n\n写下具体做法…"
        @State private var error: String?
        @State private var busy = false
        var body: some View {
            NavigationStack {
                VStack(alignment: .leading) {
                    TextEditor(text: $text).font(.system(.callout, design: .monospaced)).scrollContentBackground(.hidden)
                        .padding(12).glassCard(cornerRadius: 18)
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
                .padding(16)
                .screenBackground()
                .navigationTitle("新建技能").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("保存") {
                            busy = true
                            Task {
                                do { onSaved(try await API.shared.post("skills", body: ["content": text], as: Skill.self)); Haptics.success(); dismiss() }
                                catch { self.error = error.localizedDescription }
                                busy = false
                            }
                        }
                        .disabled(busy)
                    }
                }
            }
        }
    }
}

struct ConnectorsView: View {
    struct Connector: Decodable, Identifiable {
        var key: String; var name: String; var kind: String?; var summary: String?
        var provides: [String]?; var note: String?; var connectable: Bool?; var connected: Bool?; var connectedAt: String?
        var id: String { key }
    }
    struct ConnectState: Decodable { var token: String?; var key: String?; var state: String; var message: String?; var screenshotToken: String? }
    @State private var items: [Connector] = []
    @State private var connecting: ConnectState?
    @State private var tick = 0
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            if let connecting, connecting.state == "starting" || connecting.state == "waiting" {
                Section("扫码连接") {
                    Text(connecting.message ?? "正在打开登录页…").font(.subheadline)
                    if let token = connecting.screenshotToken, !token.isEmpty {
                        RemoteImage(path: "/travel/api/connectors/connect/\(token)/screenshot?t=\(tick)")
                            .frame(height: 320).clipShape(.rect(cornerRadius: 14))
                    }
                    Button("取消连接", role: .destructive) {
                        Task { _ = try? await API.shared.request("DELETE", "connectors/connect"); self.connecting = nil }
                    }
                }
            }
            ForEach(items) { item in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(item.name).font(.headline)
                        Spacer()
                        Text(item.connected == true ? "已连接" : "未连接").font(.caption.weight(.semibold))
                            .foregroundStyle(item.connected == true ? .green : .secondary)
                    }
                    if let summary = item.summary { Text(summary).font(.subheadline).foregroundStyle(.secondary) }
                    if let note = item.note, !note.isEmpty { Text(note).font(.caption).foregroundStyle(.tertiary) }
                    if item.connectable == true {
                        HStack {
                            if item.connected == true {
                                Button("断开", role: .destructive) { disconnect(item) }.buttonStyle(.glass)
                            } else {
                                Button("扫码连接") { connect(item) }.buttonStyle(.glassProminent).tint(Palette.sky)
                            }
                        }
                        .font(.footnote)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("连接")
        .task { await load() }
        .task(id: tick) {
            guard connecting != nil else { return }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            if let state = try? await API.shared.get("connectors/connect/status", as: ConnectState.self) {
                connecting = state
                if state.state != "starting" && state.state != "waiting" { await load() }
            }
            tick += 1
        }
    }

    private func load() async {
        struct Reply: Decodable { var connectors: [Connector] }
        do { items = try await API.shared.get("connectors", as: Reply.self).connectors } catch { self.error = error.localizedDescription }
    }
    private func connect(_ item: Connector) {
        Task {
            do { connecting = try await API.shared.post("connectors/\(item.key)/connect", as: ConnectState.self); tick += 1 }
            catch { self.error = error.localizedDescription }
        }
    }
    private func disconnect(_ item: Connector) {
        Task {
            do { _ = try await API.shared.request("DELETE", "connectors/\(item.key)"); await load() }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct Announcement: Decodable, Identifiable { var id: String; var title: String; var content: String; var createdAt: String?; var read: Bool?; var author: String? }

struct AnnouncementsView: View {
    @State private var items: [Announcement] = []
    @State private var loading = true
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            if item.read != true { Circle().fill(Palette.sky).frame(width: 8, height: 8) }
                            Text(item.title).font(.headline)
                        }
                        MarkdownView(item.content)
                        Text("\(item.author ?? "管理员") · \(ISODate.relative(item.createdAt))").font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 22)
                    .task { if item.read != true { _ = try? await API.shared.request("POST", "announcements/\(item.id)/read") } }
                }
            }
            .padding(16)
        }
        .overlay {
            if loading { ProgressView() }
            else if items.isEmpty { EmptyState(symbol: "megaphone", title: "暂无公告", message: "管理员发布的新功能和通知会出现在这里。") }
        }
        .screenBackground()
        .navigationTitle("公告")
        .task {
            struct Reply: Decodable { var announcements: [Announcement] }
            items = (try? await API.shared.get("announcements", as: Reply.self).announcements) ?? []
            loading = false
        }
    }
}

// MARK: Support chat (user ↔ admin)

struct SupportChatView: View {
    enum Mode: Equatable { case user, admin(userID: String, username: String) }
    struct Message: Decodable, Identifiable, Equatable { var id: String; var sender: String; var content: String; var createdAt: String? }
    let mode: Mode
    @State private var messages: [Message] = []
    @State private var draft = ""
    @State private var error: String?

    private var path: String {
        switch mode {
        case .user: return "support/messages"
        case .admin(let id, _): return "admin/support/\(id)/messages"
        }
    }
    private var mine: String { mode == .user ? "user" : "admin" }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    if messages.isEmpty {
                        EmptyState(symbol: "bubble.left.and.bubble.right", title: mode == .user ? "有问题随时说" : "还没有消息",
                                   message: mode == .user ? "管理员看到后会在这里回复你。" : "")
                    }
                    ForEach(messages) { message in
                        let isMine = message.sender == mine
                        Text(message.content)
                            .padding(.horizontal, 14).padding(.vertical, 10)
                            .foregroundStyle(isMine ? .white : .primary)
                            .glassEffect(isMine ? .regular.tint(Palette.sky.opacity(0.85)) : .regular, in: .rect(cornerRadius: 20))
                            .frame(maxWidth: .infinity, alignment: isMine ? .trailing : .leading)
                            .id(message.id)
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
                .padding(16)
            }
            .onChange(of: messages.count) { if let last = messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } } }
        }
        .safeAreaInset(edge: .bottom) {
            GlassEffectContainer(spacing: 10) {
                HStack(alignment: .bottom, spacing: 10) {
                    TextField("输入消息", text: $draft, axis: .vertical).lineLimit(1...5)
                        .padding(.horizontal, 16).padding(.vertical, 12)
                        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22))
                    Button(action: send) {
                        Image(systemName: "arrow.up").font(.body.weight(.bold)).foregroundStyle(.white).frame(width: 44, height: 44)
                    }
                    .glassEffect(.regular.tint(Palette.sky).interactive(), in: .circle)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(.horizontal, 12).padding(.bottom, 6)
        }
        .screenBackground()
        .navigationTitle({ if case .admin(_, let name) = mode { return name } else { return "联系客服" } }())
        .navigationBarTitleDisplayMode(.inline)
        .task {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    private func load() async {
        struct Reply: Decodable { var messages: [Message] }
        if let reply = try? await API.shared.get(path, as: Reply.self), reply.messages != messages { messages = reply.messages }
    }
    private func send() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        Task {
            do { messages.append(try await API.shared.post(path, body: ["content": text], as: Message.self)) }
            catch { self.error = error.localizedDescription; draft = text }
        }
    }
}
