import Foundation

@main struct ChatPreferencesTests {
    static func main() {
        let suite = "ChatPreferencesTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        precondition(ChatPreferences.webSearch(in: defaults))
        precondition(defaults.object(forKey: "webSearch") == nil)
        defaults.set(false, forKey: "webSearch")
        precondition(!ChatPreferences.webSearch(in: defaults))
        defaults.set(true, forKey: "webSearch")
        precondition(ChatPreferences.webSearch(in: defaults))
        print("ChatPreferences: unset / explicit false / explicit true passed")
    }
}
