from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_step(name: str, command: list[str], cwd: Path = ROOT) -> bool:
    print(f"\n== {name} ==")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=cwd, text=True)
    if completed.returncode == 0:
        print(f"PASS {name}")
        return True
    print(f"FAIL {name} exit={completed.returncode}")
    return False


def check_file(path: Path, label: str) -> bool:
    exists = path.exists()
    print(f"{'PASS' if exists else 'FAIL'} {label}: {path.relative_to(ROOT)}")
    return exists


def check_report() -> bool:
    report_path = ROOT / "eval" / "v2_eval_report.json"
    if not check_file(report_path, "eval report"):
        return False
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {})
    required = [
        "route_accuracy",
        "tool_selection_accuracy",
        "citation_hit_rate",
        "guardrail_interception",
        "memory_followup_accuracy",
    ]
    missing = [key for key in required if key not in metrics]
    if missing:
        print(f"FAIL eval metrics missing: {', '.join(missing)}")
        return False
    print(
        "PASS eval metrics: "
        f"route={metrics['route_accuracy']} "
        f"tool={metrics['tool_selection_accuracy']} "
        f"citation={metrics['citation_hit_rate']} "
        f"guardrail={metrics['guardrail_interception']} "
        f"memory={metrics['memory_followup_accuracy']}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local readiness checks for the interview demo.")
    parser.add_argument("--full", action="store_true", help="Also run pytest and frontend production build.")
    parser.add_argument("--eval", action="store_true", help="Regenerate the offline eval report before checking it.")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend checks even in --full mode.")
    args = parser.parse_args()

    checks: list[bool] = []

    checks.append(check_file(ROOT / ".env.example", "env example"))
    checks.append(check_file(ROOT / "README.md", "README"))
    checks.append(check_file(ROOT / "docs" / "evaluation.md", "evaluation docs"))
    checks.append(check_file(ROOT / "docs" / "agent_governance.md", "agent governance docs"))
    checks.append(check_file(ROOT / "frontend" / "package.json", "frontend package"))

    checks.append(run_step("python syntax", [sys.executable, "-m", "py_compile", "app/runtime.py", "main.py"]))

    if args.eval:
        checks.append(run_step("offline eval", [sys.executable, "scripts/evaluate_rag.py", "--force-lexical"]))

    checks.append(check_report())

    if args.full:
        checks.append(run_step("pytest", [sys.executable, "-m", "pytest", "tests"]))
        if not args.skip_frontend:
            npm = shutil.which("npm")
            if not npm:
                print("FAIL frontend build: npm not found")
                checks.append(False)
            else:
                checks.append(run_step("frontend build", [npm, "run", "build"], cwd=ROOT / "frontend"))

    if all(checks):
        print("\nReady for demo.")
        return 0
    print("\nSome checks failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
