import SwiftUI

struct HomeView: View {
    @Environment(AppSession.self) private var session
    @Environment(AppRouter.self) private var router
    @State private var path = NavigationPath()
    @State private var trips: [TripSummary] = []
    @State private var cities = ["杭州", "平潭岛", "武功山", "武汉"]
    @State private var covers: [String: String] = [:]
    @State private var loading = true
    @State private var error: String?
    @State private var showAll = false
    @State private var showNotifications = false
    @State private var creating = false
    @State private var title = ""
    @State private var hasDate = false
    @State private var startDate = Date()
    @State private var busy = false
    @State private var unread = 0
    @State private var today: TodayTrip?
    @Environment(\.openURL) private var openURL
    @Namespace private var transition

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("\(session.account?.displayName ?? "朋友")，下一站去哪儿？").font(.subheadline).foregroundStyle(.secondary)
                        Text("把期待，\n变成一段旅行。").font(.largeTitle.weight(.semibold))
                    }.padding(.top, 16)
                    if let today { todayCard(today) }
                    HStack(spacing: 12) {
                        Button { creating = true } label: { Label("新建旅行", systemImage: "plus").frame(minHeight: 32) }.buttonStyle(.glassProminent)
                        Button { ask("帮我把这篇攻略整理成行程：") } label: { Label("导入攻略", systemImage: "arrow.up.right").frame(minHeight: 32) }.buttonStyle(.glass)
                    }.font(.subheadline)
                    VStack(alignment: .leading, spacing: 16) {
                        HStack { Text("我的旅行").font(.title3.weight(.semibold)); Spacer(); Button("全部行程 ↗") { showAll = true }.font(.caption).frame(minHeight: 44) }
                        PendingInvites { Task { await load() } }
                        if loading { ProgressView("正在打开旅行册…").frame(maxWidth: .infinity).padding(24) }
                        else if let error {
                            VStack(spacing: 12) { Text(error).font(.subheadline); Button("重新加载") { Task { await load() } } }.padding()
                        } else if trips.isEmpty {
                            VStack(spacing: 12) {
                                Image(systemName: "book.closed").font(.system(size: 42)).foregroundStyle(Palette.sky).rotationEffect(.degrees(-8))
                                Text("第一本旅行册，等你翻开").font(.headline)
                                Text("先选一个目的地，慢慢安排每一天。").font(.subheadline).foregroundStyle(.secondary)
                                Button("一起想想去哪儿 ↗") { ask("帮我规划一次轻松的周末旅行") }.buttonStyle(.glass)
                            }.frame(maxWidth: .infinity).padding(24).glassCard(cornerRadius: 24)
                        } else {
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 14) {
                                    ForEach(Array(trips.prefix(4).enumerated()), id: \.element.id) { index, trip in
                                        NavigationLink(value: TripRef(id: trip.id)) {
                                            TravelBookCard(trip: trip, index: index)
                                                .containerRelativeFrame(.horizontal) { width, _ in width * 0.86 }
                                                .matchedTransitionSource(id: trip.id, in: transition)
                                        }.buttonStyle(TravelPressStyle())
                                    }
                                }.scrollTargetLayout().padding(.vertical, 6)
                            }.scrollTargetBehavior(.viewAligned).scrollClipDisabled()
                        }
                    }
                    VStack(alignment: .leading, spacing: 14) {
                        Text("下一站灵感").font(.title3.weight(.semibold))
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 14) {
                                ForEach(cities.prefix(4), id: \.self) { city in
                                    Button { ask("我想去\(city)，帮我规划一次旅行") } label: {
                                        ZStack(alignment: .bottomLeading) {
                                            RoundedRectangle(cornerRadius: 22).fill(Palette.sky.opacity(0.16))
                                            RemoteImage(path: covers[city].map(API.proxied)).frame(width: 220, height: 150).clipped()
                                            LinearGradient(colors: [.clear, .black.opacity(0.6)], startPoint: .top, endPoint: .bottom)
                                            VStack(alignment: .leading, spacing: 4) { Text(city).font(.headline); Text("留一点时间，去看看").font(.caption) }.foregroundStyle(.white).padding(16)
                                        }.frame(width: 220, height: 150).clipShape(.rect(cornerRadius: 22))
                                    }.buttonStyle(TravelPressStyle())
                                }
                            }.padding(.vertical, 4)
                        }.scrollClipDisabled()
                    }
                }.padding(.horizontal, 18).padding(.bottom, 26)
            }
            .screenBackground().toolbar(.hidden, for: .tabBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Text("17同游").font(.headline).fixedSize() }.sharedBackgroundVisibility(.hidden)
                ToolbarItem(placement: .topBarTrailing) { Button { showNotifications = true } label: { Image(systemName: unread > 0 ? "bell.badge" : "bell") }.accessibilityLabel(unread > 0 ? "通知，\(unread) 条未读" : "通知") }
            }
            .navigationDestination(for: TripRef.self) { ref in
                TripDetailView(tripID: ref.id).navigationTransition(.zoom(sourceID: ref.id, in: transition))
                    .onDisappear { Task { await load() } }
            }
            .sheet(isPresented: $showAll, onDismiss: { Task { await load() } }) { TripsView() }
            .sheet(isPresented: $showNotifications, onDismiss: { Task { await loadUnread() } }) { NotificationsView() }
            .sheet(isPresented: $creating) { createSheet }
            .onChange(of: router.openTripID, initial: true) { _, id in
                if let id { path.append(TripRef(id: id)); router.openTripID = nil }
            }
            .task { await load(); await loadInspiration(); await loadUnread() }
            .refreshable { await load() }
        }
        .onChange(of: path.count) { _, count in router.travelDetailOpen = count > 0 }
    }
    private func ask(_ prompt: String) { router.aiPrompt = prompt; router.aiOpen = true }

    /// 出行期间（或临出发）先给今天的安排，不用再去翻行程。
    private func todayCard(_ trip: TodayTrip) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Button { path.append(TripRef(id: trip.id)) } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(trip.day.map { "今天 · 第 \($0) / \(trip.days ?? $0) 天" } ?? (trip.startsIn == 1 ? "明天出发" : "还有 \(trip.startsIn ?? 0) 天出发"))
                            .font(.footnote.weight(.semibold)).foregroundStyle(Palette.sky)
                        Text((trip.dayTitle ?? "").isEmpty ? trip.title : trip.dayTitle!).font(.title3.weight(.semibold)).foregroundStyle(.primary)
                            .multilineTextAlignment(.leading)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").font(.footnote).foregroundStyle(.secondary)
                }
            }.buttonStyle(TravelPressStyle())
            if trip.day != nil, (trip.stops ?? []).isEmpty {
                Text("今天还没有安排，打开行程加几个地点。").font(.footnote).foregroundStyle(.secondary)
            }
            ForEach((trip.stops ?? []).prefix(5)) { stop in
                Divider()
                HStack(spacing: 8) {
                    if !(stop.startTime ?? "").isEmpty { Text(stop.startTime!).font(.footnote).monospacedDigit().foregroundStyle(.secondary) }
                    Text(stop.name).font(.subheadline).lineLimit(1)
                    Spacer(minLength: 8)
                    if let url = stop.navURL {
                        Button("导航") { openURL(url) }.buttonStyle(.glassProminent).font(.footnote)
                            .accessibilityLabel("导航到 \(stop.name)")
                    }
                }
            }
            if (trip.stops ?? []).count > 5 { Text("还有 \((trip.stops ?? []).count - 5) 个地点").font(.footnote).foregroundStyle(.secondary) }
        }
        .padding(16).glassCard(cornerRadius: 24)
    }
    private var createSheet: some View {
        NavigationStack {
            Form {
                Section("给这次旅行起个名字") { TextField("比如：杭州的慢周末", text: $title) }
                Section {
                    Toggle("已确定出发日期", isOn: $hasDate.animation())
                    if hasDate { DatePicker("出发日期", selection: $startDate, displayedComponents: .date) }
                } footer: { Text("填了之后，出行当天首页会直接显示今天的安排。之后也可以在行程里改。") }
                Section { Button(busy ? "正在创建…" : "创建旅行") { Task { await create() } }.disabled(busy || title.trimmingCharacters(in: .whitespaces).isEmpty) }
                if let error { Text(error).foregroundStyle(.red).font(.footnote) }
            }.navigationTitle("新建旅行").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { creating = false } } }
        }.presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
    }
    private func create() async {
        guard !busy else { return }; busy = true
        defer { busy = false }
        do {
            struct Created: Decodable { var id: String }
            let day = startDate.formatted(.iso8601.year().month().day().dateSeparator(.dash))
            let result = try await API.shared.post("trips", body: ["title": title, "days": 2, "start_date": hasDate ? String(day.prefix(10)) : ""], as: Created.self)
            Haptics.success()
            creating = false; title = ""; hasDate = false; await load(); path.append(TripRef(id: result.id))
        } catch { Haptics.error(); self.error = error.localizedDescription }
    }
    private func load() async {
        let date = Date().formatted(.iso8601.year().month().day().dateSeparator(.dash).timeZone(separator: .omitted))
        struct Today: Decodable { var trip: TodayTrip? }
        today = (try? await API.shared.get("trips/today", query: ["date": String(date.prefix(10))], as: Today.self))?.trip
        do { trips = try await API.shared.get("trips", as: [TripSummary].self); error = nil }
        catch { self.error = error.localizedDescription }
        loading = false
    }
    private func loadUnread() async {
        struct Count: Decodable { var unread: Int }
        async let notes = try? API.shared.get("notifications/unread-count", as: Count.self)
        async let news = try? API.shared.get("announcements/unread", as: Count.self)
        unread = (await notes)?.unread ?? 0
        unread += (await news)?.unread ?? 0
    }
    private func loadInspiration() async {
        struct Inspiration: Decodable { var trending: [String] }
        if let data = try? await API.shared.get("onboarding", as: Inspiration.self), !data.trending.isEmpty { cities = data.trending }
        struct Covers: Decodable { var covers: [String: String] }
        if let data = try? await API.shared.request("GET", "onboarding/covers", items: cities.prefix(4).map { URLQueryItem(name: "destinations", value: $0) }),
           let reply = try? API.shared.decode(Covers.self, data) { covers = reply.covers }
    }
}

struct TravelBookCard: View {
    var trip: TripSummary
    var index: Int
    @Environment(\.colorScheme) private var scheme
    private var tint: Color { [Color.blue, .green, .orange, .purple][index % 4] }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack { Text(trip.destination?.isEmpty == false ? trip.destination! : "目的地待定").lineLimit(1); Spacer(); Text("\(trip.days ?? 1) 天") }.font(.caption)
            HStack { Image(systemName: "location.circle"); Rectangle().fill(tint.opacity(0.25)).frame(height: 1); Image(systemName: "paperplane") }.foregroundStyle(tint).padding(.vertical, 6)
            Text(trip.title).font(.headline).lineLimit(2).multilineTextAlignment(.leading)
            HStack { Text(trip.role == "owner" ? "我的行程" : "一起规划"); Spacer(); Text("打开 ↗") }.font(.caption2).foregroundStyle(.secondary)
        }
        .padding(20).padding(.leading, 8).frame(maxWidth: .infinity, minHeight: 170, alignment: .leading)
        .background(tint.opacity(scheme == .dark ? 0.18 : 0.10), in: .rect(cornerRadius: 22))
        .overlay(alignment: .leading) { Rectangle().fill(tint.opacity(0.14)).frame(width: 1).padding(.leading, 12).padding(.vertical, 8) }
        .background { RoundedRectangle(cornerRadius: 22).fill(tint.opacity(0.08)).padding(.horizontal, 6).offset(y: 5) }
        .padding(.bottom, 6)
    }
}


struct TodayTrip: Decodable {
    struct Stop: Decodable, Identifiable {
        var id: String; var name: String; var startTime: String?; var nav: JSONValue?
        /// 境内开高德，境外开苹果地图（高德没有当地数据）
        var navURL: URL? {
            (nav?["domestic"]?.bool == false ? nav?["apple"]?.string : nav?["amap"]?.string).flatMap(URL.init(string:))
        }
    }
    var id: String; var title: String; var days: Int?
    var day: Int?; var dayTitle: String?; var startsIn: Int?; var stops: [Stop]?
}
