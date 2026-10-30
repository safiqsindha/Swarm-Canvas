"""A reproducible native transport check with scripted agents and zero model calls."""

from __future__ import annotations

import json
import re
from pathlib import Path

from swarm_canvas.paths import ROOT
from swarm_canvas.runner import load_config, run_config


class TransportCheckAgent:
    def __init__(self):
        self.round = 0
        self.handle = ""

    def act(self, observation: str) -> dict:
        self.round += 1
        if self.round == 1:
            return {"messages": [f"{self.handle}: native transport check"]}
        if self.round == 2:
            exposed = re.findall(r"^#(\d+) ", observation, flags=re.MULTILINE)
            return {"acks": [int(exposed[0])]} if exposed else {}
        return {}


def check_swarmchat(
    *, output_root: Path, server_url: str = "", token_file: str = ""
) -> dict:
    cfg = load_config(ROOT / "configs/c2b_swarmchat.yaml")
    cfg.update(
        rounds=3, run_code="swarmchat_check", output_dir=str(output_root.resolve())
    )
    cfg["agents"]["type"] = "random"
    cfg["task"] = {"mode": "free_creation"}
    cfg["comms"].update(
        backend="remote" if server_url else "local",
        server_url=server_url,
        token_file=token_file,
    )
    result = run_config(
        cfg,
        agents=[TransportCheckAgent() for _ in cfg["agents"]["handles"]],
        render=False,
    )
    events = [
        json.loads(line)
        for line in (result.run_dir / "events.jsonl").read_text().splitlines()
    ]
    messages = [e for e in events if e["type"] == "message" and e.get("applied")]
    participants = {e["agent_id"] for e in messages}
    if len(messages) != 4 or not all(e.get("remote_id") for e in messages):
        raise RuntimeError("Native send verification failed")
    views = [e for e in events if e["type"] == "exposure" and e["round"] == 3]
    if len(views) != 4:
        raise RuntimeError("Native inbox verification failed")
    for view in views:
        own = next(m for m in messages if m["agent_id"] == view["agent_id"])
        receipt = next(
            m for m in view["native_messages"] if m["remote_id"] == own["remote_id"]
        )
        if set(receipt["read_by"] or []) != participants - {view["agent_id"]}:
            raise RuntimeError("Native read receipt verification failed")
    if result.scores["token_totals"]["calls"] != 0:
        raise RuntimeError("A scripted transport check must never call a model")
    summary = {
        "status": "passed",
        "run_dir": str(result.run_dir),
        "messages": len(messages),
        "receipt_checks": len(views),
        "model_calls": 0,
        "research_evidence": False,
    }
    (result.run_dir / "transport_check.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary
