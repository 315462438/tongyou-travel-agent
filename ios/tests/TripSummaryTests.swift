import Foundation

@main struct TripSummaryTests {
    static func main() throws {
        let cases: [(String?, Int?, String)] = [
            (nil, nil, "时间待定"), ("", 30, "时间待定"),
            ("09:00", 90, "09:00 – 10:30"), ("23:30", 90, "23:30 – 次日 01:00"),
            ("09:00", nil, "09:00"), ("09:00", 0, "09:00"), ("待定", 30, "待定")
        ]
        for (start, duration, expected) in cases {
            var raw: [String: Any] = ["id": "stop", "day": 1, "name": "西湖"]
            if let start { raw["startTime"] = start }
            if let duration { raw["stayMin"] = duration }
            let stop = try JSONDecoder().decode(TripDetail.Stop.self, from: JSONSerialization.data(withJSONObject: raw))
            precondition(stop.compactTimeRange == expected)
        }
        print("TripSummary: 7 time-range cases passed")
    }
}
