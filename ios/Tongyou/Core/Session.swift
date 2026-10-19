import Foundation
import Observation

struct AccountInfo: Codable, Equatable {
    var username: String
    var isAdmin: Bool
    var displayName: String
    var avatarUrl: String
    var mustChangePassword: Bool
}

private struct AuthReply: Decodable {
    var token: String
    var username: String
    var isAdmin: Bool
    var displayName: String?
    var avatarUrl: String?
    var mustChangePassword: Bool?
    var account: AccountInfo {
        AccountInfo(username: username, isAdmin: isAdmin, displayName: displayName ?? username,
                    avatarUrl: avatarUrl ?? "", mustChangePassword: mustChangePassword ?? false)
    }
}

@MainActor @Observable
final class AppSession {
    enum State: Equatable { case checking, signedOut, signedIn }
    private(set) var state: State
    private(set) var account: AccountInfo?

    init() {
        state = API.shared.token == nil ? .signedOut : .checking
        API.shared.onUnauthorized = { [weak self] in self?.signOutLocally() }
    }

    /// Confirms a stored token is still valid; network failures keep the person signed in.
    func restore() async {
        guard API.shared.token != nil else { state = .signedOut; return }
        do {
            account = try await API.shared.get("auth/me", as: AccountInfo.self)
            state = .signedIn
        } catch APIError.unauthorized {
            signOutLocally()
        } catch {
            state = .signedIn
        }
    }

    func login(username: String, password: String) async throws {
        try await authenticate("auth/login", ["username": username, "password": password])
    }

    func register(username: String, password: String, invite: String) async throws {
        try await authenticate("auth/register", ["username": username, "password": password, "invite_code": invite])
    }

    private func authenticate(_ path: String, _ body: [String: String]) async throws {
        API.shared.token = nil
        let reply = try await API.shared.post(path, body: body, as: AuthReply.self)
        TokenStore.save(reply.token)
        API.shared.token = reply.token
        account = reply.account
        state = .signedIn
    }

    func logout() async {
        _ = try? await API.shared.request("POST", "auth/logout")
        signOutLocally()
    }

    private func signOutLocally() {
        TokenStore.save(nil)
        API.shared.token = nil
        account = nil
        state = .signedOut
    }
}
