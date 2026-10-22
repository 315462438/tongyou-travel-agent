import Foundation

@main struct TravelPetTests {
    static func main() throws {
        var count = 0
        func check(_ condition: Bool) { precondition(condition); count += 1 }
        let user = PetMessage(id: "u1", role: "user", content: "杭州两天")
        let answer = PetMessage(id: "a1", role: "assistant", content: "沿湖散步")
        check(TravelPetLogic.task([], running: false).phase == .idle)
        check(TravelPetLogic.task([user, answer], running: false).phase == .ready)
        check(TravelPetLogic.task([answer, user], running: true).phase == .working)
        check(TravelPetLogic.task([user, answer], running: false, stopped: true).phase == .stopped)
        check(TravelPetLogic.task([user, answer], running: false, failed: true).phase == .error)
        check(TravelPetLogic.task([user, PetMessage(id: "a", role: "assistant", content: "部分结果", cancelled: true)], running: false).phase == .stopped)
        check(TravelPetLogic.task([user, PetMessage(id: "a", role: "assistant", content: "部分结果", failed: true)], running: false).phase == .error)
        let confirm = PetMessage(id: "p", role: "progress", content: "请确认", confirmID: "ask")
        check(TravelPetLogic.task([user, confirm], running: true).phase == .waiting)
        check(TravelPetLogic.task([user, confirm, PetMessage(id: "r", role: "action", content: "", replyID: "ask")], running: true).phase == .working)
        check(TravelPetLogic.task([user, PetMessage(id: "a", role: "assistant", content: "初步回答", preliminary: true)], running: false).phase == .idle)
        check(TravelPetLogic.task([user, PetMessage(id: "a", role: "assistant", content: "已停止本轮。")], running: false).phase == .stopped)
        check(TravelPetLogic.task([user, PetMessage(id: "a", role: "assistant", content: "抱歉，处理过程中出错了，请重试。")], running: false).phase == .error)
        check(TravelPetLogic.addedMembers(previous: nil, current: ["me", "old"], username: "me").isEmpty)
        check(TravelPetLogic.addedMembers(previous: ["me", "old"], current: ["me"], username: "me").isEmpty)
        check(TravelPetLogic.addedMembers(previous: ["me"], current: ["me", "new", "new"], username: "me") == ["new"])
        check(PetPreferences.read(Data("broken".utf8)) == PetPreferences())
        check(PetPreferences.read(Data("{\"visible\":false,\"quiet\":true,\"side\":\"left\"}".utf8)).side == "left")
        let trip = PetCheckTrip(id: "t", title: "旅行", destination: nil, startDate: nil, stops: [])
        check(trip.preparation(issues: []).count == 3)
        let complete = PetCheckTrip(id: "t", title: "旅行", destination: "杭州", startDate: "2026-10-24", stops: [.init(name: "西湖", location: "120.15,30.25", startTime: "09:00"), .init(name: "休息", startTime: "12:00", tags: ["no_location"])])
        check(complete.preparation(issues: []).isEmpty)
        check(complete.preparation(issues: [.init(text: "时间冲突", level: "warn"), .init(text: "时间冲突", level: "warn")]).count == 1)
        let invalid = PetCheckTrip(id: "t", title: "旅行", destination: "杭州", startDate: "2026-10-24", stops: [.init(name: "西湖", location: ",30")])
        check(invalid.preparation(issues: []).count == 2)
        // Motion: deterministic, never repeats an act back to back, calm phases only.
        check(PetMotion.act(at: 3) == nil)
        for window in 1...40 {
            let t = Double(window) * PetMotion.actWindow + 0.5
            if let (a, _) = PetMotion.act(at: t), let (b, _) = PetMotion.act(at: t + PetMotion.actWindow) { check(a != b) }
            check(PetMotion.act(at: t + 2) == nil)
        }
        let actTime = 9.0 * 3 + 0.9
        check(PetMotion.at(actTime, phase: "idle") != PetMotion.at(actTime, phase: "working"))
        check(PetMotion.at(actTime, phase: "working").wave == nil && PetMotion.at(actTime, phase: "waiting").mark == "?")
        check(PetMotion.at(10, phase: "stopped").blink == 0.3 && PetMotion.at(10, phase: "error").mark == "!")
        check((0..<200).allSatisfy { i in let m = PetMotion.at(Double(i) * 0.37, phase: "idle"); return m.breath >= 0 && m.breath <= 1 && m.blink > 0 && m.hop <= 0 })
        // Bubbles: progress text, priority, one-time tips.
        check(TravelPetLogic.progressText("🔎 搜索：杭州 美食") == "搜索：杭州 美食")
        check(TravelPetLogic.progressText("🌐 浏览器读取：https://www.xiaohongshu.com/explore/abc?x=1") == "浏览器读取：xiaohongshu.com")
        check(TravelPetLogic.progressText("\n**正在理解你的旅行需求…**\n第二行") == "正在理解你的旅行需求…")
        check(TravelPetLogic.progressText("  ") == nil)
        let long = TravelPetLogic.progressText("正在补充资料：" + String(repeating: "西湖、灵隐寺、", count: 10))!
        check(long.count == TravelPetLogic.bubbleMax && long.hasSuffix("…"))
        check(TravelPetLogic.task([user, PetMessage(id: "p", role: "progress", content: "📕 小红书搜索：杭州")], running: true).detail == "小红书搜索：杭州")
        check(TravelPetLogic.task([user, PetMessage(id: "a", role: "assistant", content: "第一天", streaming: true)], running: true).detail == "正在写回复…")
        check(TravelPetLogic.task([PetMessage(id: "p0", role: "progress", content: "旧进度"), user], running: true).detail == nil)
        check(TravelPetLogic.task([user, PetMessage(id: "p", role: "progress", content: "搜索")], running: true, stopped: true).detail == nil)
        check(TravelPetLogic.nextTip(seen: nil, phase: .idle) == .ask && TravelPetLogic.nextTip(seen: ["ask"], phase: .ready) == .tools)
        check(TravelPetLogic.nextTip(seen: PetTip.allCases.map(\.rawValue), phase: .idle) == nil && TravelPetLogic.nextTip(seen: [], phase: .working) == nil)
        check(TravelPetLogic.bubble(task: PetTask(phase: .working, label: "整理中", detail: "搜索：杭州"), finished: false, tip: .ask)?.text == "搜索：杭州")
        check(TravelPetLogic.bubble(task: PetTask(phase: .waiting), finished: false, tip: .ask)?.kind == .waiting)
        check(TravelPetLogic.bubble(task: PetTask(phase: .ready), finished: true, tip: .ask)?.kind == .done)
        check(TravelPetLogic.bubble(task: PetTask(), finished: false, tip: .ask)?.kind == .tip && TravelPetLogic.bubble(task: PetTask(), finished: false, tip: nil) == nil)
        check(PetPreferences.read(Data("{\"tipsSeen\":[\"ask\"]}".utf8)).tipsSeen == ["ask"])
        // Done bubble names the conversation it opens; old finished chats can't overwrite a live turn elsewhere.
        check(TravelPetLogic.bubble(task: PetTask(phase: .ready), finished: true, tip: nil, title: "延吉烤海鲜")?.text == "「延吉烤海鲜」写好啦，点我看看")
        check(TravelPetLogic.bubble(task: PetTask(phase: .ready), finished: true, tip: nil, title: "新对话")?.text == "回复准备好啦，点我看看")
        check(TravelPetLogic.bubble(task: PetTask(phase: .ready), finished: true, tip: nil, title: "哈尔滨延吉五日冰雪美食路线")!.text.contains("…」"))
        let liveA: (conversation: String?, turn: String)? = ("A", "u1")
        check(!TravelPetLogic.accepts(PetTask(phase: .ready), from: "B", live: liveA))
        check(TravelPetLogic.accepts(PetTask(phase: .ready), from: "A", live: liveA))
        check(TravelPetLogic.accepts(PetTask(phase: .working), from: "B", live: liveA))
        check(TravelPetLogic.accepts(PetTask(), from: "B", live: nil))
        print("\(count) TravelPet checks passed")
    }
}
