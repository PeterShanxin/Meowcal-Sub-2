import json
import threading
from pathlib import Path

from meocosub2.event_log import MAX_EVENT_LOG_BYTES, log_event


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


def test_log_event_preserves_reserved_metadata_and_nests_conflicts(
    tmp_path: Path, monkeypatch
) -> None:
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

    log_event(
        "error.event", error="GET https://api.assrt.net/v1/sub/search?token=secret&q=fate failed"
    )

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert "token=%5Bredacted%5D" in record["error"]
    assert "secret" not in record["error"]


def test_log_event_rotates_a_full_log_into_one_previous_file(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    previous_path = tmp_path / "events.jsonl.1"
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(log_path))
    previous_path.write_bytes(b"oldest\n")
    filler = "x" * (MAX_EVENT_LOG_BYTES - 2)
    log_path.write_bytes(filler.encode() + b"\n")

    log_event("below.bound")
    assert previous_path.read_bytes() == b"oldest\n"

    log_event("above.bound")

    previous_lines = previous_path.read_text(encoding="utf-8").splitlines()
    assert previous_lines[0] == filler
    assert [json.loads(line)["event"] for line in previous_lines[1:]] == ["below.bound"]
    current_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in current_lines] == ["above.bound"]


def test_log_event_keeps_every_event_written_concurrently(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(log_path))
    writers, events_per_writer = 8, 300

    def write(worker: int) -> None:
        for n in range(events_per_writer):
            log_event("concurrent.write", worker=worker, n=n)

    threads = [threading.Thread(target=write, args=(worker,)) for worker in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == writers * events_per_writer
