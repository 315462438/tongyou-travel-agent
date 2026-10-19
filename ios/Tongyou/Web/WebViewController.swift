import SafariServices
import SwiftUI
import UIKit
import WebKit

/// Presents the web app for features that are not native yet, signed in with the native session.
@MainActor
enum WebSheet {
    static func present(path: String) {
        guard let url = URL(string: path, relativeTo: API.origin)?.absoluteURL,
              let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              var top = scene.keyWindow?.rootViewController else { return }
        while let presented = top.presentedViewController { top = presented }
        let navigation = UINavigationController(rootViewController: WebViewController(url: url))
        navigation.modalPresentationStyle = .fullScreen
        top.present(navigation, animated: true)
    }
}

/// WKScriptMessageHandler is retained by the content controller; this breaks the cycle.
private final class WeakHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(controller, didReceive: message)
    }
}

final class WebViewController: UIViewController, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    private let startURL: URL
    private var webView: WKWebView!
    private let errorView = UIHostingController(rootView: AnyView(EmptyView()))
    private var downloads: [ObjectIdentifier: URL] = [:]

    init(url: URL) {
        startURL = url
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()   // keeps the login token in localStorage across launches
        config.allowsInlineMediaPlayback = true
        config.applicationNameForUserAgent = "Mobile/15E148 TongyouApp/1.0"
        let content = config.userContentController
        content.addUserScript(WKUserScript(source: WebBridge.source(token: API.shared.token), injectionTime: .atDocumentStart, forMainFrameOnly: false))
        content.add(WeakHandler(self), name: WebBridge.handler)

        webView = makeWebView(config)
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        webView.load(URLRequest(url: startURL))
        navigationItem.title = "网页版"
        navigationItem.leftBarButtonItem = UIBarButtonItem(systemItem: .close, primaryAction: UIAction { [weak self] _ in
            self?.dismiss(animated: true)
        })
        navigationItem.rightBarButtonItem = UIBarButtonItem(image: UIImage(systemName: "arrow.clockwise"), primaryAction: UIAction { [weak self] _ in
            self?.webView.reload()
        })
    }

    private func makeWebView(_ config: WKWebViewConfiguration) -> WKWebView {
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        #if DEBUG
        web.isInspectable = true
        #endif
        return web
    }

    // MARK: Errors

    private func showError(_ error: Error) {
        let nsError = error as NSError
        // Cancelled loads and policy-cancelled navigations (downloads, external links) are not failures.
        if nsError.code == NSURLErrorCancelled || (nsError.domain == "WebKitErrorDomain" && nsError.code == 102) { return }
        errorView.rootView = AnyView(OfflineView(message: nsError.localizedDescription) { [weak self] in self?.retry() })
        guard errorView.parent == nil else { return }
        addChild(errorView)
        errorView.view.frame = view.bounds
        errorView.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(errorView.view)
        errorView.didMove(toParent: self)
    }

    private func retry() {
        hideError()
        if webView.url == nil { webView.load(URLRequest(url: startURL)) } else { webView.reload() }
    }

    private func hideError() {
        guard errorView.parent != nil else { return }
        errorView.willMove(toParent: nil)
        errorView.view.removeFromSuperview()
        errorView.removeFromParent()
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 preferences: WKWebpagePreferences) async -> (WKNavigationActionPolicy, WKWebpagePreferences) {
        if action.shouldPerformDownload { return (.download, preferences) }
        guard let url = action.request.url, let scheme = url.scheme?.lowercased() else { return (.allow, preferences) }
        if !["http", "https", "about", "blob", "data"].contains(scheme) {
            // Map apps (iosamap://, baidumap://), tel:, mailto: and similar.
            await UIApplication.shared.open(url)
            return (.cancel, preferences)
        }
        if action.targetFrame?.isMainFrame == true, action.navigationType == .linkActivated, isExternal(url) {
            openExternally(url)
            return (.cancel, preferences)
        }
        return (.allow, preferences)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse) async -> WKNavigationResponsePolicy {
        response.canShowMIMEType ? .allow : .download
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { hideError() }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if webView === self.webView { showError(error) }
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if webView === self.webView { showError(error) }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

    private func isExternal(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        return !(host == WebBridge.host || host.hasSuffix("." + WebBridge.host))
    }

    private func openExternally(_ url: URL) {
        if url.host?.lowercased() == "maps.apple.com" {
            UIApplication.shared.open(url)
            return
        }
        let safari = SFSafariViewController(url: url)
        safari.preferredControlTintColor = UIColor(named: "AccentColor")
        topController.present(safari, animated: true)
    }

    // MARK: WKUIDelegate

    func webView(_ webView: WKWebView, createWebViewWith config: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, url.scheme?.hasPrefix("http") == true {
            if isExternal(url) { openExternally(url) } else { self.webView.load(action.request) }
            return nil
        }
        // window.open('') followed by document.write: the PDF/print preview of a trip guide.
        let popup = makeWebView(config)
        let controller = PopupController(webView: popup) { [weak self] web in self?.exportPDF(from: web) }
        let navigation = UINavigationController(rootViewController: controller)
        navigation.modalPresentationStyle = .pageSheet
        topController.present(navigation, animated: true)
        return popup
    }

    func webViewDidClose(_ webView: WKWebView) {
        if webView !== self.webView { webView.window?.rootViewController?.presentedViewController?.dismiss(animated: true) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo) async {
        await withCheckedContinuation { done in
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "好", style: .default) { _ in done.resume() })
            topController.present(alert, animated: true)
        }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo) async -> Bool {
        await withCheckedContinuation { done in
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in done.resume(returning: false) })
            alert.addAction(UIAlertAction(title: "确定", style: .default) { _ in done.resume(returning: true) })
            topController.present(alert, animated: true)
        }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo) async -> String? {
        await withCheckedContinuation { done in
            let alert = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
            alert.addTextField { $0.text = defaultText }
            alert.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in done.resume(returning: nil) })
            alert.addAction(UIAlertAction(title: "确定", style: .default) { [weak alert] _ in done.resume(returning: alert?.textFields?.first?.text ?? "") })
            topController.present(alert, animated: true)
        }
    }

    // MARK: Bridge messages

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "download":
            guard let data = body["data"] as? String, let file = DownloadFile.write(dataURL: data, name: body["name"] as? String ?? "download") else {
                showMessage("文件保存失败，请重试")
                return
            }
            share([file])
        case "downloadError":
            showMessage("文件保存失败，请重试")
        case "print":
            if let web = message.webView { exportPDF(from: web) }
        default:
            break
        }
    }

    // MARK: Files

    private func exportPDF(from web: WKWebView) {
        let title = (web.title?.isEmpty == false ? web.title! : "旅行攻略")
        guard let file = DownloadFile.write(data: PDFRenderer.paginated(web), name: title + ".pdf") else {
            showMessage("PDF 生成失败，请重试")
            return
        }
        share([file])
    }

    private func share(_ items: [Any]) {
        let sheet = UIActivityViewController(activityItems: items, applicationActivities: nil)
        sheet.popoverPresentationController?.sourceView = view
        topController.present(sheet, animated: true)
    }

    private func showMessage(_ text: String) {
        let alert = UIAlertController(title: nil, message: text, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        topController.present(alert, animated: true)
    }

    private var topController: UIViewController {
        var top: UIViewController = self
        while let presented = top.presentedViewController, !presented.isBeingDismissed { top = presented }
        return top
    }

    // MARK: WKDownloadDelegate

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String) async -> URL? {
        let url = DownloadFile.freshURL(name: suggestedFilename)
        downloads[ObjectIdentifier(download)] = url
        return url
    }

    func downloadDidFinish(_ download: WKDownload) {
        if let url = downloads.removeValue(forKey: ObjectIdentifier(download)) { share([url]) }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
        showMessage("下载失败：\(error.localizedDescription)")
    }
}

struct OfflineView: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "wifi.exclamationmark").font(.system(size: 40, weight: .light)).foregroundStyle(.secondary)
            Text("连接不上 17同游").font(.title3.weight(.semibold))
            Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button("重新加载", action: retry)
                .font(.body.weight(.semibold))
                .padding(.horizontal, 26).padding(.vertical, 12)
                .glassPill()
                .padding(.top, 8)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color("LaunchBackground").ignoresSafeArea())
    }
}
