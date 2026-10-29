from swarm_canvas.engine import Canvas, Paint, parse_cell
from swarm_canvas.validate import validate_action


def test_later_painter_wins_and_records_overwrite():
    canvas = Canvas()
    events = canvas.apply(
        [Paint("SkyKeeper", "C5", "S"), Paint("Boatwright", "C5", "Y")],
        ["SkyKeeper", "Boatwright"],
    )
    assert canvas.snapshot()["cells"] == [
        {"cell": "C5", "color": "Y", "handle": "Boatwright"}
    ]
    assert events[-1]["overwrote"] == "SkyKeeper"
    assert events[-1]["order"] == 2
    assert events[-1]["applied"] is True


def test_nine_paints_eight_apply_one_over_budget():
    paints = [{"cell": f"A{i}", "color": "S"} for i in range(1, 10)]
    prepared = validate_action(
        handle="a1",
        action={"paints": paints},
        round_num=1,
        palette=["S"],
        paint_budget=8,
        comms_enabled=False,
        max_messages=2,
        max_chars=200,
    )
    assert len(prepared.paints) == 8
    over = [item for item in prepared.rejections if item["type"] == "over_budget"]
    assert len(over) == 1
    assert over[0]["cell"] == "A9"


def test_invalid_cell_and_unheld_color():
    prepared = validate_action(
        handle="a1",
        action={
            "paints": [
                {"cell": "Z9", "color": "S"},
                {"cell": "A17", "color": "S"},
                {"cell": "C5", "color": "O"},
                {"cell": "C5", "color": "S"},
            ]
        },
        round_num=2,
        palette=["S", "W"],
        paint_budget=8,
        comms_enabled=False,
        max_messages=2,
        max_chars=200,
    )
    reasons = [item["reason"] for item in prepared.rejections if item["type"] == "invalid"]
    assert reasons.count("cell") == 2
    assert "color" in reasons
    assert [paint.cell for paint in prepared.paints] == ["C5"]
    assert parse_cell("X16") == (23, 15)
    assert parse_cell("A0") is None


def test_text_grid_marks_blanks():
    text = Canvas().to_text()
    assert "A" in text.splitlines()[0] and "X" in text.splitlines()[0]
    assert text.splitlines()[1].startswith(" 1 ")
    assert "." in text
