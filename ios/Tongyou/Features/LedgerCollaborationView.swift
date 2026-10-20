import SwiftUI

func ledgerRoleName(_ role: String) -> String {
    ["owner": "创建者", "editor": "可编辑", "viewer": "只读"][role] ?? role
}
struct LedgerInvite: Decodable, Identifiable {
    var id: String; var title: String; var inviter: String; var role: String
}
private struct LedgerMember: Decodable, Identifiable {
    var id: String; var username: String; var role: String; var status: String
}
private struct LedgerShare: Decodable {
    var token: String; var role: String; var expiresAt: String
    var url: URL { URL(string: "https://17tongyou.com/travel/?ledger_join=\(token)")! }
}

struct LedgerMemberPanel: View {
    let bookID: String
    let owner: Bool
    var onChanged: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var members: [LedgerMember] = []
    @State private var share: LedgerShare?
    @State private var username = ""
    @State private var role = "viewer"
    @State private var linkRole = "viewer"
    @State private var busy = false
    @State private var error: String?
    @State private var notice: String?
    @State private var removal: LedgerMember?
    @State private var shareAction: String?
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("账本权限独立于行程。编辑成员可增改删账单，只读成员只能查看。").font(.footnote)
                    if let error { Text(error).foregroundStyle(.red); Button("重新加载") { Task { await load() } } }
                    if let notice { Text(notice).foregroundStyle(.secondary) }
                    ForEach(members) { member in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(member.username).font(.headline)
                            Text(member.status == "pending" ? "待接受邀请" : ledgerRoleName(member.role)).font(.caption).foregroundStyle(.secondary)
                            if owner && member.role != "owner" {
                                Picker("权限", selection: Binding(get: {member.role}, set: {change("/members/\(member.id)", "PATCH", ["role": $0])})) {
                                    Text("只读").tag("viewer"); Text("可编辑").tag("editor")
                                }
                                Button("移除成员", role: .destructive) { removal = member }
                            }
                        }
                    }
                } header: { Text("成员") }
                if owner {
                    Section("邀请用户") {
                        TextField("完整用户名", text: $username).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Text("无需是好友或行程成员，对方将在记账页收到邀请。").font(.caption).foregroundStyle(.secondary)
                        Picker("邀请权限", selection: $role) { Text("只读").tag("viewer"); Text("可编辑").tag("editor") }
                        Button("发送邀请") { change("/members", "POST", ["username": username.trimmingCharacters(in: .whitespacesAndNewlines), "role": role], "邀请已发送") }.disabled(username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    Section("通过链接加入") {
                        Text("持有链接的人登录后可自行加入。有效期 7 天，请只发给信任的人。").font(.footnote)
                        Picker("链接加入权限", selection: $linkRole) { Text("只读").tag("viewer"); Text("可编辑 · 可增改删账单").tag("editor") }
                        Button(share == nil ? "生成分享链接" : "重新生成链接") {
                            if share == nil { change("/share", "POST", ["role": linkRole]) } else { shareAction = "reset" }
                        }
                        if let share {
                            Text("当前链接：\(ledgerRoleName(share.role))").font(.subheadline)
                            Text("到期：\(share.expiresAt)").font(.caption).foregroundStyle(.secondary)
                            ShareLink(item: share.url) { Label("分享账本链接", systemImage: "square.and.arrow.up") }
                            Button("复制链接") { UIPasteboard.general.string = share.url.absoluteString; notice = "链接已复制" }
                            Button("撤销链接", role: .destructive) { shareAction = "revoke" }
                            Text("撤销链接不影响已加入成员；收回访问权限请移除成员。").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }.disabled(busy)
            .navigationTitle("成员与分享").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() }.disabled(busy) } }
            .confirmationDialog("移除此成员？已有账单保留，对方将失去访问权限。", isPresented: Binding(get: {removal != nil}, set: {if !$0 {removal = nil}}), titleVisibility: .visible) {
                if let removal { Button("移除成员", role: .destructive) { change("/members/\(removal.id)", "DELETE") } }
            }
            .confirmationDialog("旧链接将立即失效，已加入成员不受影响。", isPresented: Binding(get: {shareAction != nil}, set: {if !$0 {shareAction = nil}}), titleVisibility: .visible) {
                if let shareAction { Button(shareAction == "reset" ? "重新生成" : "撤销链接", role: .destructive) { change("/share", shareAction == "reset" ? "POST" : "DELETE", shareAction == "reset" ? ["role": linkRole] : nil) } }
            }
            .task { await load() }.interactiveDismissDisabled(busy)
        }
    }
    private func load() async {
        do {
            members = try await API.shared.get("ledger/\(bookID)/members", as: [LedgerMember].self)
            if owner { share = try await API.shared.get("ledger/\(bookID)/share", as: LedgerShare?.self) }
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    private func change(_ path: String, _ method: String, _ body: [String: String]? = nil, _ message: String? = nil) {
        guard !busy else { return }; busy = true; notice = nil
        Task {
            defer { busy = false }
            do { _ = try await API.shared.request(method, "ledger/\(bookID)\(path)", body: body); await load(); notice = message; onChanged() }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct LedgerJoinEditor: View {
    var initialToken: String? = nil
    var onJoined: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var link = ""
    @State private var token = ""
    @State private var preview: Preview?
    @State private var error: String?
    @State private var busy = false
    private struct Preview: Decodable { var title: String; var role: String; var inviter: String }
    private struct Joined: Decodable { var id: String }
    var body: some View {
        NavigationStack {
            Form {
                Section("粘贴账本分享链接") {
                    TextField("https://17tongyou.com/travel/?ledger_join=…", text: $link, axis: .vertical).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onChange(of: link) { _, _ in preview = nil; token = "" }
                    Button("查看邀请") { inspect() }.disabled(link.isEmpty || busy)
                }
                if let preview {
                    Section(preview.title) {
                        Text("\(preview.inviter) 邀请你加入 · \(ledgerRoleName(preview.role))")
                        Text(preview.role == "editor" ? "可查看、添加、修改和删除账单。" : "可查看账单和统计，不可修改账单。")
                        Text("加入账本不会加入关联行程。").font(.footnote).foregroundStyle(.secondary)
                        Button("确认加入账本") { join() }.disabled(busy)
                    }
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("加入账本")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) } }
            .interactiveDismissDisabled(busy)
            .task {
                if let initialToken { link = LedgerDeepLink(token: initialToken).webURL.absoluteString; inspect() }
            }
        }
    }
    private func inspect() {
        let value = link.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: value), let invite = LedgerDeepLink.parse(url) else { error = "请粘贴完整的 17同游账本分享链接"; return }
        let code = invite.token
        busy = true; error = nil
        Task {
            defer { busy = false }
            do { let result = try await API.shared.get("ledger/shared/\(code)", as: Preview.self); token = code; preview = result }
            catch { self.error = error.localizedDescription }
        }
    }
    private func join() {
        busy = true
        Task {
            defer { busy = false }
            do { let result = try await API.shared.post("ledger/join", body: ["token": token], as: Joined.self); onJoined(result.id); dismiss() }
            catch { self.error = error.localizedDescription }
        }
    }
}
