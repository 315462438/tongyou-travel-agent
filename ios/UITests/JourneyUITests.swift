import XCTest

final class JourneyUITests: XCTestCase {
    func testNavigationAndAssistantDraft() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--journey-ui-test"]
        app.launch()
        XCTAssertTrue(app.buttons["journeyTab_旅行"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["journeyTab_记账"].exists)
        XCTAssertTrue(app.buttons["journeyTab_我的"].exists)
        XCTAssertEqual(app.tabBars.count, 0)
        app.buttons["journeyTab_记账"].tap()
        XCTAssertTrue(app.staticTexts["测试旅行账本"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.tabBars.count, 0)
        let ledger = XCTAttachment(screenshot: app.screenshot()); ledger.name = "ledger-single-dock"; ledger.lifetime = .keepAlways; add(ledger)
        app.buttons.containing(.staticText, identifier: "测试旅行账本").firstMatch.tap()
        XCTAssertTrue(app.staticTexts["累计支出 · 1 笔"].waitForExistence(timeout: 5), app.debugDescription)
        app.navigationBars["测试旅行账本"].buttons.firstMatch.tap()
        XCTAssertEqual(app.tabBars.count, 0)
        XCTAssertEqual(app.buttons.matching(identifier: "journeyTab_记账").count, 1)
        app.buttons["journeyTab_旅行"].tap()
        XCTAssertTrue(app.staticTexts["杭州的慢周末"].waitForExistence(timeout: 10))
        let home = XCTAttachment(screenshot: app.screenshot()); home.name = "journey-home"; home.lifetime = .keepAlways; add(home)
        app.buttons["openAI"].tap()
        XCTAssertTrue(app.buttons["找美食"].waitForExistence(timeout: 5))
        app.buttons["找美食"].tap()
        let field = app.textFields["assistantDraft"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        let draft = field.value as? String
        XCTAssertTrue(draft?.contains("当地") == true, "Draft: \(String(describing: draft))\n\(app.debugDescription)")
        app.buttons["closeAI"].tap()
        app.buttons["openAI"].tap()
        XCTAssertEqual(field.value as? String, draft)
        let ai = XCTAttachment(screenshot: app.screenshot()); ai.name = "journey-ai"; ai.lifetime = .keepAlways; add(ai)
        app.buttons["开始"].tap()
        XCTAssertTrue(app.buttons["closeAI"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["沿湖散步，轻松安排每一天。"].waitForExistence(timeout: 10))
        app.buttons["closeAI"].tap()
        app.buttons["openAI"].tap()
        XCTAssertTrue(app.staticTexts["沿湖散步，轻松安排每一天。"].exists)
        app.buttons["closeAI"].tap()
        app.buttons["journeyTab_我的"].tap()
        XCTAssertTrue(app.buttons["历史对话"].waitForExistence(timeout: 5))
        app.buttons["历史对话"].tap()
        XCTAssertTrue(app.staticTexts["杭州两天"].waitForExistence(timeout: 5))
        app.buttons["closeHistory"].tap()
        XCTAssertTrue(app.buttons["journeyTab_旅行"].isHittable)
    }
    func testTripMapAndTimelineTogether() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--journey-ui-test"]
        app.launch()
        let trip = app.staticTexts["杭州的慢周末"]
        XCTAssertTrue(trip.waitForExistence(timeout: 15))
        trip.tap()
        // MapKit exposes its accessibility element as a map on some OS versions.
        let mapElement = app.descendants(matching: .any)["tripRouteMap"].firstMatch
        XCTAssertTrue(mapElement.waitForExistence(timeout: 10))
        let first = app.buttons["tripStop_s1"]
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        XCTAssertTrue(first.isHittable)
        XCTAssertTrue(app.buttons["tripStop_s2"].isHittable)
        XCTAssertFalse(app.staticTexts["费用待补充"].exists)
        XCTAssertLessThan(mapElement.frame.minY, first.frame.minY - 80)
        first.tap()
        XCTAssertTrue(app.staticTexts["浙江省杭州市"].waitForExistence(timeout: 5))
        let detail = XCTAttachment(screenshot: app.screenshot()); detail.name = "place-detail"; detail.lifetime = .keepAlways; add(detail)
        app.buttons["closePlaceDetail"].tap()
        app.buttons["展开行程面板"].tap()
        XCTAssertTrue(app.buttons["收起行程面板"].waitForExistence(timeout: 5))
        app.buttons["收起行程面板"].tap()
        app.buttons["展开行程面板"].tap()
        XCTAssertTrue(app.buttons["编辑西湖"].isHittable)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "trip-map-timeline"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["tripDay_2"].tap()
        XCTAssertTrue(app.buttons["tripStop_s4"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tripStop_s1"].exists)
        app.buttons["tripDay_3"].tap()
        XCTAssertTrue(app.otherElements["tripRouteMapEmpty"].exists || app.descendants(matching: .any)["tripRouteMapEmpty"].firstMatch.exists)
        XCTAssertTrue(app.staticTexts["这一天还没有安排"].exists)
        XCTAssertTrue(app.buttons["添加地点"].isHittable)
        XCTAssertFalse(app.buttons["journeyTab_旅行"].exists)
    }

}
