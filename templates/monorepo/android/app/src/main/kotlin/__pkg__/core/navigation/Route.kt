package {{id}}.core.navigation

import kotlinx.serialization.Serializable

/**
 * Every screen the app can navigate to. Routes carry IDs only — never whole objects (AGENT.md §14).
 * The same list exists in iOS `Route.swift`; the static gate compares the two.
 * Push payloads (`screen` + `params`) map onto these routes.
 */
sealed interface Route {
    @Serializable
    data object Root : Route
    // Screens are appended here by the build step, e.g. `@Serializable data class Detail(val id: String) : Route`.
}
