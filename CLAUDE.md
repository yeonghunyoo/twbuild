# CLAUDE.md

twbuild — iOS · Android 네이티브 개발자 둘과 리드로 이뤄진 가상 모바일 개발 팀을 굴리는 Claude Code 플러그인(하네스).
설계 원칙 · 흐름 · 팀 · 메모리 · 금지 사항은 `AGENT.md` 가 정본이다 — 코드를 고치기 전에 먼저 읽는다.

이 리포는 플러그인 자체다. `features/` `api/` `.twbuild/` 는 여기가 아니라 플러그인을 쓰는 대상 레포에 생긴다.
참고 구현: `../handoff-agent` (가져올 부품은 AGENT.md "handoff-agent 에서 가져올 것").
로컬 환경 메모(정리할 경로 · 비공개 링크)는 `CLAUDE.local.md`(gitignore)에 둔다.

## 현재 상태 · 다음 할 일

- 설계 초안 v0.0.1 (2026-10-11). 코드 없음. PoC 1~3 확인. 플러그인 매니페스트만 있어 설치는 되지만 기능은 없다.
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
