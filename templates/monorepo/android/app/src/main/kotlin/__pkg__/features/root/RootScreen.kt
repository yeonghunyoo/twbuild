package {{id}}.features.root

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import {{id}}.core.AppContainer
import {{id}}.core.navigation.Route

/**
 * Root of the navigation tree — the single NavHost. Screens are added per feature under
 * `features/<feature>/<screen>/` (Screen · UiState · Action · ViewModel) by the twbuild build step.
 */
@Composable
fun RootScreen(container: AppContainer) {
    val nav = rememberNavController()
    NavHost(navController = nav, startDestination = Route.Root) {
        composable<Route.Root> {
            Text("{{name}}", modifier = Modifier.testTag("n.root"))
        }
        // Screens are appended here by the build step.
    }
}
