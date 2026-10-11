import Foundation
import Observation

/// Composition root — constructor injection, no DI framework (AGENT.md §14).
/// Long-lived data objects live here: `*Repository` (synced entities), `*Store` (app-wide state).
/// Flow-scoped `*Draft` objects are created by the Router when a flow starts, not here.
@Observable
final class AppContainer {
    /// Base URL of the backend. Empty → the bundled mock server address. Switching to production is this one value.
    let apiBaseURL: URL

    init(apiBaseURL: URL = URL(string: ProcessInfo.processInfo.environment["API_BASE_URL"] ?? "http://localhost:8787")!) {
        self.apiBaseURL = apiBaseURL
    }
}
