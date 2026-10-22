import SwiftUI

private let ledgerCurrencies = ["CNY", "MYR", "SGD", "USD", "EUR", "JPY", "HKD", "THB", "KRW", "GBP", "AUD", "TWD", "VND", "IDR"]
private let ledgerCurrencyNames = ["CNY": "人民币", "MYR": "马币", "SGD": "新币", "USD": "美元", "EUR": "欧元", "JPY": "日元", "HKD": "港币", "THB": "泰铢", "KRW": "韩元", "GBP": "英镑", "AUD": "澳元", "TWD": "台币", "VND": "越南盾", "IDR": "印尼盾"]
private let ledgerCategories = ["餐饮", "交通", "住宿", "门票", "购物", "其他"]
private func ledgerMoney(_ minor: Int, _ currency: String) -> String { currency + " " + String(format: "%.2f", Double(minor) / 100) }

struct LedgerTrip: Decodable, Identifiable { var id: String; var title: String }
private struct LedgerRef: Hashable, Identifiable { var id: String }

struct LedgerBook: Decodable, Identifiable {
    var id: String
    var title: String
    var count: Int
    var targetCurrency: String
    var role: String
    var trip: LedgerTrip?
    var totals: [String: Int]
    var byCategory: [CategoryTotal]
    var entries: [LedgerEntry]?
    struct CategoryTotal: Decodable { var currency: String; var category: String; var amountMinor: Int }
}
struct LedgerEntry: Decodable, Identifiable {
    var version: Int?
    var id: String
    var title: String
    var amountMinor: Int
    var currency: String
    var category: String
    var spentAt: String
    var note: String
}

private struct LedgerConversion: Decodable {
    var targetCurrency: String
    var totalMinor: Int?
    var stale: Bool
    var fetchedAt: String
    var missing: [String]
    var items: [Quote]
    struct Quote: Decodable { var currency: String; var rate: String; var rateDate: String }
}

struct LedgerView: View {
    var initialTrip: LedgerTrip? = nil
    @Environment(AppRouter.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var allBooks = false
    @State private var joining = false
    @State private var selectedBook: LedgerRef?
    @State private var invites: [LedgerInvite] = []
    @State private var responding = false
    @State private var books: [LedgerBook] = []
    @State private var loading = true
    @State private var creating = false
    @State private var error: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("旅行中的每一笔，都记在这里").font(.subheadline).foregroundStyle(.secondary)
                    Text(initialTrip != nil && !allBooks ? "\(initialTrip!.title) · 关联账本" : "个人记账，也能邀请同伴协作").font(.caption).foregroundStyle(.secondary)
                    if let error { Text(error).foregroundStyle(.red) }
                    if loading { ProgressView() }
                    if !loading && books.isEmpty {
                        EmptyState(symbol: "creditcard", title: "记录第一趟旅行的花费", message: "不用先建行程。新建账本后，就能记录餐饮、交通和住宿等支出。")
                        Button("新建账本", systemImage: "plus") { creating = true }.buttonStyle(.glassProminent)
                    }
                    if initialTrip != nil && !allBooks { Button("显示全部账本") { allBooks = true; Task { await load() } } }
                    ForEach(invites) { invite in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(invite.title).font(.headline)
                            Text("\(invite.inviter) 邀请你加入 · \(ledgerRoleName(invite.role))").font(.subheadline)
                            HStack { Button("接受邀请") { respond(invite, true) }; Button("拒绝") { respond(invite, false) } }.disabled(responding)
                        }.padding(16).glassCard(cornerRadius: 18)
                    }
                    ForEach(books) { book in
                        NavigationLink {
                            LedgerDetailView(bookID: book.id).onDisappear { Task { await load() } }
                        } label: {
                            VStack(alignment: .leading, spacing: 12) {
                                HStack { Text(book.title).font(.headline); Spacer(); Image(systemName: "chevron.right") }
                                TotalsView(totals: book.totals)
                                Text(book.trip.map { "关联行程：\($0.title)" } ?? "独立账本").font(.caption).foregroundStyle(.secondary)
                                Text("\(book.count) 笔支出 · \(ledgerRoleName(book.role))").font(.caption).foregroundStyle(.secondary)
                            }.padding(18).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 22).contentShape(Rectangle())
                        }.buttonStyle(TravelPressStyle())
                    }
                }.padding(16)
            }
            .navigationTitle("旅行记账")
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button("加入账本", systemImage: "link") { joining = true }
                    Button("新建账本", systemImage: "plus") { creating = true }
                }
                if initialTrip != nil { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } } }
            }
            .navigationDestination(item: $selectedBook) { ref in LedgerDetailView(bookID: ref.id).onDisappear { Task { await load() } } }
            .sheet(isPresented: $joining) { LedgerJoinEditor { id in selectedBook = LedgerRef(id: id); Task { await load() } } }
            .sheet(isPresented: $creating) { LedgerBookEditor(defaultTrip: allBooks ? nil : initialTrip) { Task { await load() } } }
            .onChange(of: router.openLedgerID, initial: true) { _, id in
                guard initialTrip == nil, let id else { return }
                selectedBook = LedgerRef(id: id)
                router.openLedgerID = nil
                Task { await load() }
            }
            .task {
                await load()
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(15)) } catch { break }
                    if !creating && !joining && !responding { await load() }
                }
            }.refreshable { await load() }.screenBackground()
        }
    }
    private func load() async {
        do {
            books = try await API.shared.get("ledger", query: initialTrip != nil && !allBooks ? ["trip_id": initialTrip!.id] : [:], as: [LedgerBook].self)
            invites = try await API.shared.get("ledger/invites/pending", as: [LedgerInvite].self); error = nil
        }
        catch is CancellationError {} catch { self.error = error.localizedDescription }
        loading = false
    }
    private func respond(_ invite: LedgerInvite, _ accept: Bool) {
        responding = true
        Task {
            defer { responding = false }
            do {
                _ = try await API.shared.request("POST", "ledger/\(invite.id)/invites/respond", body: ["accept": accept])
                await load(); if accept { selectedBook = LedgerRef(id: invite.id) }
            } catch { self.error = error.localizedDescription }
        }
    }
}

private struct TotalsView: View {
    let totals: [String: Int]
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if totals.isEmpty { Text("还没有支出").foregroundStyle(.secondary) }
            ForEach(totals.keys.sorted(), id: \.self) { currency in
                Text(ledgerMoney(totals[currency] ?? 0, currency)).font(.title3.bold()).monospacedDigit().foregroundStyle(Palette.sky)
            }
        }
    }
}

private struct LedgerDetailView: View {
    let bookID: String
    @Environment(\.dismiss) private var dismiss
    @State private var book: LedgerBook?
    @State private var error: String?
    @State private var adding = false
    @State private var editing: LedgerEntry?
    @State private var renaming = false
    @State private var showingMembers = false
    private var isOwner: Bool { book?.role == "owner" }
    private var canEdit: Bool { isOwner || book?.role == "editor" }
    @State private var fx: LedgerConversion?
    @State private var fxBusy = false
    @State private var fxGeneration = 0
    @State private var fxError: String?
    @State private var confirmBookDelete = false
    @State private var deleting: LedgerEntry?
    @State private var busy = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if let error { Text(error).foregroundStyle(.red) }
                if let book {
                    Text((book.trip.map { "关联行程：\($0.title)" } ?? "独立账本") + " · " + ledgerRoleName(book.role)).font(.footnote).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("累计支出 · \(book.count) 笔").font(.subheadline).foregroundStyle(.secondary)
                            Spacer()
                            Picker("汇总币种", selection: Binding(get: { book.targetCurrency }, set: { setCurrency($0) })) {
                                ForEach(ledgerCurrencies, id: \.self) { Text("\($0) · \(ledgerCurrencyNames[$0] ?? $0)").tag($0) }
                            }.pickerStyle(.menu).labelsHidden().disabled(!isOwner || busy || fxBusy)
                                .accessibilityLabel("汇总币种")
                        }
                        HStack(alignment: .center, spacing: 12) {
                            Group {
                                if fxBusy { ProgressView("正在换算…") }
                                else if let total = fx?.totalMinor {
                                    Text(ledgerMoney(total, book.targetCurrency)).font(.system(size: 30, weight: .bold)).foregroundStyle(Palette.sky).minimumScaleFactor(0.55).lineLimit(1)
                                } else { Text("暂无法完整换算").font(.headline).foregroundStyle(.secondary) }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                            if canEdit { Button("记一笔", systemImage: "plus") { adding = true }.buttonStyle(.glassProminent) }
                        }
                        Text("按最新参考汇率估算").font(.caption).foregroundStyle(.secondary)
                        if let fxError { Text(fxError + "，可展开明细重试。").font(.footnote).foregroundStyle(.red) }
                        if fx?.stale == true { Text("更新暂不可用，当前使用上次查询汇率。").font(.footnote).foregroundStyle(.orange) }
                        if let fx, !fx.missing.isEmpty { Text("未获得 \(fx.missing.joined(separator: "、")) 汇率，暂不显示完整总额。").font(.footnote).foregroundStyle(.orange) }
                        Divider()
                        DisclosureGroup("汇率与原币明细") {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("原币合计").font(.caption).foregroundStyle(.secondary)
                                ForEach(book.totals.keys.sorted(), id: \.self) { currency in
                                    Text(ledgerMoney(book.totals[currency] ?? 0, currency)).font(.subheadline).monospacedDigit()
                                }
                                if let fx {
                                    ForEach(fx.items.filter { $0.currency != fx.targetCurrency }, id: \.currency) { quote in
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text("1 \(quote.currency) ≈ \(String(format: "%.6f", Double(quote.rate) ?? 0)) \(fx.targetCurrency)")
                                            Text("行情日期 \(quote.rateDate)").font(.caption).foregroundStyle(.secondary)
                                        }
                                    }
                                    if !fx.fetchedAt.isEmpty { Text("Frankfurter · 查询于 \(fx.fetchedAt)").font(.caption).foregroundStyle(.secondary) }
                                }
                                Text("参考汇率按日更新，实际换汇或刷卡金额可能不同。").font(.caption).foregroundStyle(.secondary)
                                Button("刷新汇率", systemImage: "arrow.clockwise") { Task { await refreshFx(true) } }.disabled(fxBusy)
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
                        }.font(.subheadline)
                    }.padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 20)
                    HStack {
                        Text("支出明细").font(.headline)
                        Spacer()
                        Button("成员与分享", systemImage: "person.2") { showingMembers = true }.font(.subheadline)
                    }
                    if (book.entries ?? []).isEmpty { Text("还没有账单，先记下今天的第一笔花费吧。").foregroundStyle(.secondary) }
                    let grouped = Dictionary(grouping: book.entries ?? [], by: \.spentAt)
                    ForEach(grouped.keys.sorted(by: >), id: \.self) { date in
                        Text(date).font(.headline).padding(.top, 4)
                        let entries = grouped[date] ?? []
                        let totals = entries.reduce(into: [String: Int]()) { $0[$1.currency, default: 0] += $1.amountMinor }
                        Text(totals.keys.sorted().map { ledgerMoney(totals[$0] ?? 0, $0) }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                        ForEach(entries) { entry in
                            HStack(alignment: .top) {
                                Button { editing = entry } label: {
                                    VStack(alignment: .leading, spacing: 7) {
                                        Text(entry.title).font(.headline).foregroundStyle(.primary)
                                        Text(ledgerMoney(entry.amountMinor, entry.currency)).font(.title3.bold()).foregroundStyle(Palette.sky)
                                        Text(entry.category).font(.caption).foregroundStyle(.secondary)
                                        if !entry.note.isEmpty { Text(entry.note).font(.subheadline).foregroundStyle(.secondary) }
                                    }.frame(maxWidth: .infinity, alignment: .leading)
                                }.buttonStyle(TravelPressStyle()).disabled(!canEdit).accessibilityLabel(canEdit ? "编辑账单 \(entry.title)" : entry.title)
                                if canEdit { Button { deleting = entry } label: { Image(systemName: "trash").frame(width: 44, height: 44) }
                                    .tint(.red).accessibilityLabel("删除账单 \(entry.title)") }
                            }.padding(16).glassCard(cornerRadius: 18)
                        }
                    }
                    if !book.byCategory.isEmpty {
                        DisclosureGroup("分类汇总") {
                            ForEach(Array(book.byCategory.enumerated()), id: \.offset) { _, total in
                                HStack { Text(total.category); Spacer(); Text(ledgerMoney(total.amountMinor, total.currency)).monospacedDigit() }.padding(.vertical, 4)
                            }
                        }.padding(16).glassCard(cornerRadius: 18)
                    }
                } else if error == nil { ProgressView() }
            }.padding(16)
        }
        .navigationTitle(book?.title ?? "账本").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            Menu {
                if canEdit { Button("记一笔", systemImage: "plus") { adding = true } }
                Button("成员与分享", systemImage: "person.2") { showingMembers = true }
                if isOwner { Button("编辑账本", systemImage: "pencil") { renaming = true } }
                Button(isOwner ? "删除账本" : "退出账本", systemImage: isOwner ? "trash" : "rectangle.portrait.and.arrow.right", role: .destructive) { confirmBookDelete = true }
            } label: { Image(systemName: "ellipsis") }.disabled(book == nil || busy)
        }
        .sheet(isPresented: $showingMembers) { LedgerMemberPanel(bookID: bookID, owner: isOwner) { Task { await load() } } }
        .sheet(isPresented: $adding) { LedgerEntryEditor(bookID: bookID, defaultCurrency: book?.entries?.first?.currency ?? "CNY") { Task { await load() } } }
        .sheet(item: $editing) { entry in LedgerEntryEditor(bookID: bookID, entry: entry) { Task { await load() } } }
        .sheet(isPresented: $renaming) { if let book { LedgerBookEditor(book: book) { Task { await load() } } } }
        .confirmationDialog(isOwner ? "删除账本及全部账单？所有成员失去访问权，无法恢复。" : "退出此账本？已有账单保留，你将失去访问权限。", isPresented: $confirmBookDelete, titleVisibility: .visible) {
            Button(isOwner ? "删除账本" : "退出账本", role: .destructive) { remove(nil) }
        }
        .confirmationDialog("删除这笔账单？", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            if let entry = deleting { Button("删除账单", role: .destructive) { remove(entry) } }
        }
        .disabled(busy).task {
            await load()
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(15)) } catch { break }
                if !busy && !adding && editing == nil && !renaming && !showingMembers && !confirmBookDelete && deleting == nil { await load() }
            }
        }.refreshable { await load() }.screenBackground()
    }
    private func load() async {
        do { book = try await API.shared.get("ledger/\(bookID)", as: LedgerBook.self); error = nil; await refreshFx() }
        catch is CancellationError {} catch { self.book = nil; self.fx = nil; self.error = error.localizedDescription }
    }
    private func refreshFx(_ refresh: Bool = false) async {
        fxGeneration += 1
        let generation = fxGeneration
        fxBusy = true; fx = nil; fxError = nil
        defer { if generation == fxGeneration { fxBusy = false } }
        do {
            let value = try await API.shared.get("ledger/\(bookID)/conversion", query: ["refresh": String(refresh)], as: LedgerConversion.self)
            if generation == fxGeneration { fx = value }
        } catch is CancellationError {} catch { if generation == fxGeneration { fxError = error.localizedDescription } }
    }
    private func setCurrency(_ currency: String) {
        guard !busy else { return }; busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.shared.request("PATCH", "ledger/\(bookID)/currency", body: ["target_currency": currency])
                await load()
            } catch { self.error = error.localizedDescription }
        }
    }
    private func remove(_ entry: LedgerEntry?) {
        guard !busy else { return }; busy = true
        Task {
            defer { busy = false }
            do {
                let leaving = entry == nil && !isOwner
                _ = try await API.shared.request(leaving ? "POST" : "DELETE", "ledger/\(bookID)" + (entry.map { "/entries/\($0.id)" } ?? (leaving ? "/leave" : "")), query: entry?.version.map { ["version": String($0)] } ?? [:])
                if entry == nil { dismiss() } else { await load() }
            } catch { self.error = error.localizedDescription }
        }
    }
}

private struct LedgerBookEditor: View {
    var book: LedgerBook? = nil
    var defaultTrip: LedgerTrip? = nil
    var onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var tripID = ""
    @State private var trips: [LedgerTrip] = []
    @State private var tripError: String?
    @State private var error: String?
    @State private var busy = false
    var body: some View {
        NavigationStack {
            Form {
                TextField("比如：马来西亚旅行", text: $title)
                Picker("关联行程（选填）", selection: $tripID) {
                    Text("不关联 · 独立账本").tag("")
                    if !tripID.isEmpty && !trips.contains(where: {$0.id == tripID}) { Text("原关联行程（需重新选择）").tag(tripID) }
                    ForEach(trips) { Text($0.title).tag($0.id) }
                }
                Text("默认仅自己可见。创建后可邀请账本成员，关联行程不会自动共享。").font(.footnote).foregroundStyle(.secondary)
                if let tripError { Text(tripError).foregroundStyle(.red); Button("重试加载行程") { Task { await loadTrips() } } }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle(book == nil ? "新建账本" : "编辑账本")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) }
                ToolbarItem(placement: .confirmationAction) { Button(busy ? "保存中…" : "保存") { save() }.disabled(busy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) }
            }.onAppear { title = book?.title ?? ""; tripID = (book?.trip ?? defaultTrip)?.id ?? "" }.task { await loadTrips() }.interactiveDismissDisabled(busy)
        }
    }
    private func loadTrips() async {
        do { trips = try await API.shared.get("trips", as: [LedgerTrip].self); tripError = nil }
        catch { tripError = "行程加载失败，可重试或保存独立账本。" }
    }
    private func save() {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.shared.request(book == nil ? "POST" : "PATCH", "ledger" + (book.map { "/\($0.id)" } ?? ""), body: ["title": title, "trip_id": tripID.isEmpty ? NSNull() : tripID] as [String: Any])
                Haptics.success(); onSaved(); dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}

private struct LedgerEntryEditor: View {
    let bookID: String
    var defaultCurrency = "CNY"
    var entry: LedgerEntry? = nil
    var onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var requestID = UUID().uuidString
    @State private var title = ""
    @State private var amount = ""
    @State private var currency = "CNY"
    @State private var category = "餐饮"
    @State private var date = Date()
    @State private var note = ""
    @State private var error: String?
    @State private var busy = false
    private var formatter: DateFormatter { let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.calendar = Calendar(identifier: .gregorian); f.dateFormat = "yyyy-MM-dd"; return f }
    var body: some View {
        NavigationStack {
            Form {
                Section("支出") {
                    TextField("金额", text: $amount).keyboardType(.decimalPad)
                    Picker("币种", selection: $currency) { ForEach(ledgerCurrencies, id: \.self) { Text("\($0) · \(ledgerCurrencyNames[$0] ?? $0)").tag($0) } }
                    Picker("分类", selection: $category) { ForEach(ledgerCategories, id: \.self) { Text($0).tag($0) } }
                    TextField("花了什么（选填，默认使用分类）", text: $title)
                    DatePicker("发生日期", selection: $date, displayedComponents: .date)
                    TextField("备注（选填）", text: $note, axis: .vertical).lineLimit(2...5)
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle(entry == nil ? "记一笔" : "编辑账单")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) }
                ToolbarItem(placement: .confirmationAction) { Button(busy ? "保存中…" : "保存") { save() }.disabled(busy || amount.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) }
            }
            .interactiveDismissDisabled(busy)
            .onAppear {
                if entry == nil { currency = defaultCurrency }
                if let entry { title = entry.title; amount = String(format: "%.2f", Double(entry.amountMinor) / 100); currency = entry.currency; category = entry.category; note = entry.note; date = formatter.date(from: entry.spentAt) ?? Date() }
            }
        }
    }
    private func save() {
        let clean = amount.replacingOccurrences(of: ",", with: ".").trimmingCharacters(in: .whitespaces)
        guard clean.range(of: #"^\d{1,7}(\.\d{1,2})?$"#, options: .regularExpression) != nil,
              let value = Decimal(string: clean, locale: Locale(identifier: "en_US_POSIX")), value > 0 else {
            error = "请输入大于 0、最多两位小数的金额"; return
        }
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.shared.request(entry == nil ? "POST" : "PATCH", "ledger/\(bookID)/entries" + (entry.map { "/\($0.id)" } ?? ""), body: ["id": requestID, "title": title, "amount": clean, "currency": currency, "category": category, "spent_at": formatter.string(from: date), "note": note, "version": entry?.version as Any? ?? NSNull()] as [String: Any])
                Haptics.success(); onSaved(); dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}
