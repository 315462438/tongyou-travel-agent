import MapKit
import SwiftUI

struct TripsView: View {
    @Environment(AppRouter.self) private var router
    @State private var path = NavigationPath()
    @State private var creating = false
    @State private var newTitle = ""
    @State private var trips: [TripSummary] = []
    @State private var removal: TripSummary?
    @State private var removing = false
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
                        HStack(spacing: 6) {
                            NavigationLink(value: TripRef(id: trip.id)) { TripRow(trip: trip) }
                                .buttonStyle(TravelPressStyle())
                            Button { removal = trip } label: {
                                Image(systemName: trip.role == "owner" ? "trash" : "rectangle.portrait.and.arrow.right")
                                    .frame(width: 44, height: 44)
                            }
                            .tint(trip.role == "owner" ? .red : Palette.sky)
                            .accessibilityLabel(trip.role == "owner" ? "删除行程 \(trip.title)" : "退出行程 \(trip.title)")
                            .disabled(removing)
                        }
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
            .navigationDestination(for: TripRef.self) { TripDetailView(tripID: $0.id).onDisappear { Task { await load() } } }
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
            .confirmationDialog(removal?.role == "owner" ? "删除这份行程？" : "退出这份行程？", isPresented: Binding(get: { removal != nil }, set: { if !$0 { removal = nil } }), titleVisibility: .visible) {
                if let target = removal {
                    Button(target.role == "owner" ? "删除行程" : "退出行程", role: .destructive) { remove(target) }
                }
                Button("取消", role: .cancel) { removal = nil }
            } message: {
                Text(removal?.role == "owner" ? "所有成员都将失去此行程及其共同账单，无法恢复。" : "只从你的列表移除，不影响其他成员和已有共同账单。")
            }
            .onChange(of: router.openTripID, initial: true) { _, id in
                if let id { path.append(TripRef(id: id)); router.openTripID = nil }
            }
            .refreshable { await load() }
            .task { await load() }
            .screenBackground()
        }
    }

    private func remove(_ trip: TripSummary) {
        guard !removing else { return }
        removing = true
        Task {
            defer { removing = false }
            do {
                _ = try await API.shared.request(trip.role == "owner" ? "DELETE" : "POST", "trips/\(trip.id)" + (trip.role == "owner" ? "" : "/leave"))
                trips.removeAll { $0.id == trip.id }
                error = nil
            } catch { self.error = error.localizedDescription }
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
    @State private var viewingStop: TripDetail.Stop?
    @State private var editing: TripDetail.Stop?
    @State private var adding = false
    @State private var sheet: Sheet?
    @State private var showingLedger = false
    @State private var retryingImport = false
    @State private var confirmingRemoval = false
    @State private var removing = false
    @State private var petMemberBaseline: [String]?
    @State private var petBaselineTrip: String?
    @State private var petWelcome = ""
    @Environment(AppRouter.self) private var router
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(AppSession.self) private var session

    private enum Sheet: String, Identifiable { case settings, reorder, members, copilot, expense; var id: String { rawValue } }
    private var isOwner: Bool {
        trip?.members?.first { $0.username == session.account?.username }?.role == "owner"
    }

    var body: some View {
        Group {
            if let trip {
                TripMapPanel { inset in
                    map(trip).safeAreaInset(edge: .bottom) { Color.clear.frame(height: inset) }
                } content: {
                VStack(spacing: 10) {
                if !petWelcome.isEmpty && router.petPreferences.visible {
                    PetMemberWelcome(text: petWelcome, quiet: router.petPreferences.quiet) { petWelcome = "" }
                }
                daySelector(trip)
                dayOverview(trip)
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
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
                            timeline(trip)
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
                        }.padding(.bottom, 18)
                    }
                    .accessibilityIdentifier("tripTimeline")
                    .onChange(of: selectedStop) { _, id in
                        guard let id else { return }
                        if reduceMotion { proxy.scrollTo(id, anchor: .top) }
                        else { withAnimation(.easeInOut(duration: 0.25)) { proxy.scrollTo(id, anchor: .top) } }
                        if let coordinate = trip.stops.first(where: { $0.id == id })?.coordinate {
                            camera = .region(MKCoordinateRegion(center: coordinate, span: MKCoordinateSpan(latitudeDelta: 0.025, longitudeDelta: 0.025)))
                        }
                    }
                    .refreshable { await load() }
                }
                }
                }
            } else if let error {
                EmptyState(symbol: "exclamationmark.triangle", title: "打不开这个行程", message: error)
            } else {
                ProgressView().padding(.top, 120)
            }
        }
        .screenBackground()
        .navigationTitle(trip?.title ?? "行程")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: petWelcome) {
            guard !petWelcome.isEmpty else { return }
            do { try await Task.sleep(nanoseconds: 4_500_000_000) } catch { return }
            petWelcome = ""
        }
        .sheet(item: $viewingStop) { stop in
            PlaceDetailView(tripID: tripID, stop: stop) {
                Task { @MainActor in
                    try? await Task.sleep(for: .milliseconds(350))
                    editing = stop
                }
            }
        }
        .sheet(isPresented: $showingLedger) { LedgerView(initialTrip: LedgerTrip(id: tripID, title: trip?.title ?? "行程")) }
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                NavigationLink { TripChatView(tripID: tripID) } label: { Image(systemName: "bubble.left.and.bubble.right") }
                    .accessibilityLabel("行程群聊")
                Menu {
                    Button("让 AI 改行程", systemImage: "wand.and.stars") { sheet = .copilot }
                    Button("添加地点", systemImage: "plus") { adding = true }
                    Button("调整当天顺序", systemImage: "arrow.up.arrow.down") { sheet = .reorder }
                    Button("旅行账本", systemImage: "book.closed") { showingLedger = true }
                    Button("记一笔共同账单", systemImage: "creditcard") { sheet = .expense }
                    Divider()
                    Button("成员与邀请", systemImage: "person.2") { sheet = .members }
                    Button("行程设置", systemImage: "gearshape") { sheet = .settings }
                    Divider()
                    Button(isOwner ? "删除行程" : "退出行程", systemImage: isOwner ? "trash" : "rectangle.portrait.and.arrow.right", role: .destructive) { confirmingRemoval = true }
                        .disabled(removing)
                } label: { Image(systemName: "ellipsis") }
                .disabled(trip == nil)
            }
        }
        .confirmationDialog(isOwner ? "删除这份行程？" : "退出这份行程？", isPresented: $confirmingRemoval, titleVisibility: .visible) {
            Button(isOwner ? "删除行程" : "退出行程", role: .destructive) {
                guard !removing else { return }
                removing = true
                Task {
                    defer { removing = false }
                    do {
                        _ = try await API.shared.request(isOwner ? "DELETE" : "POST", "trips/\(tripID)" + (isOwner ? "" : "/leave"))
                        dismiss()
                    } catch { self.error = error.localizedDescription }
                }
            }
        } message: {
            Text(isOwner ? "行程及共同账单会对所有成员删除，无法恢复。" : "退出不影响其他成员和已有共同账单。")
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
    }

    private func header(_ trip: TripDetail) -> some View {
        HStack(spacing: 8) {
            Text([trip.destination, "\(trip.dayCount) 天", trip.startDate].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                .lineLimit(1)
            Spacer(minLength: 4)
            Button { sheet = .members } label: {
                Label("\(trip.members?.count ?? 1) 人同行", systemImage: "person.2")
            }.accessibilityLabel("成员与邀请")
        }
        .font(.caption).foregroundStyle(.secondary)
        .frame(minHeight: 30)
    }

    private func dayOverview(_ trip: TripDetail) -> some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(trip.dayTitles?[String(day)] ?? "当天安排").font(.subheadline.bold()).lineLimit(1)
                Text("\(trip.stops(on: day).count) 个地点")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Button { sheet = .copilot } label: { Image(systemName: "wand.and.stars").frame(width: 30, height: 30) }
                .buttonStyle(.glass).accessibilityLabel("AI 调整行程")
                .disabled(["seeding", "reviewing", "copilot"].contains(trip.aiStatus ?? ""))
            Button { adding = true } label: { Image(systemName: "plus").frame(width: 30, height: 30) }
                .buttonStyle(.glassProminent).tint(Palette.sky).accessibilityLabel("添加地点")
                .disabled(trip.aiStatus == "seeding")
        }
    }

    private func daySelector(_ trip: TripDetail) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: 8) {
                HStack(spacing: 8) {
                    ForEach(1...trip.dayCount, id: \.self) { value in
                        Button {
                            day = value; selectedStop = nil; camera = .automatic
                        } label: {
                            VStack(spacing: 1) {
                                Text("Day \(value)").font(.subheadline.weight(.semibold))
                            }
                            .foregroundStyle(day == value ? .white : .primary)
                            .padding(.horizontal, 14).padding(.vertical, 8)
                        }
                        .accessibilityIdentifier("tripDay_\(value)")
                        .glassEffect(day == value ? .regular.tint(Palette.sky).interactive() : .regular.interactive(), in: .capsule)
                    }
                }
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }

    @ViewBuilder private func map(_ trip: TripDetail) -> some View {
        let stops = trip.stops(on: day)
        let located = Array(stops.enumerated()).filter { $0.element.coordinate != nil }
        if !located.isEmpty {
            Map(position: $camera, selection: $selectedStop) {
                ForEach(located, id: \.element.id) { index, stop in
                    Marker(stop.name, monogram: Text("\(index + 1)"), coordinate: stop.coordinate!)
                        .tint(Palette.sky)
                        .tag(stop.id)
                }
                if stops.count > 1 {
                    MapPolyline(coordinates: stops.compactMap(\.coordinate)).stroke(Palette.sky.opacity(0.7), lineWidth: 3)
                }
            }
            .mapStyle(.standard(pointsOfInterest: .excludingAll))
            .accessibilityIdentifier("tripRouteMap")
            .overlay(alignment: .topTrailing) {
                Button { selectedStop = nil; camera = .automatic } label: { Label("全览", systemImage: "arrow.up.left.and.arrow.down.right").font(.caption).padding(8) }
                    .buttonStyle(.glass).padding(8)
            }
        } else {
            VStack(spacing: 8) {
                Image(systemName: "mappin.slash").font(.title2).foregroundStyle(Palette.sky)
                Text("这一天还没有定位的地点").font(.subheadline)
                Text("可以继续编辑下方行程，补充位置后自动显示").font(.caption).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Palette.sky.opacity(0.07)).accessibilityIdentifier("tripRouteMapEmpty")
        }
    }

    private func timeline(_ trip: TripDetail) -> some View {
        let stops = trip.stops(on: day)
        return LazyVStack(alignment: .leading, spacing: 18) {
            if stops.isEmpty {
                EmptyState(symbol: "calendar.badge.plus", title: "这一天还没有安排", message: "添加一个地点，或者让 AI 帮你规划。")
            }
            ForEach(Array(stops.enumerated()), id: \.element.id) { index, stop in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Button { selectedStop = stop.id; viewingStop = stop } label: {
                            HStack(spacing: 12) {
                                TripStopThumbnail(tripID: tripID, stop: stop, index: index + 1)
                                Text(stop.name).font(.system(size: 16, weight: .semibold)).foregroundStyle(.primary).multilineTextAlignment(.leading).lineLimit(2)
                                Spacer(minLength: 0)
                            }.contentShape(.rect)
                        }.buttonStyle(TravelPressStyle()).accessibilityIdentifier("tripStop_\(stop.id)")
                        Menu {
                            Button("在地图上看", systemImage: "map") { selectedStop = stop.id }
                            if let url = stop.navigationURL { Button("导航", systemImage: "location.north") { openURL(url) } }
                            Button("调整当天顺序", systemImage: "arrow.up.arrow.down") { sheet = .reorder }
                        } label: { Image(systemName: "ellipsis").foregroundStyle(.secondary).frame(width: 32, height: 44) }
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(stop.compactTimeRange).font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            Spacer()
                            Button { editing = stop } label: { Image(systemName: "pencil").font(.system(size: 15)).foregroundStyle(.secondary).frame(width: 38, height: 34) }
                                .buttonStyle(TravelPressStyle()).accessibilityLabel("编辑\(stop.name)")
                        }
                        if let note = stop.note, !note.isEmpty { Text(note).font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(2) }
                        if let price = stop.ticketPrice { Text("参考 ¥\(Int(price))").font(.caption2).foregroundStyle(.secondary) }
                        if stop.coordinate == nil { Text(trip.aiStatus == "locating" ? "位置补充中" : "位置待补充").font(.caption2).foregroundStyle(.secondary) }
                    }.padding(.horizontal, 10).padding(.bottom, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary.opacity(0.25), in: .rect(cornerRadius: 12)).padding(.leading, 66)
                }.id(stop.id)
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
            let names = detail.members?.map(\.username) ?? []
            let added = TravelPetLogic.addedMembers(previous: petBaselineTrip == tripID ? petMemberBaseline : nil, current: names, username: session.account?.username ?? "")
            petMemberBaseline = names; petBaselineTrip = tripID
            if !added.isEmpty { petWelcome = added.prefix(2).joined(separator: "、") + (added.count > 2 ? "等搭子" : "") + " 加入啦，一起出发！" }
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
struct PendingInvites: View {
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
