import json

from helpers_redesign import Scripted, events_of, recon_cfg

from swarm_canvas.paths import TARGETS
from swarm_canvas.runner import run_config
from swarm_canvas.score import load_plate, score_run

PLATE = load_plate(TARGETS / "sun_boat.txt")
NONBG = [(chr(65 + c), r + 1, ch) for r, line in enumerate(PLATE) for c, ch in enumerate(line) if ch not in "SW"]
WATER = sum(ch == "W" for line in PLATE for ch in line)


def paint(col, row, color):
    return {"column": col, "row": row, "color": color}


def solo(tmp_path, script, *, rounds, budget=8, task=None):
    agent = Scripted(script)
    return run_config(recon_cfg(tmp_path, agents=1, rounds=rounds, budget=budget, task=task),
                      render=False, agents=[agent])


def test_useful_and_wasted_paints(tmp_path):
    script = [
        {"paints": [paint("A", 1, "S"), paint("R", 2, "Y"), paint("A", 2, "Y")]},
        {"paints": [paint("A", 1, "S"), paint("A", 2, "S"), paint("R", 2, "W")]},
        {"paints": [paint("R", 2, "Y"), paint("A", 2, "W")]},
    ]
    scores = solo(tmp_path, script, rounds=3).scores
    assert scores["paints"] == 8
    assert scores["useful_paints"] == 4  # A1, R2 (r1), A2 (r2), R2 (r3)
    assert scores["wasted_same_color"] == 1  # A1 repainted S
    assert scores["wasted_destroyed_correct"] == 2  # R2 Y->W, A2 S->W
    assert scores["wasted_paints"] == 3
    assert scores["neutral_paints"] == 1  # A2 blank -> wrong Y
    assert (scores["useful_paints"] + scores["wasted_paints"] + scores["neutral_paints"]) == scores["paints"]
    # existing keys keep their meaning
    assert scores["redundant_paints"] == 1 and scores["correct_cells_destroyed"] == 2


def test_nonbackground_curve_and_final(tmp_path):
    script = [
        {"paints": [paint("A", 1, "S"), paint("R", 2, "Y")]},
        {"paints": [paint("R", 2, "W")]},
        {"paints": [paint("R", 2, "Y")]},
    ]
    scores = solo(tmp_path, script, rounds=3).scores
    assert scores["nonbackground_cells"] == len(NONBG) == 51
    assert [p["accuracy"] for p in scores["nonbackground_by_round"]] == [round(1 / 51, 6), 0.0, round(1 / 51, 6)]
    assert scores["nonbackground_matches"] == 1
    assert scores["nonbackground_accuracy"] == round(1 / 51, 4)
    assert scores["rounds_to_nonbg_threshold"] is None
    # background agreement does not leak into the non-background metric
    assert scores["target_matches"] == 2 and scores["nonbackground_matches"] == 1


def test_rounds_to_nonbg_threshold_reports_paints_and_tokens(tmp_path):
    cells = [paint(c, r, ch) for c, r, ch in NONBG]
    result = solo(tmp_path, [{"paints": cells[:40]}, {"paints": cells[40:]}, {}], rounds=3, budget=51)
    reached = result.scores["rounds_to_nonbg_threshold"]
    assert reached["round"] == 2 and reached["paints"] == 51
    assert result.scores["nonbackground_accuracy"] == 1.0
    assert [p["accuracy"] for p in result.scores["nonbackground_by_round"]][:2] == [round(40 / 51, 6), 1.0]
    # tokens up to and including the threshold round count; later rounds do not
    with (result.run_dir / "events.jsonl").open("a") as out:
        for rnd, tokens in ((1, (100, 10)), (2, (200, 20)), (3, (900, 90))):
            out.write(json.dumps({"type": "model_call", "status": "ok", "round": rnd,
                                  "input_tokens": tokens[0], "output_tokens": tokens[1]}) + "\n")
    rescored = score_run(result.run_dir)["rounds_to_nonbg_threshold"]
    assert rescored["input_tokens"] == 300 and rescored["output_tokens"] == 30 and rescored["tokens"] == 330


def test_background_override_changes_the_denominator(tmp_path):
    scores = solo(tmp_path, [{}], rounds=1, task={"background": ["S"]}).scores
    assert scores["nonbackground_cells"] == 51 + WATER
    scores = solo(tmp_path / "w", [{}], rounds=1, task={"background": []}).scores
    assert scores["nonbackground_cells"] == 384


def test_prefill_excluded_from_agent_metrics(tmp_path):
    agents = [Scripted([]) for _ in range(4)]
    result = run_config(recon_cfg(tmp_path, rounds=2, task={"prefill_background": ["S", "W"]}),
                        render=False, agents=agents)
    scores = result.scores
    assert scores["paints"] == 0 and scores["useful_paints"] == 0 and scores["wasted_paints"] == 0
    assert scores["prefill_cells"] == 384 - 51
    assert scores["nonbackground_accuracy"] == 0.0
    assert scores["target_accuracy"] == round(333 / 384, 4)
    assert scores["rounds_to_nonbg_threshold"] is None


def test_legacy_keys_present_and_unchanged_for_plain_runs(tmp_path):
    agents = [Scripted([{"paints": [paint("A", 1, "S")]}]), Scripted([]), Scripted([]), Scripted([])]
    scores = run_config(recon_cfg(tmp_path, rounds=1), render=False, agents=agents).scores
    for key in ("target_accuracy", "accuracy_by_round", "threshold_90", "redundant_paints",
                "correct_cells_destroyed", "per_agent", "overwrites", "paints"):
        assert key in scores
    assert scores["prefill_cells"] == 0
