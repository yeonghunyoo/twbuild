# twbuild

Claude Design 디자인과 같은 화면을 iOS · Android 에 같은 구조로 만드는 Claude Code 플러그인.
lead(메인 세션)와 개발자 둘(ios-dev · android-dev)이 LangGraph 순서대로 화면 단위로 동시에 만들고, 스모크를 통과하면 자동 머지한다.

> **상태: 설계 단계 (v0.0.1).** 설계 문서(`AGENT.md`)와 플러그인 매니페스트만 있다. 설치는 되지만 아직 기능(스킬 · 에이전트 · MCP 서버 · 훅)이 없다.

## 설치

```
claude plugin marketplace add yeonghunyoo/twbuild
claude plugin install twbuild@twbuild
```

## 쓰는 법 (계획)

1. 앱을 만들 레포에서 `/twbuild` — 사전 점검(`twbuild doctor`) 뒤 앱 주제 · 이름 · 요구사항 셋만 묻고 골격을 만든다.
2. 다시 `/twbuild` — Claude Design 링크 · 화면을 고르면 기능 한 사이클(intake → plan → build → smoke → merge)이 돈다.
3. 결과는 화면별 증거 보고서와 `twbuild stats` 로 본다.

요구 사항(계획): Claude Code · Python 3.10+ · Xcode(iOS) · Android SDK + JDK(Android) · Claude Design 커넥터.

## 보안

- 권한은 bypass(욜로) 모드가 기본이 될 예정이다 — 원격 push · 레포 밖 쓰기 · 삭제 · 시크릿 파일 접근 · git 이력 재작성은 훅이 차단한다.
- 시크릿 값은 대화를 지나지 않는다(`.env.local`, gitignore).

설계 정본: [`AGENT.md`](AGENT.md) · 라이선스: [MIT](LICENSE)
