import Foundation

struct PetTask: Equatable {
    enum Phase: String { case idle, working, waiting, ready, stopped, error }
    var phase: Phase = .idle
    var label = "想去哪儿，我陪你想想"
    var turn = ""
    /// 生成中时最新一步在做什么（来自进度消息），给气泡和标题栏用。
    var detail: String? = nil
}

struct PetMessage {
    var id: String
    var role: String
    var content: String
    var streaming = false
    var preliminary = false
    var confirmID: String?
    var handoff = false
    var replyID: String?
    var cancelled = false
    var failed = false
}

enum TravelPetLogic {
    static func task(_ messages: [PetMessage], running: Bool, stopped: Bool = false, failed: Bool = false) -> PetTask {
        let index = messages.lastIndex { $0.role == "user" }
        let turn = index.map { messages[$0].id } ?? ""
        let current = Array(messages.dropFirst(index.map { $0 + 1 } ?? 0))
        let final = current.last { $0.role == "assistant" && !$0.streaming && !$0.preliminary && !$0.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        if failed { return PetTask(phase: .error, label: "这次没能完成，点开看看", turn: turn) }
        if running {
            let last = current.last(where: { $0.role != "action" })
            if let last, last.role == "progress" {
                let answered = last.confirmID.map { id in current.contains { $0.replyID == id } } ?? false
                if (last.confirmID != nil && !answered) || last.handoff { return PetTask(phase: .waiting, label: "有件事需要你确认", turn: turn) }
            }
            var detail: String?
            if !stopped, let last {
                if last.role == "assistant", last.streaming, !last.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { detail = "正在写回复…" }
                else if last.role == "progress" { detail = progressText(last.content) }
            }
            return PetTask(phase: .working, label: stopped ? "正在保存，稍等一下" : "正在整理你的旅行想法", turn: turn, detail: detail)
        }
        if stopped || final?.cancelled == true || final?.content.trimmingCharacters(in: .whitespacesAndNewlines) == "已停止本轮。" {
            return PetTask(phase: .stopped, label: "已停下，随时可以继续", turn: turn)
        }
        if let final, final.failed || final.content.hasPrefix("模型服务（DeepSeek）暂时不可用") || final.content.hasPrefix("抱歉，处理过程中出错了") {
            return PetTask(phase: .error, label: "这次没能完成，点开看看", turn: turn)
        }
        if final != nil { return PetTask(phase: .ready, label: "回复准备好啦", turn: turn) }
        return PetTask(turn: turn)
    }

    static let bubbleMax = 22
    /// 进度消息变成气泡里的一句话：取首行、去掉开头表情/符号、网址只留域名、过长截断（与网页 petProgressText 一致）。
    static func progressText(_ content: String) -> String? {
        guard var text = content.split(separator: "\n").map({ $0.trimmingCharacters(in: .whitespaces) }).first(where: { !$0.isEmpty }) else { return nil }
        text = text.replacingOccurrences(of: #"https?://(?:www\.)?([^/\s]+)\S*"#, with: "$1", options: .regularExpression)
        text = text.replacingOccurrences(of: #"[*`#>_]+"#, with: "", options: .regularExpression)
        text = String(text.drop { !($0.isLetter || $0.isNumber) })
        text = text.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return nil }
        return text.count > bubbleMax ? String(text.prefix(bubbleMax - 1)) + "…" : text
    }

    /// 新手指引：每条只说一次，按顺序。
    static func nextTip(seen: [String]?, phase: PetTask.Phase) -> PetTip? {
        guard phase == .idle || phase == .ready else { return nil }
        return PetTip.allCases.first { !(seen ?? []).contains($0.rawValue) }
    }

    /// 对话页之外的更新能不能改游游：另一个对话还在跑时，打开一条已结束的旧对话不能把它的进度盖掉。
    static func accepts(_ task: PetTask, from conversation: String?, live: (conversation: String?, turn: String)?) -> Bool {
        if task.phase == .working || task.phase == .waiting { return true }
        guard let live else { return true }
        return live.conversation == conversation
    }

    /// 停靠处气泡选哪条：任务状态优先于指引。完成提醒带上对话名，点进去去的就是它。
    static func bubble(task: PetTask, finished: Bool, tip: PetTip?, title: String? = nil) -> PetBubble? {
        switch task.phase {
        case .waiting: return PetBubble(kind: .waiting, text: "有件事需要你确认，点我去看看")
        case .error: return PetBubble(kind: .error, text: "这次没能完成，点我看看")
        case .working: return PetBubble(kind: .progress, text: task.detail ?? task.label)
        default:
            if finished {
                let name = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                if name.isEmpty || name == "新对话" { return PetBubble(kind: .done, text: "回复准备好啦，点我看看") }
                return PetBubble(kind: .done, text: "「\(name.count > 10 ? String(name.prefix(9)) + "…" : name)」写好啦，点我看看")
            }
            if let tip { return PetBubble(kind: .tip, text: tip.text, tip: tip) }
            return nil
        }
    }

    static func addedMembers(previous: [String]?, current: [String], username: String) -> [String] {
        guard let previous else { return [] }
        let known = Set(previous)
        return Set(current).filter { !$0.isEmpty && $0 != username && !known.contains($0) }.sorted()
    }
}

struct PetPreferences: Codable, Equatable {
    var visible = true
    var quiet = false
    var side = "right"
    var tipsSeen: [String]? = nil

    init() {}
    /// Missing keys keep their defaults, so adding a field never resets someone's saved choices.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        visible = try c.decodeIfPresent(Bool.self, forKey: .visible) ?? true
        quiet = try c.decodeIfPresent(Bool.self, forKey: .quiet) ?? false
        side = try c.decodeIfPresent(String.self, forKey: .side) ?? "right"
        tipsSeen = try? c.decodeIfPresent([String].self, forKey: .tipsSeen)
    }

    static func read(_ data: Data?) -> PetPreferences {
        guard let data, var value = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        if value.side != "left" { value.side = "right" }
        return value
    }
}

struct PetCheck: Decodable, Equatable {
    var text: String
    var level: String?
}

struct PetCheckTrip: Decodable {
    var id: String
    var title: String
    var destination: String?
    var startDate: String?
    var stops: [Stop]

    struct Stop: Decodable {
        var name: String
        var location: String?
        var startTime: String?
        var tags: [String]?
    }

    func preparation(issues: [PetCheck]) -> [PetCheck] {
        var result: [PetCheck] = []
        func add(_ text: String, level: String = "info") {
            if !result.contains(where: { $0.text == text }) { result.append(PetCheck(text: text, level: level)) }
        }
        func empty(_ value: String?) -> Bool { value?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false }
        if empty(destination) { add("补充这次旅行的目的地") }
        if empty(startDate) { add("确认并填写出发日期") }
        if stops.isEmpty { add("把想去的地方加入每日路线") }
        let unlocated = stops.filter { stop in
            if stop.tags?.contains("no_location") == true { return false }
            let parts = stop.location?.split(separator: ",", omittingEmptySubsequences: false).map { $0.trimmingCharacters(in: .whitespaces) }
            guard let parts, parts.count == 2, let lng = Double(parts[0]), let lat = Double(parts[1]), lng.isFinite, lat.isFinite else { return true }
            return abs(lng) > 180 || abs(lat) > 90
        }.count
        if unlocated > 0 { add("\(unlocated) 个地点还需要补充地图位置") }
        let untimed = stops.filter { empty($0.startTime) }.count
        if untimed > 0 { add("\(untimed) 个地点的游览时间还可补充") }
        for issue in issues {
            let text = issue.text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty { add(text, level: issue.level == "warn" ? "warn" : "info") }
        }
        return result
    }
}

/// One frame of 游游's body language, derived only from time and phase so the view can be a cheap
/// TimelineView redraw. `.still` is the original static drawing (quiet / reduced motion).
struct PetMotion: Equatable {
    enum Act: Int, CaseIterable { case look, wave, map, stretch, hop }
    var breath: Double = 0      // 0…1, vertical breathing
    var blink: Double = 1       // eye height factor
    var tail: Double = 0        // extra degrees
    var head: Double = 0        // extra degrees
    var headDrop: Double = 0
    var look: Double = 0        // eye x offset in art units
    var lift: Double = 0        // map raise in art units
    var hop: Double = 0         // body y offset (negative = up)
    var stretch: Double = 0     // 0…1
    var wave: Double? = nil     // right paw raised, angle in degrees
    var heart = false
    var mark: String? = nil
    var markRise: Double = 0
    var markOpacity: Double = 0.9

    static let still = PetMotion()
    static let actWindow = 9.0, actLength = 1.8

    /// Deterministic act schedule: each 9s window plays one act for 1.8s; neighbours never repeat.
    static func act(at time: Double) -> (Act, Double)? {
        let window = Int(floor(time / actWindow))
        let offset = time - Double(window) * actWindow
        guard window > 0, offset < actLength else { return nil }
        func pick(_ w: Int) -> Int { Int((UInt64(truncatingIfNeeded: w &* 2654435761) >> 7) % UInt64(Act.allCases.count)) }
        var index = pick(window)
        if index == pick(window - 1) { index = (index + 1) % Act.allCases.count }
        return (Act(rawValue: index)!, offset / actLength)
    }

    static func at(_ time: Double, phase: String) -> PetMotion {
        func wave(_ period: Double) -> Double { sin(2.0 * Double.pi * time / period) }
        var m = PetMotion()
        m.breath = (wave(3.4) + 1.0) / 2.0
        let blinkPhase = time.truncatingRemainder(dividingBy: 5.2) / 5.2
        m.blink = blinkPhase > 0.93 && blinkPhase < 0.97 ? 0.12 : 1
        m.tail = 6 + 6 * wave(2.8)
        switch phase {
        case "working":
            m.head = -2.0 + 2.0 * wave(1.6); m.look = 3.0 * wave(2.2)
            let flip: Double = sin(Double.pi * time / 0.8); m.lift = 2.0 * abs(flip)
        case "waiting":
            let tilt: Double = wave(1.8)
            m.head = -3.5 + 3.5 * tilt; m.mark = "?"; m.markRise = 1.5 * (tilt + 1.0)
        case "stopped":
            m.blink = 0.3; m.breath *= 0.6; m.mark = "z"
            let cycle = time.truncatingRemainder(dividingBy: 2.6) / 2.6
            m.markRise = 10.0 * cycle; m.markOpacity = 0.85 * sin(Double.pi * cycle)
        case "error":
            m.head = -6; m.headDrop = 4; m.mark = "!"
        case "idle", "ready":
            guard let (act, q) = act(at: time) else { break }
            let bell: Double = sin(Double.pi * q)
            let swing: Double = sin(2.0 * Double.pi * q)
            switch act {
            case .look: m.head = 11.0 * swing; m.look = 4.0 * swing
            case .wave: let flap: Double = sin(4.0 * Double.pi * q); m.wave = 25.0 * flap; m.heart = true
            case .map: m.lift = 7.0 * bell; m.head = 8.0 * bell
            case .stretch: m.stretch = bell; m.blink = 0.25
            case .hop: let height: Double = abs(swing) * (1.0 - q); m.hop = -12.0 * height
            }
        default: break
        }
        return m
    }
}


enum PetTip: String, CaseIterable {
    case ask, tools, drag
    var text: String {
        switch self {
        case .ask: "想去哪儿？点我直接问 AI"
        case .tools: "长按我，能检查行程还缺什么"
        case .drag: "挡住内容了？把我拖到另一边"
        }
    }
}

struct PetBubble: Equatable {
    enum Kind { case progress, waiting, error, done, tip }
    var kind: Kind
    var text: String
    var tip: PetTip? = nil
}
