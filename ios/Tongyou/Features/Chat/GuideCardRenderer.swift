import UIKit
import CoreText

/// Fixed-size drawing has no SwiftUI layout, scroll containers, materials or async dependencies.
@MainActor
enum GuideCardRenderer {
    static let width: CGFloat = 560
    private static let ink = UIColor(red: 0.10, green: 0.14, blue: 0.20, alpha: 1)
    private static let blue = UIColor(red: 0.15, green: 0.36, blue: 0.78, alpha: 1)

    /// book=true：整份行程画成一张「旅行手册」长图（发给朋友只有一张）；否则按页切成卡片。
    static func images(_ summary: GuideShareSummary, book: Bool = false) -> [UIImage] {
        if book { return [image(summary, days: summary.days, page: 1, total: 1, book: true)] }
        let pages = summary.pages()
        return pages.enumerated().map { image(summary, days: $0.element, page: $0.offset + 1, total: pages.count) }
    }

    /// 长图像素上限，与网页一致：超过就降倍率，避免超大位图占满内存。
    static let maxPixelArea: CGFloat = 16_000_000

    private static func image(_ summary: GuideShareSummary, days: [GuideShareSummary.Day], page: Int, total: Int, book: Bool = false) -> UIImage {
        struct Label { var text: String; var rect: CGRect; var font: UIFont; var color: UIColor; var align: NSTextAlignment = .natural }
        var labels: [Label] = [], rules: [CGFloat] = [], bands: [CGRect] = []
        var y: CGFloat = 36
        func text(_ value: String, size: CGFloat, bold: Bool = false, x: CGFloat = 36, w: CGFloat = 488, color: UIColor = ink, gap: CGFloat = 0) {
            let font = bold ? UIFont.boldSystemFont(ofSize: size) : UIFont.systemFont(ofSize: size)
            let height = ceil((value as NSString).boundingRect(with: CGSize(width: w, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: [.font: font], context: nil).height)
            labels.append(Label(text: value, rect: CGRect(x: x, y: y, width: w, height: height + 3), font: font, color: color))
            y += height + gap
        }
        // A row with a truly right-aligned end; padding with spaces drifts with the font.
        func edges(_ left: String, _ right: String, size: CGFloat, bold: Bool = false, color: UIColor, gap: CGFloat) {
            let font = bold ? UIFont.boldSystemFont(ofSize: size) : UIFont.systemFont(ofSize: size)
            labels.append(Label(text: right, rect: CGRect(x: 36, y: y, width: 488, height: ceil(font.lineHeight) + 3), font: font, color: color, align: .right))
            text(left, size: size, bold: bold, color: color, gap: gap)
        }
        edges("17同游", book ? "TRAVEL HANDBOOK" : "TRAVEL NOTES", size: 12, bold: true, color: blue, gap: 38)
        text(summary.title, size: 30, bold: true, gap: 14)
        let count = summary.days.reduce(0) { $0 + $1.stops.count }
        text(summary.isItinerary ? "\(summary.days.count) 天计划 · \(count) 项安排" : "旅行笔记 · 随身简版", size: 15, color: .darkGray, gap: 26)
        rules.append(y); y += 28
        if book && summary.isItinerary && days.count > 1 {
            text("行程一览", size: 14, bold: true, color: blue, gap: 8)
            for (index, day) in days.enumerated() { text(String(format: "%02d  ", index + 1) + day.title, size: 15, color: .darkGray, gap: 4) }
            y += 18; rules.append(y); y += 28
        }
        for day in days {
            if book {
                let top = y - 10
                text(day.title, size: 21, bold: true, x: 48, w: 464)
                bands.append(CGRect(x: 36, y: top, width: 488, height: y - top + 8)); y += 22
            } else { text(day.title, size: 21, bold: true, gap: 19) }
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
        text("简版计划 · 详细说明请查看完整攻略", size: 12, color: .darkGray, gap: 8)
        edges("17tongyou.com", book ? "旅行手册" : "\(page) / \(total)", size: 12, color: .darkGray, gap: 30)
        let height = max(y, 640)
        let format = UIGraphicsImageRendererFormat(); format.scale = min(2, sqrt(maxPixelArea / (width * height))); format.opaque = true
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
            for band in bands {
                blue.withAlphaComponent(0.07).setFill(); UIBezierPath(roundedRect: band, cornerRadius: 10).fill()
                blue.setFill(); UIBezierPath(roundedRect: CGRect(x: band.minX, y: band.minY + 8, width: 4, height: band.height - 16), cornerRadius: 2).fill()
            }
            for label in labels {
                let style = NSMutableParagraphStyle(); style.alignment = label.align
                (label.text as NSString).draw(in: label.rect, withAttributes: [.font: label.font, .foregroundColor: label.color, .paragraphStyle: style])
            }
            context.setStrokeColor(ink.withAlphaComponent(0.25).cgColor); context.setLineWidth(1)
            context.setLineDash(phase: 0, lengths: [2, 4])
            for rule in rules { context.move(to: CGPoint(x: 36, y: rule)); context.addLine(to: CGPoint(x: 524, y: rule)); context.strokePath() }
        }
    }
}
