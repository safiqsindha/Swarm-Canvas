"""Small open-ended boat smoke test; development observation, not a benchmark."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from swarm_canvas.larger_pilot import MODEL, preflight
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import load_config, run_config


def run_open_boat(output_root: Path | None = None):
    cfg = load_config(ROOT / 'configs/open_boat_dev.yaml')
    if cfg['model']['name'] != MODEL or cfg['model']['provider'] != 'openrouter':
        raise ValueError('smoke check requires the pinned free OpenRouter model')
    if output_root is not None:
        cfg['output_dir'] = str(output_root.resolve())
    with httpx.Client(timeout=20) as client:
        quota = preflight(client, os.environ.get('OPENROUTER_API_KEY'), 32)
    print(json.dumps({'stage': 'preflight', **quota}), flush=True)
    with model_request_budget(interval_seconds=3.5, max_requests=32) as budget:
        result = run_config(cfg, render=False,
                            on_round=lambda p: print(json.dumps({'stage': 'round', **p}), flush=True))
    scores = result.scores
    if (not scores.get('model_metadata_complete') or scores.get('cost_usd') != 0
            or scores.get('observed_models') != [cfg['model']['name']]):
        raise RuntimeError('pinned free model and reported zero cost not verified')
    return {'run_dir': str(result.run_dir), 'http_attempts': budget.requests, 'scores': scores}


if __name__ == '__main__':
    print(json.dumps(run_open_boat(), indent=2), flush=True)
