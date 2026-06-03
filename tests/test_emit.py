# PROMPT: Cover the JSONL event replay CLI so the challenge demo path is tested along with the API.
# CHANGES MADE: Used a fake requests session to avoid network calls while still verifying batching, totals, and CLI validation paths.

from __future__ import annotations

import json

from pipeline import emit
from tests.conftest import sample_event


def test_read_jsonl_and_chunks(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(sample_event(visitor_id="VIS_A")) + "\n\n", encoding="utf-8")

    events = list(emit.read_jsonl(path))
    batches = list(emit.chunks(events * 3, 2))

    assert events[0]["visitor_id"] == "VIS_A"
    assert [len(batch) for batch in batches] == [2, 1]


def test_post_events_batches_and_prints_totals(monkeypatch, capsys):
    class DummyResponse:
        def __init__(self, accepted):
            self.accepted = accepted

        def raise_for_status(self):
            return None

        def json(self):
            return {"accepted": self.accepted, "duplicates": 0, "errors": []}

    class DummySession:
        def __init__(self):
            self.calls = []

        def post(self, url, json, timeout):
            self.calls.append((url, json, timeout))
            return DummyResponse(len(json["events"]))

    session = DummySession()
    monkeypatch.setattr(emit.requests, "Session", lambda: session)

    emit.post_events([sample_event(), sample_event(), sample_event()], "http://api/events/ingest", 2, 0)

    assert len(session.calls) == 2
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[-1] == {"accepted": 3, "duplicates": 0, "errors": 0}


def test_emit_main_validates_inputs(tmp_path, capsys):
    missing = tmp_path / "missing.jsonl"
    assert emit.main(["--sample", str(missing)]) == 2
    assert "Event file not found" in capsys.readouterr().err

    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(sample_event()) + "\n", encoding="utf-8")
    assert emit.main(["--sample", str(path), "--batch-size", "501"]) == 2
    assert "batch-size must be <= 500" in capsys.readouterr().err

