---
name: ios-playbook
description: iOS build environment of a twbuild repo — project layout (xcodegen project.yml → .xcodeproj), incremental build command, where files go (Features/<Feature>/<Screen>, Core/*), app-structure rules (MVVM + UDF, Route/Router, AppContainer), generated files you never edit. Preloaded into ios-dev.
user-invocable: false
---

# ios-playbook

## Project
- `apps/ios/project.yml` is the project source (xcodegen). The `.xcodeproj` is generated and git-ignored — new files are picked up by
  `xcodegen generate` (run it after adding files). Target and scheme = product name (see `features/app.md` / config `app.product`).
- Deployment target iOS 17 (config `min_os.ios`). Swift 5.10, strict concurrency `complete` — treat concurrency warnings as things to fix when cheap.

## Build (incremental, from `apps/ios` inside your worktree)
```
xcodegen generate --quiet && xcodebuild -project <Product>.xcodeproj -scheme <Product> \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath ../../.twbuild/derived/ios CODE_SIGNING_ALLOWED=NO -quiet build
```
Use the same `-derivedDataPath` every time (incremental). Read errors from the output; do not re-run the same failing build unchanged.

## Where files go
```
App/
  <Product>App.swift              entry — do not restructure
  Core/AppContainer.swift         composition root: repositories, stores (add yours here, constructor injection)
  Core/Navigation/Route.swift     enum Route — one case per screen (the generator adds `case <screen>`; parameters are IDs only)
  Core/Navigation/Router.swift    single router — destination(for:) switch (the generator adds the screen's case)
  Core/DesignSystem/Generated/    Tokens.swift — GENERATED, never edit
  Core/Data/                      *Repository (protocol + impls) · *Store · *Draft
  Features/<Feature>/<Screen>/    <Screen>View · <Screen>UiState · <Screen>Action · <Screen>ViewModel (the draft; yours after generation)
```

## Architecture (MVVM + UDF)
- View renders `viewModel.state` and sends `Action`s. It holds no state except pure UI state (focus, scroll).
- ViewModel: `@Observable final class`, `private(set) var state`, `func send(_:)` — the only place state changes.
- Data: subscribe to `*Repository`/`*Store` streams from the container; pass IDs between screens, never objects.
- Icons: SF Symbols closest to the SVG, or an asset added under `App/Resources/` (keep a `// raw-svg` comment with the path count).

## Never
- Edit `Tokens.swift`, `design/`, `api/`, Android, or files outside `apps/ios/`. Never change the structure the tree gives.
