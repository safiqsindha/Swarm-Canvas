"""Play-stage coding. Live providers go through call_model; dry runs stay heuristic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from swarm_canvas.models import ModelConfig, call_model
from swarm_canvas.prompts_render import fill, read_prompt


def judge_run(run_dir: str | Path, model_cfg: ModelConfig | None = None) -> dict:
    run_dir = Path(run_dir)
    events = []
    events_path = run_dir / "events.jsonl"
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    config = {}
    config_path = run_dir / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    notes = [
        f"r{event.get('round')} {event.get('agent')}: {event.get('text')}"
        for event in events
        if event.get("type") == "message" and event.get("applied") and event.get("text")
    ]
    transcript = "\n".join(notes) if notes else "(no notes)"
    prompt = fill(
        read_prompt("judge_play_stage.txt"),
        {
            "condition": config.get("condition", run_dir.name),
            "rounds": config.get("rounds", ""),
            "transcript": transcript,
        },
    )
    provider = model_cfg.provider if model_cfg else "heuristic"
    if model_cfg and provider in {
        "anthropic",
        "openrouter",
        "openai_compatible",
        "fake",
    }:
        model_cfg = replace(model_cfg, output_kind="judge")
        raw = call_model([{"role": "user", "content": prompt}], model_cfg)
        result = {"mode": provider, "raw": raw, "prompt_sha_inputs": True}
    else:
        result = {
            "mode": "heuristic",
            "stages": _heuristic(events, int(config.get("rounds") or 30)),
        }
    result["run"] = config.get("run", run_dir.name)
    (run_dir / "judge.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _heuristic(events: list[dict], rounds: int) -> list[dict]:
    if rounds <= 0 or not any(
        e.get("type") == "message" and e.get("applied") for e in events
    ):
        return []
    cuts = [1, max(1, rounds // 3 + 1), max(1, 2 * rounds // 3 + 1), rounds + 1]
    labels = ["opening", "middle", "closing"]
    stages = []
    for label, start, end in zip(labels, cuts, cuts[1:]):
        if end <= start:
            continue
        paints = sum(
            1
            for event in events
            if event.get("type") == "paint"
            and event.get("applied")
            and start <= int(event.get("round") or 0) < end
        )
        stages.append(
            {
                "name": label,
                "rounds": [start, end - 1],
                "evidence": f"{paints} applied paints in this span",
            }
        )
    return stages
