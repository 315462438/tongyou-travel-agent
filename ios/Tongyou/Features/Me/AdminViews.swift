import SwiftUI

struct AdminUsersView: View {
    struct User: Decodable, Identifiable, Hashable {
        var id: String; var username: String; var isAdmin: Bool
        var conversations: Int?; var memories: Int?; var createdAt: String?; var lastSeenAt: String?; var online: Bool?
    }
    @Environment(AppSession.self) private var session
    @State private var users: [User] = []
    @State private var search = ""
    @State private var loading = true
    @State private var error: String?
    @State private var pendingRole: User?

    private var filtered: [User] {
        let q = search.trimmingCharacters(in: .whitespaces)
        let sorted = users.sorted { ($0.online == true ? 0 : 1, $0.username) < ($1.online == true ? 0 : 1, $1.username) }
        return q.isEmpty ? sorted : sorted.filter { $0.username.localizedCaseInsensitiveContains(q) }
    }

    var body: some View {
        List {
            Section {
                HStack {
                    stat("\(users.count)", "注册用户")
                    stat("\(users.filter { $0.online == true }.count)", "在线")
                    stat("\(users.filter(\.isAdmin).count)", "管理员")
                }
            }
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            Section {
                ForEach(filtered) { user in
                    NavigationLink { SupportChatView(mode: .admin(userID: user.id, username: user.username)) } label: { HStack(spacing: 12) {
                        Avatar(user: UserCard(username: user.username), size: 38)
                            .overlay(alignment: .bottomTrailing) {
                                if user.online == true { Circle().fill(.green).frame(width: 10, height: 10).overlay(Circle().stroke(.background, lineWidth: 2)) }
                            }
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 6) {
                                Text(user.username).font(.body.weight(.medium))
                                if user.isAdmin { Text("管理员").font(.caption2.weight(.semibold)).foregroundStyle(Palette.sky)
                                    .padding(.horizontal, 6).padding(.vertical, 2).background(Palette.sky.opacity(0.12), in: .capsule) }
                            }
                            Text("对话 \(user.conversations ?? 0) · 记忆 \(user.memories ?? 0) · " + (user.online == true ? "在线" : "上次 " + ISODate.relative(user.lastSeenAt)))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    } }
                    .swipeActions(edge: .trailing) {
                        if user.username != session.account?.username {
                            Button(user.isAdmin ? "取消管理员" : "设为管理员") { pendingRole = user }.tint(user.isAdmin ? .orange : Palette.sky)
                        }
                    }
                }
            } footer: { Text("左滑可以调整管理员权限，点进去可以给该用户发客服消息。") }
        }
        .overlay { if loading { ProgressView() } }
        .searchable(text: $search, prompt: "搜索用户名")
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("用户管理")
        .refreshable { await load() }
        .task { await load() }
        .confirmationDialog(pendingRole.map { $0.isAdmin ? "取消 \($0.username) 的管理员权限？" : "把 \($0.username) 设为管理员？" } ?? "",
                            isPresented: Binding(get: { pendingRole != nil }, set: { if !$0 { pendingRole = nil } }), titleVisibility: .visible) {
            Button("确定") { if let user = pendingRole { setRole(user) } }
        }
    }

    private func stat(_ value: String, _ title: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.title2.weight(.bold)).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private func load() async {
        struct Reply: Decodable { var users: [User] }
        do { users = try await API.shared.get("admin/users", as: Reply.self).users; error = nil }
        catch is CancellationError {} catch { self.error = error.localizedDescription }
        loading = false
    }

    private func setRole(_ user: User) {
        Task {
            do {
                _ = try await API.shared.request("PATCH", "admin/users/\(user.id)/role", body: ["is_admin": !user.isAdmin])
                await load()
            } catch { self.error = error.localizedDescription }
        }
    }
}

struct InviteCodesView: View {
    struct Invite: Decodable, Identifiable { var code: String; var maxUses: Int; var usedCount: Int; var active: Bool; var usable: Bool; var createdAt: String?; var id: String { code } }
    @State private var invites: [Invite] = []
    @State private var uses = 5
    @State private var error: String?
    @State private var copied: String?

    var body: some View {
        List {
            Section {
                Stepper("每个邀请码可邀请 \(uses) 人", value: $uses, in: 1...500)
                Button { create() } label: { Label("生成邀请码", systemImage: "plus.circle.fill") }
            } footer: { Text("把邀请码发给朋友，注册时填写即可。") }
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            Section("全部邀请码") {
                ForEach(invites) { invite in
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(invite.code).font(.system(.body, design: .monospaced).weight(.semibold))
                                .foregroundStyle(invite.usable ? .primary : .secondary)
                            Text("已用 \(invite.usedCount)/\(invite.maxUses)" + (invite.active ? (invite.usable ? "" : " · 已用完") : " · 已停用"))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if invite.usable {
                            Button(copied == invite.code ? "已复制" : "复制") {
                                UIPasteboard.general.string = invite.code
                                copied = invite.code
                            }
                            .buttonStyle(.glass).font(.footnote)
                        }
                    }
                    .swipeActions {
                        if invite.active {
                            Button("停用", role: .destructive) { deactivate(invite) }
                        }
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("邀请码")
        .task { await load() }
    }

    private func load() async {
        struct Reply: Decodable { var invites: [Invite] }
        do { invites = try await API.shared.get("admin/invites", as: Reply.self).invites } catch { self.error = error.localizedDescription }
    }
    private func create() {
        Task {
            do {
                let invite = try await API.shared.post("admin/invites", body: ["max_uses": uses], as: Invite.self)
                invites.insert(invite, at: 0)
                UIPasteboard.general.string = invite.code
                copied = invite.code
            } catch { self.error = error.localizedDescription }
        }
    }
    private func deactivate(_ invite: Invite) {
        Task {
            do { _ = try await API.shared.request("DELETE", "admin/invites/\(invite.code)"); await load() }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct AdminAnnouncementsView: View {
    @State private var items: [Announcement] = []
    @State private var title = ""
    @State private var content = ""
    @State private var busy = false
    @State private var error: String?
    @State private var withdrawing: Announcement?

    var body: some View {
        List {
            Section("新公告") {
                TextField("标题", text: $title)
                TextField("内容，支持 Markdown", text: $content, axis: .vertical).lineLimit(4...12)
                Button {
                    publish()
                } label: { Label(busy ? "发布中…" : "发布给所有用户", systemImage: "paperplane.fill") }
                .disabled(busy || title.trimmingCharacters(in: .whitespaces).isEmpty || content.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            Section("已发布") {
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.title).font(.headline)
                        Text(item.content).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                        Text(ISODate.relative(item.createdAt)).font(.caption).foregroundStyle(.tertiary)
                    }
                    .swipeActions { Button("撤回", role: .destructive) { withdrawing = item } }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("发布公告")
        .task { await load() }
        .confirmationDialog("撤回后所有人都看不到这条公告", isPresented: Binding(get: { withdrawing != nil }, set: { if !$0 { withdrawing = nil } }), titleVisibility: .visible) {
            Button("撤回", role: .destructive) { if let item = withdrawing { withdraw(item) } }
        }
    }

    private func load() async {
        struct Reply: Decodable { var announcements: [Announcement] }
        items = (try? await API.shared.get("announcements", as: Reply.self).announcements) ?? []
    }
    private func publish() {
        busy = true
        Task {
            do {
                _ = try await API.shared.request("POST", "admin/announcements", body: ["title": title, "content": content])
                title = ""; content = ""; error = nil
                await load()
            } catch { self.error = error.localizedDescription }
            busy = false
        }
    }
    private func withdraw(_ item: Announcement) {
        Task {
            do { _ = try await API.shared.request("DELETE", "admin/announcements/\(item.id)"); await load() }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct SupportInboxView: View {
    struct Thread: Decodable, Identifiable { var userId: String; var username: String; var online: Bool?; var unread: Int; var lastAt: String?; var lastSender: String?; var lastExcerpt: String?; var id: String { userId } }
    @State private var threads: [Thread] = []
    @State private var loading = true

    var body: some View {
        List(threads) { thread in
            NavigationLink { SupportChatView(mode: .admin(userID: thread.userId, username: thread.username)) } label: {
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(thread.username).font(.body.weight(.medium))
                        if thread.online == true { Circle().fill(.green).frame(width: 7, height: 7) }
                        Spacer()
                        Text(ISODate.relative(thread.lastAt)).font(.caption).foregroundStyle(.secondary)
                    }
                    Text((thread.lastSender == "admin" ? "你：" : "") + (thread.lastExcerpt ?? "")).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                }
                .badge(thread.unread)
            }
        }
        .overlay {
            if loading { ProgressView() }
            else if threads.isEmpty { EmptyState(symbol: "tray", title: "没有客服消息", message: "用户发来的问题会出现在这里。") }
        }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("客服消息")
        .refreshable { await load() }
        .task { await load() }
    }

    private func load() async {
        struct Reply: Decodable { var threads: [Thread] }
        threads = (try? await API.shared.get("admin/support/threads", as: Reply.self).threads) ?? []
        loading = false
    }
}
