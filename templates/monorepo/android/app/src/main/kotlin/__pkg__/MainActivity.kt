package {{id}}

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import {{id}}.core.AppContainer
import {{id}}.features.root.RootScreen

/** App entry. Architecture: MVVM + UDF (AGENT.md §14). One [AppContainer] owns long-lived data objects. */
class MainActivity : ComponentActivity() {
    private val container by lazy { AppContainer() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { RootScreen(container) }
    }
}
