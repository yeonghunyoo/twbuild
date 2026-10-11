"""MCP 계층 — `mcp` 를 import 하는 유일한 파일. 구현은 router · probe 에 있다.

사람 승인(elicitation)은 없다 — 멈춤은 task(submit 으로 재개) 와 blocked(사람이 풀면 재개) 둘뿐이다.
채팅으로 나가는 응답은 전부 시크릿 · 개인정보를 마스킹한다.
"""
import os

from mcp.server.mcpserver import MCPServer

from . import leaks, probe, router

ROOT = os.path.abspath(os.environ.get("TWBUILD_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

mcp = MCPServer(
    "twbuild",
    instructions=("Workflow server of the twbuild harness: it builds iOS and Android screens 1:1 from a Claude Design snapshot. "
                  "Call `advance` to move the graph to its next stop. If the response has `pending` (kind=task), do that task "
                  "and hand the result back with `submit(payload)` — the payload shape is in the task. When `report` is present, "
                  "show it to the user verbatim (Korean). Never edit config, design/ or generated files by hand."),
)


def _out(r):
    return leaks.mask_all_deep(r)


@mcp.tool()
def status() -> dict:
    """Where the harness is: wired? ready? a task waiting? Call this when unsure what to do next."""
    return _out(router.status(ROOT))


@mcp.tool()
def advance() -> dict:
    """Run the graph to its next stop (the router picks setup or cycle). A `pending` task must be done and handed back with submit."""
    return _out(router.advance(ROOT))


@mcp.tool()
def submit(payload: dict) -> dict:
    """Hand back the answer to the pending task. `payload` follows the task's `submit` shape; partial answers are allowed where the task says so."""
    return _out(router.submit(ROOT, payload))


@mcp.tool()
def doctor() -> dict:
    """Pre-flight check of this repo and machine (toolchains, git, config, contract, readiness) as a Korean markdown table for the user."""
    return _out({"ok": True, "markdown": probe.doctor_markdown(ROOT)})


def main():
    mcp.run(transport="stdio")
