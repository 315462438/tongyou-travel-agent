import SwiftUI

struct FriendRow: Decodable, Identifiable, Hashable {
    var id: String
    var username: String
    var displayName: String?
    var avatarUrl: String?
    var homeCity: String?
    var friendshipId: String?
    var friendshipStatus: String?
    var card: UserCard { UserCard(id: id, username: username, displayName: displayName, avatarUrl: avatarUrl) }
}

struct FriendGroups: Decodable {
    var friends: [FriendRow] = []
    var received: [FriendRow] = []
    var sent: [FriendRow] = []
}

/// 好友：搜索加人、处理申请、看列表。好友不会自动看到私人行程，只是邀请同行时更好找人。
struct FriendsView: View {
    @State private var groups = FriendGroups()
    @State private var loaded = false
    @State private var query = ""
    @State private var results: [FriendRow] = []
    @State private var searching = false
    @State private var error: String?

    var body: some View {
        List {
            Section {
                HStack(spacing: 10) {
                    TextField("搜索用户名或昵称", text: $query)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .submitLabel(.search).onSubmit(search)
                    if searching { ProgressView() } else {
                        Button("搜索", action: search).disabled(query.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                ForEach(results) { person in
                    row(person) {
                        switch person.friendshipStatus {
                        case "accepted": Text("已是好友").font(.footnote).foregroundStyle(.secondary)
                        case "pending": Text("申请处理中").font(.footnote).foregroundStyle(.secondary)
                        default: Button("加好友") { request(person) }.buttonStyle(.glassProminent).font(.footnote)
                        }
                    }
                }
            } header: { Text("找人") } footer: {
                if let error { Text(error).foregroundStyle(.red) }
            }
            if !groups.received.isEmpty {
                Section("新的好友申请") {
                    ForEach(groups.received) { person in
                        row(person) {
                            HStack(spacing: 8) {
                                Button("忽略") { respond(person, accept: false) }.buttonStyle(.glass)
                                Button("接受") { respond(person, accept: true) }.buttonStyle(.glassProminent)
                            }
                            .font(.footnote)
                        }
                    }
                }
            }
            Section("我的好友 · \(groups.friends.count)") {
                if loaded && groups.friends.isEmpty {
                    Text("还没有好友。在上面搜索对方的用户名或昵称，发个申请。").font(.subheadline).foregroundStyle(.secondary)
                }
                ForEach(groups.friends) { person in row(person) { EmptyView() } }
            }
            if !groups.sent.isEmpty {
                Section("已发送的申请") {
                    ForEach(groups.sent) { person in row(person) { Text("等待对方确认").font(.footnote).foregroundStyle(.secondary) } }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .screenBackground()
        .navigationTitle("好友")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private func row<Trailing: View>(_ person: FriendRow, @ViewBuilder trailing: () -> Trailing) -> some View {
        HStack(spacing: 12) {
            Avatar(user: person.card, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(person.card.name).font(.body.weight(.medium))
                Text("@\(person.username)" + ((person.homeCity ?? "").isEmpty ? "" : " · \(person.homeCity!)"))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            trailing()
        }
        .buttonStyle(.borderless)
    }

    private func load() async {
        if let reply = try? await API.shared.get("social/friends", as: FriendGroups.self) { groups = reply }
        loaded = true
    }

    private struct Users: Decodable { var users: [FriendRow] }

    private func search() {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, !searching else { return }
        searching = true
        error = nil
        Task {
            do {
                results = try await API.shared.get("social/users", query: ["q": text], as: Users.self).users
                if results.isEmpty { error = "没有找到这个人，确认一下用户名。" }
            } catch { self.error = "搜索失败，请重试。" }
            searching = false
        }
    }

    private func request(_ person: FriendRow) {
        Task {
            do {
                _ = try await API.shared.request("POST", "social/friends/request/\(person.id)", body: [String: Any]())
                Haptics.success()
                if let index = results.firstIndex(of: person) { results[index].friendshipStatus = "pending" }
                await load()
            } catch { Haptics.error(); self.error = "发送申请失败，请重试。" }
        }
    }

    private func respond(_ person: FriendRow, accept: Bool) {
        guard let id = person.friendshipId else { return }
        Task {
            do {
                _ = try await API.shared.request("POST", "social/friends/\(id)/respond", body: ["accept": accept])
                if accept { Haptics.success() }
                await load()
            } catch { Haptics.error(); self.error = "操作失败，请重试。" }
        }
    }
}
