from __future__ import annotations

import glob
import shlex
from pathlib import Path

from app.config import BASE_DIR, FRONTEND_ASSETS_DIR, FRONTEND_DIST_DIR


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = ROOT / "Dockerfile"


def test_ci_builds_the_vue_frontend_without_removed_root_static_files() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "node --check static/app.js" not in workflow
    assert "node --check static/review.js" not in workflow
    assert "working-directory: frontend" in workflow
    assert "run: npm run build" in workflow


def test_runtime_frontend_paths_point_only_to_vite_dist() -> None:
    assert FRONTEND_DIST_DIR == BASE_DIR / "frontend" / "dist"
    assert FRONTEND_ASSETS_DIR == FRONTEND_DIST_DIR / "assets"

    runtime_source = (ROOT / "app" / "runtime.py").read_text(encoding="utf-8")
    assert "Jinja2Templates" not in runtime_source
    assert "StaticFiles(directory=FRONTEND_ASSETS_DIR)" in runtime_source
    assert 'FRONTEND_DIST_DIR / "index.html"' in runtime_source


def test_every_local_docker_copy_source_exists() -> None:
    for raw_line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY ") or line.startswith("COPY --from="):
            continue

        tokens = shlex.split(line)
        for source in tokens[1:-1]:
            matches = glob.glob(str(ROOT / source))
            assert matches, f"Docker COPY source does not exist: {source}"


def test_ci_smokes_the_container_api_and_frontend() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "docker run --detach --name complaint-copilot-ci" in workflow
    assert "http://127.0.0.1:8000/api/health" in workflow
    assert "http://127.0.0.1:8000/" in workflow
    assert "if: always()" in workflow
    assert "docker rm --force complaint-copilot-ci" in workflow
