import SwiftUI

private let ledgerCurrencies = ["CNY", "MYR", "SGD", "USD", "EUR", "JPY", "HKD", "THB", "KRW", "GBP", "AUD", "TWD", "VND", "IDR"]
private let ledgerCurrencyNames = ["CNY": "人民币", "MYR": "马币", "SGD": "新币", "USD": "美元", "EUR": "欧元", "JPY": "日元", "HKD": "港币", "THB": "泰铢", "KRW": "韩元", "GBP": "英镑", "AUD": "澳元", "TWD": "台币", "VND": "越南盾", "IDR": "印尼盾"]
private let ledgerCategories = ["餐饮", "交通", "住宿", "门票", "购物", "其他"]
private func ledgerMoney(_ minor: Int, _ currency: String) -> String { currency + " " + String(format: "%.2f", Double(minor) / 100) }

struct LedgerBook: Decodable, Identifiable {
    var id: String
    var title: String
    var count: Int
    var targetCurrency: String
    var totals: [String: Int]
    var byCategory: [CategoryTotal]
    var entries: [LedgerEntry]?
    struct CategoryTotal: Decodable { var currency: String; var category: String; var amountMinor: Int }
}
struct LedgerEntry: Decodable, Identifiable {
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
    @State private var books: [LedgerBook] = []
    @State private var loading = true
    @State private var creating = false
    @State private var error: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("旅行中的每一笔，都记在这里").font(.subheadline).foregroundStyle(.secondary)
                    Text("个人账本 · 按币种分别统计").font(.caption).foregroundStyle(.secondary)
                    if let error { Text(error).foregroundStyle(.red) }
                    if loading { ProgressView() }
                    if !loading && books.isEmpty {
                        EmptyState(symbol: "creditcard", title: "记录第一趟旅行的花费", message: "不用先建行程。新建账本后，就能记录餐饮、交通和住宿等支出。")
                        Button("新建账本", systemImage: "plus") { creating = true }.buttonStyle(.glassProminent)
                    }
                    ForEach(books) { book in
                        NavigationLink {
                            LedgerDetailView(bookID: book.id).onDisappear { Task { await load() } }
                        } label: {
                            VStack(alignment: .leading, spacing: 12) {
                                HStack { Text(book.title).font(.headline); Spacer(); Image(systemName: "chevron.right") }
                                TotalsView(totals: book.totals)
                                Text("\(book.count) 笔支出").font(.caption).foregroundStyle(.secondary)
                            }.padding(18).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 22)
                        }.buttonStyle(.plain)
                    }
                }.padding(16)
            }
            .navigationTitle("旅行记账")
            .toolbar { Button("新建账本", systemImage: "plus") { creating = true } }
            .sheet(isPresented: $creating) { LedgerBookEditor { Task { await load() } } }
            .task { await load() }.refreshable { await load() }.screenBackground()
        }
    }
    private func load() async {
        do { books = try await API.shared.get("ledger", as: [LedgerBook].self); error = nil }
        catch is CancellationError {} catch { self.error = error.localizedDescription }
        loading = false
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
                    VStack(alignment: .leading, spacing: 12) {
                        Text("累计支出 · \(book.count) 笔").font(.subheadline)
                        Picker("汇总币种", selection: Binding(get: { book.targetCurrency }, set: { setCurrency($0) })) {
                            ForEach(ledgerCurrencies, id: \.self) { Text("\($0) · \(ledgerCurrencyNames[$0] ?? $0)").tag($0) }
                        }.disabled(busy || fxBusy)
                        if fxBusy { ProgressView("正在查询汇率…") }
                        else if let total = fx?.totalMinor {
                            Text(ledgerMoney(total, book.targetCurrency)).font(.largeTitle.bold()).foregroundStyle(Palette.sky).minimumScaleFactor(0.6).lineLimit(1)
                        } else { Text("暂无法完整换算").foregroundStyle(.secondary) }
                        Text("原币合计").font(.caption).foregroundStyle(.secondary)
                        TotalsView(totals: book.totals)
                        DisclosureGroup("汇率与更新时间") {
                            if let fx {
                                ForEach(fx.items.filter { $0.currency != fx.targetCurrency }, id: \.currency) { quote in
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text("1 \(quote.currency) ≈ \(String(format: "%.6f", Double(quote.rate) ?? 0)) \(fx.targetCurrency)")
                                        Text("行情日期 \(quote.rateDate)").font(.caption).foregroundStyle(.secondary)
                                    }.padding(.vertical, 4)
                                }
                                if fx.stale { Text("更新暂不可用，当前使用上次查询汇率。").foregroundStyle(.orange) }
                                if !fx.missing.isEmpty { Text("未获得 \(fx.missing.joined(separator: "、")) 汇率，暂不显示完整总额。").foregroundStyle(.orange) }
                                if !fx.fetchedAt.isEmpty { Text("Frankfurter · 查询于 \(fx.fetchedAt)").font(.caption).foregroundStyle(.secondary) }
                            }
                            if let fxError { Text(fxError).foregroundStyle(.red) }
                            Text("参考汇率按日更新，实际换汇或刷卡金额可能不同。").font(.caption).foregroundStyle(.secondary)
                            Button("刷新汇率", systemImage: "arrow.clockwise") { Task { await refreshFx(true) } }.disabled(fxBusy)
                        }
                        Button("记一笔", systemImage: "plus") { adding = true }.buttonStyle(.glassProminent)
                    }.padding(18).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 22)
                    if !book.byCategory.isEmpty {
                        DisclosureGroup("分类汇总") {
                            ForEach(Array(book.byCategory.enumerated()), id: \.offset) { _, total in
                                HStack { Text(total.category); Spacer(); Text(ledgerMoney(total.amountMinor, total.currency)).monospacedDigit() }.padding(.vertical, 4)
                            }
                        }.padding(16).glassCard(cornerRadius: 18)
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
                                }.buttonStyle(.plain).accessibilityLabel("编辑账单 \(entry.title)")
                                Button { deleting = entry } label: { Image(systemName: "trash").frame(width: 44, height: 44) }
                                    .tint(.red).accessibilityLabel("删除账单 \(entry.title)")
                            }.padding(16).glassCard(cornerRadius: 18)
                        }
                    }
                } else { ProgressView() }
            }.padding(16)
        }
        .navigationTitle(book?.title ?? "账本").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            Menu {
                Button("记一笔", systemImage: "plus") { adding = true }
                Button("重命名账本", systemImage: "pencil") { renaming = true }
                Button("删除账本", systemImage: "trash", role: .destructive) { confirmBookDelete = true }
            } label: { Image(systemName: "ellipsis") }.disabled(book == nil || busy)
        }
        .sheet(isPresented: $adding) { LedgerEntryEditor(bookID: bookID, defaultCurrency: book?.entries?.first?.currency ?? "CNY") { Task { await load() } } }
        .sheet(item: $editing) { entry in LedgerEntryEditor(bookID: bookID, entry: entry) { Task { await load() } } }
        .sheet(isPresented: $renaming) { if let book { LedgerBookEditor(book: book) { Task { await load() } } } }
        .confirmationDialog("删除账本及全部账单？此操作无法恢复。", isPresented: $confirmBookDelete, titleVisibility: .visible) {
            Button("删除账本", role: .destructive) { remove(nil) }
        }
        .confirmationDialog("删除这笔账单？", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            if let entry = deleting { Button("删除账单", role: .destructive) { remove(entry) } }
        }
        .disabled(busy).task { await load() }.refreshable { await load() }.screenBackground()
    }
    private func load() async {
        do { book = try await API.shared.get("ledger/\(bookID)", as: LedgerBook.self); error = nil; await refreshFx() }
        catch is CancellationError {} catch { self.error = error.localizedDescription }
    }
    private func refreshFx(_ refresh: Bool = false) async {
        fxGeneration += 1
        let generation = fxGeneration
        fxBusy = true; fx = nil; fxError = nil
        defer { if generation == fxGeneration { fxBusy = false } }
        do {
            let value = try await API.shared.get("ledger/\(bookID)/conversion?refresh=\(refresh)", as: LedgerConversion.self)
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
                _ = try await API.shared.request("DELETE", "ledger/\(bookID)" + (entry.map { "/entries/\($0.id)" } ?? ""))
                if entry == nil { dismiss() } else { await load() }
            } catch { self.error = error.localizedDescription }
        }
    }
}

private struct LedgerBookEditor: View {
    var book: LedgerBook? = nil
    var onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var error: String?
    @State private var busy = false
    var body: some View {
        NavigationStack {
            Form {
                TextField("比如：马来西亚旅行", text: $title)
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle(book == nil ? "新建账本" : "重命名账本")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) }
                ToolbarItem(placement: .confirmationAction) { Button(busy ? "保存中…" : "保存") { save() }.disabled(busy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) }
            }.onAppear { title = book?.title ?? "" }.interactiveDismissDisabled(busy)
        }
    }
    private func save() {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.shared.request(book == nil ? "POST" : "PATCH", "ledger" + (book.map { "/\($0.id)" } ?? ""), body: ["title": title])
                onSaved(); dismiss()
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
                    TextField("花了什么？比如：海鲜晚餐", text: $title)
                    Picker("分类", selection: $category) { ForEach(ledgerCategories, id: \.self) { Text($0).tag($0) } }
                    DatePicker("发生日期", selection: $date, displayedComponents: .date)
                    TextField("备注（选填）", text: $note, axis: .vertical).lineLimit(2...5)
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle(entry == nil ? "记一笔" : "编辑账单")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) }
                ToolbarItem(placement: .confirmationAction) { Button(busy ? "保存中…" : "保存") { save() }.disabled(busy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || amount.isEmpty) }
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
                _ = try await API.shared.request(entry == nil ? "POST" : "PATCH", "ledger/\(bookID)/entries" + (entry.map { "/\($0.id)" } ?? ""), body: ["id": requestID, "title": title, "amount": clean, "currency": currency, "category": category, "spent_at": formatter.string(from: date), "note": note])
                onSaved(); dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}
