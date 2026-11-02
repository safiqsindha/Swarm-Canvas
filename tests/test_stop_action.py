import json

import pytest
from helpers_redesign import Scripted, events_of, recon_cfg

from swarm_canvas.agents import LLMAgent
from swarm_canvas.models import ModelConfig, _openai_compatible
from swarm_canvas.paths import TARGETS
from swarm_canvas.runner import run_config
from swarm_canvas.score import load_plate

PLATE = load_plate(TARGETS / "sun_boat.txt")
NONBG = [(chr(65 + c), r + 1, ch) for r, line in enumerate(PLATE) for c, ch in enumerate(line) if ch not in "SW"]
PREFILL = {"prefill_background": ["S", "W"]}


def paint(col, row, color):
    return {"column": col, "row": row, "color": color}


def done_events(run_dir):
    return [e for e in events_of(run_dir) if e["type"] == "done"]


def test_done_event_counts_use_round_start_and_post_round_frames(tmp_path):
    a1 = Scripted([{}, {"done": True, "paints": [paint("S", 3, "Y")]}])
    a2 = Scripted([{"paints": [paint("R", 2, "Y")]}, {"paints": [paint("T", 2, "Y")]}])
    a3 = Scripted([{"paints": [paint("R", 3, "K")]}])  # wrong colour on a non-background cell
    a4 = Scripted([])
    result = run_config(recon_cfg(tmp_path, rounds=3, task=PREFILL, stop_action=True),
                        render=False, agents=[a1, a2, a3, a4])
    (done,) = done_events(result.run_dir)
    assert (done["round"], done["agent"], done["agent_id"]) == (2, "a1", "slot-0")
    assert (done["blank_nonbg_seen"], done["incorrect_nonbg_seen"]) == (49, 1)
    assert (done["blank_nonbg_after"], done["incorrect_nonbg_after"]) == (47, 1)
    # its same-round paint still applied
    assert any(e["type"] == "paint" and e["cell"] == "S3" and e["round"] == 2 for e in events_of(result.run_dir))
    # no further turns for a1; everyone else kept playing
    assert len(a1.seen) == 2 and len(a2.seen) == len(a3.seen) == len(a4.seen) == 3
    assert not [e for e in events_of(result.run_dir)
                if e.get("agent_id") == "slot-0" and e["round"] == 3 and e["type"] == "exposure"]
    scores = result.scores
    assert scores["first_done_round"] == 2 and scores["done_rounds"] == {"slot-0": 2}
    assert scores["done_while_incomplete"] is True
    assert scores["done_while_incomplete_by_agent"] == {"slot-0": True}
    assert scores["rounds_executed"] == 3


def test_seen_and_after_counts_can_differ_and_complete_is_not_incomplete(tmp_path):
    agent = Scripted([{"done": True, "paints": [paint(c, r, ch) for c, r, ch in NONBG]}])
    result = run_config(recon_cfg(tmp_path, agents=1, rounds=4, budget=51, task=PREFILL, stop_action=True),
                        render=False, agents=[agent])
    (done,) = done_events(result.run_dir)
    assert done["blank_nonbg_seen"] == 51 and done["blank_nonbg_after"] == 0 and done["incorrect_nonbg_after"] == 0
    assert result.scores["done_while_incomplete"] is False
    assert result.scores["rounds_executed"] == 1 and result.scores["nonbackground_accuracy"] == 1.0


def test_run_ends_early_when_every_agent_is_done(tmp_path):
    agents = [Scripted([{"done": True}]), Scripted([{}, {"done": True}]),
              Scripted([{}, {"done": True}]), Scripted([{}, {}, {"done": True}])]
    result = run_config(recon_cfg(tmp_path, rounds=6, task=PREFILL, stop_action=True), render=False, agents=agents)
    assert [len(a.seen) for a in agents] == [1, 2, 2, 3]
    assert sorted(p.name for p in (result.run_dir / "canvas").glob("round_*.json")) == [
        "round_01.json", "round_02.json", "round_03.json"]
    config = json.loads((result.run_dir / "config.json").read_text())
    assert config["rounds_executed"] == 3 and config["final_frame"] == "canvas/round_03.json"
    scores = result.scores
    assert scores["first_done_round"] == 1
    assert scores["done_rounds"] == {"slot-0": 1, "slot-1": 2, "slot-2": 2, "slot-3": 3}
    assert scores["done_while_incomplete"] is True
    # the anytime curve still spans the configured horizon, flat after the stop
    assert len(scores["nonbackground_by_round"]) == 6
    assert len({p["accuracy"] for p in scores["nonbackground_by_round"]}) == 1


def test_done_agents_make_no_model_calls(tmp_path):
    def llm(handle, responses):
        return LLMAgent(handle, ModelConfig(provider="fake", name="fake", fake_responses=responses), "system")

    agents = [llm("a1", ['{"done": true}']), llm("a2", ['{}', '{"done": true}']),
              llm("a3", ['{"done": true}']), llm("a4", ['{}', '{}', '{"done": true}'])]
    result = run_config(recon_cfg(tmp_path, rounds=6, task=PREFILL, stop_action=True), render=False, agents=agents)
    assert [a.model_cfg.usage["calls"] for a in agents] == [1, 2, 1, 3]
    assert result.scores["rounds_executed"] == 3


def test_fragment_counts_separate_own_piece_from_whole_canvas(tmp_path):
    sun = [paint(c, r, ch) for c, r, ch in NONBG if ch == "Y"]
    agents = [Scripted([{"done": True, "paints": sun}]), Scripted([]), Scripted([]), Scripted([])]
    split = {"a1": "sun", "a2": "cloud", "a3": "hull", "a4": "mast_sail"}
    result = run_config(recon_cfg(tmp_path, rounds=2, budget=11, task={**PREFILL, "reference_split": split},
                                  stop_action=True), render=False, agents=agents)
    (done,) = done_events(result.run_dir)
    assert done["fragment_blank_after"] == 0 and done["fragment_incorrect_after"] == 0
    assert done["blank_nonbg_after"] == 40
    assert result.scores["done_while_incomplete"] is True


def test_done_is_ignored_and_unprompted_when_option_is_off(tmp_path):
    agents = [Scripted([{"done": True}, {}]) for _ in range(4)]
    result = run_config(recon_cfg(tmp_path, rounds=2), render=False, agents=agents)
    assert not done_events(result.run_dir)
    assert all(len(a.seen) == 2 for a in agents)
    assert "DONE:" not in agents[0].seen[0]
    assert result.scores["stop_action"] is False and result.scores["first_done_round"] is None
    assert result.scores["done_rounds"] is None and result.scores["done_while_incomplete"] is None
    assert "rounds_executed" not in json.loads((result.run_dir / "config.json").read_text())


def test_done_prompt_and_bad_values(tmp_path):
    agents = [Scripted([{"done": "yes"}, {}]), Scripted([]), Scripted([]), Scripted([])]
    result = run_config(recon_cfg(tmp_path, rounds=2, stop_action=True), render=False, agents=agents)
    assert "DONE:" in agents[0].seen[0] and "no further turns" in agents[0].seen[0]
    assert not done_events(result.run_dir)
    assert any(e["type"] == "invalid" and e["reason"] == "done_not_bool" for e in events_of(result.run_dir))
    assert result.scores["done_rounds"] == {} and result.scores["done_while_incomplete"] is False
    with pytest.raises(ValueError, match="stop_action"):
        run_config(recon_cfg(tmp_path, rounds=1, stop_action="yes"), render=False)


def test_done_with_swarmchat_skips_finished_agents(tmp_path):
    agents = [Scripted([{"done": True, "messages": ["finished my part"]}]), Scripted([]), Scripted([]), Scripted([])]
    result = run_config(recon_cfg(tmp_path, rounds=3, kind="swarmchat", task=PREFILL, stop_action=True),
                        render=False, agents=agents)
    events = events_of(result.run_dir)
    assert not [e for e in events if e["type"] == "exposure" and e["agent_id"] == "slot-0" and e["round"] > 1]
    # peers still see the last message from the agent that left
    assert any("finished my part" in obs for obs in agents[1].seen[1:])
    assert len(agents[0].seen) == 1 and len(agents[1].seen) == 3


def test_reply_schema_gains_done_only_when_on(monkeypatch):
    captured = {}
    monkeypatch.setattr("swarm_canvas.models._post_chat",
                        lambda url, payload, cfg: (captured.update(payload) or ("{}", {})))
    _openai_compatible([{"role": "user", "content": "x"}], ModelConfig(provider="openrouter", name="x:free", stop_action=True))
    assert captured["response_format"]["json_schema"]["schema"]["properties"]["done"] == {"type": "boolean"}
    _openai_compatible([{"role": "user", "content": "x"}], ModelConfig(provider="openrouter", name="x:free"))
    assert "done" not in captured["response_format"]["json_schema"]["schema"]["properties"]
