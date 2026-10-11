import SwiftUI

/// App entry. Architecture: MVVM + UDF (AGENT.md §14). One `AppContainer` owns long-lived data objects;
/// every screen gets its dependencies through its ViewModel's initializer.
@main
struct {{product}}App: App {
    @State private var container = AppContainer()

    var body: some Scene {
        WindowGroup {
            RootView(container: container)
        }
    }
}
