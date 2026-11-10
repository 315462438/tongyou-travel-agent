import Foundation

struct TripNotificationTarget: Hashable {
    let requestID = UUID()
    let tripID: String
    let day: Int?
    let pollID: String?

    init?(tripID: String?, fallbackID: String? = nil, day: Double?, pollID: String?) {
        let primary = tripID?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let id = primary.isEmpty ? (fallbackID?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "") : primary
        guard !id.isEmpty else { return nil }
        self.tripID = id
        self.day = day.flatMap { $0.isFinite && $0 >= 1 && $0 < Double(Int.max) && $0.rounded() == $0 ? Int($0) : nil }
        let poll = pollID?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.pollID = poll?.isEmpty == false ? poll : nil
    }

    /// Notifications can outlive edits to the trip. Prefer the poll's current day, including nil (whole trip).
    func resolve(days: Int, polls: [(id: String, day: Int?)], currentDay: Int = 1) -> (day: Int, pollID: String?) {
        let poll = polls.first { $0.id == pollID }
        let wanted: Int? = poll != nil ? poll!.day : day
        let count = max(1, days)
        let selected = wanted.flatMap { (1...count).contains($0) ? $0 : nil }
            ?? ((1...count).contains(currentDay) ? currentDay : 1)
        return (selected, poll.flatMap { $0.day == nil || $0.day == selected ? $0.id : nil })
    }
}
