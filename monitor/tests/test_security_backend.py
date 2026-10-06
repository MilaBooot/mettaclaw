import json

from monitor.security_backend import SecurityEventReader


def falco_event(container="omega", output="Outbound connection token=secret"):
    return json.dumps(
        {
            "time": "2026-10-04T12:00:00Z",
            "priority": "Warning",
            "rule": "Oma outbound connection attempt",
            "output": output,
            "output_fields": {"container.name": container},
        }
    ).encode()


def test_security_status_is_explicit_when_not_configured():
    assert SecurityEventReader(None, "omega").status() == {
        "state": "not-configured",
        "configured": False,
    }


def test_security_event_is_filtered_and_redacted(tmp_path):
    events_file = tmp_path / "events.jsonl"
    events_file.write_bytes(
        falco_event(container="other") + b"\n" + falco_event() + b"\n"
    )
    reader = SecurityEventReader(events_file, "omega", sleeper=lambda _seconds: None)
    event = next(reader.events())
    assert event["type"] == "security"
    assert event["priority"] == "Warning"
    assert event["rule"] == "Oma outbound connection attempt"
    assert event["text"] == "Outbound connection token=[REDACTED]"


def test_security_reader_ignores_malformed_input(tmp_path):
    events_file = tmp_path / "events.jsonl"
    events_file.write_bytes(b"not-json\n" + falco_event() + b"\n")
    reader = SecurityEventReader(events_file, "omega", sleeper=lambda _seconds: None)
    assert next(reader.events())["type"] == "security"


def test_security_tail_is_bounded_to_latest_100_records(tmp_path):
    events_file = tmp_path / "events.jsonl"
    events_file.write_bytes(b"\n".join(falco_event(output=f"event {i}") for i in range(105)))
    reader = SecurityEventReader(events_file, "omega", sleeper=lambda _seconds: None)
    events = reader.events()
    assert next(events)["text"] == "event 5"
