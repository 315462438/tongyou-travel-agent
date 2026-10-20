import Foundation

@main struct LedgerDeepLinkTests {
    @MainActor static func main() {
        let token = String(repeating: "a", count: 43)
        let web = "https://17tongyou.com/travel/?ledger_join=\(token)"
        let native = "tongyou://ledger/join?token=\(token)"
        func parse(_ value: String) -> LedgerDeepLink? { URL(string: value).flatMap(LedgerDeepLink.parse) }
        precondition(parse(web)?.token == token)
        precondition(parse(native)?.webURL.absoluteString == web)
        for bad in [
            "http://17tongyou.com/travel/?ledger_join=\(token)",
            "https://17tongyou.com.evil.test/travel/?ledger_join=\(token)",
            "https://evil@17tongyou.com/travel/?ledger_join=\(token)",
            "https://17tongyou.com:8443/travel/?ledger_join=\(token)",
            "https://17tongyou.com/travel/api/?ledger_join=\(token)",
            web + "&ledger_join=\(token)", native + "&token=\(token)",
            native + "#redirect", "tongyou://ledger/join?token=short",
            "tongyou://ledger/join?token=" + String(repeating: "a", count: 65),
            "tongyou://evil/join?token=\(token)", "tongyou://ledger/delete?token=\(token)",
            "tongyou://ledger/join?token=%2F" + token
        ] { precondition(parse(bad) == nil, "Accepted invalid URL: \(bad)") }
        let name = "TongyouLinkTests-\(UUID().uuidString)"
        let store = UserDefaults(suiteName: name)!
        defer { store.removePersistentDomain(forName: name) }
        let inbox = LedgerLinkInbox(defaults: store)
        precondition(inbox.pending == nil)
        precondition(inbox.receive(URL(string: native)!))
        precondition(!inbox.receive(URL(string: "tongyou://evil")!))
        precondition(inbox.pending?.token == token)
        let restored = LedgerLinkInbox(defaults: store)
        precondition(restored.pending?.token == token)
        restored.pending = nil
        precondition(LedgerLinkInbox(defaults: store).pending == nil)
        print("PASS: HTTPS/custom URL parsing, 13 rejection cases, pending invitation persistence and cancellation")
    }
}
