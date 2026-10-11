import SwiftUI
import Observation

/// Single router. Screens never push each other directly — they emit an Action, the ViewModel asks the Router.
@Observable
final class Router {
    var path: [Route] = []

    func push(_ route: Route) { path.append(route) }
    func pop() { _ = path.popLast() }
    func popToRoot() { path.removeAll() }

    /// Builds the destination view for a route. The build step appends one `case` per screen above `default`.
    @ViewBuilder
    func destination(for route: Route, container: AppContainer) -> some View {
        switch route {
        // Screens are appended here by the build step, e.g. `case .detail(let id): DetailView(...)`.
        default:
            EmptyView()
        }
    }
}
