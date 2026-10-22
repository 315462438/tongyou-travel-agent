import SwiftUI

struct MembersSheet: View {
    let trip: TripDetail
    let isOwner: Bool
    let onDone: () -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @GestureState private var drag: CGSize = .zero
    @State private var username = ""
    @State private var working = false
    @State private var notice: String?
    @State private var error: String?
    @State private var link: URL?
    @State private var sharing = false
    @State private var entered = false
    @State private var success = 0
    @State private var confirmDisable = false
    @FocusState private var usernameFocused: Bool
    private var accent: Color { colorScheme == .dark ? Color(red: 0.52, green: 0.70, blue: 1) : Palette.sky }

    private var reduceMotion: Bool {
        #if DEBUG
        systemReduceMotion || ProcessInfo.processInfo.arguments.contains("--share-reduce-motion")
        #else
        systemReduceMotion
        #endif
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(isOwner ? "好风景，想和你一起。" : "这趟旅行，一起完成。")
                            .font(.title2.bold())
                        Text(isOwner ? "邀请同行的人，一起添上这趟旅行的灵感。" : "在同一份行程里，留下每个人的想法。")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    invitationCard
                        .rotationEffect(.degrees(reduceMotion ? 0 : Double(drag.width / 12)))
                        .offset(x: reduceMotion ? 0 : drag.width / 5, y: entered || reduceMotion ? 0 : 16)
                        .opacity(entered ? 1 : 0)
                        .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.72), value: drag)
                        .simultaneousGesture(DragGesture(minimumDistance: 10).updating($drag) { value, state, _ in
                            if abs(value.translation.width) > abs(value.translation.height) { state = CGSize(width: max(-60, min(60, value.translation.width)), height: 0) }
                        })
                    if isOwner {
                        VStack(alignment: .leading, spacing: 14) {
                            HStack(spacing: 10) {
                                Button { makeLink(copy: true) } label: { Label("复制邀请链接", systemImage: "link").frame(maxWidth: .infinity).padding(.vertical, 9) }
                                    .buttonStyle(.glass).accessibilityIdentifier("copyTripInvite")
                                Button { makeLink(copy: false) } label: { Label("分享给朋友", systemImage: "paperplane").frame(maxWidth: .infinity).padding(.vertical, 9) }
                                    .buttonStyle(.glassProminent)
                            }.disabled(working)
                            Text("持有链接的人可以加入并编辑行程。请只发给同行的人；可在右上角关闭链接。")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        VStack(alignment: .leading, spacing: 14) {
                            Label("也可以按用户名邀请", systemImage: "at").font(.headline)
                            HStack(spacing: 10) {
                                TextField("对方的用户名", text: $username)
                                    .focused($usernameFocused)
                                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                                    .submitLabel(.send).onSubmit(sendInvite)
                                    .padding(14).background(.quaternary, in: .rect(cornerRadius: 14))
                                    .accessibilityIdentifier("tripInviteUsername")
                                Button(action: sendInvite) {
                                    if working { ProgressView().frame(width: 28, height: 28) }
                                    else { Image(systemName: "arrow.up").font(.title3.bold()).frame(width: 28, height: 28) }
                                }.buttonStyle(.glassProminent)
                                    .disabled(working || username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                                    .accessibilityLabel("发送邀请")
                            }
                            Text("对方接受后，就能共同编辑。")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    if let notice {
                        Label(notice, systemImage: "checkmark.circle.fill").font(.subheadline).foregroundStyle(accent)
                            .accessibilityIdentifier("tripInviteSuccess")
                    }
                    if let error { Label(error, systemImage: "exclamationmark.circle").font(.subheadline).foregroundStyle(.red).accessibilityIdentifier("tripInviteError") }
                    VStack(alignment: .leading, spacing: 14) {
                        Text("同行的人 · \(trip.members?.count ?? 0)").font(.headline)
                        ForEach(trip.members ?? [], id: \.self) { member in
                            HStack(spacing: 12) {
                                Avatar(user: UserCard(username: member.username), size: 38)
                                Text(member.username).font(.subheadline.weight(.medium))
                                Spacer()
                                Text(member.role == "owner" ? "创建者" : "可编辑").font(.caption).foregroundStyle(.secondary)
                                if member.online == true { Circle().fill(.green).frame(width: 7, height: 7).accessibilityLabel("在线") }
                            }
                        }
                    }.padding(18).glassCard(cornerRadius: 22)
                }.padding(22)
            }
            .scrollDismissesKeyboard(.interactively)
            .screenBackground()
            .navigationTitle("邀请同行")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("完成") { dismiss() }.accessibilityIdentifier("closeTripMembers") }
                if isOwner {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu { Button("关闭链接邀请", systemImage: "link.badge.plus", role: .destructive) { confirmDisable = true } } label: { Image(systemName: "ellipsis") }
                    }
                }
            }
            .confirmationDialog("关闭邀请链接？已加入成员会保留。", isPresented: $confirmDisable, titleVisibility: .visible) {
                Button("关闭邀请链接", role: .destructive) { disableLink() }
            }
            .sheet(isPresented: $sharing) { if let link { GuideActivitySheet(items: ["邀请你一起规划「\(trip.title)」", link]) } }
            .sensoryFeedback(.success, trigger: success)
            .task { withAnimation(reduceMotion ? nil : .spring(response: 0.45, dampingFraction: 0.8)) { entered = true } }
        }
    }

    private var invitationCard: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack {
                Label("同行邀请函", systemImage: "ticket").font(.caption.weight(.semibold))
                Spacer()
                Image(systemName: success > 0 ? "checkmark.seal.fill" : "paperplane").font(.title2)
                    .contentTransition(reduceMotion ? .identity : .symbolEffect(.replace))
            }.foregroundStyle(accent)
            Text(trip.title).font(.title2.bold()).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Text(trip.destination?.isEmpty == false ? trip.destination! : "目的地待定")
                Text("· \(trip.dayCount) 天 · \(trip.stops.count) 个地点")
            }.font(.subheadline).foregroundStyle(.secondary)
            HStack(spacing: -7) {
                ForEach(Array((trip.members ?? []).prefix(4)), id: \.self) { member in
                    Avatar(user: UserCard(username: member.username), size: 34).padding(3).background(.background, in: .circle)
                }
                Spacer()
                Text("下一位，是你呀").font(.caption).foregroundStyle(accent)
            }
        }
        .padding(24).frame(maxWidth: .infinity, alignment: .leading)
        .background(LinearGradient(colors: [Palette.sky.opacity(0.15), Palette.warm.opacity(0.16)], startPoint: .topLeading, endPoint: .bottomTrailing), in: .rect(cornerRadius: 28))
        .overlay(RoundedRectangle(cornerRadius: 28).strokeBorder(Palette.sky.opacity(0.12)))
        .accessibilityIdentifier("tripInvitationCard")
    }

    private func sendInvite() {
        let name = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !working, !name.isEmpty else { return }
        working = true; error = nil; notice = nil
        Task { @MainActor in
            defer { working = false }
            do {
                _ = try await API.shared.request("POST", "trips/\(trip.id)/invite", body: ["username": name])
                notice = "已邀请 \(name)，等对方接受就能一起规划。"; username = ""; usernameFocused = false; success += 1; onDone()
            } catch { self.error = error.localizedDescription }
        }
    }
    private func makeLink(copy: Bool) {
        guard !working else { return }; working = true; error = nil; notice = nil
        Task { @MainActor in
            defer { working = false }
            do {
                struct Reply: Decodable { var shortCode: String }
                let reply = try API.shared.decode(Reply.self, try await API.shared.request("POST", "trips/\(trip.id)/share", body: ["reset": false]))
                guard let url = URL(string: "https://17tongyou.com/t/\(reply.shortCode)") else { return }
                link = url
                if copy { UIPasteboard.general.string = "邀请你一起规划「\(trip.title)」 \(url.absoluteString)"; notice = "邀请链接已复制，发给同行的人吧。"; success += 1 }
                else { sharing = true }
            } catch { self.error = error.localizedDescription }
        }
    }
    private func disableLink() {
        guard !working else { return }; working = true; error = nil
        Task { @MainActor in
            defer { working = false }
            do { _ = try await API.shared.request("DELETE", "trips/\(trip.id)/share"); link = nil; notice = "邀请链接已关闭，已加入成员不受影响。"; success += 1 }
            catch { self.error = error.localizedDescription }
        }
    }
}
