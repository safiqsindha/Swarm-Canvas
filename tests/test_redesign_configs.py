import copy
import json

import pytest

from swarm_canvas.paths import ROOT
from swarm_canvas.reference_split import resolve
from swarm_canvas.runner import _validate_config, load_config, run_from_yaml
from swarm_canvas.score import load_plate

NAMES = ["redesign_split_comms", "redesign_split_nocomms", "redesign_solo", "redesign_size_2",
         "redesign_size_4", "redesign_size_8", "redesign_size_16"]
SIZES = {2: 16, 4: 8, 8: 4, 16: 2}


def cfg_of(name):
    return load_config(ROOT / "configs" / f"{name}.yaml")


@pytest.mark.parametrize("name", NAMES)
def test_offline_config_runs_and_scores_new_metrics(tmp_path, name):
    cfg = cfg_of(name)
    assert cfg["agents"]["type"] == "random"
    result = run_from_yaml(ROOT / "configs" / f"{name}.yaml", seed=1, rounds=3, output_root=tmp_path, render=False)
    scores = result.scores
    for key in ("nonbackground_accuracy", "nonbackground_by_round", "rounds_to_nonbg_threshold",
                "useful_paints", "wasted_paints", "first_done_round", "done_while_incomplete", "done_rounds"):
        assert key in scores
    assert scores["prefill_cells"] == 333 and scores["reliability_ok"]
    assert scores["grants"] == scores["denies"] == 0
    assert len(scores["nonbackground_by_round"]) == 3
    config = json.loads((result.run_dir / "config.json").read_text())
    assert config["redesign"]["stop_action"] is True and config["redesign"]["prefill_background"] == ["S", "W"]
    prompts = "".join(p.read_text() for p in result.run_dir.glob("prompts_rendered/*.txt")).lower()
    assert "catalog" not in prompts


def test_contrast_arms_differ_only_where_intended():
    comms, nocomms = cfg_of("redesign_split_comms"), cfg_of("redesign_split_nocomms")
    assert comms["comms"]["kind"] == "swarmchat" and nocomms["comms"]["kind"] == "none"
    for key in set(comms) - {"comms", "condition", "run_code"}:
        assert comms[key] == nocomms[key], key
    assert comms["rounds"] == 24 and comms["stop_action"] is True
    assert comms["supplier"]["enabled"] is False and comms["supplier"]["swarm_budget"] == 0
    solo, team = cfg_of("redesign_solo"), comms
    assert solo["agents"]["count"] == 1 and solo["comms"]["kind"] == "none"
    assert solo["paint_budget_per_round"] == 4 * team["paint_budget_per_round"] == 32
    assert "reference_split" not in solo["task"] and solo["task"]["prefill_background"] == ["S", "W"]
    assert solo["stop_action"] is True and solo["supplier"]["enabled"] is False


def test_reasoning_calibration_differs_only_in_type_and_reasoning():
    base, calib = cfg_of("redesign_split_comms"), cfg_of("redesign_reasoning_calibration")
    assert calib["agents"]["type"] == "llm" and calib["model"]["reasoning_enabled"] is True
    assert calib["model"]["name"] == "nvidia/nemotron-3.5-super-vl:free" == base["model"]["name"]
    a, b = copy.deepcopy(base), copy.deepcopy(calib)
    for cfg in (a, b):
        for key in ("condition", "run_code"):
            cfg.pop(key)
        cfg["agents"].pop("type")
        cfg["model"].pop("reasoning_enabled")
    assert a == b
    _validate_config(calib, None)  # free-only policy accepts it; no network involved
    paid = copy.deepcopy(calib)
    paid["model"]["name"] = "anthropic/claude-sonnet-4"
    with pytest.raises(ValueError, match="OpenRouter :free"):
        _validate_config(paid, None)


@pytest.mark.parametrize("size", sorted(SIZES))
def test_size_sweep_fixes_team_allowance_and_partitions_target(size):
    cfg = cfg_of(f"redesign_size_{size}")
    assert cfg["agents"]["count"] == size == len(cfg["agents"]["handles"])
    assert cfg["paint_budget_per_round"] * size == 32 and cfg["paint_budget_per_round"] == SIZES[size]
    assert cfg["comms"]["kind"] == "swarmchat" and cfg["stop_action"] is True
    plate = load_plate(ROOT / cfg["task"]["target"])
    fragments = resolve(cfg["task"]["reference_split"], cfg["agents"]["handles"], plate, {"S", "W"})
    assert len(fragments) == size
    sizes = [len(f.cells) for f in fragments.values()]
    assert sum(sizes) == 51 and min(sizes) >= 1  # a true partition of the non-background cells
    _validate_config(cfg, None)
