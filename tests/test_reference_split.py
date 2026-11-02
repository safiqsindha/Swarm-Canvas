import json

import pytest
from helpers_redesign import Scripted, events_of, recon_cfg

from swarm_canvas.paths import TARGETS
from swarm_canvas.reference_split import (
    NAMED_REGIONS, derive_fragment, parse_spec, render_lines, resolve,
)
from swarm_canvas.runner import run_config
from swarm_canvas.score import load_plate

PLATE = load_plate(TARGETS / "sun_boat.txt")
SPLIT = {"a1": "sun", "a2": "cloud", "a3": "hull", "a4": "mast_sail"}


def test_fragment_by_color_and_rows():
    sun = derive_fragment(PLATE, {"colors": ["Y"]})
    assert len(sun.cells) == 11
    cloud = derive_fragment(PLATE, {"colors": ["w"], "rows": [1, 4]})
    assert len(cloud.cells) == 8
    sail = derive_fragment(PLATE, {"colors": ["K", "P", "w"], "rows": [7, 11]})
    assert len(sail.cells) == 15  # 4 K + 1 P + 10 w
    assert cloud.lines[2] == "??www???????????????????"  # row 3
    assert set("".join(sun.lines)) == {"Y", "?"}
    assert all(len(line) == 24 for line in sun.lines) and len(sun.lines) == 16


def test_fragment_by_columns_and_named_regions_match_explicit():
    left = derive_fragment(PLATE, {"colors": ["B"], "cols": ["A", "K"]})
    right = derive_fragment(PLATE, {"colors": ["B"], "cols": ["L", "X"]})
    hull = derive_fragment(PLATE, "hull")
    assert left.cells | right.cells == hull.cells and not left.cells & right.cells
    for name, spec in NAMED_REGIONS.items():
        assert derive_fragment(PLATE, name).cells == derive_fragment(PLATE, spec).cells
    assert derive_fragment(PLATE, ["Y"]).cells == derive_fragment(PLATE, "sun").cells


@pytest.mark.parametrize("bad", [
    "nope", {}, {"colors": []}, {"colors": ["Y"], "extra": 1}, {"colors": ["Y"], "rows": [5, 2]},
    {"colors": ["Y"], "rows": [0, 4]}, {"colors": ["Y"], "rows": [1]}, {"colors": ["Y"], "cols": ["C", "A"]},
    {"colors": ["Y"], "cols": [1, 2]}, 7,
])
def test_bad_specs_rejected(bad):
    with pytest.raises(ValueError):
        parse_spec(bad)


def test_resolve_requires_full_unique_coverage():
    handles = ["a1", "a2", "a3", "a4"]
    ok = resolve(SPLIT, handles, PLATE, {"S", "W"})
    assert sorted(ok) == [0, 1, 2, 3]
    assert resolve({"slot-0": "sun", "a2": "cloud", "a3": "hull", "slot-3": "mast_sail"}, handles, PLATE, {"S", "W"})
    with pytest.raises(ValueError, match="every agent"):
        resolve({k: v for k, v in SPLIT.items() if k != "a4"}, handles, PLATE, {"S", "W"})
    with pytest.raises(ValueError, match="unknown slot"):
        resolve({**SPLIT, "zz": "sun"}, handles, PLATE, {"S", "W"})
    with pytest.raises(ValueError, match="more than once"):
        resolve({**SPLIT, "slot-0": "sun"}, handles, PLATE, {"S", "W"})
    with pytest.raises(ValueError, match="no target cells"):
        resolve({**SPLIT, "a1": ["G"]}, handles, PLATE, {"S", "W"})
    with pytest.raises(ValueError, match="unassigned"):
        resolve({**SPLIT, "a3": {"colors": ["B"], "rows": [12, 12]}}, handles, PLATE, {"S", "W"})
    # without prefill the background is unknown too, so sky and water must be assigned
    with pytest.raises(ValueError, match="unassigned"):
        resolve(SPLIT, handles, PLATE, set())


def test_each_agent_sees_only_its_own_piece(tmp_path):
    agents = [Scripted([]) for _ in range(4)]
    task = {"prefill_background": ["S", "W"], "reference_split": SPLIT}
    result = run_config(recon_cfg(tmp_path, rounds=1, task=task, kind="doc_log"), render=False, agents=agents)
    for index, name in enumerate(["sun", "cloud", "hull", "mast_sail"]):
        seen = agents[index].seen[0]
        grid = render_lines(PLATE, derive_fragment(PLATE, name).cells)
        assert "\n".join(grid) in seen
        assert "YOUR PIECE OF THE TARGET" in seen and "teammates hold the rest" in seen
        assert "TARGET (visible to every painter)" not in seen
        assert "\n".join(PLATE[6:10]) not in seen
        # the full target grid never appears in the prompt
        assert "\n".join(PLATE) not in seen
    # distinct pieces: the sun's Y never shows in the hull painter's prompt target block
    hull_grid = agents[2].seen[0].split("no one sees the whole target.\n")[1].split("\nA ? marks")[0]
    assert set(hull_grid) == {"B", "?", "\n"}
    system = (result.run_dir / "prompts_rendered/system_slot-0.txt").read_text()
    assert "each painter sees only a different piece" in system
    saved = json.loads((result.run_dir / "reference_fragments.json").read_text())
    assert saved["slot-0"]["grid"] == grid_of(PLATE, "sun")
    config = json.loads((result.run_dir / "config.json").read_text())
    assert config["redesign"]["reference_split"]["slot-3"]["cells"] == 15


def grid_of(plate, name):
    return render_lines(plate, derive_fragment(plate, name).cells)


def test_without_split_everyone_sees_the_full_target(tmp_path):
    agents = [Scripted([]) for _ in range(4)]
    run_config(recon_cfg(tmp_path, rounds=1), render=False, agents=agents)
    assert "\n".join(PLATE) in agents[0].seen[0]
    assert "YOUR PIECE" not in agents[0].seen[0]


def test_split_conflicts_and_mode(tmp_path):
    cfg = recon_cfg(tmp_path, rounds=1, task={"reference_split": SPLIT, "prefill_background": ["S", "W"]},
                    assistance={"suggested_paints": True})
    with pytest.raises(ValueError, match="suggested_paints"):
        run_config(cfg, render=False)
    free = recon_cfg(tmp_path, rounds=1)
    free["task"] = {"mode": "free_creation", "reference_split": SPLIT}
    with pytest.raises(ValueError, match="requires reconstruction"):
        run_config(free, render=False)
