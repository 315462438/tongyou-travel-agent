import SwiftUI

struct TripPoll: Decodable, Identifiable {
    struct Option: Decodable, Hashable { var text: String; var votes: Int; var voters: [String] }
    var id: String
    var question: String
    var closed: Bool
    var options: [Option]
    var myVote: Int?
    var total: Int
    var members: Int
    var createdBy: String?
    var mine: Bool
}

/// 同行人投票：住哪家、哪天走这类事，发个投票比在群里来回问快。每人一票，可以改。
struct TripPollsView: View {
    let tripID: String
    @Environment(\.dismiss) private var dismiss
    @State private var polls: [TripPoll] = []
    @State private var loaded = false
    @State private var question = ""
    @State private var options = ["", ""]
    @State private var working = false
    @State private var error: String?

    private var filled: [String] { options.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }

    var body: some View {
        NavigationStack {
            List {
                if loaded && polls.isEmpty {
                    Text("还没有投票。住哪家、哪天走，发一个让大家点一下。").font(.subheadline).foregroundStyle(.secondary)
                }
                ForEach(polls) { poll in
                    Section {
                        ForEach(Array(poll.options.enumerated()), id: \.offset) { index, option in
                            Button { vote(poll, index) } label: { row(poll, option, index) }
                                .disabled(poll.closed || working)
                        }
                        if poll.mine {
                            HStack {
                                if !poll.closed { Button("结束投票") { act(poll, "close", method: "POST") } }
                                Spacer()
                                Button("删除", role: .destructive) { act(poll, "", method: "DELETE") }
                            }
                            .font(.footnote).buttonStyle(.borderless)
                        }
                    } header: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(poll.question).font(.headline).foregroundStyle(.primary).textCase(nil)
                            Text((poll.closed ? "已结束" : "\(poll.total)/\(poll.members) 人已投")
                                 + ((poll.createdBy ?? "").isEmpty ? "" : " · \(poll.createdBy!) 发起"))
                                .font(.caption).textCase(nil)
                        }
                    }
                }
                Section("发起投票") {
                    TextField("要大家决定什么？如「住哪家」", text: $question)
                    ForEach(options.indices, id: \.self) { index in
                        TextField("选项 \(index + 1)", text: $options[index])
                    }
                    if options.count < 4 { Button("加一个选项", systemImage: "plus") { options.append("") } }
                    Button(working ? "正在发起…" : "发起投票", action: create)
                        .disabled(working || question.trimmingCharacters(in: .whitespaces).isEmpty || filled.count < 2)
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
            }
            .navigationTitle("一起决定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private func row(_ poll: TripPoll, _ option: TripPoll.Option, _ index: Int) -> some View {
        let share = poll.total > 0 ? Double(option.votes) / Double(poll.total) : 0
        let top = poll.options.map(\.votes).max() ?? 0
        return HStack(spacing: 10) {
            Image(systemName: poll.myVote == index ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(poll.myVote == index ? Palette.sky : .secondary)
            VStack(alignment: .leading, spacing: 4) {
                Text(option.text).fontWeight(poll.closed && option.votes == top && top > 0 ? .semibold : .regular)
                    .foregroundStyle(.primary)
                ProgressView(value: share).tint(Palette.sky)
                if !option.voters.isEmpty {
                    Text(option.voters.joined(separator: "、")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            Text("\(option.votes) 票").font(.footnote).foregroundStyle(.secondary).monospacedDigit()
        }
    }

    private func load() async {
        if let rows = try? await API.shared.get("trips/\(tripID)/polls", as: [TripPoll].self) { polls = rows }
        loaded = true
    }

    private func vote(_ poll: TripPoll, _ index: Int) {
        working = true
        Task {
            do {
                let updated = try await API.shared.post("trips/\(tripID)/polls/\(poll.id)/vote", body: ["option": index], as: TripPoll.self)
                if let at = polls.firstIndex(where: { $0.id == poll.id }) { polls[at] = updated }
                UISelectionFeedbackGenerator().selectionChanged()
            } catch { self.error = "投票失败，请重试。" }
            working = false
        }
    }

    private func act(_ poll: TripPoll, _ action: String, method: String) {
        Task {
            do {
                _ = try await API.shared.request(method, "trips/\(tripID)/polls/\(poll.id)" + (action.isEmpty ? "" : "/\(action)"))
                await load()
            } catch { self.error = "操作失败，请重试。" }
        }
    }

    private func create() {
        working = true
        error = nil
        Task {
            do {
                _ = try await API.shared.request("POST", "trips/\(tripID)/polls", body: ["question": question, "options": filled])
                Haptics.success()
                question = ""; options = ["", ""]
                await load()
            } catch { Haptics.error(); self.error = "发起失败：需要 2 到 4 个不重复的选项。" }
            working = false
        }
    }
}
