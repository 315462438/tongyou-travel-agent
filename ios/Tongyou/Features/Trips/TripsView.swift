import MapKit
import SwiftUI

struct TripsView: View {
    @Environment(AppRouter.self) private var router
    @State private var path = NavigationPath()
    @State private var creating = false
    @State private var newTitle = ""
    @State private var trips: [TripSummary] = []
    @State private var loading = true
    @State private var error: String?

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(spacing: 14) {
                    PendingInvites { Task { await load() } }
                    if let error {
                        Label(error, systemImage: "wifi.exclamationmark").font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(trips) { trip in
                        NavigationLink(value: TripRef(id: trip.id)) { TripRow(trip: trip) }
                            .buttonStyle(.plain)
                    }
                }
                .padding(16)
            }
            .overlay {
                if loading && trips.isEmpty { ProgressView() }
                else if !loading && trips.isEmpty && error == nil {
                    EmptyState(symbol: "map", title: "还没有协同行程", message: "在对话里生成攻略后，点“转成协同行程”就会出现在这里。")
                }
            }
            .navigationTitle("行程")
            .navigationDestination(for: TripRef.self) { TripDetailView(tripID: $0.id) }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { newTitle = ""; creating = true } label: { Image(systemName: "plus") }.accessibilityLabel("新建行程")
                }
            }
            .alert("新建行程", isPresented: $creating) {
                TextField("比如：国庆杭州 3 天", text: $newTitle)
                Button("取消", role: .cancel) {}
                Button("创建") { create() }
            }
            .onChange(of: router.openTripID, initial: true) { _, id in
                if let id { path.append(TripRef(id: id)); router.openTripID = nil }
            }
            .refreshable { await load() }
            .task { await load() }
            .screenBackground()
        }
    }

    private func create() {
        Task {
            struct Created: Decodable { var id: String }
            do {
                let trip = try await API.shared.post("trips", body: ["title": newTitle.isEmpty ? "新行程" : newTitle, "days": 2], as: Created.self)
                await load()
                path.append(TripRef(id: trip.id))
            } catch { self.error = error.localizedDescription }
        }
    }

    private func load() async {
        do {
            trips = try await API.shared.get("trips", as: [TripSummary].self)
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
        loading = false
    }
}

private struct TripRow: View {
    let trip: TripSummary
    var body: some View {
        HStack(spacing: 14) {
            VStack(spacing: 0) {
                Text("\(trip.days ?? 1)").font(.title2.bold()).foregroundStyle(Palette.sky)
                Text("天").font(.caption2).foregroundStyle(.secondary)
            }
            .frame(width: 56, height: 56)
            .glassEffect(.regular.tint(Palette.sky.opacity(0.12)), in: .rect(cornerRadius: 16))
            VStack(alignment: .leading, spacing: 4) {
                Text(trip.title).font(.headline).lineLimit(1)
                HStack(spacing: 6) {
                    if let destination = trip.destination, !destination.isEmpty { Text(destination) }
                    if trip.role == "editor" { Text("· 受邀编辑") }
                    Text("· " + ISODate.relative(trip.updatedAt))
                }
                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(.tertiary)
        }
        .padding(14)
        .glassCard(cornerRadius: 22, interactive: true)
    }
}

struct TripDetailView: View {
    let tripID: String
    @State private var trip: TripDetail?
    @State private var expenses: ExpenseSummary?
    @State private var day = 1
    @State private var error: String?
    @State private var camera: MapCameraPosition = .automatic
    @State private var selectedStop: String?
    @State private var editing: TripDetail.Stop?
    @State private var adding = false
    @State private var sheet: Sheet?
    @State private var showingMap = false
    @State private var retryingImport = false
    @Environment(\.openURL) private var openURL
    @Environment(AppSession.self) private var session

    private enum Sheet: String, Identifiable { case settings, reorder, members, copilot, expense; var id: String { rawValue } }
    private var isOwner: Bool {
        trip?.members?.first { $0.username == session.account?.username }?.role == "owner"
    }

    var body: some View {
        ScrollView {
            if let trip {
                VStack(alignment: .leading, spacing: 18) {
                    header(trip)
                    if let error {
                        Label(error, systemImage: "exclamationmark.circle")
                            .font(.subheadline).foregroundStyle(.secondary)
                            .padding(14).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 18)
                    }
                    if ["seeding", "reviewing", "copilot", "locating"].contains(trip.aiStatus ?? "") {
                        HStack(alignment: .top, spacing: 10) {
                            ProgressView().padding(.top, 3)
                            Text(trip.aiStatus == "locating" ? "路线已导入，正在补充地图位置。现在可以先查看和编辑行程。" : (trip.aiReview?.isEmpty == false ? trip.aiReview! : "正在整理行程，完成后会自动更新。"))
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                        .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 18)
                    }
                    daySelector(trip)
                    dayOverview(trip)
                    Picker("当天视图", selection: $showingMap) {
                        Label("当天行程", systemImage: "list.bullet.rectangle").tag(false)
                        Label("路线地图", systemImage: "map").tag(true)
                    }.pickerStyle(.segmented)
                    if showingMap { map(trip) } else { timeline(trip) }
                    if let expenses, expenses.count > 0 { expenseCard(expenses) }
                    if let review = trip.aiReview, !review.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Label("行程提示", systemImage: "info.circle").font(.headline)
                            MarkdownView(review)
                            if ["failed", "partial"].contains(trip.aiStatus ?? "") {
                                Button(retryingImport ? "正在重试…" : "继续导入失败的部分", systemImage: "arrow.clockwise") {
                                    Task {
                                        retryingImport = true
                                        defer { retryingImport = false }
                                        do {
                                            _ = try await API.shared.request("POST", "trips/\(tripID)/import/retry")
                                            await load()
                                            await poll()
                                        } catch { self.error = error.localizedDescription }
                                    }
                                }.buttonStyle(.glass).disabled(retryingImport)
                            }
                        }
                        .padding(16).glassCard(cornerRadius: 22)
                    }
                }
                .padding(16)
            } else if let error {
                EmptyState(symbol: "exclamationmark.triangle", title: "打不开这个行程", message: error)
            } else {
                ProgressView().padding(.top, 120)
            }
        }
        .screenBackground()
        .navigationTitle(trip?.title ?? "行程")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                NavigationLink { TripChatView(tripID: tripID) } label: { Image(systemName: "bubble.left.and.bubble.right") }
                    .accessibilityLabel("行程群聊")
                Menu {
                    Button("让 AI 改行程", systemImage: "wand.and.stars") { sheet = .copilot }
                    Button("添加地点", systemImage: "plus") { adding = true }
                    Button("调整当天顺序", systemImage: "arrow.up.arrow.down") { sheet = .reorder }
                    Button("记一笔账", systemImage: "creditcard") { sheet = .expense }
                    Divider()
                    Button("成员与邀请", systemImage: "person.2") { sheet = .members }
                    Button("行程设置", systemImage: "gearshape") { sheet = .settings }
                } label: { Image(systemName: "ellipsis") }
                .disabled(trip == nil)
            }
        }
        .sheet(isPresented: $adding) {
            if let trip { StopEditor(tripID: tripID, dayCount: trip.dayCount, defaultDay: day) { Task { await load() } } }
        }
        .sheet(item: $editing) { stop in
            StopEditor(tripID: tripID, dayCount: trip?.dayCount ?? 1, stop: stop) { Task { await load() } }
        }
        .sheet(item: $sheet) { which in
            if let trip {
                switch which {
                case .settings: TripSettingsSheet(trip: trip) { Task { await load() } }
                case .reorder: ReorderSheet(tripID: tripID, day: day, stops: trip.stops(on: day)) { Task { await load() } }
                case .members: MembersSheet(trip: trip, isOwner: isOwner) { Task { await load() } }
                case .copilot: CopilotSheet(tripID: tripID) { Task { await load() } }
                case .expense: ExpenseEditor(trip: trip, me: session.account?.username ?? "") { Task { await load() } }
                }
            }
        }
        .task { await load(); await poll() }
        .refreshable { await load() }
    }

    private func header(_ trip: TripDetail) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("一起规划 · 一起出发").font(.caption).foregroundStyle(.secondary)
            Text(trip.title).font(.title2.bold()).fixedSize(horizontal: false, vertical: true)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), alignment: .leading)], alignment: .leading, spacing: 8) {
                if let destination = trip.destination, !destination.isEmpty { Chip(text: destination, symbol: "mappin") }
                Chip(text: "\(trip.dayCount) 天", symbol: "calendar")
                if let start = trip.startDate, !start.isEmpty { Chip(text: start, symbol: "airplane.departure") }
                if let budget = trip.budget { Chip(text: "¥\(Int(budget))", symbol: "yensign") }
            }
            if let members = trip.members, members.count > 1 {
                HStack(spacing: -8) {
                    ForEach(members.prefix(6), id: \.self) { member in
                        Text(String(member.username.prefix(1)))
                            .font(.caption.bold()).foregroundStyle(.white)
                            .frame(width: 30, height: 30)
                            .background(Palette.sky.gradient, in: .circle)
                            .overlay(alignment: .bottomTrailing) {
                                if member.online == true { Circle().fill(.green).frame(width: 9, height: 9).overlay(Circle().stroke(.white, lineWidth: 1.5)) }
                            }
                    }
                    Text("  \(members.count) 人同行").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func dayOverview(_ trip: TripDetail) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(trip.dayTitles?[String(day)] ?? "第 \(day) 天").font(.title3.bold())
            Text("\(trip.stops(on: day).count) 项安排 · \(trip.stops(on: day).filter { $0.coordinate != nil }.count) 处已定位")
                .font(.subheadline).foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Button { adding = true } label: { Label("添加地点", systemImage: "plus").frame(maxWidth: .infinity) }
                    .buttonStyle(.glassProminent).tint(Palette.sky).disabled(trip.aiStatus == "seeding")
                Button { sheet = .copilot } label: { Label("AI 调整", systemImage: "wand.and.stars").frame(maxWidth: .infinity) }
                    .buttonStyle(.glass).disabled(["seeding", "reviewing", "copilot"].contains(trip.aiStatus ?? ""))
            }
            .font(.subheadline.weight(.semibold))
        }
        .padding(18).glassCard(cornerRadius: 22)
    }

    private func daySelector(_ trip: TripDetail) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: 8) {
                HStack(spacing: 8) {
                    ForEach(1...trip.dayCount, id: \.self) { value in
                        Button {
                            withAnimation(.snappy) { day = value; camera = .automatic }
                        } label: {
                            VStack(spacing: 1) {
                                Text("Day \(value)").font(.subheadline.weight(.semibold))
                                if let title = trip.dayTitles?[String(value)], !title.isEmpty {
                                    Text(title).font(.caption2).lineLimit(1)
                                }
                            }
                            .foregroundStyle(day == value ? .white : .primary)
                            .padding(.horizontal, 14).padding(.vertical, 8)
                        }
                        .glassEffect(day == value ? .regular.tint(Palette.sky).interactive() : .regular.interactive(), in: .capsule)
                    }
                }
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }

    @ViewBuilder private func map(_ trip: TripDetail) -> some View {
        let stops = trip.stops(on: day).filter { $0.coordinate != nil }
        if !stops.isEmpty {
            Map(position: $camera, selection: $selectedStop) {
                ForEach(Array(stops.enumerated()), id: \.element.id) { index, stop in
                    Marker(stop.name, monogram: Text("\(index + 1)"), coordinate: stop.coordinate!)
                        .tint(Palette.sky)
                        .tag(stop.id)
                }
                if stops.count > 1 {
                    MapPolyline(coordinates: stops.compactMap(\.coordinate)).stroke(Palette.sky.opacity(0.7), lineWidth: 3)
                }
            }
            .mapStyle(.standard(pointsOfInterest: .excludingAll))
            .frame(height: 240)
            .clipShape(.rect(cornerRadius: 24))
            .overlay(RoundedRectangle(cornerRadius: 24).strokeBorder(.white.opacity(0.4), lineWidth: 0.5))
        } else {
            EmptyState(symbol: "mappin.slash", title: "位置还在补充", message: "行程已保留。可以先切回当天行程查看安排，位置补齐后会自动显示。")
        }
    }

    private func timeline(_ trip: TripDetail) -> some View {
        let stops = trip.stops(on: day)
        return VStack(alignment: .leading, spacing: 0) {
            if stops.isEmpty {
                EmptyState(symbol: "calendar.badge.plus", title: "这一天还没有安排", message: "点下方“添加地点”，或者让 AI 帮你排。")
            }
            ForEach(Array(stops.enumerated()), id: \.element.id) { index, stop in
                HStack(alignment: .top, spacing: 14) {
                    VStack(spacing: 0) {
                        Text("\(index + 1)").font(.caption.bold()).foregroundStyle(.white)
                            .frame(width: 26, height: 26).background(Palette.sky, in: .circle)
                        if index < stops.count - 1 {
                            Rectangle().fill(Palette.sky.opacity(0.25)).frame(width: 2).frame(maxHeight: .infinity)
                        }
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(stop.name).font(.headline)
                            Spacer()
                            if let time = stop.startTime, !time.isEmpty { Text(time).font(.subheadline.monospacedDigit()).foregroundStyle(.secondary) }
                        }
                        if let note = stop.note, !note.isEmpty { Text(note).font(.subheadline).foregroundStyle(.secondary) }
                        HStack(spacing: 6) {
                            if let stay = stop.stayMin, stay > 0 { Chip(text: stay >= 60 ? "\(stay / 60)小时\(stay % 60 > 0 ? "\(stay % 60)分" : "")" : "\(stay)分钟", symbol: "clock") }
                            if let transport = stop.transport, !transport.isEmpty { Chip(text: transport, symbol: "figure.walk") }
                            if let price = stop.ticketPrice { Chip(text: "参考 ¥\(Int(price))", symbol: "ticket") }
                            else { Text("费用待补充").font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            if stop.coordinate == nil { Text(trip.aiStatus == "locating" ? "位置补充中" : "暂未定位").font(.caption).foregroundStyle(.secondary) }
                        }
                        HStack(spacing: 12) {
                            Button { editing = stop } label: { Label("编辑", systemImage: "pencil") }
                                .accessibilityLabel("编辑\(stop.name)")
                            if let url = stop.navigationURL {
                                Button { openURL(url) } label: { Label("导航", systemImage: "location.north") }
                                    .accessibilityLabel("导航到\(stop.name)")
                            }
                            Menu {
                                Button("在地图上看", systemImage: "map") { showingMap = true; selectedStop = stop.id }
                                Button("调整当天顺序", systemImage: "arrow.up.arrow.down") { sheet = .reorder }
                            } label: { Label("更多", systemImage: "ellipsis") }
                        }
                        .font(.subheadline.weight(.medium)).buttonStyle(.glass).padding(.top, 6)
                    }
                    .padding(14)
                    .glassCard(cornerRadius: 20)
                    .padding(.bottom, 12)
                    .contentShape(.rect)
                    .contextMenu {
                        Button("编辑", systemImage: "pencil") { editing = stop }
                        Button("在地图上看", systemImage: "map") { showingMap = true; selectedStop = stop.id }
                    }
                }
            }
            GlassEffectContainer(spacing: 10) {
                HStack(spacing: 10) {
                    Button { adding = true } label: { Label("继续添加", systemImage: "plus").frame(maxWidth: .infinity) }
                        .buttonStyle(.glass)
                }
                .font(.subheadline.weight(.semibold))
            }
            .padding(.top, 4)
        }
    }

    private func expenseCard(_ summary: ExpenseSummary) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("账单", systemImage: "creditcard").font(.headline)
                Spacer()
                Text("¥" + Int(summary.total.rounded()).formatted()).font(.title3.bold()).monospacedDigit()
            }
            ForEach(summary.transfers ?? [], id: \.self) { transfer in
                Text("\(transfer.from) → \(transfer.to)  ¥\(Int(transfer.amount.rounded()))").font(.subheadline)
            }
            if let text = summary.text, !text.isEmpty {
                Button { UIPasteboard.general.string = text } label: { Label("复制账单", systemImage: "doc.on.doc") }
                    .buttonStyle(.glass).font(.footnote)
            }
        }
        .padding(16).glassCard(cornerRadius: 22)
    }

    private func load() async {
        do {
            let detail = try await API.shared.get("trips/\(tripID)", as: TripDetail.self)
            trip = detail
            if day > detail.dayCount { day = 1 }
            error = nil
            expenses = try? await API.shared.get("trips/\(tripID)/expenses/summary", as: ExpenseSummary.self)
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
    }

    /// While the AI is still extracting the trip, refresh every few seconds.
    private func poll() async {
        while !Task.isCancelled, let status = trip?.aiStatus, ["seeding", "reviewing", "copilot", "locating"].contains(status) {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            await load()
        }
    }
}

/// Invitations to other people's trips, accepted or declined in place.
private struct PendingInvites: View {
    let onChange: () -> Void
    struct Invite: Decodable, Identifiable { var tripId: String; var title: String?; var inviter: String?; var id: String { tripId } }
    @State private var invites: [Invite] = []

    var body: some View {
        ForEach(invites) { invite in
            VStack(alignment: .leading, spacing: 10) {
                Label("\(invite.inviter ?? "有人")邀请你一起编辑「\(invite.title ?? "行程")」", systemImage: "envelope.open")
                    .font(.subheadline.weight(.medium))
                GlassEffectContainer {
                    HStack {
                        Button("接受") { respond(invite, true) }.buttonStyle(.glassProminent).tint(Palette.sky)
                        Button("拒绝") { respond(invite, false) }.buttonStyle(.glass)
                    }
                }
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 22)
        }
        .task { await load() }
    }

    private func load() async {
        if let data = try? await API.shared.request("GET", "trips/invites/pending") {
            if let list = try? API.shared.decode([Invite].self, data) { invites = list }
            else if let wrapped = try? API.shared.decode([String: [Invite]].self, data) { invites = wrapped.values.first ?? [] }
        }
    }

    private func respond(_ invite: Invite, _ accept: Bool) {
        Task {
            _ = try? await API.shared.request("POST", "trips/\(invite.tripId)/invites/respond", body: ["accept": accept])
            invites.removeAll { $0.id == invite.id }
            onChange()
        }
    }
}
