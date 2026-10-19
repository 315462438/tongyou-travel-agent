import SwiftUI

struct LoginView: View {
    @Environment(AppSession.self) private var session
    @State private var registering = false
    @State private var username = ""
    @State private var password = ""
    @State private var invite = ""
    @State private var busy = false
    @State private var error: String?
    @FocusState private var field: Field?
    private enum Field { case username, password, invite }

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                VStack(spacing: 14) {
                    Image("LaunchMark").resizable().frame(width: 76, height: 76)
                        .clipShape(.rect(cornerRadius: 18, style: .continuous))
                        .shadow(color: Palette.sky.opacity(0.35), radius: 20, y: 10)
                    Text("17同游").font(.largeTitle.bold())
                    Text("一起规划，一起出发").font(.subheadline).foregroundStyle(.secondary)
                }
                .padding(.top, 70)

                VStack(spacing: 14) {
                    Picker("", selection: $registering.animation(.snappy)) {
                        Text("登录").tag(false)
                        Text("注册").tag(true)
                    }
                    .pickerStyle(.segmented)

                    field("用户名", text: $username, symbol: "person")
                        .textContentType(.username)
                        .focused($field, equals: .username)
                        .submitLabel(.next)
                        .onSubmit { field = .password }
                    secureField
                    if registering {
                        field("邀请码", text: $invite, symbol: "ticket")
                            .focused($field, equals: .invite)
                            .transition(.move(edge: .top).combined(with: .opacity))
                        Text("目前为邀请注册，可以向邀请你的朋友要邀请码。")
                            .font(.footnote).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    if let error {
                        Label(error, systemImage: "exclamationmark.circle")
                            .font(.footnote).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    Button(action: submit) {
                        Group {
                            if busy { ProgressView().tint(.white) } else { Text(registering ? "注册并登录" : "登录") }
                        }
                        .font(.headline)
                        .frame(maxWidth: .infinity, minHeight: 50)
                    }
                    .buttonStyle(.glassProminent)
                    .tint(Palette.sky)
                    .disabled(busy || username.isEmpty || password.isEmpty)
                    .padding(.top, 4)
                }
                .padding(22)
                .glassCard(cornerRadius: 30)
            }
            .padding(.horizontal, 20)
            .frame(maxWidth: 480)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .screenBackground()
    }

    private func field(_ title: String, text: Binding<String>, symbol: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol).foregroundStyle(.secondary).frame(width: 20)
            TextField(title, text: text).textInputAutocapitalization(.never).autocorrectionDisabled()
        }
        .padding(.horizontal, 16).frame(height: 50)
        .glassEffect(.regular, in: .capsule)
    }

    private var secureField: some View {
        HStack(spacing: 10) {
            Image(systemName: "lock").foregroundStyle(.secondary).frame(width: 20)
            SecureField("密码", text: $password)
                .textContentType(registering ? .newPassword : .password)
                .focused($field, equals: .password)
                .submitLabel(.go)
                .onSubmit(submit)
        }
        .padding(.horizontal, 16).frame(height: 50)
        .glassEffect(.regular, in: .capsule)
    }

    private func submit() {
        guard !busy, !username.isEmpty, !password.isEmpty else { return }
        busy = true
        error = nil
        Task {
            do {
                if registering {
                    try await session.register(username: username, password: password, invite: invite)
                } else {
                    try await session.login(username: username, password: password)
                }
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}
