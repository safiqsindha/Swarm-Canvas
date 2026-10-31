"""Regressions for data integrity, budget enforcement and matched conditions."""

import json

import httpx
import pytest
from test_rules_and_run import Scripted, _cfg, _events

from swarm_canvas.agents import LLMAgent
from swarm_canvas.models import ModelConfig, call_model
from swarm_canvas.paths import ROOT
from swarm_canvas.pilot import run_pilot
from swarm_canvas.runner import _build_slots, run_config, run_from_yaml
from swarm_canvas.score import score_run


def test_reruns_are_isolated_and_score_only_manifest_frame(tmp_path):
    old = run_from_yaml(
        ROOT / "configs/c1_nochat.yaml", rounds=30, output_root=tmp_path, render=False
    )
    new = run_from_yaml(
        ROOT / "configs/c1_nochat.yaml", rounds=1, output_root=tmp_path, render=False
    )
    assert old.run_dir != new.run_dir
    snapshot = json.loads((new.run_dir / "canvas/round_01.json").read_text())
    assert new.scores["painted"] == len(snapshot["cells"])
    (new.run_dir / "canvas/round_999.json").write_text(
        (old.run_dir / "canvas/round_30.json").read_text()
    )
    assert score_run(new.run_dir) == new.scores
    snapshot["cells"][0]["color"] = "K"
    (new.run_dir / "canvas/round_01.json").write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="hash mismatch"):
        score_run(new.run_dir)


def test_all_simultaneous_duplicate_renames_are_rejected(tmp_path):
    agents = [
        Scripted([{"name": "Same", "paints": [{"cell": f"{c}1", "color": "S"}]}])
        for c in "ABCD"
    ]
    result = run_config(
        _cfg(output_dir=str(tmp_path), rounds=1), agents=agents, render=False
    )
    events = _events(result.run_dir)
    renames = [e for e in events if e["type"] == "rename"]
    assert len(renames) == 4 and all(not e["applied"] for e in renames)
    assert set(result.scores["per_agent"]) == {f"slot-{i}" for i in range(4)}
    assert sorted(e["order"] for e in events if e["type"] == "paint") == [1, 2, 3, 4]


def test_rename_keeps_paints_and_supplier_under_permanent_id(tmp_path):
    agents = [
        Scripted(
            [
                {
                    "name": "Renamed",
                    "requests": ["O"],
                    "paints": [{"cell": "A1", "color": "S"}],
                },
                {"paints": [{"cell": "B1", "color": "O"}]},
            ]
        )
    ] + [Scripted([{}, {}]) for _ in range(3)]
    result = run_config(_cfg(output_dir=str(tmp_path)), agents=agents, render=False)
    assert result.scores["per_agent"]["slot-0"]["paints"] == 2
    assert set(
        e["agent_id"]
        for e in _events(result.run_dir)
        if e["type"] in {"paint", "grant", "request"}
    ) == {"slot-0"}


@pytest.mark.parametrize(
    "provider,name",
    [
        ("anthropic", "anything"),
        ("openai_compatible", "local"),
        ("openrouter", "paid/model"),
        ("openrouter", "openrouter/auto"),
    ],
)
def test_paid_or_non_openrouter_requests_are_blocked_before_http(provider, name):
    requests = []
    cfg = ModelConfig(
        provider=provider,
        name=name,
        transport=httpx.MockTransport(lambda r: requests.append(r)),
    )
    with pytest.raises(ValueError, match="policy"):
        call_model([{"role": "user", "content": "test"}], cfg)
    assert requests == []


def test_reasoning_and_transport_copied_without_shared_usage():
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    cfg = ModelConfig(
        provider="openrouter",
        name="test/model:free",
        reasoning_max_tokens=100,
        transport=transport,
    )
    slots = _build_slots(["a1", "a2"], "llm", 1, 32, ["S"], cfg, "c0", "none", None)
    assert all(
        s.model_cfg.reasoning_max_tokens == 100
        and s.model_cfg.paint_budget == 32
        and s.model_cfg.transport is transport
        for s in slots
    )
    slots[0].model_cfg.usage["calls"] = 3
    assert slots[1].model_cfg.usage["calls"] == cfg.usage["calls"] == 0


def test_free_request_keeps_zero_price_guard_on_schema_fallback():
    bodies = []

    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(400, json={"error": "schema unsupported"})
        return httpx.Response(
            200,
            json={
                "id": "test-id",
                "model": "served/model",
                "provider": "test-provider",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0},
            },
        )

    cfg = ModelConfig(
        provider="openrouter",
        name="test/model:free",
        paint_budget=32,
        reasoning_max_tokens=100,
        transport=httpx.MockTransport(handle),
    )
    assert call_model([{"role": "user", "content": "test"}], cfg) == "{}"
    assert (
        bodies[0]["response_format"]["json_schema"]["schema"]["properties"]["paints"][
            "maxItems"
        ]
        == 32
    )
    assert all(
        b["model"] == "test/model:free"
        and b["provider"]
        == {
            "allow_fallbacks": False,
            "max_price": {"prompt": 0, "completion": 0, "request": 0},
        }
        for b in bodies
    )
    assert all(b["reasoning"] == {"max_tokens": 100} for b in bodies)
    assert cfg.call_records[0]["served_model"] == "served/model"
    assert cfg.call_records[0]["cost_usd"] == 0


def test_api_failure_is_not_json_failure_or_voluntary_pass(tmp_path):
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "rate limit"})

    agent = LLMAgent(
        "a1",
        ModelConfig(
            provider="openrouter",
            name="test/model:free",
            transport=httpx.MockTransport(fail),
        ),
        "system",
    )
    result = run_config(
        _cfg(output_dir=str(tmp_path), rounds=1),
        agents=[agent] + [Scripted([{}]) for _ in range(3)],
        render=False,
    )
    assert len(calls) == 1  # no JSON repair for an API failure
    assert result.scores["api_errors"] == 1
    assert result.scores["parse_errors"] == 0
    assert result.scores["passes"] == 3
    assert result.scores["reliability_ok"] is False


def test_remote_swarmchat_requires_endpoint_and_tokens_before_model_calls(tmp_path):
    cfg = _cfg(kind="swarmchat", agent_type="llm", output_dir=str(tmp_path))
    cfg["model"] = {"provider": "openrouter", "name": "test/model:free"}
    cfg["comms"]["backend"] = "remote"
    with pytest.raises(ValueError, match="server_url"):
        run_config(cfg, render=False)
    cfg["comms"]["server_url"] = "http://example.invalid"
    with pytest.raises(ValueError, match="real tokens"):
        run_config(cfg, render=False)
    assert not list(tmp_path.iterdir())


def test_required_swarmchat_delivery_failure_marks_run_failed(tmp_path, monkeypatch):
    from swarmchat.client import Client, ClientError

    cfg = _cfg(kind="swarmchat", agent_type="llm", output_dir=str(tmp_path), rounds=1)
    cfg["model"] = {"provider": "openrouter", "name": "test/model:free"}
    monkeypatch.setattr(LLMAgent, "act", lambda self, obs: {"messages": ["hello"]})

    def fail(*args, **kwargs):
        raise ClientError(503, "test failure")

    monkeypatch.setattr(Client, "send", fail)
    with pytest.raises(RuntimeError, match="SwarmChat send failed"):
        run_config(cfg, render=False)
    directory = next(tmp_path.iterdir())
    assert json.loads((directory / "config.json").read_text())["status"] == "failed"
    with pytest.raises(ValueError, match="completed"):
        score_run(directory)


def test_solo_has_matched_team_action_budget_and_prompt(tmp_path):
    solo = run_from_yaml(
        ROOT / "configs/c0_baseline.yaml", rounds=1, output_root=tmp_path, render=False
    )
    group = run_from_yaml(
        ROOT / "configs/c1_nochat.yaml", rounds=1, output_root=tmp_path, render=False
    )
    c0 = json.loads((solo.run_dir / "config.json").read_text())
    c1 = json.loads((group.run_dir / "config.json").read_text())
    assert len(c0["agents"]) == 1 and len(c1["agents"]) == 4
    assert c0["team_paint_budget_per_round"] == c1["team_paint_budget_per_round"] == 32
    prompt = (solo.run_dir / "prompts_rendered/system_slot-0.txt").read_text()
    observation = (solo.run_dir / "prompts_rendered/round_01_slot-0.txt").read_text()
    assert "only painter" in prompt and "up to 32 objects" in observation


def test_scoring_counts_destroyed_correct_cells_and_redundant_work(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), rounds=3)
    cfg["task"] = {"mode": "reconstruction", "target": "targets/sun_boat.txt"}
    agents = [
        Scripted(
            [
                {"paints": [{"cell": "A1", "color": "S"}]},
                {"paints": [{"cell": "A1", "color": "Y"}]},
                {"paints": [{"cell": "A1", "color": "Y"}]},
            ]
        )
    ] + [Scripted([{}, {}, {}]) for _ in range(3)]
    result = run_config(cfg, agents=agents, render=False)
    assert result.scores["correct_cells_destroyed"] == 1
    assert result.scores["redundant_paints"] == 1
    assert result.scores["target_matches"] == 0
    assert result.scores["accuracy_by_round"][0]["accuracy"] > 0


def test_pilot_includes_swarmchat_and_preflights_before_running(tmp_path):
    with pytest.raises(ValueError, match="explicit OpenRouter"):
        run_pilot(
            output_root=tmp_path,
            live=True,
            model="openrouter/free",
            swarmchat_url="http://test",
        )
    with pytest.raises(ValueError, match="real tokens"):
        run_pilot(
            output_root=tmp_path,
            live=True,
            model="test/model:free",
            swarmchat_url="http://test.invalid",
        )
    assert not list(tmp_path.iterdir())
    manifest = run_pilot(output_root=tmp_path, repeats=1, rounds=1)
    suite = json.loads(manifest.read_text())
    assert len(suite["runs"]) == 12
    assert "c2b_swarmchat" in suite["conditions"]
    assert suite["research_evidence"] is False and suite["status"] == "completed"
    assert all(r["scores"]["token_totals"]["calls"] == 0 for r in suite["runs"])


def test_disabled_reasoning_and_truncation_metadata_are_preserved():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "test/model:free",
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 100,
                    "completion_tokens_details": {"reasoning_tokens": 100},
                    "cost": 0,
                },
            },
        )

    cfg = ModelConfig(
        provider="openrouter",
        name="test/model:free",
        reasoning_enabled=False,
        transport=httpx.MockTransport(handle),
    )
    slots = _build_slots(["a1"], "llm", 1, 8, ["S"], cfg, "c2b", "swarmchat", None)
    effective = slots[0].model_cfg
    assert effective.reasoning_enabled is False
    assert call_model([{"role": "user", "content": "test"}], effective) == ""
    assert requests[0]["reasoning"] == {"enabled": False}
    assert requests[0]["provider"]["max_price"]["completion"] == 0
    record = effective.call_records[0]
    assert record["finish_reason"] == "length"
    assert record["reasoning_tokens"] == 100
    assert record["has_visible_content"] is False


def test_disabled_reasoning_rejects_conflicting_token_budget():
    cfg = ModelConfig(
        provider="openrouter",
        name="test/model:free",
        reasoning_enabled=False,
        reasoning_max_tokens=100,
    )
    with pytest.raises(ValueError, match="Do not combine"):
        call_model([{"role": "user", "content": "test"}], cfg)


def test_coordination_schema_is_opt_in_and_never_falls_back():
    requests = []

    def reject(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"error": "unsupported schema"})

    cfg = ModelConfig(provider="openrouter", name="test/model:free",
                      require_coordination_fields=True, transport=httpx.MockTransport(reject))
    from swarm_canvas.models import ModelCallError
    with pytest.raises(ModelCallError):
        call_model([{"role": "user", "content": "test"}], cfg)
    assert len(requests) == 1
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["messages", "acks", "paints"]
    assert requests[0]["provider"]["max_price"]["completion"] == 0


def test_peer_ack_schema_limits_choices_to_exposed_peer_ids():
    payloads = []
    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
    cfg = ModelConfig(provider="openrouter", name="test/model:free", require_coordination_fields=True,
                      allowed_ack_lines=[3, 8], transport=httpx.MockTransport(respond))
    call_model([{"role": "user", "content": "test"}], cfg)
    ack = payloads[0]["response_format"]["json_schema"]["schema"]["properties"]["acks"]
    assert ack["items"]["enum"] == [3, 8] and ack["minItems"] == 1
    cfg.allowed_ack_lines = []
    call_model([{"role": "user", "content": "test"}], cfg)
    assert payloads[1]["response_format"]["json_schema"]["schema"]["properties"]["acks"]["maxItems"] == 0


def test_open_boat_has_goal_but_no_hidden_target_or_territory(tmp_path):
    from swarm_canvas.prompts_render import render_system
    goal = 'Create a recognizable boat together on the shared canvas.'
    prompt = render_system('a1', 'S W', 'open_boat', 'swarmchat',
                           task_mode='free_creation', agent_id='slot-0', goal=goal,
                           open_coordination=True)
    assert goal in prompt
    assert 'assigned columns' not in prompt
    assert 'You may keep a scratchpad' in prompt
    cfg = _cfg(kind='swarmchat', output_dir=str(tmp_path), rounds=1,
               task={'mode': 'free_creation', 'goal': goal, 'open_coordination': True})
    result = run_config(cfg, render=False)
    manifest = json.loads((result.run_dir / 'config.json').read_text())
    assert manifest['task']['goal'] == goal
    assert goal in (result.run_dir / 'prompts_rendered/system_slot-0.txt').read_text()
    assert not (result.run_dir / 'target.json').exists()
    assert result.scores['target_accuracy'] is None


def test_goal_must_be_valid_before_run(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), task={'mode': 'free_creation', 'goal': ''})
    with pytest.raises(ValueError, match='goal'):
        run_config(cfg, render=False)
