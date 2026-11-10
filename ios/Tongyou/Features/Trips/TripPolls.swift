import SwiftUI

struct TripPoll: Decodable, Identifiable {
    struct Option: Decodable, Hashable { var text: String; var votes: Int; var voters: [String] }
    var id: String
    var question: String
    var closed: Bool
    /// 属于第几天；nil = 关于整趟行程。
    var day: Int?
    var options: [Option]
    var myVote: Int?
    var total: Int
    var members: Int
    var createdBy: String?
    var mine: Bool
    /// 没结束、我还没投：行程里要提醒的就是这些。
    var waitingForMe: Bool { !closed && myVote == nil }
}

/// 一个投票，直接放在那一天的行程里：点选项就投，每人一票可以改；发起人可以结束或删除。
struct PollCardView: View {
    let tripID: String
    let poll: TripPoll
    /// 投票/结束后的新状态；nil 表示已删除。
    let onChange: (TripPoll?) -> Void
    @State private var working = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "checklist").foregroundStyle(Palette.sky)
                Text(poll.question).font(.headline)
                Spacer(minLength: 0)
                if poll.waitingForMe {
                    Text("等你投票").font(.caption2.weight(.semibold)).foregroundStyle(.white)
                        .padding(.horizontal, 8).padding(.vertical, 3).background(.red, in: .capsule)
                }
            }
            Text((poll.closed ? "已结束" : "\(poll.total)/\(poll.members) 人已投 · 每人一票，可以改")
                 + ((poll.createdBy ?? "").isEmpty ? "" : " · \(poll.createdBy!) 发起"))
                .font(.caption).foregroundStyle(.secondary)
            ForEach(Array(poll.options.enumerated()), id: \.offset) { index, option in
                Button { vote(index) } label: { row(option, index) }
                    .buttonStyle(TravelPressStyle())
                    .disabled(poll.closed || working || poll.myVote == index)
            }
            if poll.mine {
                HStack(spacing: 16) {
                    if !poll.closed { Button("结束投票") { act("close", method: "POST") } }
                    Button("删除", role: .destructive) { act("", method: "DELETE") }
                }
                .font(.footnote).disabled(working)
            }
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).glassCard(cornerRadius: 20)
    }

    private func row(_ option: TripPoll.Option, _ index: Int) -> some View {
        let mine = poll.myVote == index
        let share = poll.total > 0 ? CGFloat(option.votes) / CGFloat(poll.total) : 0
        let top = poll.options.map(\.votes).max() ?? 0
        return HStack(spacing: 8) {
            Text((mine ? "✓ " : "") + option.text)
                .fontWeight(poll.closed && option.votes == top && top > 0 ? .semibold : .regular)
                .foregroundStyle(.primary)
            Spacer(minLength: 4)
            Text("\(option.votes) 票" + (option.voters.isEmpty ? "" : " · " + option.voters.joined(separator: "、")))
                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
        .font(.subheadline)
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(alignment: .leading) {
            GeometryReader { geo in Palette.sky.opacity(0.12).frame(width: geo.size.width * share) }
        }
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(mine ? Palette.sky : Color.secondary.opacity(0.25), lineWidth: 1))
        .clipShape(.rect(cornerRadius: 12))
    }

    private func vote(_ index: Int) {
        working = true
        Task {
            defer { working = false }
            do {
                onChange(try await API.shared.post("trips/\(tripID)/polls/\(poll.id)/vote", body: ["option": index], as: TripPoll.self))
                UISelectionFeedbackGenerator().selectionChanged()
            } catch { self.error = "投票失败，请重试。" }
        }
    }

    private func act(_ action: String, method: String) {
        working = true
        Task {
            defer { working = false }
            do {
                let data = try await API.shared.request(method, "trips/\(tripID)/polls/\(poll.id)" + (action.isEmpty ? "" : "/\(action)"))
                onChange(method == "DELETE" ? nil : try API.shared.decode(TripPoll.self, data))
            } catch { self.error = "操作失败，请重试。" }
        }
    }
}

/// 发起投票：默认归到当前这一天，也可以选「整趟行程」。
struct NewPollSheet: View {
    let tripID: String
    let dayCount: Int
    let onCreated: (TripPoll) -> Void
    @State var day: Int          // 0 = 整趟行程
    @Environment(\.dismiss) private var dismiss
    @State private var question = ""
    @State private var options = ["", ""]
    @State private var working = false
    @State private var error: String?

    private var filled: [String] { options.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("属于", selection: $day) {
                        ForEach(1...max(1, dayCount), id: \.self) { Text("第 \($0) 天").tag($0) }
                        Text("整趟行程").tag(0)
                    }
                }
                Section("要大家决定什么") {
                    TextField("如「晚上住哪家」", text: $question)
                }
                Section {
                    ForEach(options.indices, id: \.self) { index in TextField("选项 \(index + 1)", text: $options[index]) }
                    if options.count < 4 { Button("再加一个选项", systemImage: "plus") { options.append("") } }
                } footer: {
                    Text("发起后同行的人会收到通知，在这一天的行程里直接点选。")
                }
                if let error { Text(error).foregroundStyle(.red).font(.footnote) }
            }
            .navigationTitle("发起投票")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(working) }
                ToolbarItem(placement: .confirmationAction) {
                    Button("发起", action: create).disabled(working || question.trimmingCharacters(in: .whitespaces).isEmpty || filled.count < 2)
                }
            }
        }
    }

    private func create() {
        working = true
        error = nil
        Task {
            defer { working = false }
            do {
                var body: [String: Any] = ["question": question, "options": filled]
                if day > 0 { body["day"] = day }
                let poll = try API.shared.decode(TripPoll.self, try await API.shared.request("POST", "trips/\(tripID)/polls", body: body))
                Haptics.success()
                onCreated(poll)
                dismiss()
            } catch { Haptics.error(); self.error = "发起失败：需要 2 到 4 个不重复的选项。" }
        }
    }
}
