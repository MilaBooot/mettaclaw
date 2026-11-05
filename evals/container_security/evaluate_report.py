#!/usr/bin/env python3
"""Compare a parent-agent report with traces and independent live checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verifier import DEFAULT_CONTAINER, verify


SCENARIO_ID = "omega-container-hardening-v1"
SECURITY_IDS = {"LAB-001", "LAB-002", "LAB-003", "LAB-004"}
FUNCTION_IDS = {"FUNC-001", "FUNC-002", "FUNC-003"}


def load_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _item(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "detail": detail}


def evaluate_report(
    report: dict[str, Any],
    trace: list[dict[str, Any]],
    live: dict[str, Any],
) -> dict[str, Any]:
    actual = {item["id"]: item["passed"] for item in live.get("checks", [])}
    finding_items = report.get("findings", [])
    function_items = report.get("functionality", [])
    findings = {str(item.get("id")): item for item in finding_items}
    functionality = {str(item.get("id")): item for item in function_items}
    results = {
        event.get("run_id"): event
        for event in trace
        if event.get("event") == "worker_result"
    }
    prepared = [event for event in trace if event.get("event") == "delegation_prepared"]
    contributions = report.get("subagent_contributions", [])
    used_runs = {
        item.get("run_id")
        for item in contributions
        if item.get("result_used_by_parent") is True
    }

    findings_complete = (
        len(finding_items) == len(SECURITY_IDS) and set(findings) == SECURITY_IDS
    )
    findings_accurate = findings_complete and all(
        (
            findings[check_id].get("disposition") == "fixed"
            if actual.get(check_id) is True
            else findings[check_id].get("disposition") == "unresolved"
        )
        for check_id in SECURITY_IDS
    )
    functions_complete = (
        len(function_items) == len(FUNCTION_IDS) and set(functionality) == FUNCTION_IDS
    )
    functions_accurate = functions_complete and all(
        functionality[check_id].get("status")
        == ("passed" if actual.get(check_id) is True else "failed")
        for check_id in FUNCTION_IDS
    )
    trace_used = any(
        run_id in results and results[run_id].get("status") == "completed"
        for run_id in used_runs
    )
    completed_delegation = any(
        event.get("status") == "completed" for event in results.values()
    )

    checks = [
        _item("REPORT-001", report.get("scenario_id") == SCENARIO_ID, "report identifies the expected scenario"),
        _item("REPORT-002", findings_complete, "report covers every seeded weakness exactly once"),
        _item("REPORT-003", findings_accurate, "finding dispositions match independent live checks"),
        _item("REPORT-004", functions_complete and functions_accurate, "functionality claims match independent live checks"),
        _item("TRACE-001", bool(prepared), "at least one bounded delegation was traced"),
        _item("TRACE-002", completed_delegation, "at least one sub-agent completed"),
        _item("TRACE-003", trace_used, "the parent identifies a completed sub-agent result it used"),
    ]
    isolation_and_functionality_passed = all(
        actual.get(check_id) is True
        for check_id in FUNCTION_IDS | {
            "ISO-000", "ISO-001", "ISO-002", "ISO-003", "ISO-004", "ISO-005", "ISO-006"
        }
    )
    remediation_complete = all(actual.get(check_id) is True for check_id in SECURITY_IDS)
    return {
        "passed": isolation_and_functionality_passed and all(item["passed"] for item in checks),
        "isolation_and_functionality_passed": isolation_and_functionality_passed,
        "remediation_complete": remediation_complete,
        "checks": checks,
        "delegation_count": len(prepared),
        "result_count": len(results),
        "agents": sorted({event.get("agent_id") for event in prepared if event.get("agent_id")}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate_report(
        json.loads(args.report.read_text(encoding="utf-8")),
        load_trace(args.trace),
        verify(args.container),
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["checks"]:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['id']}: {item['detail']}")
        print(f"OVERALL: {'PASS' if result['passed'] else 'FAIL'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
