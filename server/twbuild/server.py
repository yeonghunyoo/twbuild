"""MCP 계층 — `mcp` 를 import 하는 유일한 파일. 구현은 router · probe 에 있다.

사람 승인(elicitation)은 없다 — 멈춤은 task(submit 으로 재개) 와 blocked(사람이 풀면 재개) 둘뿐이다.
채팅으로 나가는 응답은 전부 시크릿 · 개인정보를 마스킹한다.
"""
import os

from mcp.server.mcpserver import MCPServer

from . import design, leaks, probe, router, util

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


def _design(fn):
    try:
        return _out(fn())
    except design.DesignError as e:
        return {"ok": False, "message": str(e)}


@mcp.tool()
def design_start(feature: str, project_id: str, screens: list, ds_project_id: str = "", bootstrap: bool = False) -> dict:
    """Open a design run for `feature`: afterwards the Claude Design connector may read the listed .dc.html screens (plus what they reference and the design-system files) — the hooks capture them into design/. bootstrap=true also allows the design-system catalog (first cycle)."""
    return _design(lambda: {"ok": True, "run": design.start(ROOT, feature, project_id, screens, ds_project_id or None, bootstrap=bootstrap),
                            "message": "Run opened. Read the screen files with the connector (read_file); then design_trial, confirm screen ids with the user, render_preview(project_id, <screen .dc.html>) and design_finish(spec, preview_url=<its serve_url>)."})


@mcp.tool()
def design_trial(spec: list | None = None) -> dict:
    """Dry run over the captured .dc.html of the active run: detected screens (id · kind · when · style) and per-screen tree status. Pass `spec` (edited screens list) to see the effect of renames."""
    def go():
        run = design.active(ROOT)
        if not run:
            raise design.DesignError("No active design run — call design_start first.")
        out = []
        for f in run["files"]:
            if f["path"].endswith(".dc.html"):
                out.append({"file": f["dest"], **design.trial(ROOT, util.read_text(os.path.join(ROOT, f["dest"]), ""), spec)})
        return {"ok": True, "trials": out, "message": "Confirm the screen ids with the user (rename with spec), then render_preview the screen .dc.html and design_finish(spec, preview_url=<serve_url>)."}
    return _design(go)


@mcp.tool()
def design_finish(spec: list | None = None, preview_url: str = "") -> dict:
    """Close the active design run: write layout trees and tokens, update the ledger, commit + tag `design-run/R-000N`. `spec` = the confirmed screens list from design_trial (ids may be renamed).
    `preview_url` = the `serve_url` from the connector's render_preview of the screen .dc.html (call it right before this): the harness renders one reference image per screen (design/<feature>/shots) for the visual check. It is used once and never stored."""
    return _design(lambda: {"ok": True, **design.finish(ROOT, spec, preview_url=preview_url or None), "message": "Design run finished. Continue the cycle: submit the intake task."})


@mcp.tool()
def design_abort() -> dict:
    """Abort the active design run (nothing captured is committed)."""
    return _design(lambda: {"ok": True, "run": design.abort(ROOT)})


def main():
    mcp.run(transport="stdio")
