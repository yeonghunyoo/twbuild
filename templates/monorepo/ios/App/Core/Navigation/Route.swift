import Foundation

/// Every screen the app can navigate to. Cases carry IDs only — never whole objects (AGENT.md §14).
/// The same list exists in Android `Route.kt`; the static gate compares the two.
/// Push payloads (`screen` + `params`) map onto these cases.
enum Route: Hashable {
    // Screens are appended here by the build step, e.g. `case detail(id: String)`.
}
