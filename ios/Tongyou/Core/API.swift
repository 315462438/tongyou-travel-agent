import Foundation
import Security
import SwiftUI

enum APIError: LocalizedError {
    case unauthorized
    case server(Int, String)
    case decoding(String)
    case network(String)
    var errorDescription: String? {
        switch self {
        case .unauthorized: return "登录已过期，请重新登录"
        case .server(_, let message): return message
        case .decoding: return "服务器返回的数据看不懂，请更新 App 或稍后再试"
        case .network(let message): return message
        }
    }
}

/// Thin client for https://17tongyou.com/travel/api. Every request carries the Bearer token;
/// a 401 signs the person out, matching the web app's `authFetch`.
final class API {
    static let shared = API()
    static let origin = URL(string: "https://17tongyou.com")!
    static let base = URL(string: "https://17tongyou.com/travel/api")!
    var token: String? = TokenStore.read()
    var onUnauthorized: (() -> Void)?

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        #if DEBUG
        if JourneyUITestProtocol.enabled { config.protocolClasses = [JourneyUITestProtocol.self] }
        #endif
        config.timeoutIntervalForRequest = 30
        config.waitsForConnectivity = true
        config.timeoutIntervalForResource = 120
        return URLSession(configuration: config)
    }()

    let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    /// Resolves the site's relative media paths ("/travel/api/uploads/…", "/travel/api/img?…").
    static func resolve(_ path: String?) -> URL? {
        guard let path, !path.isEmpty else { return nil }
        if path.hasPrefix("http://") || path.hasPrefix("https://") { return URL(string: path) }
        // Upload replies say /api/uploads/…, artifacts /sandbox-artifacts/…; both live under /travel/api.
        if path.hasPrefix("/api/") { return URL(string: "/travel" + path, relativeTo: origin)?.absoluteURL }
        if path.hasPrefix("/sandbox-artifacts/") { return URL(string: "/travel/api" + path, relativeTo: origin)?.absoluteURL }
        if path.hasPrefix("/") { return URL(string: path, relativeTo: origin)?.absoluteURL }
        return URL(string: path, relativeTo: base.appendingPathComponent("/"))?.absoluteURL
    }

    func request(_ method: String, _ path: String, query: [String: String] = [:], items: [URLQueryItem] = [],
                 body: Any? = nil) async throws -> Data {
        var components = URLComponents(url: API.base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        let all = query.map { URLQueryItem(name: $0.key, value: $0.value) } + items
        if !all.isEmpty { components.queryItems = all }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        return try await send(request)
    }

    func upload(_ path: String, field: String, fileName: String, mime: String, data: Data) async throws -> Data {
        let boundary = "Boundary-" + UUID().uuidString
        var request = URLRequest(url: API.base.appendingPathComponent(path))
        request.httpMethod = "POST"
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(field)\"; filename=\"\(fileName)\"\r\nContent-Type: \(mime)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        return try await send(request)
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data, response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError.network("网络不可用，请检查网络后重试")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 {
            await MainActor.run { self.onUnauthorized?() }
            throw APIError.unauthorized
        }
        guard (200..<300).contains(status) else { throw APIError.server(status, Self.message(from: data, status: status)) }
        return data
    }

    /// FastAPI errors are {"detail": "…"} or {"detail": [{"msg": …}]}.
    private static func message(from data: Data, status: Int) -> String {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = object["detail"] as? String { return detail }
            if let list = object["detail"] as? [[String: Any]], let first = list.first?["msg"] as? String { return first }
        }
        switch status {
        case 404: return "内容不存在或已被删除"
        case 409: return "上一轮还在进行中，请稍等"
        case 429: return "操作太频繁，请稍后再试"
        case 500...: return "服务器开小差了（\(status)），请稍后再试"
        default: return "请求失败（\(status)）"
        }
    }

    /// External images (AMap covers) go through the site's whitelisted proxy.
    static func proxied(_ external: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        return "/travel/api/img?u=" + (external.addingPercentEncoding(withAllowedCharacters: allowed) ?? external)
    }

    static func upload(_ id: String) -> String { "/travel/api/uploads/" + id }

    func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try decoder.decode(type, from: data) } catch { throw APIError.decoding(String(describing: error)) }
    }

    func get<T: Decodable>(_ path: String, query: [String: String] = [:], as type: T.Type = T.self) async throws -> T {
        try decode(type, try await request("GET", path, query: query))
    }

    func post<T: Decodable>(_ path: String, body: Any? = [String: Any](), as type: T.Type = T.self) async throws -> T {
        try decode(type, try await request("POST", path, body: body))
    }
}

/// The login token lives in the Keychain, never in UserDefaults.
enum TokenStore {
    private static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                               kSecAttrService as String: "com.yuchengjiang.tongyou",
                                               kSecAttrAccount as String: "session-token"]
    static func read() -> String? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func save(_ token: String?) {
        SecItemDelete(query as CFDictionary)
        guard let token, !token.isEmpty else { return }
        var q = query
        q[kSecValueData as String] = Data(token.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }
}

/// Loose JSON for message `meta`, whose keys vary by message kind.
enum JSONValue: Decodable, Hashable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    subscript(key: String) -> JSONValue? { if case .object(let o) = self { return o[key] } else { return nil } }
    var string: String? {
        switch self {
        case .string(let s): return s
        case .number(let n): return n == n.rounded() ? String(Int(n)) : String(n)
        default: return nil
        }
    }
    var double: Double? { if case .number(let n) = self { return n } else if case .string(let s) = self { return Double(s) } else { return nil } }
    var int: Int? { double.map { Int($0) } }
    var bool: Bool? { if case .bool(let b) = self { return b } else { return nil } }
    var array: [JSONValue]? { if case .array(let a) = self { return a } else { return nil } }
    var object: [String: JSONValue]? { if case .object(let o) = self { return o } else { return nil } }
    var isNull: Bool { if case .null = self { return true } else { return false } }
}

/// Remote images through a shared in-memory cache. `AsyncImage` gave up for good when a load was
/// cancelled (rows re-render while a chat polls), leaving a blank placeholder; this loader retries,
/// lets a tap retry, and lets off-screen renders (shared long images) use what is already loaded.
@MainActor
final class ImageCache {
    static let shared = ImageCache()
    private let memory = NSCache<NSURL, UIImage>()
    private var inFlight: [URL: Task<UIImage?, Never>] = [:]

    func cached(_ url: URL) -> UIImage? { memory.object(forKey: url as NSURL) }

    func load(_ url: URL) async -> UIImage? {
        if let image = cached(url) { return image }
        if let task = inFlight[url] { return await task.value }
        let task = Task<UIImage?, Never> {
            for attempt in 0..<3 {
                if attempt > 0 { try? await Task.sleep(nanoseconds: UInt64(attempt) * 700_000_000) }
                guard let (data, response) = try? await URLSession.shared.data(from: url) else { continue }
                let status = (response as? HTTPURLResponse)?.statusCode ?? 200
                if status == 200, let image = UIImage(data: data) { return image }
                if (400..<500).contains(status) { return nil }   // not allowed or gone: retrying won't help
            }
            return nil
        }
        inFlight[url] = task
        let image = await task.value
        inFlight[url] = nil
        if let image { memory.setObject(image, forKey: url as NSURL) }
        return image
    }

    /// Image hosts the backend proxies (hotlink-protected CDNs); a bare link to one is routed through /api/img.
    static func url(for path: String?) -> URL? {
        guard let path, !path.isEmpty else { return nil }
        if path.hasPrefix("http"), let host = URL(string: path)?.host?.lowercased(),
           ["autonavi.com", "amap.com", "c-ctrip.com", "tripcdn.com", "xhscdn.com"].contains(where: { host == $0 || host.hasSuffix("." + $0) }) {
            return API.resolve(API.proxied(path))
        }
        return API.resolve(path)
    }
}

struct RemoteImage: View {
    let path: String?
    @State private var image: UIImage?
    @State private var failed = false
    @State private var attempt = 0

    init(path: String?) {
        self.path = path
        _image = State(initialValue: ImageCache.url(for: path).flatMap { ImageCache.shared.cached($0) })
    }

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image).resizable().scaledToFill().transition(.opacity)
            } else {
                placeholder
                if failed {
                    Image(systemName: "arrow.clockwise").foregroundStyle(.tertiary)
                }
            }
        }
        .contentShape(.rect)
        .onTapGesture { if failed { failed = false; attempt += 1 } }
        .task(id: "\(path ?? "")#\(attempt)") {
            guard image == nil, let url = ImageCache.url(for: path) else { return }
            let loaded = await ImageCache.shared.load(url)
            guard !Task.isCancelled else { return }   // a cancelled load is not a failure
            withAnimation(.easeOut(duration: 0.25)) { image = loaded }
            failed = loaded == nil
        }
    }
    private var placeholder: some View {
        Rectangle().fill(LinearGradient(colors: [Palette.sky.opacity(0.18), Palette.dusk.opacity(0.12)], startPoint: .topLeading, endPoint: .bottomTrailing))
    }
}
