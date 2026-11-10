import CoreLocation

/// 取一次设备定位，只在用户问「附近」时用。拿不到（拒绝/超时）返回 nil，发送照常进行。
@MainActor
final class LocationOnce: NSObject, CLLocationManagerDelegate {
    static let shared = LocationOnce()
    private let manager = CLLocationManager()
    private var waiters: [CheckedContinuation<String?, Never>] = []

    static func wantsNearby(_ text: String) -> Bool {
        ["附近", "周边", "周围", "离我", "我旁边", "就近", "我这边", "我这儿"].contains { text.contains($0) }
    }

    override private init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    /// 后端要的 "lng,lat"（WGS-84）。
    func current(timeout: Duration = .seconds(5)) async -> String? {
        switch manager.authorizationStatus {
        case .denied, .restricted: return nil
        case .notDetermined: manager.requestWhenInUseAuthorization()
        default: manager.requestLocation()
        }
        Task { try? await Task.sleep(for: timeout); finish(nil) }
        return await withCheckedContinuation { waiters.append($0) }
    }

    private func finish(_ value: String?) {
        let pending = waiters
        waiters = []
        pending.forEach { $0.resume(returning: value) }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            guard !waiters.isEmpty else { return }
            switch manager.authorizationStatus {
            case .authorizedWhenInUse, .authorizedAlways: manager.requestLocation()
            case .denied, .restricted: finish(nil)
            default: break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let c = locations.last?.coordinate else { return }
        let value = String(format: "%.6f,%.6f", c.longitude, c.latitude)
        Task { @MainActor in finish(value) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in finish(nil) }
    }
}
