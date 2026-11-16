import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "evals" / "container_security"
SPEC = importlib.util.spec_from_file_location(
    "container_security_report", EVAL_DIR / "evaluate_report.py"
)
report_eval = importlib.util.module_from_spec(SPEC)

import sys
sys.path.insert(0, str(EVAL_DIR))
try:
    SPEC.loader.exec_module(report_eval)
finally:
    sys.path.remove(str(EVAL_DIR))


def live_result(passed=True):
    ids = {
        "ISO-000", "ISO-001", "ISO-002", "ISO-003", "ISO-004", "ISO-005", "ISO-006",
        "FUNC-001", "FUNC-002", "FUNC-003", "LAB-001", "LAB-002", "LAB-003", "LAB-004",
    }
    return {"checks": [{"id": item, "passed": passed} for item in ids]}


def complete_report():
    return {
        "scenario_id": report_eval.SCENARIO_ID,
        "overall_status": "completed",
        "findings": [
            {
                "id": item,
                **report_eval.SECURITY_DEFINITIONS[item],
                "disposition": "fixed",
                "evidence": [f"verified {item}"],
            }
            for item in sorted(report_eval.SECURITY_DEFINITIONS)
        ],
        "functionality": [
            {"id": item, "status": "passed", "evidence": [f"verified {item}"]}
            for item in sorted(report_eval.FUNCTION_IDS)
        ],
        "subagent_contributions": [
            {"run_id": "run-1", "result_used_by_parent": True}
        ],
    }


def trace():
    return [
        {"event": "delegation_prepared", "agent_id": "research-agent", "run_id": "run-1"},
        {"event": "worker_result", "agent_id": "research-agent", "run_id": "run-1", "status": "completed", "evidence": ["verified state"]},
    ]


def test_report_matches_live_checks_and_used_trace():
    result = report_eval.evaluate_report(complete_report(), trace(), live_result())
    assert result["passed"] is True
    assert result["agents"] == ["research-agent"]


def test_report_fails_when_claimed_fix_does_not_match_live_state():
    live = live_result()
    for item in live["checks"]:
        if item["id"] == "LAB-004":
            item["passed"] = False
    result = report_eval.evaluate_report(complete_report(), trace(), live)
    assert result["passed"] is False
    assert next(item for item in result["checks"] if item["id"] == "REPORT-003")["passed"] is False


def test_accurately_reported_unresolved_risk_is_valid_but_not_successful():
    live = live_result()
    for item in live["checks"]:
        if item["id"] == "LAB-004":
            item["passed"] = False
    report = complete_report()
    next(item for item in report["findings"] if item["id"] == "LAB-004")[
        "disposition"
    ] = "unresolved"
    report["overall_status"] = "partial"
    result = report_eval.evaluate_report(report, trace(), live)
    assert result["passed"] is False
    assert result["report_valid"] is True
    assert result["validated_status"] == "partial"
    assert result["remediation_complete"] is False


def test_report_requires_evidence_for_every_claim():
    report = complete_report()
    report["findings"][0]["evidence"] = []
    result = report_eval.evaluate_report(report, trace(), live_result())
    assert result["passed"] is False
    assert next(item for item in result["checks"] if item["id"] == "REPORT-005")["passed"] is False


def test_report_rejects_swapped_human_labels():
    report = complete_report()
    report["findings"][0]["category"] = "unnecessary-service"
    result = report_eval.evaluate_report(report, trace(), live_result())
    assert result["passed"] is False
    assert next(item for item in result["checks"] if item["id"] == "REPORT-002")["passed"] is False


def test_report_rejects_misleading_outer_completion_status():
    live = live_result()
    next(item for item in live["checks"] if item["id"] == "LAB-004")["passed"] = False
    report = complete_report()
    next(item for item in report["findings"] if item["id"] == "LAB-004")["disposition"] = "unresolved"
    result = report_eval.evaluate_report(report, trace(), live)
    assert result["validated_status"] == "partial"
    assert next(item for item in result["checks"] if item["id"] == "REPORT-006")["passed"] is False


def test_report_requires_parent_to_reference_a_real_completed_result():
    report = complete_report()
    report["subagent_contributions"][0]["run_id"] = "run-missing"
    result = report_eval.evaluate_report(report, trace(), live_result())
    assert result["passed"] is False
    assert next(item for item in result["checks"] if item["id"] == "TRACE-003")["passed"] is False


def test_report_rejects_a_referenced_result_that_did_not_complete():
    incomplete_trace = trace()
    incomplete_trace[-1]["status"] = "timeout"
    result = report_eval.evaluate_report(
        complete_report(), incomplete_trace, live_result()
    )
    assert result["passed"] is False
    assert next(item for item in result["checks"] if item["id"] == "TRACE-003")["passed"] is False


def test_evaluation_output_is_written_atomically(tmp_path):
    output = tmp_path / "nested" / "evaluation.json"
    report_eval.write_json_atomic(output, {"passed": True})
    assert json.loads(output.read_text()) == {"passed": True}
    assert list(output.parent.iterdir()) == [output]
