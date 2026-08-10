from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
REPO = "ZJUSCODE/enterprise-complaint-copilot"
EXPECTED_FIELDS = {
    "repo",
    "commit",
    "verifiedAt",
    "testCommand",
    "passed",
    "failed",
    "skipped",
    "warnings",
    "evalCommand",
    "evalCases",
    "ciRunUrl",
}
COUNT_FIELDS = ("passed", "failed", "skipped", "warnings", "evalCases")
CI_URL_PATTERN = re.compile(
    r"^https://github\.com/ZJUSCODE/enterprise-complaint-copilot/actions/runs/[0-9]+$"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_junit_counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = (
        [child for child in root if _local_name(child.tag) == "testsuite"]
        if _local_name(root.tag) == "testsuites"
        else [root]
    )
    if not suites:
        raise ValueError("JUnit XML contains no testsuite")

    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    failed = failures + errors
    passed = tests - failed - skipped
    if passed < 0:
        raise ValueError("JUnit counts are inconsistent")
    return {"passed": passed, "failed": failed, "skipped": skipped}


def read_warning_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"(?<![0-9])([0-9]+)\s+warnings?\b", text, flags=re.IGNORECASE)
    return int(matches[-1]) if matches else 0


def read_eval_cases(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    total = payload.get("total")
    if not isinstance(total, dict):
        raise ValueError("evaluation report is missing total")
    all_cases = total.get("all_cases")
    category_counts = [
        value
        for key, value in total.items()
        if key.endswith("_cases") and key != "all_cases"
    ]
    if not isinstance(all_cases, int) or isinstance(all_cases, bool):
        raise ValueError("evaluation all_cases must be an integer")
    if not category_counts or any(
        not isinstance(value, int) or isinstance(value, bool) for value in category_counts
    ):
        raise ValueError("evaluation category counts must be integers")
    if all_cases != sum(category_counts):
        raise ValueError("evaluation total mismatch")
    return all_cases


def validate_record(record: dict[str, Any]) -> None:
    if set(record) != EXPECTED_FIELDS:
        raise ValueError("schema keys mismatch")
    if record["repo"] != REPO:
        raise ValueError("schema repo mismatch")
    if not isinstance(record["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", record["commit"]):
        raise ValueError("schema commit mismatch")
    try:
        verified_at = datetime.fromisoformat(record["verifiedAt"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("schema verifiedAt mismatch") from exc
    if verified_at.tzinfo is None:
        raise ValueError("schema verifiedAt must include timezone")
    for field in ("testCommand", "evalCommand"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"schema {field} mismatch")
    for field in COUNT_FIELDS:
        if not isinstance(record[field], int) or isinstance(record[field], bool) or record[field] < 0:
            raise ValueError(f"schema {field} mismatch")
    if not isinstance(record["ciRunUrl"], str) or not CI_URL_PATTERN.fullmatch(record["ciRunUrl"]):
        raise ValueError("schema ciRunUrl mismatch")


def build_record(
    *,
    junit_xml: Path,
    pytest_output: Path,
    eval_report: Path,
    test_command: str,
    eval_command: str,
    ci_run_url: str,
    commit: str,
    verified_at: str,
) -> dict[str, Any]:
    counts = read_junit_counts(junit_xml)
    record: dict[str, Any] = {
        "repo": REPO,
        "commit": commit,
        "verifiedAt": verified_at,
        "testCommand": test_command,
        **counts,
        "warnings": read_warning_count(pytest_output),
        "evalCommand": eval_command,
        "evalCases": read_eval_cases(eval_report),
        "ciRunUrl": ci_run_url,
    }
    validate_record(record)
    return record


def _build(args: argparse.Namespace) -> int:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    verified_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = build_record(
        junit_xml=args.junit_xml,
        pytest_output=args.pytest_output,
        eval_report=args.eval_report,
        test_command=args.test_command,
        eval_command=args.eval_command,
        ci_run_url=args.ci_run_url,
        commit=commit,
        verified_at=verified_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    record = json.loads(args.input.read_text(encoding="utf-8"))
    validate_record(record)
    print("schema_ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate the local Complaint verification handoff.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--junit-xml", type=Path, required=True)
    build.add_argument("--pytest-output", type=Path, required=True)
    build.add_argument("--eval-report", type=Path, required=True)
    build.add_argument("--test-command", required=True)
    build.add_argument("--eval-command", required=True)
    build.add_argument("--ci-run-url", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(handler=_build)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    validate.set_defaults(handler=_validate)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
