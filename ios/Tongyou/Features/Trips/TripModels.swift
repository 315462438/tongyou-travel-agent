import CoreLocation
import Foundation

struct TripSummary: Decodable, Identifiable, Hashable {
    var id: String
    var title: String
    var destination: String?
    var days: Int?
    var role: String?
    var updatedAt: String?
}

struct TripDetail: Decodable {
    var id: String
    var title: String
    var destination: String?
    var days: Int?
    var budget: Double?
    var startDate: String?
    var aiStatus: String?
    var aiReview: String?
    var dayTitles: [String: String]?
    var members: [Member]?
    var stops: [Stop]
    var hotelRecommendations: [Hotel]?

    struct Member: Decodable, Hashable { var username: String; var role: String?; var online: Bool? }
    struct Hotel: Decodable, Hashable { var city: String?; var hotel: String?; var price: Double?; var note: String? }

    struct Stop: Decodable, Identifiable, Hashable {
        var id: String
        var day: Int
        var orderNo: Int?
        var name: String
        var note: String?
        var location: String?
        var startTime: String?
        var stayMin: Int?
        var transport: String?
        var ticketPrice: Double?
        var tags: [String]?
        var nav: Nav?

        struct Nav: Decodable, Hashable { var amap: String?; var apple: String?; var google: String?; var domestic: Bool? }

        /// `location` is "lng,lat": GCJ-02 inside mainland China, WGS-84 abroad. MapKit wants WGS-84.
        var coordinate: CLLocationCoordinate2D? {
            guard let parts = location?.split(separator: ","), parts.count == 2,
                  let lng = Double(parts[0].trimmingCharacters(in: .whitespaces)),
                  let lat = Double(parts[1].trimmingCharacters(in: .whitespaces)) else { return nil }
            let point = CLLocationCoordinate2D(latitude: lat, longitude: lng)
            return nav?.domestic == true || ChinaCoordinates.isInMainland(point) ? ChinaCoordinates.gcjToWGS(point) : point
        }

        var navigationURL: URL? {
            let preferred = nav?.domestic == true ? (nav?.amap ?? nav?.apple) : (nav?.apple ?? nav?.amap)
            return preferred.flatMap(URL.init(string:))
        }
    }

    func stops(on day: Int) -> [Stop] {
        stops.filter { $0.day == day }.sorted { ($0.orderNo ?? 0) < ($1.orderNo ?? 0) }
    }

    var dayCount: Int { max(days ?? 1, stops.map(\.day).max() ?? 1) }
}

struct ExpenseSummary: Decodable {
    var total: Double
    var count: Int
    var byCategory: [String: Double]?
    var transfers: [Transfer]?
    var text: String?
    struct Transfer: Decodable, Hashable { var from: String; var to: String; var amount: Double }
}

/// Standard GCJ-02 ⇄ WGS-84 approximation (error well under 5 m in mainland China).
enum ChinaCoordinates {
    private static let a = 6378245.0
    private static let ee = 0.00669342162296594323

    static func isInMainland(_ c: CLLocationCoordinate2D) -> Bool {
        (73.66...135.05).contains(c.longitude) && (3.86...53.55).contains(c.latitude)
    }

    static func gcjToWGS(_ gcj: CLLocationCoordinate2D) -> CLLocationCoordinate2D {
        let shifted = wgsToGCJ(gcj)
        return CLLocationCoordinate2D(latitude: gcj.latitude * 2 - shifted.latitude, longitude: gcj.longitude * 2 - shifted.longitude)
    }

    static func wgsToGCJ(_ wgs: CLLocationCoordinate2D) -> CLLocationCoordinate2D {
        var dLat = transformLat(wgs.longitude - 105, wgs.latitude - 35)
        var dLng = transformLng(wgs.longitude - 105, wgs.latitude - 35)
        let radLat = wgs.latitude / 180 * .pi
        var magic = sin(radLat)
        magic = 1 - ee * magic * magic
        let sqrtMagic = sqrt(magic)
        dLat = (dLat * 180) / ((a * (1 - ee)) / (magic * sqrtMagic) * .pi)
        dLng = (dLng * 180) / (a / sqrtMagic * cos(radLat) * .pi)
        return CLLocationCoordinate2D(latitude: wgs.latitude + dLat, longitude: wgs.longitude + dLng)
    }

    private static func transformLat(_ x: Double, _ y: Double) -> Double {
        var r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * sqrt(abs(x))
        r += (20 * sin(6 * x * .pi) + 20 * sin(2 * x * .pi)) * 2 / 3
        r += (20 * sin(y * .pi) + 40 * sin(y / 3 * .pi)) * 2 / 3
        r += (160 * sin(y / 12 * .pi) + 320 * sin(y * .pi / 30)) * 2 / 3
        return r
    }

    private static func transformLng(_ x: Double, _ y: Double) -> Double {
        var r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * sqrt(abs(x))
        r += (20 * sin(6 * x * .pi) + 20 * sin(2 * x * .pi)) * 2 / 3
        r += (20 * sin(x * .pi) + 40 * sin(x / 3 * .pi)) * 2 / 3
        r += (150 * sin(x / 12 * .pi) + 300 * sin(x / 30 * .pi)) * 2 / 3
        return r
    }
}
