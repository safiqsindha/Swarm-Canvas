"""Bounded, reproducible open-ended boat development runs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from swarm_canvas.larger_pilot import MODEL, preflight, source_hashes
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import load_config, run_config, resume_llm_run


def run_batch(seeds=(11,), rounds=4, output_root=None, *, interface_feedback=None):
    if not seeds or len(seeds) > 8 or len(set(seeds)) != len(seeds):
        raise ValueError('select between one and eight distinct seeds')
    if not 1 <= rounds <= 12:
        raise ValueError('development runs permit 1 to 12 rounds')
    cfg = load_config(ROOT / 'configs/open_boat_dev.yaml')
    if interface_feedback is not None:
        from swarm_canvas.interface_feedback import configure
        cfg['interface_feedback'] = configure({'interface_feedback': interface_feedback})
    if cfg['model']['name'] != MODEL or cfg['model']['provider'] != 'openrouter':
        raise ValueError('smoke check requires the pinned free OpenRouter model')
    cap = len(seeds) * rounds * len(cfg['agents']['handles']) * 2
    with httpx.Client(timeout=20) as client:
        quota = preflight(client, os.environ.get('OPENROUTER_API_KEY'), cap)
    root = Path(output_root or ROOT / 'runs').resolve() / ('open_boat_batch_' + uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    cfg['output_dir'] = str(root)
    source = source_hashes()
    # Include the selected config, which is not part of the assisted-pilot fingerprint.
    import hashlib
    source['configs/open_boat_dev.yaml'] = hashlib.sha256((ROOT / 'configs/open_boat_dev.yaml').read_bytes()).hexdigest()
    plan = {'status': 'running', 'research_evidence': False, 'seeds': list(seeds), 'rounds': rounds,
            'max_http_attempts': cap, 'interval_seconds': 3.5, 'preflight': quota,
            'source_sha256': source, 'interface_feedback': cfg.get('interface_feedback'), 'runs': []}
    manifest = root / 'batch.json'
    def save():
        tmp = root / 'batch.json.tmp'
        tmp.write_text(json.dumps(plan, indent=2) + '\n')
        os.replace(tmp, manifest)
    save()
    with model_request_budget(interval_seconds=3.5, max_requests=cap, ledger_path=root / "budget.sqlite3") as budget:
        try:
            for seed in seeds:
                actual = source_hashes()
                actual['configs/open_boat_dev.yaml'] = hashlib.sha256((ROOT / 'configs/open_boat_dev.yaml').read_bytes()).hexdigest()
                if actual != source:
                    raise RuntimeError('source files changed during batch')
                cfg.update(seed=seed, rounds=rounds)
                result = run_config(cfg, render=False,
                                    on_round=lambda p: print(json.dumps({'stage': 'round', **p}), flush=True))
                scores = result.scores
                plan['runs'].append({'seed': seed, 'run_dir': str(result.run_dir), 'scores': scores})
                save()
                if (not scores.get('model_metadata_complete') or scores.get('cost_usd') != 0
                        or scores.get('observed_models') != [MODEL] or not scores.get('reliability_ok')):
                    raise RuntimeError('pinned free model, cost, or reliability not verified')
            plan['status'] = 'completed'
        except Exception as exc:
            plan.update(status='failed', error_type=type(exc).__name__)
            raise
        finally:
            plan['http_attempts'] = budget.requests
            save()
    return manifest


def run_open_boat(output_root: Path | None = None):
    return run_batch(output_root=output_root)


def resume_batch(batch_dir):
    """Continue a single-seed batch only from its last clean LLM round boundary."""
    import hashlib
    root = Path(batch_dir).resolve()
    manifest = root / 'batch.json'
    plan = json.loads(manifest.read_text())
    if plan.get('status') != 'running' or len(plan.get('seeds', [])) != 1 or plan.get('runs'):
        raise ValueError('only a running single-seed batch is resumable')
    source = source_hashes()
    source['configs/open_boat_dev.yaml'] = hashlib.sha256((ROOT / 'configs/open_boat_dev.yaml').read_bytes()).hexdigest()
    if source != plan.get('source_sha256'):
        raise ValueError('source files changed since batch creation')
    cfg = load_config(ROOT / 'configs/open_boat_dev.yaml')
    if plan.get('interface_feedback') is not None:
        cfg['interface_feedback'] = plan['interface_feedback']
    if cfg['model']['name'] != MODEL or cfg['model']['provider'] != 'openrouter':
        raise ValueError('resume requires the pinned free OpenRouter model')
    cfg.update(seed=plan['seeds'][0], rounds=plan['rounds'], output_dir=str(root))
    paths = [p.parent for p in root.glob('*/config.json')]
    if len(paths) != 1:
        raise ValueError('batch must contain exactly one interrupted run')
    cap, interval = plan['max_http_attempts'], plan['interval_seconds']
    with model_request_budget(interval_seconds=interval, max_requests=cap,
                              ledger_path=root / 'budget.sqlite3', resume=True) as budget:
        with httpx.Client(timeout=20) as client:
            preflight(client, os.environ.get('OPENROUTER_API_KEY'), cap - budget.requests)
        try:
            result = resume_llm_run(cfg, paths[0], on_round=lambda p: print(
                json.dumps({'stage': 'round', **p}), flush=True))
            scores = result.scores
            if (not scores.get('model_metadata_complete') or scores.get('cost_usd') != 0
                    or scores.get('observed_models') != [MODEL] or not scores.get('reliability_ok')):
                raise RuntimeError('pinned free model, cost, or reliability not verified')
            plan['runs'].append({'seed': plan['seeds'][0], 'run_dir': str(result.run_dir), 'scores': scores})
            plan['status'] = 'completed'
        finally:
            plan['http_attempts'] = budget.requests
            tmp = root / 'batch.json.tmp'
            tmp.write_text(json.dumps(plan, indent=2) + '\n')
            os.replace(tmp, manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs='+', default=[11])
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--resume-batch', type=Path, help='resume a single-seed batch at a clean boundary')
    args = parser.parse_args()
    print(resume_batch(args.resume_batch) if args.resume_batch else run_batch(tuple(args.seeds), args.rounds), flush=True)
