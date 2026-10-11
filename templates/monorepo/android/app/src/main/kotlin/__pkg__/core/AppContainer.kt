package {{id}}.core

import {{id}}.BuildConfig

/**
 * Composition root — constructor injection, no DI framework (AGENT.md §14).
 * Long-lived data objects live here: `*Repository` (synced entities), `*Store` (app-wide state).
 * Flow-scoped `*Draft` objects are created when a flow starts, not here.
 */
class AppContainer(
    /** Base URL of the backend. Switching to production is this one value. */
    val apiBaseUrl: String = BuildConfig.API_BASE_URL,
)
