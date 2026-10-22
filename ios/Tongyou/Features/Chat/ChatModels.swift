import Foundation
import Observation
import UIKit

struct ChatMessage: Decodable, Identifiable, Equatable {
    var id: String
    var role: String
    var content: String
    var reasoning: String?
    var meta: JSONValue?
    var createdAt: String?

    private enum CodingKeys: String, CodingKey { case id, role, content, reasoning, meta, createdAt }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        role = try c.decode(String.self, forKey: .role)
        content = try c.decodeIfPresent(String.self, forKey: .content) ?? ""
        reasoning = try c.decodeIfPresent(String.self, forKey: .reasoning)
        meta = try c.decodeIfPresent(JSONValue.self, forKey: .meta)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
    }
    init(id: String, role: String, content: String, meta: JSONValue? = nil) {
        self.id = id; self.role = role; self.content = content; self.meta = meta
    }

    var streaming: Bool { meta?["streaming"]?.bool == true }
    var preliminary: Bool { meta?["preliminary"]?.bool == true }
    var hasMeta: Bool { meta.map { !$0.isNull && ($0.object?.isEmpty == false) } ?? false }
    var images: [String] { meta?["images"]?.array?.compactMap(\.string) ?? [] }
    var sources: [Source] {
        meta?["sources"]?.array?.compactMap { item in
            guard let url = item["url"]?.string else { return nil }
            return Source(title: item["title"]?.string ?? url, url: url)
        } ?? []
    }
    var candidates: [Candidate] {
        meta?["candidates"]?.array?.compactMap { item in
            guard let name = item["name"]?.string else { return nil }
            return Candidate(name: name, reason: item["reason"]?.string ?? "", tag: item["tag"]?.string ?? "")
        } ?? []
    }
    var importedTripID: String? { meta?["imported_trip_id"]?.string }
    /// The web shows guide follow-ups (budget, poster, trip import) only for finished, sourced guides.
    var isGuide: Bool {
        role == "assistant" && !streaming && meta?["direct"]?.bool != true && !sources.isEmpty && content.contains("##")
    }

    struct Source: Hashable { var title: String; var url: String
        var host: String { URL(string: url)?.host?.replacingOccurrences(of: "www.", with: "") ?? url }
    }
    struct Candidate: Hashable { var name: String; var reason: String; var tag: String }
}

private struct MessagesReply: Decodable {
    var messages: [ChatMessage]
    var running: Bool
}

@MainActor @Observable
final class ChatStore {
    private(set) var conversationID: String?
    private(set) var messages: [ChatMessage] = []
    private(set) var running = false
    private(set) var loaded = false
    var error: String?
    private var stopRequested = false
    var petTask: PetTask {
        TravelPetLogic.task(messages.map { message in
            PetMessage(id: message.id, role: message.role, content: message.content, streaming: message.streaming,
                       preliminary: message.preliminary, confirmID: message.meta?["confirm"]?["id"]?.string,
                       handoff: message.meta?["handoff"] != nil, replyID: message.meta?["confirm_reply"]?["confirm_id"]?.string,
                       cancelled: message.meta?["cancelled"]?.bool == true, failed: message.meta?["error"] != nil)
        }, running: running, stopped: stopRequested, failed: error != nil)
    }
    var deepReasoning = false
    /// Search the web before quick answers; remembered across conversations.
    var webSearch = ChatPreferences.webSearch() {
        didSet { UserDefaults.standard.set(webSearch, forKey: "webSearch") }
    }
    /// Conversation title, used to name exported guides.
    var title = "旅行攻略"
    private var pollTask: Task<Void, Never>?
    var onTurnFinished: (() -> Void)?

    init(conversationID: String? = nil) {
        self.conversationID = conversationID
        loaded = conversationID == nil
    }

    // MARK: Derived views of the message list

    /// Hidden `action` rows only record a confirm reply; plain progress rows feed the "thinking" panel.
    var visible: [ChatMessage] {
        messages.filter { message in
            if message.role == "action" { return false }
            if message.role == "progress" {
                if message.meta?["subagents"] != nil { return false }
                if !message.hasMeta { return !running }   // the backend deletes these when the turn ends
            }
            return true
        }
    }

    /// The latest plain progress lines of the running turn, newest last.
    var thinkingTrail: [String] {
        guard running else { return [] }
        let lastUser = messages.lastIndex { $0.role == "user" } ?? -1
        return messages.enumerated()
            .filter { $0.offset > lastUser && $0.element.role == "progress" && !$0.element.hasMeta && !$0.element.content.isEmpty }
            .map(\.element.content).suffix(6)
    }

    var thinkingStatus: String {
        if let last = thinkingTrail.last { return last }
        return messages.contains { $0.role == "assistant" && $0.streaming } ? "正在生成你的旅行方案…" : "正在理解你的旅行需求…"
    }

    var subagents: [JSONValue] {
        messages.last { $0.role == "progress" && $0.meta?["subagents"] != nil }?.meta?["subagents"]?.array ?? []
    }

    func confirmReply(for id: String) -> String? {
        messages.last { $0.role == "action" && $0.meta?["confirm_reply"]?["confirm_id"]?.string == id }?
            .meta?["confirm_reply"]?["choice"]?.string
    }

    // MARK: Network

    func load() async {
        guard let conversationID else { return }
        do {
            let reply = try await API.shared.get("chat/\(conversationID)/messages", as: MessagesReply.self)
            apply(reply)
            if reply.running { startPolling() }
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
        loaded = true
    }

    func send(_ text: String, images: [String] = [], deep: Bool? = nil) async {
        let content = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(4000))
        guard !content.isEmpty || !images.isEmpty else { return }
        error = nil
        stopRequested = false
        do {
            if conversationID == nil {
                struct Created: Decodable { var conversationId: String }
                conversationID = try await API.shared.post("chat/conversations", as: Created.self).conversationId
            }
            guard let conversationID else { return }
            var meta: JSONValue?
            if !images.isEmpty { meta = .object(["images": .array(images.map(JSONValue.string))]) }
            messages.append(ChatMessage(id: "local-\(UUID().uuidString)", role: "user", content: content, meta: meta))
            running = true
            do {
                _ = try await API.shared.request("POST", "chat/\(conversationID)/messages",
                                                 body: ["content": content, "deep_reasoning": deep ?? deepReasoning,
                                                        "sandbox_enabled": false, "web_search": webSearch, "image_ids": images])
            } catch APIError.server(409, _) {
                // A turn is already running; just follow it.
            }
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            startPolling()
        } catch {
            running = false
            messages.removeAll { $0.id.hasPrefix("local-") }
            self.error = error.localizedDescription
        }
    }

    func stop() {
        guard let conversationID else { return }
        stopRequested = true
        Task {
            do { _ = try await API.shared.request("POST", "chat/\(conversationID)/stop") }
            catch { stopRequested = false; self.error = "停止请求未送达，请重试" }
        }
    }

    func confirm(_ id: String, choice: String) {
        guard let conversationID else { return }
        Task {
            do {
                _ = try await API.shared.request("POST", "chat/\(conversationID)/confirm", body: ["confirm_id": id, "choice": choice])
                startPolling()
            } catch { self.error = error.localizedDescription }
        }
    }

    /// Budget breakdown and poster both append a new streaming assistant message.
    func requestExtra(_ kind: String, messageID: String) {
        guard let conversationID else { return }
        Task {
            do {
                stopRequested = false
                error = nil
                _ = try await API.shared.request("POST", "chat/\(conversationID)/\(kind)", body: ["message_id": messageID])
                running = true
                startPolling()
            } catch { self.error = error.localizedDescription }
        }
    }

    func importTrip(messageID: String) async -> String? {
        guard let conversationID else { return nil }
        struct Imported: Decodable { var id: String }
        do {
            let trip = try await API.shared.post("trips/import", body: ["conversation_id": conversationID, "message_id": messageID], as: Imported.self)
            if let index = messages.firstIndex(where: { $0.id == messageID }), case .object(var object) = messages[index].meta ?? .object([:]) {
                object["imported_trip_id"] = .string(trip.id)
                messages[index].meta = .object(object)
            }
            return trip.id
        } catch {
            self.error = error.localizedDescription
            return nil
        }
    }

    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 800_000_000)
                guard let self, let id = self.conversationID, !Task.isCancelled else { return }
                guard let reply = try? await API.shared.get("chat/\(id)/messages", as: MessagesReply.self) else { continue }
                self.apply(reply)
                if !reply.running {
                    if self.petTask.phase == .ready { UINotificationFeedbackGenerator().notificationOccurred(.success) }
                    self.onTurnFinished?()
                    return
                }
            }
        }
    }

    func stopPolling() { pollTask?.cancel() }

    private func apply(_ reply: MessagesReply) {
        if reply.messages != messages { messages = reply.messages }
        running = reply.running
    }
}
