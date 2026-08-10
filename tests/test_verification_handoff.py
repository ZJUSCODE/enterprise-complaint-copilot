from __future__ import annotations

import json

import pytest

from scripts.build_verification_handoff import (
    EXPECTED_FIELDS,
    build_record,
    read_eval_cases,
    read_warning_count,
    validate_record,
)


def test_build_record_uses_junit_log_and_eval_report(tmp_path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuites><testsuite tests="5" failures="1" errors="0" skipped="1" /></testsuites>',
        encoding="utf-8",
    )
    pytest_output = tmp_path / "pytest.log"
    pytest_output.write_text("3 passed, 1 failed, 1 skipped, 2 warnings in 1.00s\n", encoding="utf-8")
    eval_report = tmp_path / "eval.json"
    eval_report.write_text(
        json.dumps({"total": {"all_cases": 7, "rag_cases": 2, "route_cases": 2, "tool_cases": 1, "guardrail_cases": 1, "memory_cases": 1}}),
        encoding="utf-8",
    )

    record = build_record(
        junit_xml=junit,
        pytest_output=pytest_output,
        eval_report=eval_report,
        test_command="python -m pytest tests -q",
        eval_command="python scripts/evaluate_rag.py --force-lexical",
        ci_run_url="https://github.com/ZJUSCODE/enterprise-complaint-copilot/actions/runs/123456789",
        commit="a" * 40,
        verified_at="2026-08-09T08:00:00Z",
    )

    assert set(record) == EXPECTED_FIELDS
    assert record["passed"] == 3
    assert record["failed"] == 1
    assert record["skipped"] == 1
    assert record["warnings"] == 2
    assert record["evalCases"] == 7
    validate_record(record)


def test_eval_total_must_equal_category_sum(tmp_path) -> None:
    report = tmp_path / "eval.json"
    report.write_text(json.dumps({"total": {"all_cases": 4, "rag_cases": 2, "route_cases": 1}}), encoding="utf-8")

    with pytest.raises(ValueError, match="evaluation total mismatch"):
        read_eval_cases(report)


def test_warning_count_reads_powershell_utf16_log(tmp_path) -> None:
    pytest_output = tmp_path / "pytest.log"
    pytest_output.write_text("55 passed, 1 warning in 11.50s\n", encoding="utf-16")

    assert read_warning_count(pytest_output) == 1


def test_schema_rejects_extra_fields() -> None:
    record = {
        "repo": "ZJUSCODE/enterprise-complaint-copilot",
        "commit": "b" * 40,
        "verifiedAt": "2026-08-09T08:00:00Z",
        "testCommand": "python -m pytest tests -q",
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "warnings": 0,
        "evalCommand": "python scripts/evaluate_rag.py --force-lexical",
        "evalCases": 1,
        "ciRunUrl": "https://github.com/ZJUSCODE/enterprise-complaint-copilot/actions/runs/123456789",
        "unexpected": True,
    }

    with pytest.raises(ValueError, match="schema keys mismatch"):
        validate_record(record)
