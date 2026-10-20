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
                TabView(selection: $router.tab) {
                    Tab("首页", systemImage: "sparkles", value: AppRouter.TabID.home) { HomeView() }
                    Tab("行程", systemImage: "map", value: AppRouter.TabID.trips) { TripsView() }
                    Tab("记账", systemImage: "creditcard", value: AppRouter.TabID.ledger) { LedgerView() }
                    Tab("历史", systemImage: "clock.arrow.circlepath", value: AppRouter.TabID.history) {
                        HistoryView().id(router.historyVersion)
                    }
                    Tab("同游圈", systemImage: "person.2", value: AppRouter.TabID.social) { SocialView() }
                }
                .tabBarMinimizeBehavior(.onScrollDown)
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.3), value: session.state)
        .task { await session.restore() }
        .onOpenURL { url in
            if router.ledgerLinks.receive(url) { router.tab = .ledger }
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
