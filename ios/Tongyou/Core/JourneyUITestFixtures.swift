#if DEBUG
import Foundation

/// An isolated, in-memory transport used only by the explicitly launched UI test.
/// No test request reaches the production API and no fixture token enters Keychain.
final class JourneyUITestProtocol: URLProtocol {
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains("--journey-ui-test") }
    override class func canInit(with request: URLRequest) -> Bool { enabled }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url?.path.replacingOccurrences(of: "/travel/api/", with: "") ?? ""
        let value: Any
        switch path {
        case "auth/me": value = ["username":"demo", "is_admin":false, "display_name":"小旅", "avatar_url":"", "must_change_password":false] as [String:Any]
        case "trips": value = [["id":"t1", "title":"杭州的慢周末", "destination":"杭州", "days":3, "role":"owner"] as [String:Any]]
        case "trips/t1": value = ["id":"t1", "title":"杭州的慢周末", "days":3, "members":[["username":"demo","role":"owner"]], "destination":"杭州", "stops":[
            ["id":"s1","day":1,"order_no":0,"name":"西湖","location":"120.15,30.25","note":"沿湖慢慢走","start_time":"09:00"],
            ["id":"s2","day":1,"order_no":1,"name":"午餐待定","location":""],
            ["id":"s3","day":1,"order_no":2,"name":"灵隐寺","location":"120.10,30.24"],
            ["id":"s4","day":2,"order_no":0,"name":"河坊街","location":"120.17,30.23"]
        ]] as [String:Any]
        case "onboarding": value = ["trending":["杭州","平潭岛","武汉"]]
        case "onboarding/covers": value = ["covers":[:]]
        case "chat/conversations":
            if request.httpMethod == "POST" { value = ["conversation_id":"c1"] }
            else { value = [["id":"c1", "title":"杭州两天", "updated_at":"2026-10-19T09:00:00"]] }
        case "chat/c1/messages": value = ["messages":[["id":"m1", "role":"assistant", "content":"沿湖散步，轻松安排每一天。"]], "running":false] as [String:Any]
        case "ledger": value = [["id":"b1","title":"测试旅行账本","count":1,"target_currency":"CNY","role":"owner","totals":["CNY":100],"by_category":[]] as [String:Any]]
        case "ledger/b1": value = ["id":"b1","title":"测试旅行账本","count":1,"target_currency":"CNY","role":"owner","totals":["CNY":100],"by_category":[],"entries":[]] as [String:Any]
        case "ledger/b1/conversion": value = ["target_currency":"CNY","total_minor":100,"stale":false,"fetched_at":"2026-10-20","missing":[],"items":[]] as [String:Any]
        case "trips/t1/share": value = ["short_code":"abcd1234", "token":"fixture-only-token"]
        case "trips/t1/invite":
            let payload = (try? JSONSerialization.jsonObject(with: bodyData())) as? [String: String]
            if payload?["username"] == "missing" {
                let data = Data("{\"detail\":\"用户不存在，请确认对方已注册\"}".utf8)
                let response = HTTPURLResponse(url: request.url!, statusCode: 404, httpVersion: nil, headerFields: ["Content-Type":"application/json"])!
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self); return
            }
            value = ["ok":true]
        case "trips/t1/stops/s1/details": value = ["status":"ok","description":"沿湖慢慢走","description_source":"行程说明","guide_excerpt":"西湖沿湖散步，安排休息。","photos":[],"facts":[["label":"地址","value":"浙江省杭州市","source":"高德地图"]]] as [String:Any]
        default:
            if path.contains("unread") { value = ["unread":0] }
            else if path == "notifications" { value = ["notifications":[]] }
            else { value = [] }
        }
        let data = (try? JSONSerialization.data(withJSONObject: value)) ?? Data("[]".utf8)
        if let url = request.url, let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type":"application/json"]) {
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    private func bodyData() -> Data {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open(); defer { stream.close() }
        var result = Data(), buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            result.append(contentsOf: buffer.prefix(count))
        }
        return result
    }
    override func stopLoading() {}
}
#endif
