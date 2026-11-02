import json

import pytest
from helpers_redesign import Scripted, events_of, recon_cfg

from swarm_canvas.paths import TARGETS
from swarm_canvas.runner import run_config
from swarm_canvas.score import load_plate

PLATE = load_plate(TARGETS / "sun_boat.txt")
BG_CELLS = sum(ch in "SW" for line in PLATE for ch in line)


def _run(tmp_path, task, **kw):
    agents = kw.pop("agents", None)
    return run_config(recon_cfg(tmp_path, task=task, **kw), render=False, agents=agents)


def test_prefill_paints_background_before_round_one(tmp_path):
    agents = [Scripted([{}]) for _ in range(4)]
    result = _run(tmp_path, {"prefill_background": ["S", "W"]}, rounds=1, agents=agents)
    events = events_of(result.run_dir)
    prefill = [e for e in events if e["type"] == "prefill"]
    assert len(prefill) == BG_CELLS
    assert all(e["agent"] == "prefill" and e["agent_id"] == "prefill" and e["round"] == 0 for e in prefill)
    assert events.index(prefill[-1]) < next(i for i, e in enumerate(events) if e["type"] == "exposure")
    # agents see the background already painted, with a note saying so
    seen = agents[0].seen[0]
    assert "BACKGROUND PREFILL" in seen
    canvas_rows = [line for line in seen.splitlines() if line[:2].strip().isdigit()][:16]
    assert canvas_rows[0].split()[1:] == ["S"] * 24
    assert "." not in canvas_rows[0] and "." in canvas_rows[1]
    # the final frame carries the prefill, and it round-trips through config.json
    cells = json.loads((result.run_dir / "canvas/round_01.json").read_text())["cells"]
    assert len(cells) == BG_CELLS and {c["handle"] for c in cells} == {"prefill"}
    config = json.loads((result.run_dir / "config.json").read_text())
    assert config["redesign"]["prefill_background"] == ["S", "W"]


def test_prefill_is_not_an_agent_paint(tmp_path):
    action = {"paints": [{"column": "A", "row": 1, "color": "S"}, {"column": "R", "row": 2, "color": "Y"}]}
    agents = [Scripted([action]), Scripted([]), Scripted([]), Scripted([])]
    result = _run(tmp_path, {"prefill_background": ["S", "W"]}, rounds=1, agents=agents)
    scores = result.scores
    assert scores["paints"] == 2
    assert sum(b["paints"] for b in scores["per_agent"].values()) == 2
    assert "prefill" not in scores["per_agent"]
    assert scores["overwrites"] == 0  # painting over the harness is not overwriting a peer
    assert scores["redundant_paints"] == 1  # S over prefilled S
    assert scores["grants"] == scores["denies"] == 0
    # canvas-level accuracy includes the prefill
    assert scores["target_matches"] == BG_CELLS + 1
    assert scores["accuracy_by_round"][0]["accuracy"] == round((BG_CELLS + 1) / 384, 6)


def test_prefill_is_opt_in(tmp_path):
    result = _run(tmp_path, {}, rounds=1)
    assert not [e for e in events_of(result.run_dir) if e["type"] == "prefill"]
    assert "redesign" not in json.loads((result.run_dir / "config.json").read_text())
    assert "BACKGROUND PREFILL" not in (result.run_dir / "prompts_rendered/round_01_slot-0.txt").read_text()


@pytest.mark.parametrize(
    "task, message",
    [
        ({"prefill_background": "SW"}, "list of color codes"),
        ({"prefill_background": ["S", "S"]}, "duplicate"),
        ({"prefill_background": ["Q"]}, "outside the palette"),
        ({"prefill_background": ["G"]}, "not in the target"),
        ({"background": [1]}, "list of color codes"),
    ],
)
def test_prefill_validation(tmp_path, task, message):
    with pytest.raises(ValueError, match=message):
        _run(tmp_path, task, rounds=1)


def test_prefill_requires_reconstruction(tmp_path):
    cfg = recon_cfg(tmp_path, rounds=1)
    cfg["task"] = {"mode": "free_creation", "prefill_background": ["S"]}
    with pytest.raises(ValueError, match="requires reconstruction"):
        run_config(cfg, render=False)
