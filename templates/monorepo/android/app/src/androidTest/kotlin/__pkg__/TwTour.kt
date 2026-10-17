package {{id}}

import android.graphics.Bitmap
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.AndroidComposeTestRule
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.io.FileOutputStream

/**
 * Screen tour helper (twbuild) — the generated `TwScreenTour` walks the app with these steps in one launch.
 * Node ids come from the layout trees (`n.<screen>.…`, T1, testTag); screenshots go to files/twbuild-tour/<screen>.png.
 */
class TwTour(private val rule: AndroidComposeTestRule<ActivityScenarioRule<MainActivity>, MainActivity>) {
    private var at = "launch"
    private val dir = File(InstrumentationRegistry.getInstrumentation().targetContext.filesDir, "twbuild-tour").apply {
        deleteRecursively()
        mkdirs()
    }

    /** The node itself, or its first descendant (node ids are path-based). */
    private fun tagged(id: String) = SemanticsMatcher("tag $id") { n ->
        n.config.getOrNull(SemanticsProperties.TestTag)?.let { it == id || it.startsWith("$id.") } == true
    }

    private fun exists(id: String) = rule.onAllNodes(tagged(id), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()

    private fun waitFor(timeoutMs: Long, cond: () -> Boolean): Boolean =
        try {
            rule.waitUntil(timeoutMs) { cond() }
            true
        } catch (e: Throwable) {
            false
        }

    /** Clicks the first of [ids] that is on screen (a list may be empty, so the tree's alternatives come along). */
    fun tap(ids: List<String>, via: String) {
        val id = ids.firstOrNull { waitFor(if (ids.size > 1) 3_000 else 10_000) { exists(it) } }
            ?: fail("tap target missing ${ids.joinToString(" | ")} ($via) on $at")
        val exact = rule.onAllNodes(SemanticsMatcher.expectValue(SemanticsProperties.TestTag, id), useUnmergedTree = true)
        (if (exact.fetchSemanticsNodes().isNotEmpty()) exact else rule.onAllNodes(tagged(id), useUnmergedTree = true)).onFirst().performClick()
    }

    fun expect(screen: String) {
        if (!waitFor(10_000) { exists("n.$screen") }) fail("screen not reached $screen (from $at)")
        at = screen
    }

    /** Waits until the screen is gone (sheet closed, screen popped). */
    fun gone(screen: String) {
        if (!waitFor(8_000) { !exists("n.$screen") }) fail("screen did not close $screen")
    }

    /** System back — used where the tree has no close control. */
    fun back() {
        rule.activityRule.scenario.onActivity { it.onBackPressedDispatcher.onBackPressed() }
    }

    fun shot(screen: String) {
        expect(screen)
        // Compose animations run on the test clock — Thread.sleep alone freezes a sheet or crossfade halfway. Advance it, then let the frame draw.
        rule.mainClock.advanceTimeBy(1_500)
        rule.waitForIdle()
        Thread.sleep(300)
        save(screen)
    }

    /** Whole screen through UiAutomation — sheets and dialogs live in their own windows. */
    private fun save(name: String) {
        val bmp = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot() ?: return
        FileOutputStream(File(dir, "$name.png")).use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun fail(message: String): Nothing {
        save("fail-$at")
        throw AssertionError("tour: $message")
    }
}
