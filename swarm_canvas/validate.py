"""Turn an agent action into the paints, notes, and rejections that may apply."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from swarm_canvas.engine import Paint, parse_cell

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,19}$")


@dataclass
class Prepared:
    messages: list[str] = field(default_factory=list)
    acks: list[int] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    paints: list[Paint] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    rename_to: str | None = None
    scratchpad: str | None = None
    passed: bool = False
    parse_error: bool = False


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def validate_action(
    *,
    handle: str,
    action,
    round_num: int,
    palette: list[str],
    paint_budget: int,
    comms_enabled: bool,
    max_messages: int,
    max_chars: int,
    taken_handles: set[str] | None = None,
) -> Prepared:
    prepared = Prepared()
    if not isinstance(action, dict) or action.get("_parse_error"):
        prepared.parse_error = bool(isinstance(action, dict) and action.get("_parse_error"))
        prepared.passed = True
        if not isinstance(action, dict):
            prepared.rejections.append({"type": "invalid", "reason": "action_not_object"})
        return prepared

    held = set(palette)
    raw_messages = action.get("messages") or []
    if raw_messages and not isinstance(raw_messages, list):
        prepared.rejections.append({"type": "invalid", "reason": "messages_not_list"})
        raw_messages = []
    if not comms_enabled:
        if raw_messages:
            prepared.rejections.append(
                {"type": "invalid", "reason": "comms_disabled", "field": "messages"}
            )
        raw_messages = []
    else:
        for item in raw_messages:
            text = str(item).replace("\n", " ").strip()
            if not text:
                prepared.rejections.append({"type": "invalid", "reason": "empty_message"})
                continue
            text = text[:max_chars]
            if len(prepared.messages) >= max_messages:
                prepared.rejections.append(
                    {
                        "type": "message",
                        "applied": False,
                        "reason": "cap",
                        "text": text[:80],
                    }
                )
                continue
            prepared.messages.append(text)

    raw_acks = action.get("acks") or []
    if raw_acks and not isinstance(raw_acks, list):
        prepared.rejections.append({"type": "invalid", "reason": "acks_not_list"})
        raw_acks = []
    if not comms_enabled:
        if raw_acks:
            prepared.rejections.append(
                {"type": "invalid", "reason": "comms_disabled", "field": "acks"}
            )
    else:
        for item in raw_acks:
            line_no = _as_int(item)
            if line_no is None:
                prepared.rejections.append(
                    {"type": "invalid", "reason": "ack_not_int", "value": str(item)[:40]}
                )
                continue
            prepared.acks.append(line_no)

    rename = action.get("name")
    if rename is not None:
        if not isinstance(rename, str):
            prepared.rejections.append({"type": "rename", "applied": False, "reason": "name_type"})
        else:
            cleaned = rename.strip()
            if not cleaned or len(cleaned) > 20 or not _NAME_RE.match(cleaned):
                prepared.rejections.append(
                    {
                        "type": "rename",
                        "applied": False,
                        "reason": "name_length" if len(cleaned) > 20 or not cleaned else "name_chars",
                        "name": cleaned[:40],
                    }
                )
            elif taken_handles and cleaned in taken_handles and cleaned != handle:
                prepared.rejections.append(
                    {"type": "rename", "applied": False, "reason": "name_taken", "name": cleaned}
                )
            elif round_num == 1 or any(cleaned in text for text in prepared.messages):
                prepared.rename_to = cleaned
                prepared.rejections.append(
                    {"type": "rename", "applied": True, "name": cleaned, "from": handle}
                )
            else:
                prepared.rejections.append(
                    {
                        "type": "rename",
                        "applied": False,
                        "reason": "not_announced",
                        "name": cleaned,
                    }
                )

    paint_handle = prepared.rename_to or handle
    raw_paints = action.get("paints") or []
    if raw_paints and not isinstance(raw_paints, list):
        prepared.rejections.append({"type": "invalid", "reason": "paints_not_list"})
        raw_paints = []
    valid_count = 0
    for item in raw_paints:
        if not isinstance(item, dict):
            prepared.rejections.append({"type": "invalid", "reason": "paint_not_object"})
            continue
        cell = item.get("cell")
        color = item.get("color")
        cell_s = cell if isinstance(cell, str) else ""
        color_s = color if isinstance(color, str) else ""
        if parse_cell(cell_s) is None or color_s not in held:
            reason = "cell" if parse_cell(cell_s) is None else "color"
            prepared.rejections.append(
                {
                    "type": "invalid",
                    "reason": reason,
                    "cell": cell_s[:8],
                    "color": color_s[:8],
                    "applied": False,
                }
            )
            continue
        if valid_count >= paint_budget:
            prepared.rejections.append(
                {
                    "type": "over_budget",
                    "cell": cell_s,
                    "color": color_s,
                    "applied": False,
                }
            )
            continue
        valid_count += 1
        prepared.paints.append(Paint(agent=paint_handle, cell=cell_s, color=color_s))

    raw_requests = action.get("requests") or []
    if raw_requests and not isinstance(raw_requests, list):
        prepared.rejections.append({"type": "invalid", "reason": "requests_not_list"})
        raw_requests = []
    for item in raw_requests:
        if not isinstance(item, str) or not item.strip():
            prepared.rejections.append({"type": "invalid", "reason": "request_color"})
            continue
        prepared.requests.append(item.strip())

    scratch = action.get("scratchpad")
    if isinstance(scratch, str):
        prepared.scratchpad = scratch[:2000]

    did_anything = bool(
        prepared.paints
        or prepared.messages
        or prepared.acks
        or prepared.requests
        or prepared.rename_to
        or prepared.scratchpad is not None
    )
    if not did_anything and not prepared.rejections:
        prepared.passed = True
    return prepared
