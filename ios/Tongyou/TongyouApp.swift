import SwiftUI

@main
struct TongyouApp: App {
    @State private var session = AppSession()
    @State private var router = AppRouter()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .environment(router)
                .tint(Palette.sky)
        }
    }
}

struct RootView: View {
    @Environment(AppSession.self) private var session
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var petMotion: Bool { !reduceMotion && !router.petPreferences.quiet }

    var body: some View {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--share-export-test") {
            ShareExportTestView()
                .preferredColorScheme(ProcessInfo.processInfo.arguments.contains("--share-dark") ? .dark : .light)
        }
        else { normalBody }
        #else
        normalBody
        #endif
    }

    @ViewBuilder private var normalBody: some View {
        @Bindable var router = router
        Group {
            switch session.state {
            case .checking:
                LaunchView()
            case .signedOut:
                LoginView().transition(.opacity)
            case .signedIn:
                ZStack {
                    ZStack {
                        HomeView().opacity(router.tab == .home ? 1 : 0)
                            .allowsHitTesting(router.tab == .home).accessibilityHidden(router.tab != .home)
                            .zIndex(router.tab == .home ? 1 : 0)
                        LedgerView().opacity(router.tab == .ledger ? 1 : 0)
                            .allowsHitTesting(router.tab == .ledger).accessibilityHidden(router.tab != .ledger)
                            .zIndex(router.tab == .ledger ? 1 : 0)
                        MeView(isRoot: true).opacity(router.tab == .me ? 1 : 0)
                            .allowsHitTesting(router.tab == .me).accessibilityHidden(router.tab != .me)
                            .zIndex(router.tab == .me ? 1 : 0)
                    }
                    .safeAreaInset(edge: .bottom) {
                        if !router.keyboardOpen && (router.tab != .home || !router.travelDetailOpen) { JourneyDock() }
                    }
                    .allowsHitTesting(!router.aiOpen)
                    .accessibilityHidden(router.aiOpen)
                    AssistantView()
                        .mask {
                            GeometryReader { geo in
                                let frame = geo.frame(in: .global), dock = router.petDockFrame
                                PetRevealShape(progress: router.aiOpen ? 1 : 0,
                                               origin: dock == .zero ? CGPoint(x: frame.width / 2, y: frame.height) : CGPoint(x: dock.midX - frame.minX, y: dock.minY + 40 - frame.minY))
                            }.ignoresSafeArea()
                        }
                        .animation(petMotion ? .spring(duration: 0.5, bounce: 0.08) : nil, value: router.aiOpen)
                        .opacity(router.aiOpen ? 1 : 0)
                        .allowsHitTesting(router.aiOpen)
                        .accessibilityHidden(!router.aiOpen)
                        .zIndex(router.aiOpen ? 2 : -1)
                    PetFlightOverlay().zIndex(3)
                }
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.3), value: session.state)
        .task { await session.restore() }
        .onChange(of: session.account?.username, initial: true) { _, username in router.configurePet(username: username) }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in router.keyboardOpen = true }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in router.keyboardOpen = false }
        .onChange(of: router.aiOpen) { _, open in
            if !open {
                UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                router.keyboardOpen = false
            }
        }
        .sheet(isPresented: $router.petToolsOpen) { PetToolsView() }
        .onOpenURL { url in
            if router.ledgerLinks.receive(url) { router.aiOpen = false; router.tab = .ledger }
        }
        .safeAreaInset(edge: .top) {
            if session.state == .signedOut, router.ledgerLinks.pending != nil {
                HStack {
                    Text("登录后继续查看账本邀请").font(.subheadline)
                    Spacer()
                    Button("取消邀请") { router.ledgerLinks.pending = nil }
                }.padding().background(.regularMaterial)
            }
        }
        .sheet(item: Binding(get: { session.state == .signedIn ? router.ledgerLinks.pending : nil }, set: { value in
            if session.state == .signedIn { router.ledgerLinks.pending = value }
        })) { invite in
            LedgerJoinEditor(initialToken: invite.token) { id in
                router.tab = .ledger
                router.openLedgerID = id
                router.ledgerLinks.pending = nil
            }.id(invite.id)
        }
    }
}

struct LaunchView: View {
    var body: some View {
        VStack(spacing: 18) {
            Image("LaunchMark").resizable().frame(width: 84, height: 84)
                .clipShape(.rect(cornerRadius: 19, style: .continuous))
                .shadow(color: Palette.sky.opacity(0.3), radius: 18, y: 8)
            Text("17同游").font(.title2.weight(.semibold))
            ProgressView().padding(.top, 4)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .screenBackground()
    }
}


struct JourneyDock: View {
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var selection
    var body: some View {
        HStack(alignment: .bottom, spacing: 12) {
            if router.petPreferences.side == "left" { PetCompanionButton() }
            HStack(spacing: 2) {
                item("旅行", icon: "map", tab: .home)
                item("记账", icon: "creditcard", tab: .ledger)
                item("我的", icon: "person", tab: .me)
            }
            .padding(5)
            .glassEffect(.regular, in: .capsule)
            if router.petPreferences.side != "left" { PetCompanionButton() }
        }
        .padding(.horizontal, 14).padding(.bottom, 4)
        .sensoryFeedback(.selection, trigger: router.tab)
        .sensoryFeedback(.impact(weight: .light), trigger: router.aiOpen) { _, open in open }
    }
    private func item(_ title: String, icon: String, tab: AppRouter.TabID) -> some View {
        Button {
            withAnimation(reduceMotion ? nil : .spring(response: 0.3, dampingFraction: 0.85)) { router.tab = tab }
        } label: {
            VStack(spacing: 3) {
                Image(systemName: router.tab == tab ? icon + ".fill" : icon).font(.system(size: 21))
                    .contentTransition(reduceMotion ? .identity : .symbolEffect(.replace))
                    .symbolEffect(.bounce, options: .speed(1.4), value: reduceMotion ? false : router.tab == tab)
                Text(title).font(.caption2)
            }
                .frame(maxWidth: .infinity).frame(height: 50).contentShape(Capsule())
                .foregroundStyle(router.tab == tab ? Palette.sky : .secondary)
                .background {
                    if router.tab == tab { Capsule().fill(Palette.sky.opacity(0.12)).matchedGeometryEffect(id: "selection", in: selection) }
                }
        }
        .buttonStyle(.plain).accessibilityAddTraits(router.tab == tab ? .isSelected : [])
        .accessibilityIdentifier("journeyTab_" + title)
    }
}
