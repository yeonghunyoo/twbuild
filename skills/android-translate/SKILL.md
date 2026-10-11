---
name: android-translate
description: CSS → Jetpack Compose translation table used by android-dev to turn the layout tree's `// style:` comments into native modifiers. Rows are in the same CSS-key order as ios-translate so the two can be compared line by line. Preloaded into android-dev.
user-invocable: false
---

# android-translate — CSS → Compose

Rules: a value that is a `Tokens.*` constant is used as that constant. Other values are used as written in the tree (px → dp 1:1; font px → sp).
Never invent a color or size that is not in the tree. When a row says "decide", record the interpretation with `twbuild decide <node id>`.

| CSS | Compose |
|---|---|
| `display: flex; flex-direction: column` | `Column(verticalArrangement = Arrangement.spacedBy(gap), horizontalAlignment = …)` — `align-items` (`flex-start` Start · `center` CenterHorizontally · `flex-end` End) |
| `display: flex` (row) | `Row(horizontalArrangement = Arrangement.spacedBy(gap), verticalAlignment = …)` — `align-items` (`flex-start` Top · `center` CenterVertically · `flex-end` Bottom) |
| `justify-content: space-between` | `Arrangement.SpaceBetween`; `space-around` → `SpaceAround`; `center` → `Center`; `flex-end` → `End` |
| `display: grid; grid-template-columns: 1fr 1fr` | `LazyVerticalGrid(columns = GridCells.Fixed(2), …)` — inside a scrolling Column use a fixed height or a non-lazy `FlowRow`/chunked `Row`s (decide) |
| `flex: 1` | `Modifier.weight(1f)` in Row/Column (or `Spacer(Modifier.weight(1f))` for an empty node) |
| `flex: none` | no weight |
| `position: absolute` children | parent becomes `Box`; `inset: 0` → `Modifier.fillMaxSize()`; `top/left/right/bottom` → `Modifier.align(...)` + `offset`/`padding` |
| `overflow-x: auto` + row | `LazyRow` (or `Row(Modifier.horizontalScroll(rememberScrollState()))`); `scroll-snap-type` → `rememberSnapFlingBehavior` |
| `overflow-y: auto` / `overflow: auto` | `Modifier.verticalScroll(rememberScrollState())` |
| `padding: a b c d` | `Modifier.padding(top = a, end = b, bottom = c, start = d)` (two values → vertical/horizontal) |
| `margin` | parent arrangement or outer `padding`; negative margins → `Modifier.offset` / layout (decide if it bleeds past the parent) |
| `gap` | `Arrangement.spacedBy(gap)` |
| `width/height: Npx` | `Modifier.width(N.dp)/height(N.dp)`; `100%` → `fillMaxWidth()`; `min-height` → `heightIn(min =)`; `max-width` → `widthIn(max =)` |
| `background: <color>` | `Modifier.background(color, shape)`; token → `Tokens.Color.x`; `rgba(r,g,b,a)` → `Color(r, g, b, (a*255).toInt())` |
| `background: linear-gradient(135deg, a, b)` | `Brush.linearGradient(listOf(a, b), start = Offset.Zero, end = Offset.Infinite)` (map angle; decide if unusual) |
| `background: radial-gradient(circle at 35% 30%, a, b)` | `Brush.radialGradient(listOf(a, b), center = Offset(w*0.35f, h*0.30f), radius = …)` via `drawBehind` (decide radius) |
| `border-radius: Npx` | `RoundedCornerShape(N.dp)` as the shape of background/clip; `999px`/`50%` on a square → `CircleShape`; asymmetric → `RoundedCornerShape(tl, tr, br, bl)` or decide |
| `border: 1px solid <c>` | `Modifier.border(1.dp, c, shape)` |
| `color` | `Text(color = c)` / `LocalContentColor` |
| `font-family: Tokens.Font.heading; font-size: N` | `TextStyle(fontFamily = <FontFamily for Tokens.Font.heading>, fontSize = N.sp)`; `font-weight: 600` → `FontWeight.SemiBold` (400 Normal · 500 Medium · 700 Bold) |
| `line-height: 1.2` | `lineHeight = (1.2 * N).sp` |
| `letter-spacing: .08em` | `letterSpacing = 0.08.em` |
| `text-transform: uppercase` | `text.uppercase()` |
| `text-align: center` | `textAlign = TextAlign.Center` + `fillMaxWidth()` |
| `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` | `maxLines = 1, overflow = TextOverflow.Ellipsis` |
| `opacity: .55` | `Modifier.alpha(0.55f)` |
| `box-shadow: 0 2px 6px rgba(0,0,0,.35)` | `Modifier.shadow(elevation = 3.dp, shape, ambientColor/spotColor)` (blur/2 ≈ elevation) |
| `backdrop-filter: blur(24px)` | no system material on API < 31 → translucent background color (decide); API 31+ `RenderEffect.createBlurEffect` on the backdrop |
| `transition`, `animation` | `animate*AsState` / `AnimatedVisibility` / `infiniteRepeatable` for keyframes |
| `cursor: pointer` | ignore (touch) |
| `pointer-events: none` | no `clickable` |
| `z-index` | order inside `Box` (later = on top) / `Modifier.zIndex` |
| `transform: translateY(100%)` (sheet) | `ModalBottomSheet` or `AnimatedVisibility(slideInVertically)` — decide per overlay |
| `display: none` driven by state | `if` in the tree already — do not add extra conditions |

Dynamic styles (`// style_bind: xStyle`) are state-driven: the ViewModel exposes the needed Boolean/value and the composable switches modifiers; do not
copy the CSS string itself into the UI.
