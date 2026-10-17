import XCTest

/// Screen tour helper (twbuild) — the generated `TwScreenTour` walks the app with these steps in one launch.
/// Node ids come from the layout trees (`n.<screen>.…`, T1); screenshots are attachments named `tw-<screen>`.
@MainActor
final class TwTour {
    let app = XCUIApplication()
    private let test: XCTestCase
    private var at = "launch"

    init(_ test: XCTestCase) { self.test = test }

    func launch() { app.launch() }

    /// Fresh process, same install (state such as a finished first-run gate stays).
    func relaunch() {
        app.terminate()
        app.launch()
    }

    /// The node itself, or its first descendant: SwiftUI drops a container's identifier when every child has its own.
    func find(_ id: String, timeout: TimeInterval = 10) -> XCUIElement? {
        let q = app.descendants(matching: .any)
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            let exact = q.matching(identifier: id).firstMatch
            if exact.exists { return exact }
            let child = q.matching(NSPredicate(format: "identifier BEGINSWITH %@", id + ".")).firstMatch
            if child.exists { return child }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < deadline
        return nil
    }

    /// Taps the first of `ids` that is on screen (a list may be empty, so the tree's alternatives come along).
    /// Waits until it is hittable — a screen lower in the navigation stack keeps its ids in the tree.
    func tap(_ ids: [String], _ via: String) {
        guard let el = ids.lazy.compactMap({ self.find($0, timeout: ids.count > 1 ? 3 : 10) }).first else {
            return fail("tap target missing \(ids.joined(separator: " | ")) (\(via)) on \(at)")
        }
        let deadline = Date().addingTimeInterval(5)
        while !el.isHittable, Date() < deadline { Thread.sleep(forTimeInterval: 0.25) }
        el.tap()
    }

    func expect(_ screen: String) {
        guard find("n." + screen) != nil else { return fail("screen not reached \(screen) (from \(at))") }
        at = screen
    }

    /// Waits until the screen is gone (sheet closed, screen popped).
    func gone(_ screen: String, timeout: TimeInterval = 8) {
        let deadline = Date().addingTimeInterval(timeout)
        while find("n." + screen, timeout: 0) != nil {
            if Date() > deadline { return fail("screen did not close \(screen)") }
            Thread.sleep(forTimeInterval: 0.25)
        }
    }

    func shot(_ screen: String) {
        expect(screen)
        Thread.sleep(forTimeInterval: 1.0)          // let sheets and transitions settle
        attach("tw-" + screen)
    }

    private func attach(_ name: String) {
        let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        test.add(a)
    }

    private func fail(_ message: String) {
        attach("tw-fail-" + at)
        XCTFail("tour: " + message)
    }
}
