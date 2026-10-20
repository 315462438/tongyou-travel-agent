import Foundation
import Observation

struct LedgerDeepLink: Identifiable, Equatable {
    let token: String
    var id: String { token }
    var webURL: URL { URL(string: "https://17tongyou.com/travel/?ledger_join=\(token)")! }

    static func parse(_ url: URL) -> LedgerDeepLink? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.user == nil, parts.password == nil, parts.fragment == nil else { return nil }
        let key: String
        if parts.scheme == "https", parts.host == "17tongyou.com", parts.port == nil || parts.port == 443,
           ["/travel", "/travel/"].contains(parts.path) { key = "ledger_join" }
        else if parts.scheme == "tongyou", parts.host == "ledger", parts.port == nil, parts.path == "/join" { key = "token" }
        else { return nil }
        let tokens = (parts.queryItems ?? []).filter { $0.name == key }
        guard tokens.count == 1, let token = tokens.first?.value,
              token.range(of: #"^[A-Za-z0-9_-]{32,64}$"#, options: .regularExpression) != nil else { return nil }
        return LedgerDeepLink(token: token)
    }
}

/// Holds an invitation through login/relaunch. Receiving a link never grants membership.
@MainActor @Observable
final class LedgerLinkInbox {
    private let defaults: UserDefaults
    private static let key = "pendingLedgerDeepLink"
    var pending: LedgerDeepLink? {
        didSet { defaults.set(pending?.token, forKey: Self.key) }
    }
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let token = defaults.string(forKey: Self.key),
           let url = URL(string: "tongyou://ledger/join?token=\(token)") {
            pending = LedgerDeepLink.parse(url)
        }
    }
    @discardableResult func receive(_ url: URL) -> Bool {
        guard let invite = LedgerDeepLink.parse(url) else { return false }
        pending = invite
        return true
    }
}
