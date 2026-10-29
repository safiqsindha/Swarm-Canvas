from swarm_canvas.engine import Canvas, CellState, Paint, parse_cell
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


def test_column_and_row_are_joined_and_a_swapped_string_is_not():
    prepared = validate_action(
        handle="a1",
        action={
            "paints": [
                {"column": "I", "row": 8, "color": "K"},
                {"column": "i", "row": "2", "color": "S"},
                {"column": "8", "row": "I", "color": "S"},
                {"cell": "8I", "color": "S"},
            ]
        },
        round_num=2,
        palette=["S", "K"],
        paint_budget=8,
        comms_enabled=False,
        max_messages=2,
        max_chars=200,
    )
    assert [paint.cell for paint in prepared.paints] == ["I8", "I2"]
    reasons = [item["reason"] for item in prepared.rejections if item["type"] == "invalid"]
    assert reasons.count("cell") == 2


def test_text_grid_marks_blanks():
    text = Canvas().to_text()
    assert "A" in text.splitlines()[0] and "X" in text.splitlines()[0]
    assert text.splitlines()[1].startswith(" 1 ")
    assert "." in text


def test_board_check_counts_blanks_and_names_open_columns():
    canvas = Canvas()
    check = canvas.board_check()
    assert check.startswith("CHECK 0 painted, 384 blank.")
    assert "Open columns: A B C D E F G H I J K L M N O P Q R S T U V W X." in check
    canvas.cells[(0, 0)] = CellState("S", "a1")
    check = canvas.board_check()
    assert "CHECK 1 painted, 383 blank." in check
    assert "Open columns: B C" in check
    assert "A 15" in check
    assert "B 16" in check
    for col in range(canvas.cols):
        for row in range(canvas.rows):
            canvas.cells[(col, row)] = CellState("S", "a1")
    filled = canvas.board_check()
    assert filled.startswith("CHECK 384 painted, 0 blank.")
    assert "Open columns: none." in filled
