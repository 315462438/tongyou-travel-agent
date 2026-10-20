import Foundation

enum ChatPreferences {
    static let defaultWebSearch = true

    static func webSearch(in defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: "webSearch") as? Bool ?? defaultWebSearch
    }
}
