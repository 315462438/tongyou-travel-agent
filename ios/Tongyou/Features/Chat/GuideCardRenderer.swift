import UIKit
import CoreText

/// Fixed-size drawing has no SwiftUI layout, scroll containers, materials or async dependencies.
@MainActor
enum GuideCardRenderer {
    static let width: CGFloat = 560
    private static let ink = UIColor(red: 0.10, green: 0.14, blue: 0.20, alpha: 1)
    private static let blue = UIColor(red: 0.15, green: 0.36, blue: 0.78, alpha: 1)

    static func images(_ summary: GuideShareSummary) -> [UIImage] {
        let pages = summary.pages()
        return pages.enumerated().map { image(summary, days: $0.element, page: $0.offset + 1, total: pages.count) }
    }

    private static func image(_ summary: GuideShareSummary, days: [GuideShareSummary.Day], page: Int, total: Int) -> UIImage {
        struct Label { var text: String; var rect: CGRect; var font: UIFont; var color: UIColor }
        var labels: [Label] = [], rules: [CGFloat] = []
        var y: CGFloat = 36
        func text(_ value: String, size: CGFloat, bold: Bool = false, x: CGFloat = 36, w: CGFloat = 488, color: UIColor = ink, gap: CGFloat = 0) {
            let font = bold ? UIFont.boldSystemFont(ofSize: size) : UIFont.systemFont(ofSize: size)
            let height = ceil((value as NSString).boundingRect(with: CGSize(width: w, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: [.font: font], context: nil).height)
            labels.append(Label(text: value, rect: CGRect(x: x, y: y, width: w, height: height + 3), font: font, color: color))
            y += height + gap
        }
        text("17同游                                     TRAVEL NOTES", size: 12, bold: true, color: blue, gap: 38)
        text(summary.title, size: 30, bold: true, gap: 14)
        let count = summary.days.reduce(0) { $0 + $1.stops.count }
        text(summary.isItinerary ? "\(summary.days.count) 天计划 · \(count) 项安排" : "旅行笔记 · 随身简版", size: 15, color: .darkGray, gap: 26)
        rules.append(y); y += 28
        for day in days {
            text(day.title, size: 21, bold: true, gap: 19)
            if day.stops.isEmpty { text("这一天留给自由安排", size: 18, color: .darkGray, gap: 12) }
            for stop in day.stops {
                let rowY = y
                text(stop.name, size: 21, x: 36, w: 350, gap: 16)
                let endY = y
                if !stop.time.isEmpty {
                    y = rowY + 3
                    text(stop.time, size: 14, x: 402, w: 122, color: .darkGray)
                    y = max(endY, y + 16)
                }
            }
            y += 8; rules.append(y); y += 26
        }
        text("一起规划，一起出发", size: 15, bold: true, color: blue, gap: 8)
        text("简版计划 · 详细说明请查看完整攻略 / PDF", size: 12, color: .darkGray, gap: 8)
        text("17tongyou.com                                      \(page) / \(total)", size: 12, color: .darkGray, gap: 30)
        let height = max(y, 640)
        let format = UIGraphicsImageRendererFormat(); format.scale = 2; format.opaque = true
        return UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format).image { result in
            let context = result.cgContext
            UIColor.white.setFill(); context.fill(CGRect(x: 0, y: 0, width: width, height: height))
            let colors = [UIColor(red: 0.88, green: 0.95, blue: 0.98, alpha: 1).cgColor, UIColor.white.cgColor] as CFArray
            if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 1]) {
                context.drawLinearGradient(gradient, start: .zero, end: CGPoint(x: width * 0.5, y: 600), options: [.drawsAfterEndLocation])
            }
            // A quiet route motif, drawn with native paths and kept behind the text.
            context.setStrokeColor(blue.withAlphaComponent(0.05).cgColor); context.setLineWidth(20)
            context.addEllipse(in: CGRect(x: 280, y: 48, width: 350, height: 260)); context.strokePath()
            for label in labels {
                (label.text as NSString).draw(in: label.rect, withAttributes: [.font: label.font, .foregroundColor: label.color])
            }
            context.setStrokeColor(ink.withAlphaComponent(0.25).cgColor); context.setLineWidth(1)
            context.setLineDash(phase: 0, lengths: [2, 4])
            for rule in rules { context.move(to: CGPoint(x: 36, y: rule)); context.addLine(to: CGPoint(x: 524, y: rule)); context.strokePath() }
        }
    }

    /// Full text PDF: real A4 pages; table cells become labelled rows rather than narrow columns.
    static func pdf(title: String, markdown: String, url: URL) -> Bool {
        let body = NSMutableAttributedString(string: "")
        func append(_ value: String, size: CGFloat = 12, bold: Bool = false) {
            let style = NSMutableParagraphStyle(); style.lineSpacing = 4; style.paragraphSpacing = 12
            body.append(NSAttributedString(string: value + "\n", attributes: [.font: bold ? UIFont.boldSystemFont(ofSize: size) : UIFont.systemFont(ofSize: size), .foregroundColor: ink, .paragraphStyle: style]))
        }
        append(title, size: 24, bold: true)
        for block in MarkdownBlock.parse(markdown) {
            switch block {
            case .heading(let level, let value): append(GuideShareSummary.plain(value), size: level <= 2 ? 18 : 15, bold: true)
            case .paragraph(let value), .quote(let value), .code(let value): append(GuideShareSummary.plain(value))
            case .bullet(let values): for value in values { append("• " + GuideShareSummary.plain(value)) }
            case .numbered(let values): for (i, value) in values.enumerated() { append("\(i + 1). " + GuideShareSummary.plain(value)) }
            case .table(let header, let rows):
                for row in rows { append(row.enumerated().map { "\($0.offset < header.count ? GuideShareSummary.plain(header[$0.offset]) : "补充")：\(GuideShareSummary.plain($0.element))" }.joined(separator: "\n")) }
            case .image(_, let alt): if !alt.isEmpty { append("[配图] " + GuideShareSummary.plain(alt), size: 10) }
            case .rule: append("────────────────────────", size: 10)
            }
        }
        let framesetter = CTFramesetterCreateWithAttributedString(body)
        let size = CGSize(width: 595, height: 842)
        var offset = 0, page = 0, completed = false
        do {
            try UIGraphicsPDFRenderer(bounds: CGRect(origin: .zero, size: size)).writePDF(to: url) { context in
                while offset < body.length {
                    context.beginPage(); page += 1
                    let cg = context.cgContext
                    cg.saveGState(); cg.translateBy(x: 0, y: size.height); cg.scaleBy(x: 1, y: -1)
                    let frame = CTFramesetterCreateFrame(framesetter, CFRange(location: offset, length: 0), CGPath(rect: CGRect(x: 42, y: 58, width: 511, height: 742), transform: nil), nil)
                    CTFrameDraw(frame, cg); cg.restoreGState()
                    let range = CTFrameGetVisibleStringRange(frame)
                    guard range.length > 0 else { return }
                    offset += range.length
                    ("17同游 · 完整攻略（文字版）  |  \(page)" as NSString).draw(at: CGPoint(x: 42, y: 814), withAttributes: [.font: UIFont.systemFont(ofSize: 9), .foregroundColor: UIColor.darkGray])
                }
                completed = true
            }
        } catch { return false }
        return completed
    }
}
