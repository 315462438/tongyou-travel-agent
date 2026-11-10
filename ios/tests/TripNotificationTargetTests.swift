import Foundation
@main struct TripNotificationTargetTests {
    static func main() {
        let target = TripNotificationTarget(tripID: " t1 ", day: 2, pollID: "p")!
        precondition(target.tripID == "t1" && target.day == 2 && target.pollID == "p")
        precondition(target != TripNotificationTarget(tripID: "t1", day: 2, pollID: "p")!)
        precondition(TripNotificationTarget(tripID: " ", day: nil, pollID: nil) == nil)
        precondition(TripNotificationTarget(tripID: " ", fallbackID: "t2", day: nil, pollID: nil)?.tripID == "t2")
        for invalid in [0.0, -1, 1.5, .infinity, .nan, Double(Int.max)] {
            precondition(TripNotificationTarget(tripID: "t", day: invalid, pollID: nil)?.day == nil)
        }
        precondition(target.resolve(days: 3, polls: [("p", 3)]).day == 3)
        precondition(target.resolve(days: 3, polls: [("p", nil)]).day == 1)
        precondition(target.resolve(days: 3, polls: []).day == 2)
        precondition(target.resolve(days: 1, polls: [("p", 2)]).pollID == nil)
        precondition(target.resolve(days: 0, polls: [], currentDay: 99).day == 1)
        precondition(TripNotificationTarget(tripID: "t", day: nil, pollID: "p")!.resolve(days: 3, polls: [("p", 2)]).day == 2)
        print("TripNotificationTarget: parsing, repeat requests, current day, whole trip, deleted poll and invalid days passed")
    }
}
