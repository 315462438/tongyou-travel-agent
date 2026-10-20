import XCTest

final class LedgerLinkUITests: XCTestCase {
    func testColdLink() { verify(cold: true) }
    func testWarmLink() { verify(cold: false) }
    private func verify(cold: Bool) {
        continueAfterFailure = false
        let app = XCUIApplication()
        if cold { app.terminate() } else { app.launch() }
        print("TONGYOU_READY_FOR_URL")
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let open = springboard.buttons.matching(NSPredicate(format: "label IN %@", ["打开", "Open"])).firstMatch
        let notice = app.staticTexts["登录后继续查看账本邀请"]
        // iOS can remember the prior confirmation; both delivery paths are valid.
        for _ in 0..<50 {
            if notice.exists { break }
            if open.exists { open.tap(); break }
            Thread.sleep(forTimeInterval: 0.2)
        }
        XCTAssertTrue(notice.waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["取消邀请"].exists)
        app.buttons["取消邀请"].tap()
        XCTAssertFalse(app.staticTexts["登录后继续查看账本邀请"].exists)
    }
}
