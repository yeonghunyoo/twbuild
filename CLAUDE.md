# CLAUDE.md

twbuild — iOS · Android 네이티브 개발자 둘과 리드로 이뤄진 가상 모바일 개발 팀을 굴리는 Claude Code 플러그인(하네스).
설계 원칙 · 흐름 · 팀 · 메모리 · 금지 사항은 `AGENT.md` 가 정본이다 — 코드를 고치기 전에 먼저 읽는다.

이 리포는 플러그인 자체다. `features/` `api/` `.twbuild/` 는 여기가 아니라 플러그인을 쓰는 대상 레포에 생긴다.
로컬 환경 메모(정리할 경로 · 비공개 링크)는 `CLAUDE.local.md`(gitignore)에 둔다.

## 현재 상태 · 다음 할 일

- M1 뼈대 완료 (2026-10-11) — 서버(`server/twbuild/`: 라우터 · 셋업 그래프 · probe=doctor · wire · interview · scaffold · selfcheck · report · 측정 · 계약 합치기) · MCP(`status/advance/submit/doctor`) · CLI(`bin/twbuild`) · 차단 훅(`hooks/guard.py` H1~H7) · 스킬(`twbuild` · `setup`) · 골격 템플릿(iOS xcodegen · Android Gradle, 둘 다 빈 골격 빌드 통과) · 테스트(`tests/run.sh`, 8개).
  실측과 다른 설계는 코드에 맞춰 둠: bypass 는 프로젝트 설정으로 못 켬(wire 는 allow/deny 만 씀, doctor 가 안내) · venv 는 `~/.claude/plugins/data/twbuild/venv` · 루트는 `CLAUDE_PROJECT_DIR` · interview 에 조건부 `ascii_name`. AGENT.md 갱신은 M2 뒤 한 번에.
- M2 디자인 import 완료 (2026-10-11) — `tokens.py`(styles.css → tokens.json · Tokens.swift · Tokens.kt) · `tree.py`(dc.html → 화면 후보 · 레이아웃 트리 · 노드 ID · 슬롯) · `design.py`(run 원장 · 허용 D1~D5 · 캡처 · finish 커밋 + 태그) · 훅(`design_guard.py` · `design_capture.py`) · CLI `twbuild design …` · 테스트 4개 추가(총 12).
  실측: 대상 레포 `~/orca/soundscape`(테스트 run) 에 셋업 + R-0001(사운드스케이프 명상 앱 forest.dc.html → 화면 8개) 적용. 훅 경로(캡처 래퍼 개행 처리)는 플러그인 설치 세션에서 아직 실측 전.
- M3 사이클 골격 완료 (2026-10-11) — `cycle.py`(intake → plan → prepare → dispatch → smoke → merge · blocked) · `draft.py`(트리 → SwiftUI · Compose 초안: View · UiState · Action · ViewModel · Route 등록 — 사운드스케이프 화면 8개 모두 두 플랫폼 컴파일 통과) · `gate.py`(T1~T5 정적 · 빌드) · `decide.py`(`twbuild decide`, 원장 → rules md) · 에이전트 2 · 스킬 5 · 훅(결정 주입 · 에이전트 측정) · MCP `design_*` · 테스트 13.
- 첫 실제 사이클 완료 (2026-10-12) — `~/orca/soundscape` forest: 데이터 과제(Preset · Session) + onboarding + home 머지(두 플랫폼 빌드 · T1~T6 통과). PoC 4 결과는 AGENT.md PoC 표. 이 run 에서 고친 하네스 버그: decide `--by` 파싱 · 주제 대소문자 · T4 가 디자인 데이터 색을 거부 · 과제 메모 수거 · T6 추가 · 지표 중복.
  lead 가 확인할 것(retro 전): 잠정 결정 D-06~D-10 · D-13~D-16 · D-18~D-32(두 플랫폼이 서로의 결정을 따랐음), 셸 프레임을 화면이 직접 그리는 임시 처리(D-18 — shell 화면 때 제거), 폰트 파일(Caprasimo · Figtree) 사람이 넣기, Android 는 기기 실행 미확인.
- 완료 점검 (2026-10-13) — 설계(AGENT.md) 항목별 실측 체크리스트. 고친 것: merge 가 원장 · 결정 · brief 를 `ledger(<기능>/<과제>)` 커밋으로 남김(첫 run 은 안 남겨 테스트 레포에 수동 커밋 `fb56a1b`) · 게이트 범위 T1~T6 표기 통일 · AGENT.md 상태 줄. 훅 5개는 단독 실행으로 동작 확인(플러그인 설치 세션 실측은 여전히 전).
- 남은 개발 (2026-10-13) — 플러그인 설치 세션 실측(`claude -p --plugin-dir`): MCP(`mcp__plugin_twbuild_twbuild__*`) · H1 차단 · `twbuild:ios-dev` · 결정 주입 · 에이전트 측정 모두 동작, 주입 15 KB 가 잘려 → 6 KB 상한. 구현: 기능별 측정 요약 커밋 + `stats --compare/--feature` · 빌드 · 기기 시간 · 첫 머지 뒤 설정 잠금 강제(`lock.json`) · pre-commit 시크릿 훅 + 머지 전 브랜치 검사 · doctor(훅 · 신뢰 · 기기 · 스킬). 포크 3개 병합: `device.py`(기기 층, iOS 실측 통과) · `gen.py` + `mock.py`(계약 → Swift · Kotlin 모델 · 클라이언트 · 디코딩 검사 · mock, 템플릿 계약 실측: 두 플랫폼 빌드 · 예시 16개 디코딩) · `skills.py`(공개 스킬 13개 설치 실측 · PolyForm 5개는 사람 할 일). 테스트 26.
- 디자인 시스템 과제 · `twbuild check` (2026-10-13) — plan 이 `design/ds/components/*.html` 이 있고 `ds.built` 가 없으면 `ds` 과제를 데이터 과제 앞에 둔다(`Core/DesignSystem/Catalog/<Name>`, trailing content 규약) · 게이트 T7(컴포넌트 이름 패리티) · T8(class 노드는 구현된 컴포넌트 호출) · 초안이 class 노드를 `<Name> { }` 로 감싼다 · `twbuild check`(개발자용 정적 게이트 · 패리티 · `--build`). 테스트 26. 사운드스케이프엔 아직 카탈로그 html 이 없다(R-0001 은 부트스트랩 run 이 아니었다) — 다음 design run 을 `--bootstrap` 으로.
- 웹폰트 · 헤드리스 사이클 실측 (2026-10-13) — `fonts.py`(Google Fonts 정적 TTF → `design/ds/fonts` → 두 앱 등록 · `Fonts.swift/kt` · T9) 사운드스케이프에 Caprasimo · Figtree 4개 등록 · 빌드 통과. 헤드리스 lead(`claude -p --plugin-dir`)로 sound 화면 사이클: 리드 혼자 intake · plan · 배차 · 결정까지 처리, 하네스 버그로 blocked → 고침(워크트리 디코딩 설정 · 생성물 · local.properties · prepare 의 main 합치기 · 재작업 프롬프트 · lead 결정 확정 · 훅 거짓 양성 5종). 테스트 28.
- T10 · svg (2026-10-13) — 게이트 T10(UiState 필드 이름 · 타입, Action 이름 · 매개변수 타입 패리티) · 트리 icon 노드에 `svg` 경로 데이터(해시 제외, 초안 주석) — 헤드리스 run 의 "문제" 절(타입 불일치 · 하트/별 갈림)에서 나온 것. 테스트 28.
- sound 머지 · 두 번째 사이클 (2026-10-14) — 헤드리스 lead 4차에서 sound 화면 머지(5개 층 · 기기 iOS + Android 통과, 측정 요약 커밋). 리드 보고의 문제로 고친 것: 하네스 · 사람 원인 멈춤은 시도 차감 · 증거 보고서 결정 범위 · stats 표 배차/스모크/빌드 합 · 재작업 머리말 · T7 범위 · 히어독 · 재작업 플랫폼 분리 · 옛 생성물 정리 · JUnit 템플릿. 잠정 결정 29건 정리(확정 21 · 뒤집기 1 · 폐기 1 · 셸 임시 5 잠정 유지). R-0002 부트스트랩 run(카탈로그 · foundations · readme · theme 캡처) + spec 이어받기. 번역표 포팅 완료 · handoff-agent 레포 · 메모리 · `~/.claude.json` 항목 삭제. 세 번째 사이클(stats · nowPlaying · settings + SettingsStore) 헤드리스 진행 중.
- review · fix 분류 · retro (2026-10-14) — AGENT.md 4장의 사이클 노드가 전부 구현됐다: review(플랜 ↔ 트리 린트 → lead 가 수정 병합 또는 accept) · fix 분류(rework · retry · blocked — 하네스 · 계약 원인은 재작업으로 보내지 않는다) · retro(이력 `cycles/<기능>.history.json` · `_retro.md` · `stats --retro`). 테스트 29.
- 원 설계(AGENT.md)에서 남은 구현은 없다. 그 밖은 "나중에" 목록.
- 2026-10-11 단순화: 핵심(디자인 정본 → 레이아웃 트리 → 구조 초안 → iOS ∥ AOS → 게이트 3층)만 남기고 나머지는 AGENT.md "나중에".
  지시 관리는 "정본 > 과제 프롬프트 > 나머지" 세 줄로 확정.
- 측정 확정 (2026-10-11) — 구간별 시간 · 시도 · 토큰 지표, 래퍼 · 훅에서 기록(노드 안 금지), `twbuild stats` 터미널 표만. AGENT.md 13장.
- 셋업 사용성 확정 (2026-10-11) — doctor 사전 점검 · 권한 욜로 기본 + 위험 동작 차단 훅 · 질문은 전부 ask · interview 는 앱 주제 · 이름 · 요구사항 셋만. AGENT.md 4장 · 11장.
- 앱 구조 확정 (2026-10-11) — MVVM + UDF 기본, ViewModel 은 화면 단위 · 데이터는 Repository(엔티티 단위), UiState · Action 은 생성기가 트리에서. 데이터 계층은 Repository · Store · Draft(수명으로 구분), 화면 사이엔 ID 만, build 에 데이터 과제 선행. AGENT.md 14장.
- 미정: 디자인 링크 위치(지금은 intake 에서 lead 가 묻는다).
- 다음: 화면 하나로 한 사이클 도는 골격
  (그래프 노드 · `ios-dev`/`android-dev` 에이전트 · `dev-loop`/`translate`/`playbook` 스킬 · MCP 배선 · 디자인 훅 · `twbuild decide` · 측정 기록(래퍼 · SubagentStart/Stop 훅) — PoC 4 를 이걸로 잰다).
- 단순화 전 AGENT.md(500줄)는 첫 커밋 전에 바뀌어 이력이 없다 — "나중에" 항목을 되살릴 때 설계 문서 변경 이력을 참고한다.

## 작업 방식

- 사용자와는 한국어로 대화한다. 에이전트용 텍스트(스킬 · 프롬프트 · 에이전트 정의)는 영어 명령문.
- 설계를 바꾸면 AGENT.md 를 같이 고친다. 사람용 요약 문서 "twbuild 설계 · 설명서"(Claude Docs, 링크는 `CLAUDE.local.md`)도 해당 섹션과 "변경 이력" 표를 함께 갱신한다.
