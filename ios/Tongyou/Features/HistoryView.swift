import SwiftUI

struct ConversationSummary: Decodable, Identifiable, Hashable {
    var id: String
    var title: String
    var updatedAt: String

    var date: Date? { ISODate.parse(updatedAt) }
}

enum ISODate {
    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f
    }()
    private static let plain = ISO8601DateFormatter()
    /// The backend emits naive UTC timestamps (no zone) as well as zoned ones.
    static func parse(_ text: String?) -> Date? {
        guard var text, !text.isEmpty else { return nil }
        let hasZone = text.hasSuffix("Z") || text.range(of: #"[+-]\d\d:\d\d$"#, options: .regularExpression) != nil
        if !hasZone { text += "Z" }
        return fractional.date(from: text) ?? plain.date(from: text)
    }
    static func relative(_ text: String?) -> String {
        guard let date = parse(text) else { return "" }
        return date.formatted(.relative(presentation: .named))
    }
}

struct HistoryView: View {
    @State private var conversations: [ConversationSummary] = []
    @State private var search = ""
    @State private var loading = true
    @State private var error: String?

    private var filtered: [ConversationSummary] {
        let query = search.trimmingCharacters(in: .whitespaces)
        return query.isEmpty ? conversations : conversations.filter { $0.title.localizedCaseInsensitiveContains(query) }
    }

    var body: some View {
        NavigationStack {
            List {
                if let error {
                    Label(error, systemImage: "wifi.exclamationmark").foregroundStyle(.secondary)
                        .listRowBackground(Color.clear)
                }
                ForEach(filtered) { conversation in
                    NavigationLink(value: conversation) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(conversation.title).font(.body.weight(.medium)).lineLimit(2)
                            Text(ISODate.relative(conversation.updatedAt)).font(.caption).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                    .listRowBackground(Color.clear)
                    .swipeActions {
                        Button(role: .destructive) { delete(conversation) } label: { Label("删除", systemImage: "trash") }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .overlay {
                if loading && conversations.isEmpty { ProgressView() }
                else if !loading && filtered.isEmpty && error == nil {
                    EmptyState(symbol: "bubble.left.and.text.bubble.right", title: search.isEmpty ? "还没有对话" : "没有找到",
                               message: search.isEmpty ? "在首页说一个目的地，开始第一次规划。" : "换个关键词试试。")
                }
            }
            .navigationTitle("历史")
            .searchable(text: $search, prompt: "搜索对话")
            .navigationDestination(for: ConversationSummary.self) { ChatView(conversationID: $0.id, title: $0.title) }
            .refreshable { await load() }
            .task { await load() }
            .screenBackground()
        }
    }

    private func load() async {
        do {
            conversations = try await API.shared.get("chat/conversations", as: [ConversationSummary].self)
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }

    private func delete(_ conversation: ConversationSummary) {
        withAnimation { conversations.removeAll { $0.id == conversation.id } }
        Task {
            do { _ = try await API.shared.request("DELETE", "chat/conversations/\(conversation.id)") }
            catch { self.error = error.localizedDescription; await load() }
        }
    }
}
