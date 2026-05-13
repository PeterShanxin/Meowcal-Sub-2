import json
from pathlib import Path

from meocosub2.event_log import log_event


def test_log_event_writes_jsonl_and_redacts_sensitive_fields(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(log_path))

    log_event(
        "test.event",
        layer="backend",
        correlation_id="abc123",
        api_key="secret",
        nested={"token": "secret", "safe": "ok"},
    )

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["event"] == "test.event"
    assert record["layer"] == "backend"
    assert record["correlation_id"] == "abc123"
    assert record["api_key"] == "[redacted]"
    assert record["nested"]["token"] == "[redacted]"
    assert record["nested"]["safe"] == "ok"


def test_log_event_preserves_reserved_metadata_and_nests_conflicts(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(log_path))

    log_event("actual.event", ts_ms=1)

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["event"] == "actual.event"
    assert record["layer"] == "backend"
    assert record["level"] == "info"
    assert record["ts_ms"] != 1
    assert record["data"]["ts_ms"] == 1


def test_log_event_redacts_sensitive_url_query_values(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(log_path))

    log_event("error.event", error="GET https://api.assrt.net/v1/sub/search?token=secret&q=fate failed")

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert "token=%5Bredacted%5D" in record["error"]
    assert "secret" not in record["error"]
