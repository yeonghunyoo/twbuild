# twbuild — 설계 정본

> **목표: Claude Design 디자인과 같은 화면을 iOS · Android 에 같은 구조로 만든다.**
> lead(메인 세션)와 개발자 둘(ios-dev · android-dev)이 LangGraph 순서대로 화면 단위로 동시에 만든다.
> 사용자는 코드를 읽지 않고 증거를 보고 진행한다. 스모크를 통과하면 머지까지 자동이다.

상태: v0.0.1 · 한 사이클 골격 구현 · PoC 1~4 · 6 확인(5 대기). 구현 현황은 `CLAUDE.md`, 이 문서에 없는 것은 맨 끝 "나중에" 에 있다.

## 용어

| 용어 | 뜻 |
|---|---|
| lead | 메인 세션 + `/twbuild` 스킬. 진행 · 플랜 · 배차 · 사람 창구 |
| ios-dev · android-dev | 서브에이전트(`twbuild:ios-dev` · `twbuild:android-dev`). 화면 과제를 구현 |
| 디자인 정본 | `design/` — Claude Design 원본(`.dc.html` · `styles.css`)의 레포 스냅샷 |
| 레이아웃 트리 | `.dc.html` 에서 결정적으로 만든 화면 구조. **= 네이티브 화면 구조** |
| 구조 초안 | 트리를 1:1 로 옮긴 네이티브 코드 초안. 생성기가 만들고 개발자가 이어서 쓴다 |
| design run | Claude Design 에서 디자인을 한 번 import 한 단위. ID 로 기록 · 비교 |
| 셋업 / 사이클 그래프 | 레포마다 한 번 / 기능마다 한 번 도는 LangGraph |

## 1. 정본

| 대상 | 정본 | 규칙 |
|---|---|---|
| 디자인 | `design/` | 하네스가 수집. 손으로 고치지 않는다. 디자인의 좋고 나쁨은 사용자가 정한다 |
| 구조 | `design/<기능>/layout/<화면>.json` (생성물) | 두 플랫폼이 1:1 로 따른다. 합치기 · 빼기 · 순서 변경 · 컨테이너 추가 금지 |
| 토큰 | `design/ds/styles.css` → Swift · Kotlin 토큰 코드 (생성물) | 손으로 고치지 않는다 |
| API | `api/openapi.yaml` + `api/fragments/` → `Core/Networking/Generated/{Models,Client}`(Swift · Kotlin) · mock (생성물, `gen.py` · `mock.py`, 결정적 · drift 검사). 표준 타입과 겹치는 스키마 이름은 `Model` 접미사(Error → ErrorModel), 두 플랫폼 같은 이름 | 손으로 고치지 않는다 (훅 H4) |
| 해석 | 정본이 아니라 참고 자료 | 노드 단위 = `twbuild decide`(주제 = 노드 ID). 일반 번역 규칙 = `<플랫폼>-translate` |

```
design/                         디자인 정본 (커밋)
  ds/styles.css · ds/components/  디자인 시스템 (첫 사이클)
  ds/tokens.json                  토큰 중간 표현 (생성물) → Tokens.swift · Tokens.kt
  <기능>/<화면>.dc.html           화면 원본 — 템플릿 + 인라인 스타일 + 로직 스크립트
  <기능>/layout/<화면>.json       레이아웃 트리 (생성물)
  index.json                      원장 — 화면마다 현재 run · 트리 해시 · 빌드에 쓴 트리 해시
  runs/<run-id>.json              design run 기록
features/app.md                  앱 개요 — 주제 · 요구사항 (셋업 interview)
features/<기능>/                 기능 팩
  brief.md                        요구사항 · 흐름
  refs/                           스크린샷 · 해석 메모 (gitignore)
  assets/                         이미지 (사람이 넣는다) · 폰트
api/openapi.yaml · api/fragments/  계약 본문 · 기본 조각
```

## 2. 디자인 import

시점: 사이클 intake. 사용자가 새 화면 · 갱신을 원할 때만. 첫 사이클은 디자인 시스템도 함께. 한 번 받은 `design/` 이 원장이다 — Claude Design 을 상시 보지 않는다.

| 받는 것 | 받지 않는 것 |
|---|---|
| 화면 `*.dc.html` · 그것이 참조하는 `_ds/*/styles.css` · `x-import` JSX | `support.js`(해시만 기록) · 내보낸 standalone HTML · `_ds_bundle.js` · `_restore_*` · `.thumbnail` · `*-frame.jsx` |
| 첫 사이클: 디자인 시스템의 `components/*.html` · `foundations/*.html` · `readme.md` · `theme.json` | `uploads/**` · `screenshots/**` · 바이너리 · 256 KiB 초과 |

| 훅 | 대상 | 동작 |
|---|---|---|
| 검문 (PreToolUse) | `mcp__*claude-design__*` | `hooks/design_guard.py` → `design.allowed()`: D1 run 밖 호출 · D2 다른 프로젝트 · D3 거부 목록(support.js · standalone HTML · 번들 · uploads · 바이너리) · D4 허용 목록 밖 · D5 크기 상한. 허용 목록은 고른 `.dc.html` 에서 시작해 `<helmet>` · `x-import` 참조를 따라 늘어난다. `list_projects` 같은 메타 도구는 통과. 쓰기 · 공유 · `render_preview` 는 `guard.py` H7 이 항상 거부 |
| 캡처 (PostToolUse) | `read_file` · `list_files` | `hooks/design_capture.py` → `design.capture()`: 래퍼(`<untrusted-project-content path etag>`)를 벗기고 엔티티 디코딩해 `design/` 에 바이트 그대로 쓰고(`_ds/*/x` → `design/ds/x`, 화면 · JSX → `design/<기능>/`), 모델에는 경로 · 바이트 · sha 한 줄만(`updatedMCPToolOutput`). 디스크로 빠진 큰 결과도 집어 온다. `list_files` 는 경로별 etag · size 를 run 에 남긴다(support.js etag = 형식 지문, size = D5 판정) |

**design run**
- ID `R-0001` 순번. run 은 하나만 진행(`.twbuild/intake/<기능>/run.json`). 시작 `start(scope, project, screens, ds_project)` → 받기 → `finish(spec)` 가 트리 · 토큰 생성 · 원장 갱신 · `design/runs/R-000N.json`(파일별 etag · sha256 · bytes · 이전 run 대비 추가/변경/삭제 · 화면별 트리 해시 · support.js etag) · `design-run: R-000N (<기능>)` 커밋 + `design-run/R-000N` 태그.
- 훅이 없는 자리(테스트 · 수동)는 `twbuild design start|capture|listing|trial|finish|abort|status` 로 같은 코드를 부른다.
- 원장 판정: 빌드에 쓴 트리 해시 = 현재 트리 해시 → 최신. 다르면 run 간 트리 diff(바뀐 노드 ID)를 재작업 과제로 낸다 — 개발자 코드를 덮지 않는다.
- 원장은 결정적 단계만 쓴다. LLM 은 쓰지 않는다.

**화면 매핑** — `tree.detect_screens` 가 후보를 내고 lead 가 이름을 확인한다(`sheet` → `mixer` 처럼). 못 가르면 lead 과제.

| 종류 | 근거 | 예 (사운드스케이프) |
|---|---|---|
| state | `<sc-if value="{{ isX }}">` 어디에 있든. 탭 비교로 파생된 플래그(`showPresetList: s.tab === 'sound'`)는 그 탭 화면에 붙어 구역이 여럿 | onboarding · home · sound(isSound + showPresetList + showSoundList) · stats |
| shell | is* 분기를 품은 비상태 분기 — 탭 바 같은 공용 크롬 | shell(appVisible): 콘텐츠 호스트(home · sound · stats 슬롯) + 탭 바 |
| overlay | 페이지 루트 바로 아래 `style="{{ xStyle }}"` 블록. backdrop 은 다음 형제에 붙는다 | nowPlaying · settings(backdrop + sheet) · mixer(backdrop + sheet) |

- 다른 화면에 속한 블록은 트리에서 `{"kind": "screen", "ref": "<화면>"}` 슬롯이다(연속 같은 ref 는 하나). 다른 화면 안의 조건 구역(`showFavHero`)은 화면이 아니라 그 화면의 `if` 노드다.
- 실측 (2026-10-11): 사운드스케이프 `forest.dc.html` → 화면 8개 · 노드 15~44개/화면 · 못 잼 0 · 토큰 48개(못 잼 4: color-mix 파생) · 생성 토큰으로 두 플랫폼 빌드 통과.

이미지는 사람이 `assets/` 에 넣는다(커넥터는 텍스트만). 폰트는 `styles.css` 의 웹폰트(`@import` Google Fonts · `@font-face`)를 design run 끝(finish)에 하네스가 받는다(`fonts.py` — 비브라우저 UA 로 정적 TTF, PostScript 이름은 name 테이블) → `design/ds/fonts/` + `index.json`(출처 · sha, 커밋) → 두 앱에 복사 · 등록(iOS `App/Resources/Fonts` + `project.yml` `info.properties.UIAppFonts` · Android `res/font/<family>_<weight>`) · `Fonts.swift`(`FontFamily`) · `Fonts.kt`(`FontFamilies`) 생성물. `twbuild fonts fetch|install|status`. 라이선스 OFL · Apache.
디자인 프로젝트 · 화면은 intake 에서 lead 가 사용자에게 묻는다(ask).

## 3. 레이아웃 트리 · 구조 초안

**트리 노드**

| 필드 | 내용 |
|---|---|
| `id` | 고정 노드 ID `n.<화면>.<kind><형제 index>…`(예 `n.home.column0.row0.text1`) → 코드의 `accessibilityIdentifier` / `testTag`. 경로 기반이라 같은 입력 = 같은 ID, 구조가 바뀐 자리만 ID 가 바뀐다 |
| `kind` | `if`(상태 키) · `list`(반복) · `row` · `column` · `grid` · `group` · `box` · `text` · `icon` · `input` · `image` · `screen`(다른 화면 슬롯) · `unknown`(못 잼 — 모르는 태그) |
| `style` · `style_bind` | CSS 속성 전부. 토큰과 값이 맞으면 토큰 상수 이름(`Tokens.Color.accent400` · `Tokens.Space.s2` · `Tokens.Radius.md`), 아니면 원래 값. 전체 또는 앞부분이 바인딩이면 `style_bind`(상태가 정하는 스타일) |
| `class` | 디자인 시스템 클래스 → 그 카탈로그 컴포넌트로 만든다 |
| `text` · `params` · `raw_text` · `bind` · `on_*` | 문구(바인딩이 섞이면 `{키}` 자리 + `params`) · 문구 키 연결 전엔 `raw_text` · 바인딩 상태 키 · 핸들러 이름(`on_click` · `on_input` · `on_mousedown` …) |
| `svg` | `icon` 노드의 `<path d>` · 도형 데이터(경로당 4000자) — 두 플랫폼이 같은 아이콘을 그리게. 그림이지 구조가 아니라 **해시에서 빠진다**(초안은 `// svg:` 주석으로 싣는다) |

- 원래 값(px · hex)은 트리에 있을 때만 쓴다. 트리에 없는 값을 지어내면 위반.
- 한 `.dc.html` 에 여러 화면이 `sc-if` 로 섞이면 intake 가 화면 ↔ 분기를 매핑한다. 모르는 태그는 "못 잼" 으로 남긴다.

**구조 초안 — 생성기는 구조만**

| 생성기 (결정적) | 개발자 |
|---|---|
| 노드 → 컨테이너(`VStack` · `HStack` · `ZStack` · `LazyVGrid` ↔ `Column` · `Row` · `Box` · `LazyVerticalGrid`) · 중첩 · 순서 | `// style:` 주석(CSS 원문)을 플랫폼 방식으로 번역 |
| `if` · `list` · 노드 ID · 문구 · 바인딩 자리 · `send(Action)` 호출부 · 카탈로그 컴포넌트 호출(class 가 그 플랫폼에 구현된 컴포넌트면 `<Name> { 노드 }` 로 감싼다 — 컴포넌트는 trailing content 를 받는다) | ViewModel 로직(Action 처리 → UiState) · Repository · API · 화면 전환 |
| 화면의 `UiState`(`bind` · `if` 상태 키) · `Action`(`on_*`) 타입 — 14장 | |

- 초안은 개발자 소유 코드다. 컴파일되게 내고, 확실하지 않은 매핑은 주석으로 남긴다.
- 시점: intake 에서 시험 실행(파일 안 씀) → build 에서 화면 과제 배차 직전 양쪽 워크트리에 생성 → `draft(<화면>)` 커밋. 이미 있으면 건너뛴다.

## 4. 흐름

```
/twbuild → advance() → 라우터(매번 실측)
             ├ 미준비 · 설정 변경 → 셋업 그래프
             └ 준비됨            → 사이클 그래프
```

**셋업 그래프** (레포마다 한 번, 설정이 바뀌면 그 부분만)

| 노드 | 주체 | 하는 일 |
|---|---|---|
| probe | 결정적 | git · 기존 앱 · config · 툴체인 · 커넥터 실측 → 빈 칸 목록. `twbuild doctor` 와 같은 함수 — 사전 점검(빠진 것마다 설치 명령). 툴체인이 없는 플랫폼은 끈다 |
| wire | 결정적 · 멱등 | config 기본값 · 권한 기본값(욜로, 11장) · `.gitignore`(옛 블록은 갱신) · CLAUDE.md 마커 절 · `.claude/rules/` 골격 · pre-commit 시크릿 훅 · 설정의 공개 스킬 설치(7장) |
| interview | lead | 셋만 묻는다: 앱 주제 · 앱 이름 · 요구사항 → `features/app.md`. 답마다 저장, 끊기면 남은 것부터. 식별자는 이름에서 만든다(`com.example.<이름>`). 나머지(플랫폼 · 신규/기존 · 로그인 · 스모크)는 probe · 기본값으로 정하고 report 표에 보인다 — 바꾸려면 config |
| scaffold | 결정적 | 모노레포 골격 · 계약 본문 + 조각 · 코드 생성 · mock · 최소 토큰 · `placeholders.json` |
| selfcheck · report | 결정적 | 빈 골격 스모크(정적 drift · 계약 디코딩 `decode_<플랫폼>` · 빌드) · 사람 할 일 · ✅/❌ |

**사이클 그래프** (기능마다)

| 노드 | 주체 | 하는 일 |
|---|---|---|
| intake | lead + 결정적 | brief 정리 · (필요하면) design run → 트리 · 화면 매핑 · 구조 초안 시험 실행 |
| plan | lead | 화면 플랜(쓰는 데이터 `data:` 포함) · 카탈로그 컴포넌트 매핑 · 필요한 계약 변경 + 재생성 |
| build | 결정적 + 개발자 둘 | 디자인 시스템 과제(`design/ds/components/*.html` 이 있고 원장 `ds.built` 가 없을 때 — 카탈로그 컴포넌트를 `Core/DesignSystem/Catalog/<Name>` 으로, 두 플랫폼 같은 이름 · 매개변수, trailing content 규약) → 데이터 과제(14장) → 화면마다 구조 초안 생성 → ios-dev ∥ android-dev |
| smoke | 결정적 | 게이트 3층 (6장). 실패 → build 재작업, 화면당 예산(기본 5회)을 넘으면 `blocked` |
| merge | 결정적 | 짝 둘 다 통과 + 빌드 트리 해시 = 현재 해시 → 화면 단위 squash · 태그 · 원장 갱신 · 측정 요약(13장) · 보고서 |

- 멈춤은 둘: `task`(LLM 과제 → `submit`) · `blocked`(사람 할 일 · 예산 소진).
- 구현(`server/twbuild/cycle.py`): 묻는 노드 intake · plan · dispatch · blocked(interrupt 만) / 실행 노드 prepare(워크트리 2개 — 이미 있으면 main 을 합친다(머지 커밋; 충돌은 `blocked`) · 계약 생성물 drift 면 다시 써 커밋 · `local.properties` · 구조 초안 `draft(<화면>)` 커밋 · `.twbuild/tasks/_current.json`) · smoke · merge · done.
  과제 순서는 plan 이 정한다(데이터 과제 → 화면들, 호스트 shell 은 슬롯 화면 뒤). 화면 과제는 한 쌍씩 차례로. 개발자가 `blocked` 를 내면 blocked 멈춤 → 사람이 풀고 `submit({})` → 같은 과제 재배차.
  merge 는 플랫폼별 squash · 태그 뒤에 원장(`design/index.json`) · 결정(`.claude/rules/team/`) · `features/<기능>/` · 측정 요약 · 잠금을 `ledger(<기능>/<과제>)` 커밋으로 main 에 남긴다. plan 이 계약을 바꾸면 생성물까지 `contract(<기능>)` 커밋. `_data.yaml` 의 엔티티는 사이클마다 합집합.
  실측(2026-10-13 헤드리스 lead, sound 화면): 리드가 intake · plan · 배차 · 결정(D-33 확정 · D-35→D-39 뒤집기)을 혼자 처리했고 19턴 · 8.6분 · $8.56(개발자 제외). 멈춤 원인은 하네스 버그(워크트리 디코딩 설정 · 생성물 누락 · 훅 거짓 양성 · 재작업 프롬프트 누락)였고 전부 고쳤다.
  아직 없는 것: review · fix 분류(지금은 실패 전부 → 재작업) · retro.
- 사람에게 묻는 것은 전부 ask(AskUserQuestion — 선택지 + 직접 입력, 추천을 맨 위에). 채팅 자유 질문은 쓰지 않는다.
- 그래프가 과제마다 "호출할 스킬" 을 싣는다.
- 노드는 부작용 뒤에 interrupt 하지 않는다(재개 시 노드가 처음부터 돈다). 저장 상태보다 실측이 이긴다.
- 사이클 진행 중 설정 · 디자인 변경은 다음 사이클 전에 적용한다.

## 5. 조율

```yaml
# .twbuild/plans/<기능>/<화면>.yaml
layout: design/<기능>/layout/<화면>.json   # 구조는 트리가 정한다
components: [Button, Card]                 # 클래스 노드 → 카탈로그 컴포넌트
states: [isOnboarding, isHome]             # 트리의 if 조건
interactions: [HOME-1: n.home.card 탭 → Screens.detail(id)]
translations: [D-14]                       # 트리가 못 정한 번역 해석
```

- 구현 중 해석은 개발자가 `twbuild decide <노드 ID> "<해석>" --by ios` 로 기록한다 → 메인 레포 `.claude/rules/team/` 에 D-xx(잠정; `--by lead` 는 바로 확정). 상대 개발자에게는 훅이 주입한다(6 KB 상한 · 확정 먼저 · 본문 220자 — 실측: 15 KB 주입은 잘려 앞 2 KB 만 보였다; 전체는 `twbuild decide`). 같은 주제가 있으면 먼저 쓴 쪽이 이긴다. lead 가 확정하거나 뒤집는다.
- 개발자가 정할 수 없는 것(계약 · 공용 컴포넌트 · 디자인 시스템 · 트리와 다른 구조)은 `blocked`. 디자인 자체가 바뀌어야 하면 사람 할 일.
- 개발자끼리 직접 메시지를 주고받지 않는다. 같은 화면의 두 과제는 함께 띄우고 함께 닫는다.

## 6. 게이트

| 층 | 확인 | 기기 |
|---|---|---|
| 빌드 · 실행 | 두 앱이 빌드되고 크래시 없이 뜨는가 — 기기 층(`device.py`): 부팅된 iPhone 시뮬레이터(없으면 가장 새 런타임을 부팅) · adb 기기에 설치 → 실행 → 5초 뒤 살아 있음 → 종료. 모든 명령에 시간 제한. 도구 · 기기 · 산출물이 없거나 시간이 넘으면 "못 잼"(머지를 막지 않고 보고서에 남는다 · fail 은 막는다) | 씀 (config `smoke.device`: merge = 다른 층을 다 통과한 시도에만 · every · off) |
| 트리 정합성 (정적) | 트리의 노드 ID · `if` · `list` · `on_*` 가 양쪽 코드에 있음 · UiState 필드 · Action · Route · 데이터 객체 이름 · 메서드가 iOS = Android · Route 파라미터는 단순 값(ID) · 토큰과 값이 맞는 곳은 토큰 · 트리에 없는 직접값 없음 · 클래스 노드는 카탈로그 컴포넌트 · 리소스 양쪽 등록 | 안 씀 |
| 계약 | openapi 응답 예시 전부(example · examples · 스키마 example · $ref 응답)를 생성 모델로 디코딩 — `gen.decode_check()`: iOS 는 swiftc 임시 실행 파일, Android 는 생성 JUnit 테스트 `ContractDecodeTest`(init 스크립트로 JUnit). 빌드 층 통과 뒤 매 스모크 · 셋업 selfcheck 에서도 | 안 씀 |

- 못 잰 층은 "못 잼" 으로 보이고 통과로 세지 않는다.
- 규칙은 `harness-rules` 에 ID 로 두고, 거부 메시지가 같은 ID 를 인용한다.
- 정적 규칙(`server/twbuild/gate.py`): T1 뷰 노드 ID 가 코드에 있다(`accessibilityIdentifier`/`testTag`) · T2 `if`·`list` 상태 키가 있다 · T3 `on_*` 핸들러의 Action 이 있다(리스트 안은 `<items><Handler>(item)`) ·
  T4 트리 · 토큰 · 디자인 원본(데이터 스크립트 포함)에 없는 직접 색 리터럴이 없다 · T5 Route 집합 iOS = Android · T6 데이터 계층 타입 이름 iOS = Android(`App/Core/Data` ↔ `core/data`) · T7 디자인 시스템 컴포넌트 이름(타입 + 대문자 함수) iOS = Android(`App/Core/DesignSystem` ↔ `core/designsystem`) · T8 class 노드는 그 플랫폼에 구현된 카탈로그 컴포넌트를 호출한다(`<Name>(` · `<Name> {`; 초안이 감싼다) · T9 두 플랫폼에 등록된 폰트 집합(family · weight · style)이 같다(하네스가 등록, 개발자는 손대지 않는다) · T10 화면의 `UiState` 필드(이름 · 타입: Bool≡Boolean · [T]≡List<T>)와 `Action`(이름 · 매개변수 타입)이 iOS = Android. 결과는 `.twbuild/results/<기능>/<화면>.json`, 실패 상세(위반 · 빌드 로그 꼬리)는 재작업 과제 프롬프트에 실린다.

## 7. 팀 · 스킬

| | 한다 | 안 한다 |
|---|---|---|
| lead | 그래프 진행 · 플랜 · 결정 확정 · 배차 · 사람 창구(한국어) | 플랫폼 코드 · 통과 판정 · 순서 결정 · 디자인 판단 |
| ios-dev · android-dev | 구조 초안 위에서 스타일 번역 · 모델 구현 · 빌드 오류 수정 · `decide` | 과제 경계 밖 수정(`design/` · 계약 · 디자인 시스템 · 다른 플랫폼) · 트리와 다른 구조 · 머지 |

| 방식 | 어디 | 스킬 |
|---|---|---|
| ① 미리 로드 — 항상 실림 | 에이전트 정의 `skills:` | `dev-loop` · `<플랫폼>-translate`(스타일 번역표) · `<플랫폼>-playbook`(빌드 환경 · 앱 구조 규칙) · `harness-rules` |
| ② 목록 — 필요할 때 호출 | 설정 `agents.<역할>.skills` | 언어 · OS(공개 스킬) · lead 의 `archify`(도식이 필요할 때만 — 과제가 권하지 않는다) |

- ②는 과제 프롬프트가 호출을 권한다. 강제하지 않는다 — 반드시 필요하면 ①로 옮긴다.
- ②의 설치(`skills.py`): wire 가 `SOURCES`(repo · path · 커밋 핀 · 라이선스) 의 tarball 을 캐시(`~/.claude/plugins/data/twbuild/skills-src/`)에 받아 대상 레포 `.claude/skills/<이름>/` 에 복사하고 `.claude/skills/_sources.json` 에 기록한다(커밋). 설정의 분류 이름(jetpack-compose · security · identity · navigation · play)은 `ALIASES` 가 개별 스킬로 푼다. PolyForm(dpearson2699/swift-ios-skills)은 설치하지 않고 사람 할 일로 낸다. `twbuild skills [install]`.
- 서브에이전트는 메인 대화를 못 본다. 과제 프롬프트는 그래프가 빠짐없이 만든다.

## 8. 지시 우선순위

1. **정본이 이긴다.** 정본과 다른 지시는 따르지 않고 `blocked`.
2. 그다음 **과제 프롬프트**.
3. 나머지(결정 · rules · 스킬)는 참고 — 구체적인 쪽을 따른다.

## 9. 메모리

- 프로젝트 rules 하나: `.claude/rules/{ios,android,team,lead}/` — 전부 `paths:` 경로 스코프(무경로 rule 은 워크트리에서 두 번 실린다).
- `team/` 은 `decide` 결정. 진행 중 결정은 워크트리에 안 보이므로(브랜치 시점 사본) 훅이 메인 레포에서 주입한다.
- 과제 메모: `.twbuild/tasks/<과제>.md` (gitignore, 머지 후 삭제).

## 10. 계약 — 기본 구성

| 구성 | 계약 | 앱 인터페이스 |
|---|---|---|
| 인증 | Bearer · `/auth/*` · 401 규약 | `AuthProvider` · `SecureStore` |
| 푸시 | `/devices` · payload(`screen` + `params`) | `PushService` |
| 오프라인 | 클라이언트 UUID `id` · `updatedAt` · `deletedAt` · `?since=` · `Idempotency-Key` | `Repository` + 로컬 DB + outbox |

- 셋업은 `api/fragments/`(기본 조각)만, plan 은 `openapi.yaml` 본문만 고친다. 코드 생성이 합친다.
- 앱은 mock 서버로 끝까지 가고, 실서버 전환은 `API_BASE_URL` 하나. mock 은 `twbuild mock [--port 8787]`(`mock.py`): 2xx 예시를 그대로, 보호 오퍼레이션에 Bearer 없으면 401(Unauthorized 예시), 본문은 검증하지 않는다. Android 에뮬레이터는 `http://10.0.2.2:8787`.

## 11. 사람 할 일 · 안전

- 막지 않고 placeholder · mock 으로 진행하고 사람 할 일로 모은다. 정본은 `config/placeholders.json` → `.env.example` · `SETUP.md` 생성.
- 값은 `.env.local`(gitignore). `twbuild init` 이 묻고, `twbuild doctor` 가 ✅/❌.
- 시크릿 · 개인정보는 pre-commit 훅(wire 가 `.git/hooks/pre-commit` 에 설치 — 워크트리 공용, `twbuild scan --staged`; 다른 훅이 있으면 두고 doctor 가 알린다) · 머지 전 브랜치가 바꾼 파일 전부 검사(걸리면 `blocked`, 사람이 지운다)로 막고, 채팅 출력은 마스킹. 계약 · 디자인 · 문서 경로와 `example` 이 있는 줄은 일반 규칙(assignment)을 안 본다(응답 예시). 값은 앞 3글자만 보인다.
- 권한은 **욜로(bypass) 모드를 권한다** — 단, 프로젝트 설정(`.claude/settings*.json`)으로는 켤 수 없다(Claude Code 2.1.257+). 사용자 설정(`~/.claude/settings.json` permissions.defaultMode) 또는 `claude --permission-mode bypassPermissions` 로 켜고, 서브에이전트는 메인 세션 모드를 물려받는다. wire 는 프로젝트 settings 에 하네스 명령 허용 목록과 거부 목록만 더하고, doctor · report 가 켜는 법을 안내한다.
  확인 창이 없으므로 위험 동작은 PreToolUse 훅(`hooks/guard.py`)이 **차단**한다(경보 아님, 거부 사유는 규칙 ID): H1 원격 push · H2 git 이력 재작성 · H3 레포 밖 쓰기 · H4 보호 구역(design/ · api/generated · api/fragments · .twbuild/ · `Networking/Generated`) · H5 민감 파일 · 환경 변수 덤프 · H6 설치 · 권한 상승 · H7 Claude Design 쓰기.
  doctor 는 그 외에 워크스페이스 신뢰(`~/.claude.json` — 헤드리스 세션은 미신뢰 레포의 allow 목록을 무시한다) · pre-commit 훅 · 기기 · 공개 스킬 설치를 보인다(막지는 않는다).

## 12. 언어

에이전트가 읽는 것(스킬 · 프롬프트 · 에이전트 정의 · rules)은 영어 명령문, 사람이 읽는 것(보고서 · 사람 할 일 · 거부 메시지)은 한국어.

## 13. 측정

하네스 유지보수용. 같은 잣대로 사이클 · 화면 · 플랫폼 · 하네스 버전을 비교한다. 보기는 `twbuild stats` 터미널 표 하나.

| 구간 | 재는 곳 | 뜻 |
|---|---|---|
| 노드 실행 | `advance`/`submit` 래퍼 (LangGraph `stream_mode="debug"` task 이벤트) | 결정적 코드 (intake 파서 · 초안 생성 · smoke · merge) |
| 과제 처리 | 과제 발행 → `submit` | lead 작업 (intake · plan) |
| 개발자 과제 | `SubagentStart` → `SubagentStop` 훅 (`agent_id`) | 구현. 안의 빌드 · `check` 는 따로 |
| 사람 대기 · 기기 대기 | `blocked` → 재개 · 기기 잠금 대기 | 성능에서 뺀다 |

- 지표: 시간(위 구간 · 빌드 `build_ms` · 기기 `device_ms` — smoke 이벤트) · 화면별 시도 횟수 · 첫 시도 통과율 · 실패 층 · 규칙 ID별 위반 · `blocked` 사유 · decide 수 ·
  토큰(입력 · 출력 · 캐시 — `SubagentStop` 때 트랜스크립트 usage 합산) · 못 잼 수.
- 비교: 트리 노드 수로 나눈 값(노드당 시간 · 토큰). 모든 기록에 플러그인 버전 · 커밋 · 모델 · 설정 해시를 붙인다.
- 기록: `.twbuild/metrics/events.jsonl` (추가 전용, gitignore). 래퍼 · 훅 · CLI 만 쓴다 — **노드 안에서 쓰지 않는다**(재개 때 중복). 키 `(thread, 노드, 시도)` 는 한 번만.
  merge 가 기능 요약 `.twbuild/metrics/cycles/<기능>.json`(화면 · 트리 노드 수 · 과제별 시도 · 첫 시도 통과율 · 빌드 · 개발자 시간 · 토큰 · 노드당 값 · 결정 수 · 못 잼 수)을 `ledger(…)` 커밋에 넣는다(마스킹 · 경로 없음; `.gitignore` 블록이 `.twbuild/metrics/cycles/` 와 `lock.json` 만 예외로 둔다).
- LLM 자기신고는 쓰지 않는다. `twbuild stats`(노드 · 과제 · 화면별 표) · `--feature <기능>`(요약 표) · `--compare`(기능별 한 줄 — 노드당 정규화 · 플러그인 버전). 못 잰 칸은 "못 잼".
- 외부 도구(OTel · LangSmith 등) · HTML 대시보드는 두지 않는다 — LLM 이 그래프 밖이라 트레이서엔 결정적 노드만 보이고, 외부 전송은 11장과 충돌한다.

## 14. 앱 구조 — MVVM + UDF (기본)

코드는 에이전트가 쓰므로 패턴은 단순하고, 두 플랫폼이 1:1 이고, 생성기 · 게이트가 기계적으로 잴 수 있어야 한다.

```
View ──Action──▶ ViewModel ──▶ 데이터 계층 { Repository · Store · Draft } ──▶ API 클라이언트(생성물)
  ▲                  │              └ 로컬 DB + outbox (10장)
  └──── UiState ─────┘
```

| 층 | iOS | Android | 출처 |
|---|---|---|---|
| View | SwiftUI | Compose | 구조 초안 |
| UiState | 불변 `struct` | 불변 `data class` | 생성기 — 트리의 `bind` · `if` 상태 키 |
| Action | `enum` | `sealed interface` | 생성기 — 트리의 `on_*` |
| ViewModel | `@Observable` + `send(_:)` | `ViewModel` + `StateFlow` + `onAction()` | 개발자 |
| 데이터 계층 | protocol | interface | 개발자 — 데이터 과제 (아래 표) |
| 화면 전환 | `Route` enum + 라우터 하나 | `Route` sealed + NavHost 하나 | 플랜 interactions · 푸시 딥링크와 같은 목록 |
| 의존성 | 생성자 주입 + `AppContainer` | 생성자 주입 + `AppContainer` | 프레임워크 없음 |

- **ViewModel 은 화면 단위**(= 레이아웃 트리 파일 하나 = 플랜 하나 = 머지 단위). 데이터 단위로 만들지 않는다 — 데이터는 Repository 가 엔티티 단위로 맡고,
  여러 화면이 같은 데이터를 보면 같은 Repository 를 구독한다(ViewModel 공유 금지). 화면 안의 하위 뷰는 ViewModel 없이 UiState 일부와 Action 만 받는다.
**데이터 계층** — 한 계층 안에서 수명 · 저장으로 나눈다. 이름 접미사로 구분한다.

| 객체 | 담는 것 | 수명 | 저장 |
|---|---|---|---|
| `*Repository` | 서버와 동기화되는 엔티티 (`PostRepository`) | 앱 (`AppContainer`) | 로컬 DB + API — 로컬 DB 가 정본 |
| `*Store` | 앱 전역 상태 (`SessionStore` · 설정) | 앱 (`AppContainer`) | 키체인 · 키스토어 · 설정 |
| `*Draft` | 저장 전 입력 (`SignupDraft`) | 흐름 하나 (라우터가 시작 때 만들고 끝나면 버림) | 메모리 — 마지막에 Repository 로 넘긴다 |

- 여러 화면이 같은 데이터를 쓰면 같은 데이터 객체를 구독한다(iOS `AsyncStream` · Android `Flow`). 바꿀 때도 그 객체를 거친다 → 구독하는 화면이 모두 갱신된다.
- 화면 사이에는 ID 만 넘긴다(`Route.detail(id)`). 객체를 넘기지 않는다(복사본이 어긋난다).
- 여러 단계 흐름은 ViewModel 을 공유하지 않고 Draft 를 각 단계 ViewModel 에 주입한다(nav-graph 범위 ViewModel 안 씀 — 두 플랫폼 동일 구조).
- **데이터 과제**: 데이터 객체는 여러 화면이 쓰는 공용 코드라 화면 과제보다 먼저 만든다. 목록은 plan 의 `data:` · openapi 리소스에서 결정적으로 뽑는다. 화면 과제는 쓰기만 하고 고쳐야 하면 `blocked`.
- 상태는 ViewModel 안에서만, Action → 새 UiState 한 방향으로 바뀐다. View 는 상태를 갖지 않는다(포커스 · 스크롤 같은 순수 UI 상태 제외).
- 폴더는 기능별: `Features/<기능>/<화면>/{View, State, Action, ViewModel}` · `Core/{DesignSystem, Networking(생성물), Data}`. 모듈 하나로 시작한다.
- 쓰지 않는다: UseCase 층(Clean Architecture) · TCA · 완전한 MVI reducer · Hilt · Swinject.
- config `architecture` 로 고른다(기본 `mvvm-udf`, 다른 값은 "나중에"). 생성기 템플릿은 `templates/draft/<플랫폼>/<패턴>/`. 첫 화면이 머지되면 잠긴다.

## 설정 — `.twbuild/config.yaml`

```yaml
platforms: [ios, android]         # 첫 셋업은 툴체인 실측으로 정한다
architecture: mvvm-udf            # 첫 머지 뒤 잠김 — merge 가 .twbuild/lock.json(커밋)에 적고 doctor 의 config 검사가 바뀜을 막는다
min_os: {ios: 17, android: 26}    # @Observable = iOS 17+. 첫 머지 뒤 잠김
app: {name: "", product: "", id: ""}   # interview 가 채운다. product = ASCII PascalCase, id = com.example.<slug> (첫 머지 뒤 잠김)
auth: {providers: [email, apple, google]}
setup: {build: true}             # selfcheck 에서 툴체인이 있으면 빈 골격을 한 번 빌드
smoke: {device: merge}            # every | merge | off
budget: {attempts_per_screen: 5}
design:
  fetch: {include: [], exclude: [], max_bytes: 262144}
agents:
  lead:    {skills: [archify]}       # 필요할 때만 — HTML 결과, 문서에 넣을 땐 이미지 내보내기
  ios:     {model: sonnet, skills: [swiftui-expert, swift-concurrency, swift-security, authentication, push-notifications, app-store-review]}
  android: {model: sonnet, skills: [jetpack-compose, compose-state-and-effects, kotlin-concurrency-and-flow, security, identity, navigation, play, edge-to-edge]}
```

공개 스킬 출처: AvdLee/SwiftUI-Agent-Skill · dpearson2699/swift-ios-skills(PolyForm — 사용자 설치만) · android/skills · chrisbanes/skills(Compose · Kotlin 만) · tt-a1i/archify. 셋업이 대상 레포 `.claude/skills/` 에 커밋 고정으로 설치한다.

## 구성

| 위치 | 역할 |
|---|---|
| `.claude-plugin/` | 매니페스트 |
| `skills/twbuild/` · `skills/setup/` | lead 지침 · 셋업 과제 |
| `skills/dev-loop/` · `skills/{ios,android}-translate/` · `skills/{ios,android}-playbook/` · `skills/harness-rules/` | 개발자 코어 스킬 — 절차 · CSS→네이티브 번역표(두 플랫폼 같은 행 순서) · 빌드 환경 · 규칙 ID(T · H · D) |
| `agents/{ios,android}-dev.md` | 역할 · 경계 · 입출력만. `skills:` 로 코어 스킬 프리로드, `tools:` 에 claude-design · Agent 없음. 플러그인 에이전트 타입 `twbuild:ios-dev` |
| `server/` | `run.py`(런처 · venv 부트스트랩 `~/.claude/plugins/data/twbuild/venv` · CLI: serve · doctor · status · advance · submit · init · stats · test · decide · design · tokens · scan · device · skills · gen · mock) · `twbuild/`: util · yaml_lite · config(+ 잠금) · leaks(+ 파일 검사) · git · probe(doctor) · contract · gen(계약 → Swift · Kotlin 모델 · 클라이언트 · 디코딩 검사) · mock · setup · metrics(+ 기능 요약 · compare) · graph(LangGraph 셋업 그래프 · 구동) · cycle(사이클 그래프) · draft(구조 초안 생성기) · gate(T1~T10 · 빌드) · device(기기 층) · skills(공개 스킬 설치) · fonts(웹폰트) · decide(결정 원장 `.claude/rules/team/_decisions.json` → rules md 생성) · router · server(MCP: status · advance · submit · doctor · design_*) · tokens · tree · design. 루트는 `CLAUDE_PROJECT_DIR` |
| `hooks/` | `guard.py`(H1~H7 차단) · `design_guard.py`(D1~D5 검문) · `design_capture.py`(캡처 · 목록 etag) · `decisions.py`(SubagentStart 에 기능의 결정 전부 · PreToolUse 에 새 결정만, `agent_id` 기준 중복 제거) · `agent_metrics.py`(SubagentStart→Stop 시간 · 트랜스크립트 usage 합산). 전부 표준 라이브러리, 판정 코드는 서버 모듈과 공유 |
| `templates/` | 모노레포 골격 · 계약 조각 · 최소 토큰 · placeholders · `pre-commit.sh` · `gitignore.block`(블록이 템플릿과 다르면 wire · prepare 가 갱신) · 구조 초안(`draft/<플랫폼>/<패턴>/`) |
| `tests/` | `run.sh` → `cases.py`(+ 형제 `cases_device.py` · `cases_skills.py` · `cases_gen.py`, 같은 CASES 에 등록) — 임시 레포 · 픽스처 `fixtures/mini.dc.html` — 셋업 그래프 끝까지 · 계약 · 훅 · 토큰 · 트리 · design run · 사이클 끝까지 · 시크릿 검사 · 기기(가짜 도구) · 스킬(가짜 tarball) · 생성기 |

## handoff-agent 에서 가져올 것 (`../handoff-agent`, 이식 후 레포와 이 절 삭제)

가져왔다: `leaks.py` · `git.py` · `util.py` 일부 · `api.py` YAML 파서(→ yaml_lite) · 라우트 · `derive.py` 레이아웃 트리(→ tree) · `hooks/guard.py` · `run.py` venv 부트스트랩 · `graph.py` task/submit 패턴 · 테스트 방식 · 멱등 마커 배선 · "남은 칸만 묻기" · `gen.py`(→ gen: 계약 모델 · 클라이언트, MVVM 경로 · Sendable · kotlinx-serialization 으로 재설계).
남은 것: 빌더 CSS → SwiftUI/Compose 번역표의 나머지 행(→ `<플랫폼>-translate`). 그 뒤 레포와 이 절을 지운다.

## 금지

- 생성물 · `design/` 손으로 고치기
- 트리와 다른 구조 · 트리에 없는 직접값 · 디자인을 하네스가 판단해 바꾸기
- 리포트 · 자기신고로 판정하기 (다시 잰다) · 침묵하는 검사 · 통과로 위장한 "못 잼"
- 그래프 노드에서 부작용 뒤 interrupt
- 시크릿 · 개인정보 · 유료 자료를 레포나 채팅에 싣기
- 결정을 `twbuild decide` 밖에서 쓰기 · 과제 경계 넘기

## PoC

| # | 확인 | 결과 |
|---|---|---|
| 1 | 플러그인 에이전트 `skills:` 프리로드 | ✅ `twbuild:dev-loop` · `dev-loop` 둘 다. 에이전트 타입은 `twbuild:<이름>` |
| 2 | 서브에이전트 안 훅 `additionalContext` | ✅ SubagentStart · PreToolUse · PostToolUse 모두. 입력에 `agent_id` · `agent_type` |
| 3 | 워크트리에서 `.claude/rules` `paths:` | ✅ 그 워크트리의 rules 가 워크트리 기준으로 로드. 메인 레포 rule 은 안 붙음 → 결정은 훅 주입, rule 은 전부 경로 스코프 |
| 4 | 화면 하나 한 사이클의 수렴 횟수 · 시간 | ✅ 2026-10-12 사운드스케이프 forest: 데이터 2회(T6 이름 패리티 재작업 1회) · onboarding 1회 · home 1회 모두 통과 · 머지. 개발자 과제(두 플랫폼 병렬) 평균 9m51s, 4회 39m25s. 정적 위반 0 · 빌드 실패 0. 에이전트 토큰은 훅 미설치 세션이라 못 잼 |
| 5 | 기기 스모크를 머지 직전 한 번으로 감당 | ✅ 2026-10-13 사운드스케이프 iOS: iPhone 17 Pro 시뮬레이터에 설치 · 실행 · 5초 생존 9.6s(첫 회는 부팅 포함 통과). Android 는 에뮬레이터 미기동으로 못 잼 → 사이클 실측은 아래 |
| 6 | 디자인 import — 실제 프로젝트(사운드스케이프) 트리 · 토큰 | ✅ 화면 8개 · 생성 토큰으로 두 플랫폼 빌드 통과 (훅 경로는 플러그인 설치 세션에서 실측 필요) |

2026-10-11 · Claude Code 2.1.296 · 카나리 토큰 + 서브에이전트 트랜스크립트로 판정. 디자인 커넥터 실측: 텍스트 11개 바이트 일치 · 검문 거부 동작 · PNG 거부 · standalone HTML 은 1 MB 한 줄이 256 KiB 상한에 잘림.

## 나중에

review 노드(킥오프 검토) · fix 분류 노드 · retro(13장 지표로 개선 효과 확인) · 툴 장기 메모리 · 승격 루프 · 생성기 스타일 규칙 승격 ·
기기 접근성 트리 덤프 비교 · 백엔드 API 스모크 · 스크린샷 · 계약 옵션(실시간 · 업로드) · 에이전트 교체 탈출구 ·
메인 세션 격리 장치 · 크기 예산 · 문구 키 · 아이콘 연결 · 백엔드 개발자 · 에이전트 팀(팀원 간 메시지).
