"""Fill prompt files. Prompt text never lives as an inline string in Python."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from swarm_canvas.paths import PROMPTS

_PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")


def read_prompt(name: str) -> str:
    path = PROMPTS / name
    return path.read_text(encoding="utf-8").strip("\n")


def fill(template: str, values: dict[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return str(values[key])

    return _PLACEHOLDER.sub(replace, template)


def prompt_hashes() -> dict[str, str]:
    found = {}
    for path in sorted(PROMPTS.glob("*.txt")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        found[str(Path("prompts") / path.name)] = digest
    return found


def comms_rules_file(condition: str, kind: str, catalog_enabled: bool = True) -> str:
    if kind == "doc_log":
        return "comms_doc.txt"
    if kind == "swarmchat":
        return "comms_chat.txt"
    suffix = "" if catalog_enabled else "_nocatalog"
    if condition.startswith("c0"):
        return f"comms_c0{suffix}.txt"
    return f"comms_c1{suffix}.txt"


def render_system(
    handle: str,
    palette: str,
    condition: str,
    kind: str,
    *,
    agent_count: int = 4,
    paint_budget: int = 8,
    task_mode: str = "free_creation",
    agent_id: str = "painter",
    goal: str | None = None,
    open_coordination: bool = False,
    catalog_enabled: bool = True,
) -> str:
    rules = read_prompt(comms_rules_file(condition, kind, catalog_enabled))
    system_file = "system_open_coordination" if open_coordination else "system"
    if not catalog_enabled:
        system_file += "_nocatalog"
    return fill(
        read_prompt(system_file + ".txt"),
        {
            "handle": handle,
            "agent_id": agent_id,
            "palette": palette,
            "comms_rules": rules,
            "team_description": "the only painter on this grid"
            if agent_count == 1
            else f"one of {agent_count} painters sharing this grid",
            "paint_budget": paint_budget,
            "objective": ("Your shared goal: " + goal) if goal is not None else read_prompt(f"objective_{task_mode}.txt"),
        },
    )


def render_turn(
    *,
    round_num: int,
    rounds: int,
    handle: str,
    cols: int,
    rows: int,
    canvas: str,
    check: str,
    palette: str,
    budget: int,
    scratchpad: str,
    inbox_lines: list[str] | None,
    comms_enabled: bool,
    target: list[str] | None = None,
    paint_budget: int = 8,
    catalog: str = "",
    agent_id: str = "painter",
    catalog_enabled: bool = True,
    target_block_file: str = "target_block.txt",
    target_values: dict | None = None,
) -> str:
    suffix = "" if catalog_enabled else "_nocatalog"
    if comms_enabled:
        body = "\n".join(inbox_lines or []) or "(none yet)"
        inbox_block = fill(read_prompt("inbox_block.txt"), {"lines": body})
        reply_rules = read_prompt(f"reply_comms{suffix}.txt")
    else:
        inbox_block = ""
        reply_rules = read_prompt(f"reply_none{suffix}.txt")
    reply_rules = fill(reply_rules, {"paint_budget": paint_budget})
    target_block = (
        fill(read_prompt(target_block_file), {"target": "\n".join(target), **(target_values or {})})
        if target
        else ""
    )
    return fill(
        read_prompt(f"turn{suffix}.txt"),
        {
            "round": round_num,
            "rounds": rounds,
            "handle": handle,
            "agent_id": agent_id,
            "cols": cols,
            "rows": rows,
            "canvas": canvas,
            "target_block": target_block,
            "catalog": catalog,
            "check": check,
            "palette": palette,
            "budget": budget,
            "scratchpad": scratchpad or "(empty)",
            "inbox_block": inbox_block,
            "reply_rules": reply_rules,
        },
    )
