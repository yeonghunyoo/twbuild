---
name: ios-translate
description: CSS → SwiftUI translation table used by ios-dev to turn the layout tree's `// style:` comments into native modifiers. Rows are in the same CSS-key order as android-translate so the two can be compared line by line. Preloaded into ios-dev.
user-invocable: false
---

# ios-translate — CSS → SwiftUI

Rules: a value that is a `Tokens.*` constant is used as that constant. Other values are used as written in the tree (px → points 1:1).
Never invent a color or size that is not in the tree. When a row says "decide", record the interpretation with `twbuild decide <node id>`.

| CSS | SwiftUI |
|---|---|
| `display: flex; flex-direction: column` | `VStack(alignment:spacing:)` — `gap` → `spacing`; `align-items` → `alignment` (`flex-start` .leading · `center` .center · `flex-end` .trailing) |
| `display: flex` (row) | `HStack(alignment:spacing:)` — `align-items` (`flex-start` .top · `center` .center · `flex-end` .bottom) |
| `justify-content: space-between` | `Spacer()` between children (HStack/VStack); `space-around` → spacers at both ends and between; `center` → spacers at both ends; `flex-end` → leading `Spacer()` |
| `display: grid; grid-template-columns: 1fr 1fr` | `LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 2), spacing:)`; fixed px columns → `GridItem(.fixed(n))` |
| `flex: 1` | `.frame(maxWidth: .infinity)` in HStack / `.frame(maxHeight: .infinity)` in VStack (or `Spacer()` for an empty node) |
| `flex: none` | no expansion — leave default |
| `position: absolute` children | parent becomes `ZStack(alignment:)`; `inset: 0` → `.frame(maxWidth: .infinity, maxHeight: .infinity)`; `top/left/right/bottom` → `.offset` or alignment + `.padding` |
| `overflow-x: auto` + row | `ScrollView(.horizontal, showsIndicators: false) { HStack }`; `scroll-snap-type` → `.scrollTargetBehavior(.viewAligned)` + `.scrollTargetLayout()` |
| `overflow-y: auto` / `overflow: auto` | `ScrollView { … }` |
| `padding: a b c d` | `.padding(.top, a)` … (CSS order top right bottom left; two values → vertical/horizontal) |
| `margin` | parent spacing or `.padding` on the outside; negative margins → `.padding(-x)` (decide if it bleeds past the parent) |
| `gap` | `spacing` of the stack |
| `width/height: Npx` | `.frame(width:height:)`; `100%` → `.frame(maxWidth: .infinity)`; `min-height` → `.frame(minHeight:)`; `max-width` → `.frame(maxWidth:)` |
| `background: <color>` | `.background(color)`; token → `Tokens.Color.x`; `rgba(r,g,b,a)` → `Color(red:green:blue:opacity:)` with the same numbers |
| `background: linear-gradient(135deg, a, b)` | `LinearGradient(colors: [a, b], startPoint: .topLeading, endPoint: .bottomTrailing)` (map the angle to the nearest unit points; decide if unusual) |
| `background: radial-gradient(circle at 35% 30%, a, b)` | `RadialGradient(colors: [a, b], center: UnitPoint(x: 0.35, y: 0.30), startRadius: 0, endRadius: …)` — endRadius from the node size (decide) |
| `border-radius: Npx` | `.clipShape(RoundedRectangle(cornerRadius: N, style: .continuous))`; `999px` or `50%` on a square → `Circle()` / `Capsule()`; asymmetric (`45% 55% …`) → `UnevenRoundedRectangle` or decide |
| `border: 1px solid <c>` | `.overlay(RoundedRectangle(cornerRadius:).stroke(c, lineWidth: 1))` |
| `color` | `.foregroundStyle(c)` |
| `font-family: Tokens.Font.heading; font-size: N` | `.font(.custom(Tokens.Font.heading, size: N))`; body font → `.custom(Tokens.Font.body, size:)`; `font-weight: 600` → `.fontWeight(.semibold)` (400 regular · 500 medium · 700 bold) |
| `line-height: 1.2` | `.lineSpacing((1.2 - 1) * fontSize)` approx — decide if it matters |
| `letter-spacing: .08em` | `.tracking(0.08 * fontSize)` |
| `text-transform: uppercase` | `.textCase(.uppercase)` |
| `text-align: center` | `.multilineTextAlignment(.center)` + `.frame(maxWidth: .infinity)` |
| `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` | `.lineLimit(1)` + `.truncationMode(.tail)` |
| `opacity: .55` | `.opacity(0.55)` |
| `box-shadow: 0 2px 6px rgba(0,0,0,.35)` | `.shadow(color: .black.opacity(0.35), radius: 3, x: 0, y: 2)` (blur/2 ≈ radius) |
| `backdrop-filter: blur(24px)` | `.background(.ultraThinMaterial)` or `.thinMaterial` — decide which material; note the blur radius |
| `transition`, `animation` | `.animation(.easeInOut(duration:), value:)`; `@keyframes` breathe → `.scaleEffect` with `.repeatForever` |
| `cursor: pointer` | ignore (touch) |
| `pointer-events: none` | `.allowsHitTesting(false)` |
| `z-index` | order inside `ZStack` (later = on top) |
| `transform: translateY(100%)` (sheet) | `.offset(y:)` with animation, or `.sheet`/`presentationDetents` — decide per overlay |
| `display: none` driven by state | `if` in the tree already — do not add extra conditions |
| `flex-wrap: wrap` | `LazyVGrid(columns: [GridItem(.adaptive(minimum: …))])` for uniform tiles; tag clouds → a custom `Layout` (decide the minimum width) |
| `aspect-ratio: a / b` | `.aspectRatio(a / b, contentMode: .fit)` |
| `position: sticky` top / bottom | `.safeAreaInset(edge: .top / .bottom)` on the scroll view, or the toolbar / bottom bar of the host |
| `position: fixed` bottom action | `.safeAreaInset(edge: .bottom)` so it respects the home indicator |
| `:active` / hover styles | a `ButtonStyle` using `configuration.isPressed`; hover has no touch equivalent |
| media queries / responsive widths | ignore desktop breakpoints — the app is the narrow layout; both orientations only if the design shows it |

Dynamic styles (`// style_bind: xStyle`) are state-driven: the ViewModel exposes the needed Bool/value and the view switches modifiers; do not
copy the CSS string itself into the UI.

## Overlays · interactions (tree kinds · overlay screens)

| In the tree | SwiftUI |
|---|---|
| overlay screen that slides up (`transform: translateY(100%)` + backdrop) | `.sheet(isPresented:)` with `.presentationDetents([...])` (half → `.medium`, full → `.large`, custom → `.fraction`/`.height`) and `.presentationDragIndicator(.visible)`; the open/close handlers set the same UiState Bool |
| overlay that covers the screen / a dialog with buttons only | `.fullScreenCover` / `.alert` · `.confirmationDialog` |
| small anchored menu | `.popover(isPresented:)` + `.presentationCompactAdaptation(.popover)`; action list → `Menu` |
| host screen with a tab bar (`shell`) | one `TabView` at the root; each tab's tag is a `Route`; the slotted screens are the tab contents |
| `on_click` on a button-like node | `Button { viewModel.send(.x) }`; destructive look → `role: .destructive` |
| `input` (text) | `TextField` / `SecureField`; `.keyboardType`, `.textContentType`, `.submitLabel` from the input's purpose; the `bind` key is its binding |
| `input type="range"` | `Slider(value:in:step:)` — range from the tree's `min`/`max`; the `on_input` handler sends the value |
| toggle-like node | `Toggle` bound to the `bind` key |
| `list` | `ForEach` over the item array (`Identifiable`); the handler inside sends `.<items><Handler>(item)`; tapping navigates by id only (`Route.x(id)`) |
| drag / long press / swipe | `DragGesture` / `LongPressGesture` / `.swipeActions`; swipe-to-dismiss on sheets is native — do not reimplement |
