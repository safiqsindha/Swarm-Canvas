"""Matched four-condition development pilot; dry runs are the default."""

from __future__ import annotations

import json
import random
from pathlib import Path
from uuid import uuid4

from swarm_canvas.paths import ROOT
from swarm_canvas.runner import _validate_config, load_config, run_config

CONDITIONS = ("c0_baseline", "c1_nochat", "c2a_doc", "c2b_swarmchat")
TARGETS = ("sun_boat", "stripes", "checker")


def run_pilot(
    *,
    output_root: Path,
    live: bool = False,
    model: str = "",
    swarmchat_url: str = "",
    token_file: str = "",
    repeats: int = 5,
    rounds: int = 30,
) -> Path:
    if repeats < 1 or rounds < 1:
        raise ValueError("repeats and rounds must be positive")
    if live and (not model.endswith(":free") or model == ":free"):
        raise ValueError(
            "A live pilot requires one explicit OpenRouter model ID ending in :free; the random free router is not matched"
        )
    if live and not swarmchat_url:
        raise ValueError(
            "SwarmChat is mandatory: supply --swarmchat-url for a live pilot"
        )
    configs = []
    for target in TARGETS:
        for seed in range(1, repeats + 1):
            conditions = list(CONDITIONS)
            random.Random(f"{target}:{seed}").shuffle(conditions)
            for condition in conditions:
                cfg = load_config(ROOT / "configs" / f"{condition}.yaml")
                cfg.update(seed=seed, rounds=rounds, run_code=f"{condition}_{target}")
                cfg["task"]["target"] = f"targets/{target}.txt"
                cfg["agents"]["type"] = "llm" if live else "random"
                if live:
                    cfg["model"]["name"] = model
                if condition == "c2b_swarmchat":
                    cfg["comms"]["server_url"] = swarmchat_url
                    cfg["comms"]["token_file"] = token_file
                _validate_config(cfg, None)
                configs.append(cfg)
    suite_dir = output_root.resolve() / f"pilot_{uuid4().hex}"
    suite_dir.mkdir(parents=True, exist_ok=False)
    summary = {
        "mode": "free_model_development" if live else "random_smoke_test",
        "status": "running",
        "conditions": list(CONDITIONS),
        "targets": list(TARGETS),
        "requested_model": model if live else None,
        "runs": [],
        "research_evidence": False,
    }
    manifest = suite_dir / "pilot.json"

    def save():
        manifest.write_text(json.dumps(summary, indent=2) + "\n")

    save()
    try:
        for cfg in configs:
            cfg["output_dir"] = str(suite_dir)
            result = run_config(cfg, render=False)
            summary["runs"].append(
                {
                    "condition": cfg["condition"],
                    "target": cfg["task"]["target"],
                    "seed": cfg["seed"],
                    "run": result.run_id,
                    "scores": result.scores,
                }
            )
            save()
        summary["status"] = "completed"
    except Exception as exc:
        summary.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        save()
    return manifest
