"""Opt-in study-redesign options: background prefill, scoring background, stop action.

Every option is off unless its config key is present, so existing configs run
exactly as before. See docs/roadmap/study-redesign.md.
"""

from __future__ import annotations

from swarm_canvas.engine import Canvas, Paint, cell_name
from swarm_canvas.prompts_render import fill, read_prompt

BACKGROUND_DEFAULT = ("S", "W")
PREFILL_HANDLE = "prefill"
TASK_KEYS = ("prefill_background", "background")


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
    settings["active"] = bool(present)
    return settings


def manifest(settings: dict) -> dict | None:
    """What goes into config.json. None when no redesign option is on."""
    if not settings["active"]:
        return None
    return {key: settings[key] for key in ("prefill_background", "background")}


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
