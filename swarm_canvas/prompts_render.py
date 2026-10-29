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


def comms_rules_file(condition: str, kind: str) -> str:
    if kind == "doc_log":
        return "comms_doc.txt"
    if kind == "swarmchat":
        return "comms_chat.txt"
    if condition.startswith("c0"):
        return "comms_c0.txt"
    return "comms_c1.txt"


def render_system(handle: str, palette: str, condition: str, kind: str) -> str:
    rules = read_prompt(comms_rules_file(condition, kind))
    return fill(
        read_prompt("system.txt"),
        {"handle": handle, "palette": palette, "comms_rules": rules},
    )


def render_turn(
    *,
    round_num: int,
    rounds: int,
    handle: str,
    cols: int,
    rows: int,
    canvas: str,
    palette: str,
    budget: int,
    scratchpad: str,
    inbox_lines: list[str] | None,
    comms_enabled: bool,
) -> str:
    if comms_enabled:
        body = "\n".join(inbox_lines or []) or "(none yet)"
        inbox_block = fill(read_prompt("inbox_block.txt"), {"lines": body})
        reply_rules = read_prompt("reply_comms.txt")
    else:
        inbox_block = ""
        reply_rules = read_prompt("reply_none.txt")
    return fill(
        read_prompt("turn.txt"),
        {
            "round": round_num,
            "rounds": rounds,
            "handle": handle,
            "cols": cols,
            "rows": rows,
            "canvas": canvas,
            "palette": palette,
            "budget": budget,
            "scratchpad": scratchpad or "(empty)",
            "inbox_block": inbox_block,
            "reply_rules": reply_rules,
        },
    )
