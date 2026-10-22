import XCTest

final class TravelPetUITests: XCTestCase {
    private func launch(reset: Bool = true) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--journey-ui-test"] + (reset ? ["--pet-reset"] : [])
        app.launch()
        XCTAssertTrue(app.buttons["openAI"].waitForExistence(timeout: 15))
        return app
    }

    func testLongPressPreparationAndQuietCompanion() {
        let app = launch()
        app.buttons["openAI"].press(forDuration: 1)
        XCTAssertTrue(app.buttons["游游旅行工具"].waitForExistence(timeout: 5))
        app.buttons["游游旅行工具"].tap()
        XCTAssertTrue(app.buttons["petPat"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["assistantDraft"].isHittable)
        app.buttons["petPat"].tap()
        XCTAssertTrue(app.staticTexts["咕噜～这趟也一起走。"].exists)
        app.buttons["petPreparation"].tap()
        XCTAssertTrue(app.staticTexts["确认并填写出发日期"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["1 个地点还需要补充地图位置"].exists)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "pet-preparation"; shot.lifetime = .keepAlways; add(shot)
        app.swipeUp()
        let quiet = app.switches["petQuiet"]
        XCTAssertTrue(quiet.waitForExistence(timeout: 5))
        quiet.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertEqual(quiet.value as? String, "1")
        app.buttons["closePetTools"].tap()
        XCTAssertTrue(app.buttons["openAI"].isHittable)
        app.buttons["journeyTab_我的"].tap()
        app.buttons["petTools"].tap()
        XCTAssertEqual(app.switches["petQuiet"].value as? String, "1")
        app.buttons["closePetTools"].tap()
    }

    func testDraggingAndHidingPreserveAIEntry() {
        let app = launch()
        let pet = app.buttons["openAI"]
        let start = pet.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.07, dy: 0.89))
        start.press(forDuration: 0.1, thenDragTo: end)
        XCTAssertLessThan(pet.frame.midX, app.frame.midX)
        XCTAssertTrue(pet.isHittable)
        XCTAssertFalse(app.textFields["assistantDraft"].isHittable)
        pet.tap()
        XCTAssertTrue(app.textFields["assistantDraft"].waitForExistence(timeout: 5))
        app.buttons["closeAI"].tap()
        app.buttons["journeyTab_我的"].tap()
        app.buttons["petTools"].tap()
        let visible = app.switches["petVisible"]
        XCTAssertTrue(visible.waitForExistence(timeout: 5))
        visible.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertEqual(visible.value as? String, "0")
        app.buttons["closePetTools"].tap()
        app.terminate()
        app.launchArguments = ["--journey-ui-test"]
        app.launch()
        XCTAssertTrue(app.buttons["openAI"].waitForExistence(timeout: 10))
        app.buttons["journeyTab_我的"].tap()
        app.buttons["petTools"].tap()
        XCTAssertEqual(app.switches["petVisible"].value as? String, "0")
        app.buttons["closePetTools"].tap()
    }
}

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
        if app.buttons["Continue"].waitForExistence(timeout: 1) { app.buttons["Continue"].tap() }
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

final class ShareUITests: XCTestCase {
    private func launch(extra: [String] = []) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication(); app.launchArguments = ["--journey-ui-test", "--share-export-test"] + extra; app.launch()
        XCTAssertTrue(app.staticTexts["导出校验通过"].waitForExistence(timeout: 30), app.debugDescription)
        return app
    }
    func testRenderAndPreview() {
        let app = launch()
        app.buttons["预览简版"].tap()
        XCTAssertTrue(app.navigationBars["分享计划单"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["分享图片"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.images.containing(NSPredicate(format: "label CONTAINS %@", "合肥情侣自然风光2日游")).firstMatch.waitForExistence(timeout: 5))
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "share-plan-preview"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["closeGuidePreview"].tap()
        XCTAssertTrue(app.buttons["预览简版"].exists)
    }
    func testInviteSuccessAndFailure() {
        let app = launch(); app.buttons["邀请页"].tap()
        XCTAssertTrue(app.staticTexts["好风景，想和你一起。"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["copyTripInvite"].exists)
        let field = app.textFields["tripInviteUsername"]
        XCTAssertTrue(field.waitForExistence(timeout: 5)); field.tap(); field.typeText("missing")
        app.buttons["发送邀请"].tap()
        XCTAssertTrue(app.staticTexts["tripInviteError"].waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertEqual(field.value as? String, "missing")
        field.tap(); field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 7) + "friend")
        app.buttons["发送邀请"].tap()
        XCTAssertTrue(app.staticTexts["tripInviteSuccess"].waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertFalse((field.value as? String) == "friend")
        app.swipeDown()
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "invitation-panel"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["closeTripMembers"].tap()
        XCTAssertTrue(app.buttons["邀请页"].exists)
    }
    func testDarkReducedMotion() {
        let app = launch(extra: ["--share-dark", "--share-reduce-motion"])
        app.buttons["邀请页"].tap()
        XCTAssertTrue(app.buttons["copyTripInvite"].waitForExistence(timeout: 5))
        let invite = XCTAttachment(screenshot: app.screenshot()); invite.name = "invitation-dark-reduced"; invite.lifetime = .keepAlways; add(invite)
        app.buttons["closeTripMembers"].tap(); app.buttons["预览简版"].tap()
        XCTAssertTrue(app.buttons["分享图片"].waitForExistence(timeout: 5))
        let preview = XCTAttachment(screenshot: app.screenshot()); preview.name = "share-preview-dark"; preview.lifetime = .keepAlways; add(preview)
    }
}
