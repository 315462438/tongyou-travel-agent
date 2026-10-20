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

    var body: some View {
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
                        if router.tab != .home || !router.travelDetailOpen { JourneyDock() }
                    }
                    .allowsHitTesting(!router.aiOpen)
                    .accessibilityHidden(router.aiOpen)
                    AssistantView()
                        .opacity(router.aiOpen ? 1 : 0)
                        .allowsHitTesting(router.aiOpen)
                        .accessibilityHidden(!router.aiOpen)
                        .zIndex(router.aiOpen ? 2 : -1)
                }
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.3), value: session.state)
        .task { await session.restore() }
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
        HStack(spacing: 12) {
            HStack(spacing: 2) {
                item("旅行", icon: "map", tab: .home)
                item("记账", icon: "creditcard", tab: .ledger)
                item("我的", icon: "person", tab: .me)
            }
            .padding(5)
            .glassEffect(.regular, in: .capsule)
            Button { withAnimation(reduceMotion ? nil : .easeOut(duration: 0.22)) { router.aiOpen = true } } label: {
                Label("问 AI", systemImage: "sparkles").font(.subheadline.weight(.semibold))
                    .padding(.horizontal, 15).frame(height: 56)
            }
            .buttonStyle(.glassProminent).tint(Palette.sky)
            .accessibilityIdentifier("openAI")
        }
        .padding(.horizontal, 14).padding(.bottom, 4)
    }
    private func item(_ title: String, icon: String, tab: AppRouter.TabID) -> some View {
        Button {
            withAnimation(reduceMotion ? nil : .spring(response: 0.3, dampingFraction: 0.85)) { router.tab = tab }
        } label: {
            VStack(spacing: 3) { Image(systemName: icon).font(.system(size: 21)); Text(title).font(.caption2) }
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
