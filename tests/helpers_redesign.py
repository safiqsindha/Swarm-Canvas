"""Shared builders for the study-redesign tests. No model calls."""

import json
from pathlib import Path


class Scripted:
    """Plays a fixed list of actions, then passes. Records every observation it saw."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.handle = ""
        self.palette = []
        self.seen = []

    def act(self, observation: str) -> dict:
        self.seen.append(observation)
        return self.actions.pop(0) if self.actions else {}


def recon_cfg(output_dir, *, agents=4, rounds=3, budget=8, kind="none", task=None, **extra):
    handles = [f"a{i + 1}" for i in range(agents)]
    cfg = {
        "condition": "redesign_test",
        "run_code": "rd",
        "seed": 1,
        "rounds": rounds,
        "grid": {"cols": 24, "rows": 16},
        "agents": {"count": agents, "handles": handles, "type": "random"},
        "paint_budget_per_round": budget,
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
        "output_dir": str(output_dir),
        "task": {"mode": "reconstruction", "target": "targets/sun_boat.txt", **(task or {})},
    }
    cfg.update(extra)
    return cfg


def events_of(run_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (Path(run_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
