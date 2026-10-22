import SwiftUI

/// Original, resolution independent character. With `.still` motion it is the static drawing; `PetLiveArt` feeds frames.
struct PetArt: View {
    var pose = "idle"
    var motion = PetMotion.still
    var body: some View {
        Canvas { context, size in
            context.scaleBy(x: size.width / 120, y: size.height / 146)
            let m = motion
            let fur = Color(red: 0.71, green: 0.51, blue: 0.34)
            let deep = Color(red: 0.59, green: 0.39, blue: 0.27)
            let cream = Color(red: 1, green: 0.92, blue: 0.8)
            let ink = Color(red: 0.24, green: 0.19, blue: 0.17)
            let blue = Color(red: 0.31, green: 0.47, blue: 0.91)
            func oval(_ rect: CGRect, _ color: Color, in ctx: GraphicsContext) { ctx.fill(Path(ellipseIn: rect), with: .color(color)) }
            func round(_ rect: CGRect, _ radius: CGFloat, _ color: Color, in ctx: GraphicsContext) { ctx.fill(Path(roundedRect: rect, cornerRadius: radius), with: .color(color)) }
            oval(CGRect(x: 25, y: 136, width: 72, height: 7), .black.opacity(0.09 * (1 + m.hop / 24)), in: context)
            // Breathing / stretch scale around the feet, hop lifts the whole body.
            var body = context
            body.translateBy(x: 60, y: 136 + m.hop)
            body.scaleBy(x: 1 + 0.015 * m.breath - 0.06 * m.stretch, y: 1 + 0.03 * m.breath + 0.08 * m.stretch)
            body.translateBy(x: -60, y: -136)
            var tail = body
            tail.translateBy(x: 58, y: 124); tail.rotate(by: .degrees(m.tail)); tail.translateBy(x: -58, y: -124)
            oval(CGRect(x: 54, y: 113, width: 56, height: 22), deep, in: tail)
            round(CGRect(x: 82, y: 72, width: 24, height: 48), 10, blue, in: body)
            round(CGRect(x: 28, y: 58, width: 68, height: 75), 31, fur, in: body)
            oval(CGRect(x: 40, y: 74, width: 42, height: 51), cream, in: body)
            oval(CGRect(x: 25, y: 126, width: 29, height: 13), deep, in: body)
            oval(CGRect(x: 67, y: 126, width: 29, height: 13), deep, in: body)
            var head = body
            head.translateBy(x: 60, y: 80 + m.headDrop)
            head.rotate(by: .degrees((pose == "working" ? 9 : pose == "waiting" ? -8 : 0) + m.head))
            head.translateBy(x: -60, y: -80)
            for x: CGFloat in [13, 83] {
                oval(CGRect(x: x, y: 20, width: 24, height: 25), deep, in: head)
                oval(CGRect(x: x + 6, y: 26, width: 12, height: 12), cream, in: head)
            }
            round(CGRect(x: 11, y: 24, width: 98, height: 71), 32, fur, in: head)
            round(CGRect(x: 16, y: 42, width: 88, height: 51), 26, cream, in: head)
            round(CGRect(x: 53, y: 39, width: 14, height: 15), 7, fur, in: head)
            for x: CGFloat in [37, 78] {
                if pose == "pat" || pose == "happy" {
                    var eye = Path(); eye.move(to: CGPoint(x: x, y: 65)); eye.addQuadCurve(to: CGPoint(x: x + 6, y: 65), control: CGPoint(x: x + 3, y: 60))
                    head.stroke(eye, with: .color(ink), lineWidth: 2)
                } else {
                    let h = 7 * m.blink, ex = x + m.look
                    oval(CGRect(x: ex, y: 59 + (7 - h) / 2, width: 6, height: h), ink, in: head)
                    if m.blink > 0.5 { oval(CGRect(x: ex + 1, y: 60, width: 1.7, height: 1.7), .white, in: head) }
                }
            }
            for x: CGFloat in [26, 82] { oval(CGRect(x: x, y: 70, width: 12, height: 5), .pink.opacity(0.3), in: head) }
            oval(CGRect(x: 43, y: 70, width: 35, height: 17), Color(red: 1, green: 0.97, blue: 0.9), in: head)
            oval(CGRect(x: 54, y: 68, width: 12, height: 7), ink, in: head)
            var mouth = Path(); mouth.move(to: CGPoint(x: 54, y: 79)); mouth.addQuadCurve(to: CGPoint(x: 67, y: 79), control: CGPoint(x: 60, y: 88))
            head.stroke(mouth, with: .color(ink), lineWidth: 1.5)
            var strap = Path(); strap.move(to: CGPoint(x: 42, y: 111)); strap.addLine(to: CGPoint(x: 84, y: 78))
            body.stroke(strap, with: .color(blue), lineWidth: 7)
            var map = body; map.translateBy(x: 28, y: 100 - m.lift); map.rotate(by: .degrees(-12))
            round(CGRect(x: 0, y: 0, width: 55, height: 31), 2, Color(red: 1, green: 0.97, blue: 0.9), in: map)
            map.fill(Path(CGRect(x: 18, y: 0, width: 19, height: 31)), with: .color(Color(red: 0.88, green: 0.92, blue: 0.82)))
            var route = Path(); route.move(to: CGPoint(x: 5, y: 10)); route.addLine(to: CGPoint(x: 29, y: 22)); route.addLine(to: CGPoint(x: 47, y: 9))
            map.stroke(route, with: .color(.green.opacity(0.6)), style: StrokeStyle(lineWidth: 1.5, dash: [2, 3]))
            oval(CGRect(x: 18, y: 98 - m.lift, width: 20, height: 20), fur, in: body)
            if let angle = m.wave {
                var paw = body; paw.translateBy(x: 96, y: 92); paw.rotate(by: .degrees(angle)); paw.translateBy(x: -96, y: -92)
                oval(CGRect(x: 94, y: 71, width: 20, height: 20), fur, in: paw)
            } else {
                oval(CGRect(x: pose == "wave" ? 94 : 73, y: pose == "wave" ? 71 : 99, width: 20, height: 20), fur, in: body)
            }
            if ["pat", "happy", "wave"].contains(pose) || m.heart { body.draw(Text("♥").font(.system(size: 19)).foregroundColor(.pink.opacity(0.8)), at: CGPoint(x: 102, y: 16)) }
            if let mark = m.mark {
                var label = body; label.opacity = m.markOpacity
                label.draw(Text(mark).font(.system(size: mark == "z" ? 15 : 20, weight: .bold)).foregroundColor(mark == "!" ? .red.opacity(0.8) : blue), at: CGPoint(x: 100, y: 14 - m.markRise))
            }
        }
        .aspectRatio(120.0 / 146.0, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

/// Redraws at 30fps only while motion is allowed; with quiet / reduced motion the timeline is paused
/// and the pet is the original static drawing, so no display loop runs.
struct PetLiveArt: View {
    var pose = "idle"
    var quiet = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        let live = !quiet && !reduceMotion && scenePhase == .active
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !live)) { timeline in
            PetArt(pose: pose, motion: live ? PetMotion.at(timeline.date.timeIntervalSinceReferenceDate, phase: pose) : .still)
        }
    }
}

struct PetFeedbackArt: View {
    var pose = "idle"
    var trigger = 0
    var quiet = false
    /// 完成时的庆祝：跳两下、带一点转身，比摸摸的小弹跳更明显。
    var celebrate = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var bounce = false
    @State private var hops = 0
    var body: some View {
        PetLiveArt(pose: pose, quiet: quiet).offset(y: bounce ? (celebrate ? -18 : -6) : 0).scaleEffect(bounce ? 1.04 : 1)
            .rotationEffect(.degrees(bounce && celebrate ? (hops % 2 == 0 ? -8 : 8) : 0), anchor: .bottom)
            .task(id: trigger) {
                guard trigger > 0, !quiet, !reduceMotion else { bounce = false; return }
                for hop in 0..<(celebrate ? 2 : 1) {
                    hops = hop
                    withAnimation(.easeOut(duration: 0.16)) { bounce = true }
                    do { try await Task.sleep(nanoseconds: 180_000_000) } catch { return }
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) { bounce = false }
                    do { try await Task.sleep(nanoseconds: 220_000_000) } catch { return }
                }
            }
            .onChange(of: quiet) { _, value in if value { bounce = false } }
            .onChange(of: reduceMotion) { _, value in if value { bounce = false } }
    }
}

struct PetCompanionButton: View {
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var drag: CGFloat = 0
    @State private var finished = false
    @State private var tip: PetTip?
    private var calm: Bool { router.petTask.phase == .idle || router.petTask.phase == .ready }
    private var bubble: PetBubble? {
        guard router.petPreferences.visible, !router.aiOpen else { return nil }
        return TravelPetLogic.bubble(task: router.petTask, finished: finished, tip: tip, title: router.petChat?.title)
    }
    /// chat=true 时直达游游正在跟的那个对话，不用再去历史里找。
    private func openAI(chat: Bool = false) {
        if router.petPreferences.visible && !router.petPreferences.quiet && !reduceMotion && router.petBadgeFrame != .zero { router.petFlight += 1 }
        finished = false; tip = nil
        if chat { router.openPetChat() }
        router.aiOpen = true
    }
    var body: some View {
        Button {
            openAI(chat: !calm || finished)
        } label: {
            if router.petPreferences.visible {
                VStack(spacing: -3) {
                    PetFeedbackArt(pose: router.petTask.phase.rawValue, trigger: router.petCelebration, quiet: router.petPreferences.quiet, celebrate: true)
                        .frame(width: 66, height: 80)
                        .overlay(alignment: .top) { PetEmojiBurst(trigger: router.petCelebration, quiet: router.petPreferences.quiet) }
                    Text(router.petTask.phase == .working || router.petTask.phase == .waiting ? "生成中" : "问 AI")
                        .font(.caption.weight(.medium)).padding(.horizontal, 12).padding(.vertical, 5)
                        .background(.regularMaterial, in: Capsule())
                }.frame(width: 84)
            } else {
                Label("问 AI", systemImage: "sparkles").font(.subheadline.weight(.semibold))
                    .padding(.horizontal, 15).frame(height: 56).glassEffect(.regular.tint(Palette.sky.opacity(0.8)), in: .capsule)
            }
        }
        .buttonStyle(.plain).accessibilityLabel("问 AI").accessibilityIdentifier("openAI")
        .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { router.petDockFrame = $0 }
        .accessibilityHint(router.petPreferences.visible ? "长按打开游游旅行工具，左右拖动可以换一侧" : "打开旅行助手")
        .contextMenu { Button("游游旅行工具", systemImage: "pawprint") { router.petToolsOpen = true } }
        .accessibilityAction(named: "游游旅行工具") { router.petToolsOpen = true }
        .offset(x: drag)
        .highPriorityGesture(DragGesture(minimumDistance: 12).onChanged { value in
            guard router.petPreferences.visible else { return }
            drag = max(-180, min(180, value.translation.width))
        }.onEnded { value in
            guard router.petPreferences.visible else { return }
            withAnimation(reduceMotion || router.petPreferences.quiet ? nil : .spring(response: 0.32, dampingFraction: 0.8)) {
                if value.translation.width < -30 { router.petPreferences.side = "left" }
                else if value.translation.width > 30 { router.petPreferences.side = "right" }
                drag = 0
            }
        })
        .overlay(alignment: router.petPreferences.side == "left" ? .topLeading : .topTrailing) {
            if let bubble {
                PetBubbleView(bubble: bubble, quiet: router.petPreferences.quiet, leading: router.petPreferences.side == "left", onTap: {
                    switch bubble.tip {
                    case .tools: tip = nil; router.petToolsOpen = true
                    case .drag: tip = nil
                    default: openAI(chat: true)
                    }
                }, onClose: bubble.kind == .tip || bubble.kind == .done ? { tip = nil; finished = false } : nil)
                .alignmentGuide(.top) { $0[.bottom] + 2 }
                .transition(.scale(scale: 0.6, anchor: router.petPreferences.side == "left" ? .bottomLeading : .bottomTrailing).combined(with: .opacity))
            }
        }
        .animation(reduceMotion || router.petPreferences.quiet ? nil : .spring(response: 0.35, dampingFraction: 0.7), value: bubble)
        // 完成提醒一直留着，直到点开、点✕或开始下一轮；空闲 6 秒后说一句还没说过的指引，9 秒后收起。
        .task(id: router.petCelebration) {
            guard router.petCelebration > 0 else { return }
            finished = true
        }
        .onChange(of: router.petTask.phase) { _, phase in if phase == .working || phase == .waiting { finished = false } }
        .task(id: router.petPreferences.visible && calm && !router.aiOpen && !finished && !router.petTipShown) {
            guard router.petPreferences.visible, calm, !router.aiOpen, !finished, !router.petTipShown else { return }
            do { try await Task.sleep(for: .seconds(6)) } catch { return }
            guard !router.petTipShown, let next = TravelPetLogic.nextTip(seen: router.petPreferences.tipsSeen, phase: router.petTask.phase) else { return }
            router.petTipShown = true
            router.petPreferences.tipsSeen = (router.petPreferences.tipsSeen ?? []) + [next.rawValue]
            tip = next
        }
        .task(id: tip) {
            guard tip != nil else { return }
            do { try await Task.sleep(for: .seconds(9)) } catch { return }
            tip = nil
        }
        .onChange(of: router.aiOpen) { _, open in if open { tip = nil; finished = false } }
    }
}

struct PetBubbleView: View {
    var bubble: PetBubble
    var quiet: Bool
    var leading = false
    var onTap: () -> Void
    var onClose: (() -> Void)?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var shape: PetBubbleShape { PetBubbleShape(leading: leading) }
    var body: some View {
        HStack(spacing: 0) {
            Button(action: onTap) {
                HStack(spacing: 7) {
                    if bubble.kind == .progress {
                        Circle().fill(Palette.sky).frame(width: 7, height: 7)
                            .phaseAnimator(quiet || reduceMotion ? [1.0] : [0.35, 1.0]) { dot, value in dot.opacity(value) } animation: { _ in .easeInOut(duration: 0.6) }
                    } else if bubble.kind == .done {
                        Image(systemName: "checkmark.circle.fill").font(.footnote).foregroundStyle(Palette.sky)
                    } else if bubble.kind == .error {
                        Image(systemName: "exclamationmark.circle.fill").font(.footnote).foregroundStyle(.red)
                    }
                    Text(bubble.text).font(.footnote).multilineTextAlignment(.leading).lineLimit(2)
                        .id(bubble.text).transition(.opacity)
                }
                .padding(.leading, 13).padding(.trailing, onClose == nil ? 13 : 2).padding(.vertical, 9)
                .contentShape(Rectangle())
            }.buttonStyle(.plain)
            if let onClose {
                Button(action: onClose) { Image(systemName: "xmark").font(.caption2.weight(.semibold)).foregroundStyle(.secondary).frame(width: 30, height: 34) }
                    .buttonStyle(.plain).accessibilityLabel("收起提示")
            }
        }
        .padding(.bottom, PetBubbleShape.tail)
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: 220, alignment: .leading)
        .fixedSize()
        .background {
            shape.fill(Color(.secondarySystemGroupedBackground))
            if bubble.kind == .tip || bubble.kind == .done { shape.fill(Palette.sky.opacity(0.1)) }
        }
        .overlay(shape.stroke(border, lineWidth: 1))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 5)
        .accessibilityElement(children: .contain)
    }
    private var border: Color {
        switch bubble.kind {
        case .waiting, .done: Palette.sky.opacity(0.5)
        case .error: Color.red.opacity(0.45)
        default: Color.primary.opacity(0.08)
        }
    }
}

/// 聊天气泡：圆角主体 + 底角弯向游游的尾巴（像 iMessage；游游在哪侧，尾巴就在哪侧）。
struct PetBubbleShape: Shape {
    static let tail: CGFloat = 11
    var leading = false
    func path(in rect: CGRect) -> Path {
        let body = CGRect(x: rect.minX, y: rect.minY, width: rect.width, height: rect.height - Self.tail)
        // 停靠按钮宽 84，游游头顶在离边 42 处；尾巴尖落在头顶外侧一点。
        let d: CGFloat = leading ? -1 : 1
        let root = leading ? rect.minX + 50 : rect.maxX - 50
        let tip = CGPoint(x: root + d * 20, y: rect.maxY)
        var tail = Path()
        tail.move(to: CGPoint(x: root - d * 6, y: body.maxY - 2))
        tail.addQuadCurve(to: tip, control: CGPoint(x: root + d * 4, y: body.maxY + Self.tail * 0.9))
        tail.addQuadCurve(to: CGPoint(x: root + d * 14, y: body.maxY - 2), control: CGPoint(x: root + d * 12, y: body.maxY + 4))
        tail.closeSubpath()
        return Path(roundedRect: body, cornerRadius: 18, style: .continuous).union(tail)
    }
}

/// 完成时从游游头顶冒出几个表情，飘起来淡掉；安静模式/减少动态效果时不出现。
struct PetEmojiBurst: View {
    var trigger: Int
    var quiet = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var flying = false
    @State private var shown = false
    private static let items: [(String, CGFloat, CGFloat)] = [("🎉", -34, -58), ("✨", -12, -76), ("💙", 14, -66), ("👏", 34, -50), ("🌟", 0, -96)]
    var body: some View {
        ZStack {
            if shown {
                ForEach(Array(Self.items.enumerated()), id: \.offset) { index, item in
                    Text(item.0).font(.system(size: index == 4 ? 15 : 19))
                        .offset(x: flying ? item.1 : 0, y: flying ? item.2 : 0)
                        .scaleEffect(flying ? 1 : 0.3)
                        .opacity(flying ? 0 : 1)
                        .animation(.easeOut(duration: 1.3).delay(Double(index) * 0.06), value: flying)
                }
            }
        }
        .allowsHitTesting(false).accessibilityHidden(true)
        .task(id: trigger) {
            guard trigger > 0, !quiet, !reduceMotion else { return }
            flying = false; shown = true
            do { try await Task.sleep(for: .milliseconds(30)) } catch { return }
            flying = true
            do { try await Task.sleep(for: .seconds(1.8)) } catch { return }
            shown = false; flying = false
        }
    }
}

struct PetToolsView: View {
    @Environment(AppRouter.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var pat = 0
    @State private var patActive = false
    @State private var checking = false
    @State private var trips: [TripSummary] = []
    @State private var selected = ""
    @State private var checks: [PetCheck]?
    @State private var loading = false
    @State private var error: String?
    @State private var retry = 0

    var body: some View {
        @Bindable var router = router
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 20) {
                        Button { pat += 1 } label: { PetFeedbackArt(pose: patActive ? "pat" : "idle", trigger: pat, quiet: router.petPreferences.quiet).frame(width: 78, height: 95) }
                            .buttonStyle(.plain).accessibilityLabel("摸摸游游").accessibilityIdentifier("petPat")
                        Text(pat > 0 ? "咕噜～这趟也一起走。" : "地图我带着，好心情你带着。")
                            .font(.subheadline).accessibilityIdentifier("petResponse")
                    }.padding(.vertical, 4)
                    Button("一起问 AI ↗") { dismiss(); router.aiOpen = true }
                    Button("出发检查", systemImage: "checklist") { checking.toggle() }.accessibilityIdentifier("petPreparation")
                }
                if checking {
                    Section {
                        if !trips.isEmpty {
                            Picker("待检查的行程", selection: $selected) { ForEach(trips) { Text($0.title).tag($0.id) } }
                        }
                        if loading { ProgressView("正在查看行程资料…") }
                        else if let error { Text(error).font(.subheadline); Button("重新检查") { retry += 1 } }
                        else if trips.isEmpty { Text("还没有行程，先一起想想去哪儿。").font(.subheadline) }
                        else if let checks {
                            Text(checks.isEmpty ? "行程基础信息已填好" : "有 \(checks.count) 项信息可以再确认").font(.subheadline)
                            ForEach(Array(checks.enumerated()), id: \.offset) { _, check in
                                Label(check.text, systemImage: check.level == "warn" ? "exclamationmark.circle" : "circle.dotted").font(.subheadline)
                            }
                            Button("打开这份行程 ↗") { dismiss(); router.aiOpen = false; router.tab = .home; router.openTripID = selected }
                        }
                    } header: { Text("看看哪份行程？") } footer: { Text("检查出发日期、地点和时间安排。") }
                }
                Section {
                    Toggle("在界面显示游游", isOn: $router.petPreferences.visible).accessibilityIdentifier("petVisible")
                    Toggle("减少动态效果", isOn: $router.petPreferences.quiet).accessibilityIdentifier("petQuiet")
                    Picker("停在哪一侧", selection: $router.petPreferences.side) { Text("左侧").tag("left"); Text("右侧").tag("right") }
                } header: { Text("怎么陪着你") } footer: { Text("收起游游后，问 AI 入口仍然保留。") }
            }
            .navigationTitle("游游 · 旅行搭子").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() }.accessibilityIdentifier("closePetTools") } }
            .task(id: "\(checking)-\(selected)-\(retry)") { if checking { await loadChecks() } }
            .task(id: pat) {
                guard pat > 0 else { return }
                patActive = true
                do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
                patActive = false
            }
        }
    }

    private func loadChecks() async {
        loading = true; error = nil; checks = nil
        defer { if !Task.isCancelled { loading = false } }
        do {
            if selected.isEmpty {
                let list = try await API.shared.get("trips", as: [TripSummary].self)
                guard !Task.isCancelled else { return }
                trips = list; selected = list.first?.id ?? ""
            } else {
                struct Reply: Decodable { var issues: [PetCheck] }
                async let trip = API.shared.get("trips/\(selected)", as: PetCheckTrip.self)
                async let issues = API.shared.get("trips/\(selected)/issues", as: Reply.self)
                let (detail, reply) = try await (trip, issues)
                let result = detail.preparation(issues: reply.issues)
                guard !Task.isCancelled else { return }
                checks = result
            }
        } catch { if !Task.isCancelled { self.error = "暂时没能完成检查，请重试" } }
    }
}

struct PetStatusBadge: View {
    var title = "游游 · 同游 AI"
    var task: PetTask?
    @Environment(AppRouter.self) private var router
    var body: some View {
        Button { router.petToolsOpen = true } label: {
            HStack(spacing: 5) {
                PetLiveArt(pose: (task ?? router.petTask).phase.rawValue, quiet: router.petPreferences.quiet).frame(width: 30, height: 37)
                    .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { router.petBadgeFrame = $0 }
                    .opacity(router.petFlying ? 0 : 1)
                    .keyframeAnimator(initialValue: 1.0, trigger: router.petLanded) { art, squash in
                        art.scaleEffect(x: 2 - squash, y: squash, anchor: .bottom)
                    } keyframes: { _ in
                        CubicKeyframe(0.78, duration: 0.08)
                        SpringKeyframe(1.0, duration: 0.42, spring: .bouncy)
                    }
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.caption.weight(.semibold)).lineLimit(1)
                    Text((task ?? router.petTask).detail ?? (task ?? router.petTask).label).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
                }
            }.frame(minHeight: 44)
        }.buttonStyle(.plain).accessibilityLabel("游游，\((task ?? router.petTask).label)，打开旅行工具")
    }
}

/// 问 AI 的衔接：一只游游从停靠处起跳、划一道弧落进 AI 标题栏，落地后标题栏的小游游回弹。
struct PetFlightOverlay: View {
    @Environment(AppRouter.self) private var router
    @State private var progress = 0.0
    @State private var from = CGRect.zero
    @State private var to = CGRect.zero
    var body: some View {
        GeometryReader { geo in
            if router.petFlying {
                let origin = geo.frame(in: .global).origin
                PetArt(pose: "happy")
                    .modifier(PetFlight(progress: progress, from: from.offsetBy(dx: -origin.x, dy: -origin.y), to: to.offsetBy(dx: -origin.x, dy: -origin.y)))
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .onChange(of: router.petFlight) {
            // Dock frame includes the caption; the art is the top 80pt of the 84pt-wide column.
            let dock = router.petDockFrame
            from = CGRect(x: dock.midX - 33, y: dock.minY, width: 66, height: 80)
            to = router.petBadgeFrame
            guard dock != .zero, to != .zero else { return }
            progress = 0
            router.petFlying = true
            withAnimation(.timingCurve(0.45, 0, 0.25, 1, duration: 0.56)) { progress = 1 } completion: {
                router.petFlying = false
                router.petLanded += 1
            }
        }
    }
}

/// Animatable so the pet follows an arc instead of SwiftUI's straight-line interpolation.
struct PetFlight: ViewModifier, Animatable {
    var progress: Double
    var from: CGRect
    var to: CGRect
    var animatableData: Double { get { progress } set { progress = newValue } }
    func body(content: Content) -> some View {
        let p = min(max(progress, 0), 1)
        let lift = min(120, max(48, abs(to.midY - from.midY) * 0.25))
        let width = from.width + (to.width - from.width) * p
        let squash = p < 0.16 ? 1 - 0.1 * sin(.pi * p / 0.16) : 1
        content
            .frame(width: width, height: width * 146 / 120)
            .scaleEffect(x: 2 - squash, y: squash, anchor: .bottom)
            .rotationEffect(.degrees(-10 * sin(.pi * p)))
            .position(x: from.midX + (to.midX - from.midX) * p, y: from.midY + (to.midY - from.midY) * p - lift * sin(.pi * p))
    }
}

/// AI 面板从游游的位置圆形展开。
struct PetRevealShape: Shape {
    var progress: Double
    var origin: CGPoint
    var animatableData: Double { get { progress } set { progress = newValue } }
    func path(in rect: CGRect) -> Path {
        if progress >= 1 { return Path(rect.insetBy(dx: -40, dy: -40)) }
        let corners = [CGPoint(x: rect.minX, y: rect.minY), CGPoint(x: rect.maxX, y: rect.minY), CGPoint(x: rect.minX, y: rect.maxY), CGPoint(x: rect.maxX, y: rect.maxY)]
        let far = corners.map { hypot($0.x - origin.x, $0.y - origin.y) }.max() ?? 0
        let radius = 28 + (far - 28) * max(0, progress)
        return Path(ellipseIn: CGRect(x: origin.x - radius, y: origin.y - radius, width: radius * 2, height: radius * 2))
    }
}

struct PetMemberWelcome: View {
    var text: String
    var quiet: Bool
    var onClose: () -> Void
    var body: some View {
        HStack(spacing: 10) {
            PetFeedbackArt(pose: "wave", trigger: 1, quiet: quiet).frame(width: 40, height: 49)
            Text(text).font(.subheadline)
            Spacer(minLength: 0)
            Button(action: onClose) { Image(systemName: "xmark").frame(width: 44, height: 44) }.buttonStyle(.plain).accessibilityLabel("收起同行欢迎")
        }.padding(.horizontal, 10).glassCard(cornerRadius: 18)
        .accessibilityElement(children: .contain)
    }
}
