from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_builds_the_vue_frontend_without_removed_root_static_files() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "node --check static/app.js" not in workflow
    assert "node --check static/review.js" not in workflow
    assert "working-directory: frontend" in workflow
    assert "run: npm run build" in workflow
