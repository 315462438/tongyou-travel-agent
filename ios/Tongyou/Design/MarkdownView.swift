import SwiftUI

/// Block-level Markdown for travel guides: headings, lists, quotes, tables, code, images and rules.
/// Inline styling (bold, links, code) uses Foundation's Markdown parser.
enum MarkdownBlock: Equatable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case bullet([String])
    case numbered([String])
    case quote(String)
    case table(header: [String], rows: [[String]])
    case code(String)
    case image(url: String, alt: String)
    case rule

    static func parse(_ text: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        var lines = text.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")[...]
        func flush() {
            let joined = paragraph.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            if !joined.isEmpty { blocks.append(.paragraph(joined)) }
            paragraph = []
        }
        func cells(_ line: String) -> [String] {
            var row = line.trimmingCharacters(in: .whitespaces)
            if row.hasPrefix("|") { row.removeFirst() }
            if row.hasSuffix("|") { row.removeLast() }
            return row.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
        }
        func isDivider(_ line: String) -> Bool {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            return trimmed.contains("-") && trimmed.allSatisfy { "|-: ".contains($0) }
        }
        func listItem(_ line: String) -> (ordered: Bool, text: String)? {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            for marker in ["- ", "* ", "+ ", "• "] where trimmed.hasPrefix(marker) {
                return (false, String(trimmed.dropFirst(marker.count)))
            }
            if let dot = trimmed.firstIndex(where: { $0 == "." || $0 == "、" || $0 == ")" }),
               trimmed[..<dot].count <= 3, !trimmed[..<dot].isEmpty, trimmed[..<dot].allSatisfy(\.isNumber) {
                return (true, String(trimmed[trimmed.index(after: dot)...]).trimmingCharacters(in: .whitespaces))
            }
            return nil
        }

        while let line = lines.first {
            lines = lines.dropFirst()
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty { flush(); continue }
            if trimmed.hasPrefix("```") {
                flush()
                var code: [String] = []
                while let next = lines.first {
                    lines = lines.dropFirst()
                    if next.trimmingCharacters(in: .whitespaces).hasPrefix("```") { break }
                    code.append(next)
                }
                blocks.append(.code(code.joined(separator: "\n")))
                continue
            }
            if let hashes = trimmed.firstIndex(where: { $0 != "#" }), trimmed.hasPrefix("#"),
               trimmed[hashes] == " ", trimmed.distance(from: trimmed.startIndex, to: hashes) <= 6 {
                flush()
                blocks.append(.heading(level: trimmed.distance(from: trimmed.startIndex, to: hashes),
                                       text: String(trimmed[hashes...]).trimmingCharacters(in: .whitespaces)))
                continue
            }
            if ["---", "***", "___"].contains(trimmed) { flush(); blocks.append(.rule); continue }
            if trimmed.hasPrefix("!["), let close = trimmed.range(of: "]("), trimmed.hasSuffix(")") {
                flush()
                let alt = String(trimmed[trimmed.index(trimmed.startIndex, offsetBy: 2)..<close.lowerBound])
                let url = String(trimmed[close.upperBound..<trimmed.index(before: trimmed.endIndex)])
                blocks.append(.image(url: url.components(separatedBy: " ").first ?? url, alt: alt))
                continue
            }
            if trimmed.hasPrefix("|"), let next = lines.first, isDivider(next) {
                flush()
                lines = lines.dropFirst()
                var rows: [[String]] = []
                while let row = lines.first, row.trimmingCharacters(in: .whitespaces).hasPrefix("|") {
                    rows.append(cells(row))
                    lines = lines.dropFirst()
                }
                blocks.append(.table(header: cells(trimmed), rows: rows))
                continue
            }
            if trimmed.hasPrefix(">") {
                flush()
                var quote = [String(trimmed.dropFirst()).trimmingCharacters(in: .whitespaces)]
                while let next = lines.first, next.trimmingCharacters(in: .whitespaces).hasPrefix(">") {
                    quote.append(String(next.trimmingCharacters(in: .whitespaces).dropFirst()).trimmingCharacters(in: .whitespaces))
                    lines = lines.dropFirst()
                }
                blocks.append(.quote(quote.joined(separator: "\n")))
                continue
            }
            if let first = listItem(line) {
                flush()
                var items = [first.text]
                while let next = lines.first, let item = listItem(next), item.ordered == first.ordered {
                    items.append(item.text)
                    lines = lines.dropFirst()
                }
                blocks.append(first.ordered ? .numbered(items) : .bullet(items))
                continue
            }
            paragraph.append(line)
        }
        flush()
        return blocks
    }
}

struct InlineText: View {
    let source: String
    var body: some View {
        Text(Self.attributed(source))
    }
    static func attributed(_ source: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace,
                                                              failurePolicy: .returnPartiallyParsedIfPossible)
        return (try? AttributedString(markdown: source, options: options)) ?? AttributedString(source)
    }
}

struct MarkdownView: View {
    let blocks: [MarkdownBlock]
    init(_ text: String) { blocks = MarkdownBlock.parse(text) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Equatable rows: while text streams in, only the block still growing is rebuilt.
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                MarkdownBlockView(block: block).equatable()
            }
        }
        .textSelection(.enabled)
        .tint(Palette.sky)
    }
}

/// Reveals streamed text a few characters at a time. The backend arrives in 0.8 s polling chunks, and
/// showing each chunk at once reads as paragraphs popping in. Same pacing as the web's useTypewriter:
/// one character every 40 ms, faster as the backlog grows (up to 6, i.e. 150 characters a second) so it
/// never falls behind; text already there when the view appears, and the final version, show at once.
struct TypewriterMarkdown: View {
    let text: String
    let active: Bool
    @State private var target: String
    @State private var shown: Int

    init(_ text: String, active: Bool) {
        self.text = text
        self.active = active
        _target = State(initialValue: text)
        _shown = State(initialValue: text.count)
    }

    static let tick: Duration = .milliseconds(40)
    static func step(backlog: Int) -> Int {
        backlog > 400 ? 6 : backlog > 200 ? 4 : backlog > 100 ? 2 : 1
    }

    var body: some View {
        MarkdownView(shown >= target.count ? target : String(target.prefix(shown)))
            .onChange(of: text) { old, new in
                target = new
                // Content is append-only; a rewrite (or text arriving after the stream ended) snaps to full.
                if !active || !new.hasPrefix(old) { shown = new.count }
            }
            .onChange(of: active) { _, now in
                if !now { target = text; shown = text.count }
            }
            .task(id: active) {
                guard active else { return }
                while !Task.isCancelled {
                    try? await Task.sleep(for: Self.tick)
                    let backlog = target.count - shown
                    if backlog > 0 { shown += min(backlog, Self.step(backlog: backlog)) }
                }
            }
    }
}

private struct MarkdownBlockView: View, Equatable {
    @Environment(\.markdownExporting) private var exporting
    let block: MarkdownBlock

    static func == (a: Self, b: Self) -> Bool { a.block == b.block }

    var body: some View { view(for: block) }

    @ViewBuilder private func view(for block: MarkdownBlock) -> some View {
        switch block {
        case .heading(let level, let text):
            InlineText(source: text)
                .font(level == 1 ? .title2.bold() : level == 2 ? .title3.bold() : .headline)
                .padding(.top, level <= 2 ? 8 : 2)
        case .paragraph(let text):
            InlineText(source: text).font(.body).lineSpacing(4)
        case .bullet(let items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Circle().fill(Palette.sky.opacity(0.7)).frame(width: 5, height: 5).alignmentGuide(.firstTextBaseline) { $0.height + 1 }
                        InlineText(source: item).lineSpacing(3)
                    }
                }
            }
        case .numbered(let items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("\(index + 1).").monospacedDigit().foregroundStyle(Palette.sky).fontWeight(.semibold)
                        InlineText(source: item).lineSpacing(3)
                    }
                }
            }
        case .quote(let text):
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 2).fill(Palette.sky.opacity(0.5)).frame(width: 3)
                InlineText(source: text).foregroundStyle(.secondary)
            }
            .fixedSize(horizontal: false, vertical: true)
        case .table(let header, let rows) where exporting:
            // Off-screen renders cannot scroll: wrap cells to the page width instead.
            table(header, rows, cellWidth: nil)
                .background(Palette.sky.opacity(0.06), in: .rect(cornerRadius: 12))
        case .table(let header, let rows):
            ScrollView(.horizontal, showsIndicators: false) {
                table(header, rows, cellWidth: 220)
            }
            .glassCard(cornerRadius: 16)
        case .code(let code) where exporting:
            Text(code).font(.system(.footnote, design: .monospaced)).padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.gray.opacity(0.08), in: .rect(cornerRadius: 12))
        case .code(let code):
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code).font(.system(.footnote, design: .monospaced)).padding(12)
            }
            .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 12))
        case .image(let url, _) where exporting:
            // Off-screen renders cannot wait for downloads: use images the chat has already shown.
            if let image = ImageCache.url(for: url).flatMap({ ImageCache.shared.cached($0) }) {
                Image(uiImage: image).resizable().scaledToFill()
                    .frame(maxWidth: .infinity).frame(height: 200).clipShape(.rect(cornerRadius: 12))
            }
        case .image(let url, _):
            RemoteImage(path: url).frame(maxWidth: .infinity).frame(height: 200).clipShape(.rect(cornerRadius: 16))
        case .rule:
            Divider().padding(.vertical, 4)
        }
    }

    /// Rows of fixed-width columns. A `Grid` inside a horizontal scroll view measured rows at their
    /// single-line height and then wrapped the text, so long cells overlapped the rows below.
    private func table(_ header: [String], _ rows: [[String]], cellWidth: CGFloat?) -> some View {
        let widths = TableLayout.columnWidths(header: header, rows: rows,
                                              maxColumn: cellWidth ?? .infinity,
                                              available: cellWidth == nil ? GuideExporter.width - 48 - 28 : nil)
        func row(_ cells: [String], bold: Bool) -> some View {
            HStack(alignment: .top, spacing: TableLayout.spacing) {
                ForEach(widths.indices, id: \.self) { column in
                    InlineText(source: column < cells.count ? cells[column] : "")
                        .font(bold ? .subheadline.bold() : .subheadline)
                        .frame(width: widths[column], alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        return VStack(alignment: .leading, spacing: 8) {
            row(header, bold: true)
            Divider()
            ForEach(Array(rows.enumerated()), id: \.offset) { index, cells in
                if index > 0 { Divider().opacity(0.5) }
                row(cells, bold: false)
            }
        }
        .padding(14)
    }
}

/// Column widths from each column's longest single-line text, capped per column on screen and
/// squeezed to the page width (smallest columns keep their natural width) when exporting.
enum TableLayout {
    static let spacing: CGFloat = 14

    static func columnWidths(header: [String], rows: [[String]], maxColumn: CGFloat, available: CGFloat?) -> [CGFloat] {
        let body = UIFont.preferredFont(forTextStyle: .subheadline)
        let bold = UIFont.boldSystemFont(ofSize: body.pointSize)
        var natural = header.indices.map { column -> CGFloat in
            var width = measure(header[column], font: bold)
            for row in rows where column < row.count { width = max(width, measure(row[column], font: body)) }
            return min(max(ceil(width) + 2, 36), maxColumn)
        }
        guard let available else { return natural }
        var room = available - spacing * CGFloat(max(header.count - 1, 0))
        guard natural.reduce(0, +) > room else { return natural }
        // Water-fill: columns narrower than an equal share keep their width; the rest share what is left.
        var open = Set(natural.indices)
        while true {
            let share = room / CGFloat(max(open.count, 1))
            let fitting = open.filter { natural[$0] <= share }
            if fitting.isEmpty {
                for column in open { natural[column] = max(share, 36) }
                return natural
            }
            for column in fitting { room -= natural[column]; open.remove(column) }
            if open.isEmpty { return natural }
        }
    }

    private static func measure(_ markdown: String, font: UIFont) -> CGFloat {
        let plain = String(InlineText.attributed(markdown).characters)
        return (plain as NSString).size(withAttributes: [.font: font]).width
    }
}
