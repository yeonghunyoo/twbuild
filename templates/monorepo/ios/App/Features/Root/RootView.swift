import SwiftUI

/// Root of the navigation tree. Screens are added per feature under `Features/<feature>/<screen>/`
/// (View · UiState · Action · ViewModel) by the twbuild build step; this file only hosts the `Router`.
struct RootView: View {
    let container: AppContainer
    @State private var router = Router()

    var body: some View {
        NavigationStack(path: $router.path) {
            Text("{{name}}")
                .accessibilityIdentifier("n.root")
                .navigationDestination(for: Route.self) { route in
                    router.destination(for: route, container: container)
                }
        }
        .environment(router)
    }
}
