import json
from pathlib import Path

from openpyxl import load_workbook
from PIL import Image

from swarm_canvas.agents import LLMAgent
from swarm_canvas.models import ModelConfig
from swarm_canvas.paths import PROMPTS, ROOT, TARGETS
from swarm_canvas.runner import run_config, run_from_yaml
from swarm_canvas.validate import validate_action

BANNED = ("sun", "boat", "water")


class Scripted:
    def __init__(self, actions):
        self.actions = list(actions)
        self.handle = ""
        self.palette = []
        self.seen = []

    def act(self, observation: str) -> dict:
        self.seen.append(observation)
        if not self.actions:
            return {}
        return self.actions.pop(0)


def _cfg(kind="none", condition="c1_nochat", agent_type="random", **extra):
    base = {
        "condition": condition,
        "run_code": condition.split("_")[0],
        "seed": 1,
        "rounds": 2,
        "grid": {"cols": 24, "rows": 16},
        "agents": {"count": 4, "handles": ["a1", "a2", "a3", "a4"], "type": agent_type},
        "paint_budget_per_round": 8,
        "palette": ["S", "W", "Y", "B", "w", "P", "G", "K"],
        "supplier": {"catalog": ["O", "R", "Gy", "L"], "swarm_budget": 4},
        "comms": {
            "kind": kind,
            "messages_per_round": 2,
            "max_chars": 200,
            "acks_enabled": kind != "none",
            "inbox_context_lines": 20,
        },
        "model": {"provider": "fake", "name": "fake", "temperature": 0, "max_tokens": 100},
        "output_dir": extra.pop("output_dir"),
    }
    base.update(extra)
    return base


def _events(run_dir: Path):
    return [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rename_rules():
    ok = validate_action(
        handle="a1",
        action={"name": "Boatwright"},
        round_num=1,
        palette=["S"],
        paint_budget=8,
        comms_enabled=True,
        max_messages=2,
        max_chars=200,
    )
    assert ok.rename_to == "Boatwright"

    later = validate_action(
        handle="a1",
        action={"name": "Boatwright"},
        round_num=3,
        palette=["S"],
        paint_budget=8,
        comms_enabled=True,
        max_messages=2,
        max_chars=200,
    )
    assert later.rename_to is None

    announced = validate_action(
        handle="a1",
        action={"name": "Boatwright", "messages": ["I am Boatwright from here on."]},
        round_num=3,
        palette=["S"],
        paint_budget=8,
        comms_enabled=True,
        max_messages=2,
        max_chars=200,
    )
    assert announced.rename_to == "Boatwright"

    too_long = validate_action(
        handle="a1",
        action={"name": "BoatwrightTheVeryLongOne"},
        round_num=1,
        palette=["S"],
        paint_budget=8,
        comms_enabled=False,
        max_messages=2,
        max_chars=200,
    )
    assert too_long.rename_to is None


def test_catalog_color_usable_next_round_only_by_requester(tmp_path):
    agents = [
        Scripted(
            [
                {"requests": ["O"], "paints": [{"cell": "A1", "color": "O"}]},
                {"paints": [{"cell": "A1", "color": "O"}]},
            ]
        ),
        Scripted(
            [
                {},
                {"paints": [{"cell": "B1", "color": "O"}]},
            ]
        ),
        Scripted([{}, {}]),
        Scripted([{}, {}]),
    ]
    result = run_config(
        _cfg(output_dir=str(tmp_path), rounds=2),
        render=False,
        agents=agents,
    )
    events = _events(result.run_dir)
    round1_invalid = [
        event
        for event in events
        if event["round"] == 1 and event["type"] == "invalid" and event["agent"] == "a1"
    ]
    assert round1_invalid and round1_invalid[0]["reason"] == "color"
    grants = [event for event in events if event["type"] == "grant"]
    assert grants == [
        event
        for event in grants
        if event["agent"] == "a1" and event["color"] == "O" and event["round"] == 1
    ]
    assert len(grants) == 1
    paints = [event for event in events if event["type"] == "paint" and event.get("applied")]
    assert paints[0]["agent"] == "a1" and paints[0]["color"] == "O" and paints[0]["round"] == 2
    round2_invalid = [
        event
        for event in events
        if event["round"] == 2 and event["type"] == "invalid" and event["agent"] == "a2"
    ]
    assert round2_invalid and round2_invalid[0]["reason"] == "color"


def test_exposure_event_matches_observation(tmp_path):
    agents = [
        Scripted([{"messages": ["I will hold the left columns."]}, {}]),
        Scripted([{}, {}]),
        Scripted([{}, {}]),
        Scripted([{}, {}]),
    ]
    result = run_config(
        _cfg(kind="doc_log", condition="c2a_doc", output_dir=str(tmp_path), rounds=2),
        render=False,
        agents=agents,
    )
    events = _events(result.run_dir)
    round2 = [
        event
        for event in events
        if event["type"] == "exposure" and event["round"] == 2 and event["agent"] == "a2"
    ]
    assert round2[0]["lines"] == [1]
    observation = (result.run_dir / "prompts_rendered" / "round_02_slot-1.txt").read_text(
        encoding="utf-8"
    )
    assert "#1 a1: I will hold the left columns." in observation
    shown = [int(token[1:]) for token in observation.split() if token.startswith("#") and token[1:].isdigit()]
    assert shown == round2[0]["lines"]


def test_c1_prompts_omit_comms_and_nobody_sees_the_plate(tmp_path):
    result = run_from_yaml(
        ROOT / "configs" / "c1_nochat.yaml",
        seed=1,
        rounds=1,
        output_root=tmp_path,
        render=False,
    )
    plate = (TARGETS / "sun_boat.txt").read_text(encoding="utf-8")
    rendered = list((result.run_dir / "prompts_rendered").glob("*.txt"))
    assert rendered
    blob = "\n".join(path.read_text(encoding="utf-8") for path in rendered).lower()
    assert "message" not in blob
    assert "ack" not in blob
    for word in BANNED:
        assert word not in blob
    assert plate.strip() not in blob

    for path in PROMPTS.glob("*.txt"):
        text = path.read_text(encoding="utf-8").lower()
        for word in BANNED:
            assert word not in text, path.name


def test_same_seed_same_canvas(tmp_path):
    first = run_from_yaml(
        ROOT / "configs" / "c1_nochat.yaml",
        seed=7,
        rounds=30,
        output_root=tmp_path / "a",
        render=False,
    )
    second = run_from_yaml(
        ROOT / "configs" / "c1_nochat.yaml",
        seed=7,
        rounds=30,
        output_root=tmp_path / "b",
        render=False,
    )
    assert first.final_hash == second.final_hash
    assert (tmp_path / "a").joinpath(first.run_id, "events.jsonl").read_bytes() == (
        tmp_path / "b"
    ).joinpath(second.run_id, "events.jsonl").read_bytes()


def test_full_dry_run_writes_outputs(tmp_path):
    result = run_from_yaml(
        ROOT / "configs" / "c2a_doc.yaml",
        seed=1,
        rounds=30,
        output_root=tmp_path,
        render=True,
    )
    run_dir = result.run_dir
    for number in range(1, 31):
        assert (run_dir / "canvas" / f"round_{number:02d}.json").is_file()
        png = run_dir / "canvas" / f"round_{number:02d}.png"
        xlsx = run_dir / "canvas" / f"round_{number:02d}.xlsx"
        assert png.stat().st_size > 0
        assert xlsx.stat().st_size > 0
        assert (run_dir / "scratchpads" / f"round_{number:02d}.json").is_file()
    image = Image.open(run_dir / "canvas" / "round_01.png")
    assert image.size == (24 * 20, 16 * 20)
    book = load_workbook(run_dir / "canvas" / "round_30.xlsx")
    sheet = book.active
    assert sheet.max_row >= 16 and sheet.max_column >= 24
    assert sheet["A1"].fill.fgColor is not None
    gif = (run_dir / "timelapse.gif").read_bytes()
    assert gif[:3] == b"GIF"
    for name in ("events.jsonl", "config.json", "scores.json", "doc_log.txt"):
        assert (run_dir / name).is_file()
    for index in range(4):
        assert (run_dir / "scratchpads" / f"slot-{index}.txt").is_file()
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert config["seed"] == 1
    assert config["prompt_hashes"]
    assert "token_totals" in config
    assert result.scores["cells"] == 384


def test_unparseable_model_output_repairs_once_then_passes(tmp_path):
    cfg = ModelConfig(provider="fake", fake_responses=["nope", "still nope"])
    agent = LLMAgent("a1", cfg, "system")
    result = agent.act("observation")
    assert result.get("_parse_error") is True
    assert cfg.usage["calls"] == 2
    repair = (PROMPTS / "repair.txt").read_text(encoding="utf-8").strip()
    assert cfg.calls_log[1][-1]["content"] == repair

    recovered = ModelConfig(
        provider="fake",
        fake_responses=["not json", '{"scratchpad":"hold left","paints":[{"cell":"A1","color":"S"}]}'],
    )
    parsed = LLMAgent("a1", recovered, "system").act("observation")
    assert parsed["paints"][0]["cell"] == "A1"

    agents = [LLMAgent(f"a{i}", ModelConfig(provider="fake", fake_responses=["??", "??"]), "sys") for i in range(1, 5)]
    run = run_config(
        _cfg(agent_type="llm", output_dir=str(tmp_path), rounds=1),
        render=False,
        agents=agents,
    )
    events = _events(run.run_dir)
    assert sum(event["type"] == "parse_error" for event in events) == 4
    assert sum(event["type"] == "pass" for event in events) == 4
