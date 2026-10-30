"""Explicit-message diagnostic, separate from spontaneous coordination comparisons."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from swarm_canvas.agents import LLMAgent
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import _model_config, load_config, run_config

INSTRUCTION = """Explicit coordination diagnostic (not the spontaneous-chat task):
You must include one short coordination note in messages on every turn.
On round 1, propose column ownership for slot-0, slot-1, slot-2 and slot-3 that covers A-X without overlaps. State which columns you claim.
On later rounds, read the actual peer notes, acknowledge at least one exposed peer line in acks, and state your current claimed columns in a message. Reconcile conflicting claims rather than copying them blindly.
Paint within your claimed columns. Keep the ownership plan in scratchpad. Do not invent peer notes or line numbers.
Return the same JSON action schema, including messages, paints and scratchpad; include acks when peer notes are visible."""


class CoordinationAgent(LLMAgent):
    def __init__(self, *args):
        super().__init__(*args)
        self.actions = []

    def act(self, observation):
        action = super().act(observation + "\n\n" + INSTRUCTION)
        self.actions.append(action)
        return action


def run_coordination_check(output_root: Path | None = None):
    cfg = load_config(ROOT / "configs/free_smoke_nemotron.yaml")
    cfg.update(rounds=4, run_code="explicit_coordination", abort_on_model_failure=True)
    if output_root is not None:
        cfg["output_dir"] = str(output_root.resolve())
    model = cfg["model"]["name"]
    response = httpx.get("https://openrouter.ai/api/v1/models", timeout=20)
    response.raise_for_status()
    entry = next(m for m in response.json()["data"] if m["id"] == model)
    if any(
        float(entry.get("pricing", {}).get(k, 1)) != 0 for k in ("prompt", "completion")
    ):
        raise RuntimeError("Expected zero-priced free endpoint")
    agents = [
        CoordinationAgent(handle, _model_config(cfg["model"]), "")
        for handle in cfg["agents"]["handles"]
    ]
    with model_request_budget(interval_seconds=3.5, max_requests=32) as budget:
        result = run_config(
            cfg,
            agents=agents,
            render=True,
            on_round=lambda p: print(json.dumps({"stage": "round", **p}), flush=True),
        )
    actions = {f"slot-{i}": a.actions for i, a in enumerate(agents)}
    (result.run_dir / "diagnostic_actions.json").write_text(
        json.dumps(actions, indent=2) + "\n"
    )
    (result.run_dir / "diagnostic_instruction.txt").write_text(INSTRUCTION + "\n")
    events = [
        json.loads(line)
        for line in (result.run_dir / "events.jsonl").read_text().splitlines()
    ]
    summary = {
        "purpose": "explicit_coordination_diagnostic",
        "research_evidence": False,
        "run_dir": str(result.run_dir),
        "http_requests": budget.requests,
        "scores": result.scores,
        "message_senders": sorted(
            {
                e["agent_id"]
                for e in events
                if e["type"] == "message" and e.get("applied")
            }
        ),
        "applied_acknowledgments": sum(
            e["type"] == "ack" and e.get("applied", False) for e in events
        ),
    }
    (result.run_dir / "diagnostic_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


def probe_action_schema():
    """Two fixed message-only probes; no task-performance claim."""
    from swarm_canvas.agents import parse_model_json
    from swarm_canvas.models import ModelConfig, call_model

    rows = []
    with model_request_budget(interval_seconds=3.5, max_requests=4):
        for kind in ("painter", "judge"):
            cfg = ModelConfig(
                provider="openrouter",
                name="nvidia/nemotron-3.5-super-vl:free",
                temperature=0,
                max_tokens=400,
                reasoning_enabled=False,
                output_kind=kind,
            )
            raw = call_model(
                [
                    {
                        "role": "user",
                        "content": 'Return exactly this JSON object and no other fields: {"messages":["coordination-check"]}',
                    }
                ],
                cfg,
            )
            rows.append(
                {
                    "schema_mode": kind,
                    "raw": raw,
                    "parsed": parse_model_json(raw),
                    "calls": cfg.call_records,
                }
            )
    root = ROOT / "runs/schema_probe"
    root.mkdir(exist_ok=True)
    (root / "result.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows
