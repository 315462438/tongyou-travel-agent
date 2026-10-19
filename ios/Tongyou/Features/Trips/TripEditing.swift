import SwiftUI

/// Add or edit one stop. Locations are geocoded by the server from the name when left empty.
struct StopEditor: View {
    let tripID: String
    let dayCount: Int
    var stop: TripDetail.Stop?
    var defaultDay = 1
    let onDone: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var day = 1
    @State private var hasTime = false
    @State private var time = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: .now)!
    @State private var stay = 60
    @State private var transport = ""
    @State private var price = ""
    @State private var note = ""
    @State private var busy = false
    @State private var error: String?
    @State private var confirmDelete = false

    private let transports = ["", "步行", "公交", "打车", "驾车", "骑行"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("地点名称，如：西湖断桥", text: $name)
                    Picker("第几天", selection: $day) { ForEach(1...max(dayCount, 1), id: \.self) { Text("Day \($0)").tag($0) } }
                }
                Section("时间") {
                    Toggle("指定到达时间", isOn: $hasTime.animation())
                    if hasTime { DatePicker("到达", selection: $time, displayedComponents: .hourAndMinute) }
                    Stepper("停留 \(stay >= 60 ? "\(stay / 60) 小时\(stay % 60 > 0 ? " \(stay % 60) 分" : "")" : "\(stay) 分钟")", value: $stay, in: 0...720, step: 15)
                }
                Section("交通与费用") {
                    Picker("从上一站过来", selection: $transport) { ForEach(transports, id: \.self) { Text($0.isEmpty ? "不填" : $0).tag($0) } }
                    TextField("门票（元）", text: $price).keyboardType(.decimalPad)
                }
                Section("备注") {
                    TextField("开放时间、预约方式、注意事项…", text: $note, axis: .vertical).lineLimit(3...8)
                }
                if let error { Text(error).foregroundStyle(.red).font(.footnote) }
                if stop != nil {
                    Section { Button("删除这个地点", role: .destructive) { confirmDelete = true } }
                }
            }
            .scrollContentBackground(.hidden)
            .screenBackground()
            .navigationTitle(stop == nil ? "添加地点" : "编辑地点")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { save() }.disabled(busy || name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .confirmationDialog("删除“\(name)”？", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("删除", role: .destructive) { delete() }
            }
            .onAppear(perform: fill)
        }
    }

    private func fill() {
        guard let stop else { day = min(max(defaultDay, 1), max(dayCount, 1)); return }
        name = stop.name
        day = stop.day
        note = stop.note ?? ""
        transport = transports.contains(stop.transport ?? "") ? (stop.transport ?? "") : ""
        stay = stop.stayMin ?? 60
        price = stop.ticketPrice.map { $0 == $0.rounded() ? String(Int($0)) : String($0) } ?? ""
        if let text = stop.startTime, text.count == 5, let hour = Int(text.prefix(2)), let minute = Int(text.suffix(2)) {
            hasTime = true
            time = Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: .now) ?? time
        }
    }

    private var body_: [String: Any] {
        let parts = Calendar.current.dateComponents([.hour, .minute], from: time)
        var body: [String: Any] = [
            "name": name.trimmingCharacters(in: .whitespaces), "day": day, "note": note, "transport": transport,
            "start_time": hasTime ? String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0) : "",
            "stay_min": stay,
        ]
        if let value = Double(price) { body["ticket_price"] = value }
        return body
    }

    private func save() {
        busy = true
        Task {
            do {
                if let stop {
                    var body = body_
                    // Renaming invalidates the old coordinate; let the server geocode the new name.
                    if stop.name != name.trimmingCharacters(in: .whitespaces) { body["location"] = "" }
                    _ = try await API.shared.request("PATCH", "trips/\(tripID)/stops/\(stop.id)", body: body)
                } else {
                    _ = try await API.shared.request("POST", "trips/\(tripID)/stops", body: body_)
                }
                onDone()
                dismiss()
            } catch { self.error = error.localizedDescription }
            busy = false
        }
    }

    private func delete() {
        guard let stop else { return }
        Task {
            do {
                _ = try await API.shared.request("DELETE", "trips/\(tripID)/stops/\(stop.id)")
                onDone()
                dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}

struct TripSettingsSheet: View {
    let trip: TripDetail
    let onDone: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var destination = ""
    @State private var days = 2
    @State private var hasDate = false
    @State private var start = Date.now
    @State private var budget = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("行程名称", text: $title)
                    TextField("目的地", text: $destination)
                    Stepper("共 \(days) 天", value: $days, in: 1...30)
                }
                Section {
                    Toggle("已确定出发日期", isOn: $hasDate.animation())
                    if hasDate { DatePicker("出发", selection: $start, displayedComponents: .date) }
                    TextField("总预算（元）", text: $budget).keyboardType(.numberPad)
                }
                if let error { Text(error).foregroundStyle(.red).font(.footnote) }
            }
            .scrollContentBackground(.hidden)
            .screenBackground()
            .navigationTitle("行程设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("保存", action: save) }
            }
            .onAppear {
                title = trip.title
                destination = trip.destination ?? ""
                days = trip.days ?? trip.dayCount
                budget = trip.budget.map { String(Int($0)) } ?? ""
                if let text = trip.startDate, let date = Self.dayFormatter.date(from: text) { hasDate = true; start = date }
            }
        }
    }

    static let dayFormatter: DateFormatter = {
        let f = DateFormatter(); f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f
    }()

    private func save() {
        var body: [String: Any] = ["title": title, "destination": destination, "days": days,
                                   "start_date": hasDate ? Self.dayFormatter.string(from: start) : ""]
        if let value = Double(budget) { body["budget"] = value }
        Task {
            do {
                _ = try await API.shared.request("PATCH", "trips/\(trip.id)", body: body)
                onDone()
                dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}

struct ReorderSheet: View {
    let tripID: String
    let day: Int
    @State var stops: [TripDetail.Stop]
    let onDone: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                ForEach(stops) { stop in
                    Label(stop.name, systemImage: "line.3.horizontal")
                }
                .onMove { stops.move(fromOffsets: $0, toOffset: $1) }
                if let error { Text(error).foregroundStyle(.red).font(.footnote) }
            }
            .environment(\.editMode, .constant(.active))
            .scrollContentBackground(.hidden)
            .screenBackground()
            .navigationTitle("调整 Day \(day) 顺序")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") {
                        Task {
                            do {
                                _ = try await API.shared.request("POST", "trips/\(tripID)/stops/reorder", body: ["day": day, "ordered_ids": stops.map(\.id)])
                                onDone()
                                dismiss()
                            } catch { self.error = error.localizedDescription }
                        }
                    }
                }
            }
        }
    }
}

struct MembersSheet: View {
    let trip: TripDetail
    let isOwner: Bool
    let onDone: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var username = ""
    @State private var message: String?

    var body: some View {
        NavigationStack {
            List {
                Section("同行的人") {
                    ForEach(trip.members ?? [], id: \.self) { member in
                        HStack {
                            Avatar(user: UserCard(username: member.username), size: 32)
                            Text(member.username)
                            Spacer()
                            Text(member.role == "owner" ? "创建者" : member.role == "pending" ? "待接受" : "可编辑").font(.caption).foregroundStyle(.secondary)
                            if member.online == true { Circle().fill(.green).frame(width: 8, height: 8) }
                        }
                    }
                }
                if isOwner {
                    Section {
                        TextField("对方的用户名", text: $username).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button("发送邀请") { invite() }.disabled(username.trimmingCharacters(in: .whitespaces).isEmpty)
                    } header: { Text("邀请同行") } footer: { Text("对方接受后就能一起编辑这个行程。") }
                }
                if let message { Text(message).font(.footnote).foregroundStyle(.secondary) }
            }
            .scrollContentBackground(.hidden)
            .screenBackground()
            .navigationTitle("成员")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }

    private func invite() {
        Task {
            do {
                _ = try await API.shared.request("POST", "trips/\(trip.id)/invite", body: ["username": username.trimmingCharacters(in: .whitespaces)])
                message = "已邀请 \(username)"
                username = ""
                onDone()
            } catch { message = error.localizedDescription }
        }
    }
}

/// "让 AI 改行程": the copilot answers with a reply and optional structured changes to apply or reject.
struct CopilotSheet: View {
    let tripID: String
    let onChanged: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var prompt = ""
    @State private var suggestions: [Suggestion] = []
    @State private var working = false
    @State private var error: String?

    struct Suggestion: Decodable, Identifiable {
        var id: String; var prompt: String; var reply: String?; var status: String; var changes: [Change]; var createdAt: String?
        struct Change: Decodable, Hashable { var op: String; var stopId: String?; var day: Int?; var name: String?; var note: String?; var startTime: String?; var reason: String? }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if working {
                        Label("AI 正在修改行程…", systemImage: "sparkles").symbolEffect(.pulse)
                            .padding(14).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 18)
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                    ForEach(suggestions) { suggestion in card(suggestion) }
                    if suggestions.isEmpty && !working {
                        EmptyState(symbol: "wand.and.stars", title: "告诉 AI 怎么改", message: "例如“Day2 少走路”“预算降到 3000”“加一个亲子景点”。改动会先给你确认。")
                    }
                }
                .padding(16)
            }
            .safeAreaInset(edge: .bottom) {
                GlassEffectContainer(spacing: 10) {
                    HStack(alignment: .bottom, spacing: 10) {
                        TextField("想怎么改？", text: $prompt, axis: .vertical).lineLimit(1...4)
                            .padding(.horizontal, 16).padding(.vertical, 12)
                            .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22))
                        Button(action: send) {
                            Image(systemName: "arrow.up").font(.body.weight(.bold)).foregroundStyle(.white).frame(width: 44, height: 44)
                        }
                        .glassEffect(.regular.tint(Palette.sky).interactive(), in: .circle)
                        .disabled(working || prompt.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                .padding(.horizontal, 12).padding(.bottom, 6)
            }
            .screenBackground()
            .navigationTitle("让 AI 改行程")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .task { await load() }
        }
    }

    private func card(_ s: Suggestion) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(s.prompt).font(.subheadline.weight(.semibold))
            if let reply = s.reply, !reply.isEmpty { MarkdownView(reply) }
            ForEach(s.changes, id: \.self) { change in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: change.op == "add" ? "plus.circle.fill" : change.op == "delete" ? "minus.circle.fill" : "pencil.circle.fill")
                        .foregroundStyle(change.op == "add" ? .green : change.op == "delete" ? .red : Palette.sky)
                    VStack(alignment: .leading, spacing: 2) {
                        Text([change.day.map { "Day \($0)" }, change.startTime, change.name].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · "))
                            .font(.subheadline)
                        if let reason = change.reason, !reason.isEmpty { Text(reason).font(.caption).foregroundStyle(.secondary) }
                    }
                }
            }
            switch s.status {
            case "pending":
                GlassEffectContainer {
                    HStack {
                        Button("采纳改动") { act(s, "apply") }.buttonStyle(.glassProminent).tint(Palette.sky)
                        Button("不要") { act(s, "reject") }.buttonStyle(.glass)
                    }
                }
            case "applied":
                HStack {
                    Label("已采纳", systemImage: "checkmark.circle").font(.footnote).foregroundStyle(.green)
                    Spacer()
                    Button("撤销") { act(s, "revert") }.font(.footnote).buttonStyle(.glass)
                }
            case "rejected": Text("已忽略").font(.footnote).foregroundStyle(.secondary)
            case "reverted": Text("已撤销").font(.footnote).foregroundStyle(.secondary)
            default: EmptyView()
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 22)
    }

    private func load() async {
        suggestions = (try? await API.shared.get("trips/\(tripID)/suggestions", as: [Suggestion].self)) ?? suggestions
    }

    private func send() {
        let text = prompt.trimmingCharacters(in: .whitespaces)
        prompt = ""
        working = true
        error = nil
        Task {
            do {
                _ = try await API.shared.request("POST", "trips/\(tripID)/ai/copilot", body: ["prompt": text])
                struct Status: Decodable { var aiStatus: String? }
                for _ in 0..<90 {
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    let status = try await API.shared.get("trips/\(tripID)", as: Status.self)
                    if status.aiStatus != "copilot" { break }
                }
                await load()
            } catch { self.error = error.localizedDescription }
            working = false
        }
    }

    private func act(_ s: Suggestion, _ action: String) {
        Task {
            do {
                _ = try await API.shared.request("POST", "trips/\(tripID)/suggestions/\(s.id)/\(action)")
                await load()
                onChanged()
            } catch { self.error = error.localizedDescription }
        }
    }
}

struct TripChatView: View {
    let tripID: String
    struct Message: Decodable, Identifiable, Equatable { var id: String; var username: String; var content: String; var mine: Bool; var createdAt: String? }
    @State private var messages: [Message] = []
    @State private var draft = ""
    @State private var error: String?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    if messages.isEmpty { EmptyState(symbol: "bubble.left.and.bubble.right", title: "行程群聊", message: "和同行的人商量行程，消息会通知到每个成员。") }
                    ForEach(messages) { message in
                        VStack(alignment: message.mine ? .trailing : .leading, spacing: 3) {
                            if !message.mine { Text(message.username).font(.caption).foregroundStyle(.secondary) }
                            Text(message.content)
                                .padding(.horizontal, 14).padding(.vertical, 10)
                                .foregroundStyle(message.mine ? .white : .primary)
                                .glassEffect(message.mine ? .regular.tint(Palette.sky.opacity(0.85)) : .regular, in: .rect(cornerRadius: 20))
                        }
                        .frame(maxWidth: .infinity, alignment: message.mine ? .trailing : .leading)
                        .id(message.id)
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
                .padding(16)
            }
            .onChange(of: messages.count) { if let last = messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } } }
        }
        .safeAreaInset(edge: .bottom) {
            GlassEffectContainer(spacing: 10) {
                HStack(alignment: .bottom, spacing: 10) {
                    TextField("说点什么", text: $draft, axis: .vertical).lineLimit(1...5)
                        .padding(.horizontal, 16).padding(.vertical, 12)
                        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22))
                    Button(action: send) {
                        Image(systemName: "arrow.up").font(.body.weight(.bold)).foregroundStyle(.white).frame(width: 44, height: 44)
                    }
                    .glassEffect(.regular.tint(Palette.sky).interactive(), in: .circle)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(.horizontal, 12).padding(.bottom, 6)
        }
        .screenBackground()
        .navigationTitle("行程群聊")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            while !Task.isCancelled {
                if let list = try? await API.shared.get("trips/\(tripID)/chat", as: [Message].self), list != messages {
                    messages = list
                    _ = try? await API.shared.request("POST", "trips/\(tripID)/chat/read")
                }
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    private func send() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        draft = ""
        Task {
            do { messages.append(try await API.shared.post("trips/\(tripID)/chat", body: ["content": text], as: Message.self)) }
            catch { self.error = error.localizedDescription; draft = text }
        }
    }
}

struct ExpenseEditor: View {
    let trip: TripDetail
    let me: String
    let onDone: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var amount = ""
    @State private var title = ""
    @State private var category = "餐饮"
    @State private var payer = ""
    @State private var participants: Set<String> = []
    @State private var error: String?
    private let categories = ["餐饮", "交通", "门票", "住宿", "购物", "其他"]
    private var members: [String] { (trip.members ?? []).map(\.username) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("金额（元）", text: $amount).keyboardType(.decimalPad).font(.title2.weight(.semibold))
                    TextField("花在哪，如：晚饭 · 楼外楼", text: $title)
                    Picker("类别", selection: $category) { ForEach(categories, id: \.self) { Text($0) } }
                }
                if members.count > 1 {
                    Section("谁付的") {
                        Picker("付款人", selection: $payer) { ForEach(members, id: \.self) { Text($0).tag($0) } }
                    }
                    Section("谁分摊") {
                        ForEach(members, id: \.self) { name in
                            Button {
                                if participants.contains(name) { participants.remove(name) } else { participants.insert(name) }
                            } label: {
                                HStack { Text(name).foregroundStyle(.primary); Spacer(); if participants.contains(name) { Image(systemName: "checkmark") } }
                            }
                        }
                    }
                }
                if let error { Text(error).foregroundStyle(.red).font(.footnote) }
            }
            .scrollContentBackground(.hidden)
            .screenBackground()
            .navigationTitle("记一笔")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("保存", action: save).disabled(Double(amount) == nil) }
            }
            .onAppear { payer = me; participants = Set(members) }
        }
    }

    private func save() {
        guard let value = Double(amount) else { return }
        Task {
            do {
                _ = try await API.shared.request("POST", "trips/\(trip.id)/expenses", body: [
                    "amount": value, "title": title.isEmpty ? category : title, "category": category,
                    "payer": payer, "participant_usernames": Array(participants), "spent_at": "",
                ])
                onDone()
                dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}
