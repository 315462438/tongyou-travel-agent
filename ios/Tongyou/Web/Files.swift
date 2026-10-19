import UIKit
import WebKit

/// Writes exported files to a fresh temporary folder so they can be handed to the share sheet
/// (save to Photos / Files, send to WeChat). Nothing is kept beyond the system's temp cleanup.
enum DownloadFile {
    static func freshURL(name: String) -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let safe = name.replacingOccurrences(of: "/", with: "_").trimmingCharacters(in: .whitespacesAndNewlines)
        return folder.appendingPathComponent(safe.isEmpty ? "download" : safe)
    }

    static func write(data: Data, name: String) -> URL? {
        let url = freshURL(name: name)
        return (try? data.write(to: url)) != nil ? url : nil
    }

    /// Decodes `data:<mime>;base64,<payload>` produced by FileReader.readAsDataURL.
    static func write(dataURL: String, name: String) -> URL? {
        guard let comma = dataURL.firstIndex(of: ","), dataURL[..<comma].hasSuffix(";base64"),
              let data = Data(base64Encoded: String(dataURL[dataURL.index(after: comma)...])) else { return nil }
        return write(data: data, name: name)
    }
}

enum PDFRenderer {
    /// A4 pages through the print formatter, so long guides are split into pages rather than one strip.
    @MainActor static func paginated(_ web: WKWebView) -> Data {
        let renderer = UIPrintPageRenderer()
        renderer.addPrintFormatter(web.viewPrintFormatter(), startingAtPageAt: 0)
        let paper = CGRect(x: 0, y: 0, width: 595.2, height: 841.8)
        renderer.setValue(paper, forKey: "paperRect")
        renderer.setValue(paper.insetBy(dx: 28, dy: 32), forKey: "printableRect")
        let data = NSMutableData()
        UIGraphicsBeginPDFContextToData(data, paper, nil)
        renderer.prepare(forDrawingPages: NSRange(location: 0, length: renderer.numberOfPages))
        for page in 0..<renderer.numberOfPages {
            UIGraphicsBeginPDFPage()
            renderer.drawPage(at: page, in: UIGraphicsGetPDFContextBounds())
        }
        UIGraphicsEndPDFContext()
        return data as Data
    }
}

/// Shows a page the site opened with window.open('') (the trip guide preview) with Close and Export PDF.
final class PopupController: UIViewController {
    private let webView: WKWebView
    private let onExport: (WKWebView) -> Void

    init(webView: WKWebView, onExport: @escaping (WKWebView) -> Void) {
        self.webView = webView
        self.onExport = onExport
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func loadView() { view = webView }

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "攻略预览"
        navigationItem.leftBarButtonItem = UIBarButtonItem(systemItem: .close, primaryAction: UIAction { [weak self] _ in
            self?.dismiss(animated: true)
        })
        navigationItem.rightBarButtonItem = UIBarButtonItem(title: "导出 PDF", image: UIImage(systemName: "square.and.arrow.up"),
                                                            primaryAction: UIAction { [weak self] _ in
            guard let self else { return }
            self.onExport(self.webView)
        })
    }
}
