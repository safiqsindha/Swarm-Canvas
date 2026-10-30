"""Predeclared, bounded C1/C2b development pair. Never confirmatory research."""

from __future__ import annotations

import hashlib
import json
import os
import random
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx

from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import _validate_config, load_config, run_config


def run_paired_check(
    *,
    output_root: Path | None = None,
    rounds: int = 15,
    seed: int = 1,
    interval_seconds: float = 3.5,
    max_requests: int = 240,
    on_progress=None,
) -> dict:
    """Same target, model and settings; fixed random condition order before calls."""
    if rounds < 1 or max_requests < rounds * 8:
        raise ValueError("Budget must cover at least both conditions' main model calls")
    model = "nvidia/nemotron-3.5-super-vl:free"
    configs = []
    order = ["c1_nochat", "c2b_swarmchat"]
    random.Random(seed).shuffle(order)
    for condition in order:
        cfg = load_config(ROOT / "configs" / f"{condition}.yaml")
        cfg.update(
            rounds=rounds,
            seed=seed,
            run_code=f"paired_{condition}",
            abort_on_model_failure=True,
        )
        cfg["agents"]["type"] = "llm"
        cfg["model"].update(
            provider="openrouter",
            name=model,
            temperature=0.2,
            max_tokens=1600,
            reasoning_enabled=False,
        )
        _validate_config(cfg, None)
        configs.append(cfg)
    # Only request counters are retained; neither credentials nor credit balances are logged.
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is required")
    with httpx.Client(timeout=20) as client:
        response = client.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": "Bearer " + key},
        )
        response.raise_for_status()
        quota = response.json().get("data", {}).get("free_model_daily_requests", {})
        catalog = client.get("https://openrouter.ai/api/v1/models")
        catalog.raise_for_status()
        entry = next((m for m in catalog.json()["data"] if m["id"] == model), None)
    if entry is None or any(
        float(entry.get("pricing", {}).get(k, 1)) != 0 for k in ("prompt", "completion")
    ):
        raise RuntimeError(
            "Pinned free endpoint is unavailable or no longer zero-priced"
        )
    remaining = quota.get("remaining")
    if isinstance(remaining, (int, float)) and remaining < max_requests:
        raise RuntimeError(
            f"Insufficient free request quota for the capped pair: {remaining} remaining, {max_requests} reserved"
        )
    root = Path(output_root or ROOT / "runs").resolve() / f"paired_check_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    for cfg in configs:
        cfg["output_dir"] = str(root)
    public_configs = deepcopy(configs)
    for config in public_configs:
        config["model"].pop("api_key", None)
    source_files = [
        *sorted((ROOT / "swarm_canvas").glob("*.py")),
        *sorted((ROOT / "prompts").glob("*.txt")),
        ROOT / "targets/sun_boat.txt",
    ]
    plan = {
        "status": "planned",
        "research_evidence": False,
        "purpose": "paired_development_check",
        "requested_model": model,
        "canonical_slug": entry.get("canonical_slug"),
        "rounds": rounds,
        "seed": seed,
        "condition_order": order,
        "conditions": public_configs,
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_files
        },
        "interval_seconds": interval_seconds,
        "max_http_requests": max_requests,
        "free_request_quota_before": quota,
        "runs": [],
    }
    manifest = root / "pair.json"

    def save():
        manifest.write_text(json.dumps(plan, indent=2) + "\n")

    def progress(data):
        if on_progress is not None:
            on_progress(data)
        else:
            print(json.dumps({"stage": "round", **data}), flush=True)

    save()
    with model_request_budget(
        interval_seconds=interval_seconds, max_requests=max_requests
    ) as budget:
        plan["status"] = "running"
        save()
        try:
            for cfg in configs:
                result = run_config(cfg, render=True, on_round=progress)
                if (
                    not result.scores.get("model_metadata_complete")
                    or result.scores.get("observed_models") != [model]
                    or result.scores.get("cost_usd") != 0
                ):
                    raise RuntimeError(
                        "Expected pinned model and reported zero-cost metadata were not confirmed"
                    )
                plan["runs"].append(
                    {
                        "condition": cfg["condition"],
                        "run_dir": str(result.run_dir),
                        "scores": result.scores,
                    }
                )
                save()
            if not all(r["scores"]["reliability_ok"] for r in plan["runs"]):
                raise RuntimeError("Reliability failures make this pair ineligible")
            plan["status"] = "completed"
            plan["eligible_for_descriptive_comparison"] = True
        except Exception as exc:
            plan.update(
                status="failed",
                error_type=type(exc).__name__,
                eligible_for_descriptive_comparison=False,
            )
            raise
        finally:
            plan["http_requests_attempted"] = budget.requests
            save()
    return {
        "status": plan["status"],
        "manifest": str(manifest),
        "research_evidence": False,
        "http_requests_attempted": budget.requests,
        "runs": plan["runs"],
    }
