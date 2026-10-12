# twbuild

Claude Design 디자인과 같은 화면을 iOS · Android 에 같은 구조로 만드는 Claude Code 플러그인.
lead(메인 세션)와 개발자 둘(ios-dev · android-dev)이 LangGraph 순서대로 화면 단위로 동시에 만들고, 스모크를 통과하면 자동 머지한다.

> **상태: v0.0.1 — 한 사이클이 끝까지 돈다.** 셋업 그래프(사전 점검 · 질문 셋 · 골격 · 계약 → 클라이언트 생성 · 공개 스킬 설치 · 빈 골격 빌드 + 디코딩 검사) → 디자인 import(design run · 레이아웃 트리 · 토큰) →
> 사이클 그래프(intake → plan → 구조 초안 → 개발자 둘 → 스모크: T1~T6 · 빌드 · 계약 디코딩 · 기기 실행 → 자동 머지 + 측정 요약 커밋)까지 실제 디자인 · 플러그인 설치 세션으로 검증했다.
> 아직 없는 것: review/fix/retro 노드 · 디자인 시스템 부트스트랩 과제 · 웹폰트. 설계 정본은 [`AGENT.md`](AGENT.md).

## 설치

```
claude plugin marketplace add yeonghunyoo/twbuild
claude plugin install twbuild@twbuild
```
요구 사항: Claude Code · Python 3.10+ · Xcode + xcodegen(`brew install xcodegen`) · Android SDK + JDK 17+ + gradle(wrapper 생성용) · Claude Design 커넥터.
첫 실행 때 `~/.claude/plugins/data/twbuild/venv` 에 의존성(langgraph · mcp)을 설치한다 (네트워크, 1회).

## 쓰는 법

1. 앱을 만들 레포에서 `/twbuild` — 사전 점검(`twbuild doctor` 와 같다) 뒤 **앱 주제 · 이름 · 요구사항** 셋만 묻고 골격을 만든다. 나머지(플랫폼 · 로그인 · 아키텍처 MVVM+UDF · 최소 OS)는 실측 · 기본값이고 보고서 표에 보인다 — 바꾸려면 `.twbuild/config.yaml`.
2. 다시 `/twbuild` — 기능 하나가 한 사이클이다. 디자인을 처음 들여오면 lead 가 Claude Design 프로젝트 · 화면을 묻고 받아 레이아웃 트리를 만든다(화면 후보를 확인해 이름을 정한다). plan 뒤 데이터 과제 → 화면마다 iOS ∥ Android 개발자가 각자의 워크트리에서 구조 초안 위에 구현한다.
3. 스모크(정적 트리 정합성 T1~T6 + 두 플랫폼 빌드)를 통과하면 화면 단위로 squash 머지 · 태그 · 증거 보고서. 실패하면 위반 · 로그 꼬리가 실린 재작업 과제가 자동으로 나간다(화면당 5회).
4. 측정은 `twbuild stats` 터미널 표 — 노드 · 과제 처리 시간 · 화면별 시도 · 빌드 · 기기 · 위반 · 개발자 과제 시간 · 토큰. `--feature <기능>` 은 기능 요약, `--compare` 는 기능별 한 줄(노드당 정규화 · 플러그인 버전) — 머지가 `.twbuild/metrics/cycles/<기능>.json` 을 커밋한다.
5. 그 외 CLI: `twbuild scan [--staged]`(시크릿 검사 — pre-commit 훅이 부른다) · `twbuild mock [--port 8787]`(계약 예시로 응답하는 mock 서버) · `twbuild device ios|android`(기기 층만 다시) · `twbuild skills [install]`(공개 스킬 상태 · 설치) · `twbuild gen`(계약 → 클라이언트 재생성).

권한: 욜로(bypass) 모드를 권하지만 프로젝트 설정으로는 켤 수 없다 — `claude --permission-mode bypassPermissions` 또는 `~/.claude/settings.json`. 위험 동작(push · 이력 재작성 · 레포 밖 쓰기 · 보호 구역 · 시크릿 · 설치 · Claude Design 쓰기)은 훅이 차단한다. 시크릿 값은 `twbuild init` 으로 `.env.local` 틀만 만들고 에디터로 채운다.

## 개발

```
tests/run.sh            # 자기 검사 (임시 레포에서 셋업 · 디자인 import · 사이클 그래프 끝까지)
claude plugin validate .
```

라이선스: [MIT](LICENSE)
