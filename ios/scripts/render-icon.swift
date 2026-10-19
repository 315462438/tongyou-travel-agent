import AppKit
// Redraws frontend/public/favicon.svg (64-unit grid) as a full-bleed 1024 px app icon.
// iOS applies its own corner mask, so the rounded rect of the favicon becomes a square.
let size = 1024, s = CGFloat(size) / 64
let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
ctx.translateBy(x: 0, y: CGFloat(size)); ctx.scaleBy(x: s, y: -s)   // SVG coordinates: y grows downwards
ctx.setFillColor(CGColor(red: 0x25/255, green: 0x63/255, blue: 0xEB/255, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: 64, height: 64))
let paper = CGColor(red: 1, green: 0xFE/255, blue: 0xFB/255, alpha: 1)
ctx.setFillColor(paper); ctx.fillEllipse(in: CGRect(x: 16-4.5, y: 43-4.5, width: 9, height: 9))
ctx.setStrokeColor(paper); ctx.setLineWidth(4.2); ctx.setLineCap(.round); ctx.setLineJoin(.round)
ctx.move(to: CGPoint(x: 20.5, y: 41.8))
ctx.addCurve(to: CGPoint(x: 39.5, y: 32.6), control1: CGPoint(x: 26.2, y: 31.3), control2: CGPoint(x: 32.8, y: 44.2))
ctx.addCurve(to: CGPoint(x: 51.3, y: 23.1), control1: CGPoint(x: 43.0, y: 26.5), control2: CGPoint(x: 46.7, y: 23.9))
ctx.strokePath()
ctx.move(to: CGPoint(x: 43.5, y: 17.1)); ctx.addLine(to: CGPoint(x: 53.7, y: 21.8)); ctx.addLine(to: CGPoint(x: 46.6, y: 30.6))
ctx.strokePath()
ctx.setStrokeColor(paper.copy(alpha: 0.3)!); ctx.setLineWidth(2); ctx.strokeEllipse(in: CGRect(x: 8, y: 35, width: 16, height: 16))
// App Store icons must be opaque; noneSkipLast keeps the PNG free of an alpha channel.
try! NSBitmapImageRep(cgImage: ctx.makeImage()!).representation(using: .png, properties: [:])!
    .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
