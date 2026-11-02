"""Opt-in study-redesign options: background prefill, scoring background, stop action.

Every option is off unless its config key is present, so existing configs run
exactly as before. See docs/roadmap/study-redesign.md.
"""

from __future__ import annotations

from swarm_canvas import reference_split
from swarm_canvas.engine import Canvas, Paint, cell_name
from swarm_canvas.prompts_render import fill, read_prompt

BACKGROUND_DEFAULT = ("S", "W")
PREFILL_HANDLE = "prefill"
TASK_KEYS = ("prefill_background", "background", "reference_split")


def _color_list(value, name: str, palette: set[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(c, str) and c for c in value):
        raise ValueError(f"task.{name} must be a list of color codes")
    if len(set(value)) != len(value):
        raise ValueError(f"task.{name} has duplicate colors")
    unknown = [c for c in value if c not in palette]
    if unknown:
        raise ValueError(f"task.{name} has colors outside the palette: {unknown}")
    return list(value)


def configure(cfg: dict, plate: list[str] | None) -> dict:
    """Validate the redesign keys and return normalized settings.

    `active` is false when no redesign key is present.
    """
    task = cfg.get("task") or {}
    palette = set(cfg.get("palette", []))
    present = [key for key in TASK_KEYS if key in task]
    if present and plate is None:
        raise ValueError(f"task.{present[0]} requires reconstruction mode")
    settings: dict = {
        "prefill_background": [],
        "background": list(BACKGROUND_DEFAULT),
    }
    if "background" in task:
        settings["background"] = _color_list(task["background"], "background", palette)
    if "prefill_background" in task:
        colors = _color_list(task["prefill_background"], "prefill_background", palette)
        absent = [c for c in colors if c not in set("".join(plate))]
        if absent:
            raise ValueError(f"task.prefill_background colors not in the target: {absent}")
        settings["prefill_background"] = colors
    stop_action = cfg.get("stop_action", False)
    if not isinstance(stop_action, bool):
        raise ValueError("stop_action must be a boolean")
    settings["stop_action"] = stop_action
    settings["fragments"] = None
    if "reference_split" in task:
        if (cfg.get("assistance") or {}).get("suggested_paints"):
            raise ValueError("task.reference_split cannot be combined with assistance.suggested_paints")
        settings["fragments"] = reference_split.resolve(
            task["reference_split"],
            [str(h) for h in cfg["agents"]["handles"]],
            plate,
            set(settings["prefill_background"]),
        )
    settings["active"] = bool(present) or "stop_action" in cfg
    return settings


def manifest(settings: dict) -> dict | None:
    """What goes into config.json. None when no redesign option is on."""
    if not settings["active"]:
        return None
    out = {key: settings[key] for key in ("prefill_background", "background", "stop_action")}
    if settings["fragments"]:
        out["reference_split"] = reference_split.manifest(settings["fragments"])
    return out


def prefill_canvas(canvas: Canvas, plate: list[str], colors: list[str], run_id: str) -> list[dict]:
    """Paint every target cell whose color is in `colors` as the harness pseudo-agent.

    Returns `prefill` events (round 0). They are not agent paints.
    """
    wanted = set(colors)
    paints = [
        Paint(agent=PREFILL_HANDLE, cell=cell_name(col, row), color=char, agent_id=PREFILL_HANDLE)
        for row, line in enumerate(plate)
        for col, char in enumerate(line)
        if char in wanted
    ]
    events = []
    for event in canvas.apply(paints, [PREFILL_HANDLE]):
        event["type"] = "prefill"
        event["run"] = run_id
        event["round"] = 0
        events.append(event)
    return events


def prefill_note(colors: list[str]) -> str:
    return fill(read_prompt("redesign_prefill.txt"), {"colors": " ".join(colors)})


def objective_mode(task_mode: str, settings: dict) -> str:
    """Selects prompts/objective_<mode>.txt."""
    return "reconstruction_split" if settings["fragments"] else task_mode


def split_target(fragment: reference_split.Fragment) -> dict:
    """render_turn arguments that replace the shared target with one fragment."""
    return {
        "target": list(fragment.lines),
        "target_block_file": "target_block_split.txt",
        "target_values": {"description": fragment.description, "cell_count": len(fragment.cells)},
    }


def done_note() -> str:
    return read_prompt("redesign_done.txt")


def colors_of(canvas: Canvas) -> dict:
    """A frozen {(col, row): color} view, used as the round-start snapshot."""
    return {pos: state.color for pos, state in canvas.cells.items() if state.color}


def incomplete_counts(colors: dict, plate: list[str] | None, background, cells=None) -> dict:
    """Blank and wrong cells among the non-background target cells (or `cells`)."""
    blank = wrong = 0
    total_blank = len(plate) * len(plate[0]) - len(colors) if plate else None
    if plate:
        for row, line in enumerate(plate):
            for col, want in enumerate(line):
                if want in background or (cells is not None and (col, row) not in cells):
                    continue
                have = colors.get((col, row))
                if have is None:
                    blank += 1
                elif have != want:
                    wrong += 1
    return {"blank_nonbg": blank, "incorrect_nonbg": wrong, "blank_total": total_blank}
