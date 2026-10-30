import json

import httpx
import pytest

from swarm_canvas.models import ModelConfig, call_model
from swarm_canvas.tracing import observation, trace_run


def test_broadcast_records_attempts_redacts_secrets_and_preserves_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_CANVAS_TRACING", "broadcast")
    calls = []
    secret = "sk-or-v1-testcredential123456"

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": "unsupported schema"})
        return httpx.Response(200, json={"id": "response-1", "model": "test/model:free", "choices": [{"message": {"role": "assistant", "content": '{"paints": []}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "cost": 0}})

    cfg = ModelConfig(provider="openrouter", name="test/model:free", api_key=secret, transport=httpx.MockTransport(respond))
    with trace_run(tmp_path, {"condition": "c2", "seed": 1, "rounds": 1}) as (rec, _):
        with observation("act-slot-0", "agent", metadata={"round": 1, "agent_id": "slot-0"}):
            assert call_model([{"role": "user", "content": f"hello {secret}"}], cfg) == '{"paints": []}'
        trace_id = rec.trace_id
    records = [json.loads(x) for x in (tmp_path / "traces.jsonl").read_text().splitlines()]
    generations = [x for x in records if x.get("name") == "generate-painter-action" and x["event"] == "end"]
    assert len(generations) == 2
    assert generations[0]["metadata"]["http_status"] == 400
    assert generations[1]["metadata"]["raw_response"]["id"] == "response-1"
    assert secret not in (tmp_path / "traces.jsonl").read_text()
    assert all(x["trace"]["trace_id"] == trace_id for x in calls)
    assert all("parent_span_id" not in x["trace"] for x in calls)
    assert all(x["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0} for x in calls)
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_langfuse_requires_complete_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_CANVAS_TRACING", "langfuse")
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="LANGFUSE_SECRET_KEY"):
        with trace_run(tmp_path, {"condition": "c1", "seed": 1, "rounds": 1}):
            pass
