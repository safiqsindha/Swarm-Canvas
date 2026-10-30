"""Agent protocol, the seeded RandomAgent, and LLMAgent."""

from __future__ import annotations

import json
import random
import re
from typing import Protocol

from swarm_canvas.engine import COL_LETTERS
from swarm_canvas.models import ModelCallError, ModelConfig, call_model
from swarm_canvas.prompts_render import read_prompt
from swarm_canvas.tracing import observation

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class Agent(Protocol):
    handle: str

    def act(self, observation: str) -> dict: ...


class RandomAgent:
    """Random valid paints and no notes. One stream per painter, from the run seed."""

    def __init__(self, handle: str, seed: int, index: int, paint_budget: int = 8):
        self.handle = handle
        self.index = index
        self.paint_budget = paint_budget
        self.palette: list[str] = []
        self.scratchpad = ""
        self.rng = random.Random(f"{seed}:{index}")

    def act(self, observation: str) -> dict:
        del observation  # the runner puts the same snapshot in front of every painter
        palette = list(self.palette)
        if not palette:
            return {}
        count = self.rng.randint(1, self.paint_budget)
        paints = []
        for _ in range(count):
            column = COL_LETTERS[self.rng.randrange(24)]
            row = self.rng.randrange(1, 17)
            color = palette[self.rng.randrange(len(palette))]
            paints.append({"cell": f"{column}{row}", "color": color})
        return {"paints": paints}


class LLMAgent:
    """Keeps the system prompt, its scratchpad, and the current observation only."""

    def __init__(self, handle: str, model_cfg: ModelConfig, system_prompt: str):
        self.handle = handle
        self.model_cfg = model_cfg
        self.system_prompt = system_prompt
        self.scratchpad = ""
        self.palette: list[str] = []

    def act(self, observation: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": observation},
        ]
        try:
            return self._act(messages)
        except ModelCallError as exc:
            return {
                "_api_error": True,
                "_error_type": exc.error_type,
                "_http_status": exc.http_status,
            }

    def _act(self, messages: list[dict]) -> dict:
        raw = self._ask(messages)
        with observation("parse-painter-action", input=raw) as parse:
            parsed = parse_model_json(raw)
            parse.update(output=parsed, level="WARNING" if parsed is None else "DEFAULT")
        if parsed is None:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": read_prompt("repair.txt")})
            raw = self._ask(messages)
            with observation("parse-painter-action", input=raw, metadata={"repair": True}) as parse:
                parsed = parse_model_json(raw)
                parse.update(output=parsed, level="ERROR" if parsed is None else "DEFAULT")
        if parsed is None:
            return {"_parse_error": True, "_raw": raw[:500]}
        scratch = parsed.get("scratchpad")
        if isinstance(scratch, str):
            self.scratchpad = scratch[:2000]
        return parsed

    def _ask(self, messages: list[dict]) -> str:
        return call_model(messages, self.model_cfg)


def parse_model_json(raw: str) -> dict | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE.sub("", text).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    return value
