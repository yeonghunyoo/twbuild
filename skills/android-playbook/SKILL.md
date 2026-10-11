---
name: android-playbook
description: Android build environment of a twbuild repo — Gradle layout (wrapper, version catalog), incremental build command, where files go (features/<feature>/<screen>, core/*), app-structure rules (MVVM + UDF, Route/NavHost, AppContainer), generated files you never edit. Preloaded into android-dev.
user-invocable: false
---

# android-playbook

## Project
- `apps/android/` — Gradle Kotlin DSL, version catalog `gradle/libs.versions.toml` (AGP 8.7 · Kotlin 2.1 · Compose BOM 2024.12 · Navigation 2.8 type-safe routes · kotlinx.serialization).
- `minSdk` from config `min_os.android` (26). `compileSdk`/`targetSdk` 35. `local.properties` with `sdk.dir` is written by the harness (git-ignored).

## Build (incremental, from `apps/android` inside your worktree)
```
./gradlew assembleDebug -q
```
Read `e:` lines from the output; do not re-run the same failing build unchanged. One Gradle build at a time.

## Where files go
```
app/src/main/kotlin/<pkg>/
  MainActivity.kt                       entry — do not restructure
  core/AppContainer.kt                  composition root: repositories, stores (add yours here, constructor injection)
  core/navigation/Route.kt              sealed interface Route — one @Serializable member per screen (the generator adds it; params are IDs only)
  core/designsystem/generated/Tokens.kt GENERATED, never edit
  core/data/                            *Repository (interface + impls) · *Store · *Draft
  features/root/RootScreen.kt           single NavHost — the generator adds `composable<Route.X>`
  features/<feature>/<screen>/          <Screen>Screen · <Screen>UiState · <Screen>Action · <Screen>ViewModel (the draft; yours after generation)
```

## Architecture (MVVM + UDF)
- `<Screen>Screen(viewModel)` collects `state` and calls `<Screen>Content(state, onAction)` — content is stateless.
- ViewModel: `ViewModel` + `MutableStateFlow<UiState>`; `onAction()` is the only place state changes.
- Data: collect `Flow`s from `*Repository`/`*Store` in the container; pass IDs between screens, never objects.
- Icons: Material icons closest to the SVG, or a vector drawable under `res/drawable/` (keep a `// raw-svg` comment with the path count).

## Never
- Edit `Tokens.kt`, `design/`, `api/`, iOS, or files outside `apps/android/`. Never change the structure the tree gives.
