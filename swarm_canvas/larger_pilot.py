"""Gated, capped development pilot. No confirmatory or causal claim."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from swarm_canvas.paths import ROOT
from swarm_canvas.readiness_check import assess, run
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.score import score_run

MODEL = 'nvidia/nemotron-3.5-super-vl:free'
SEEDS = (7, 8, 9)
ROUNDS = 12
CAP = 288


def verify_frozen_sources(root=ROOT):
    fingerprint = json.loads((root / 'docs/pilot/readiness_fingerprint.json').read_text())
    for name, expected in fingerprint['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'readiness source changed: {name}')
    tree = ast.parse((root / 'swarm_canvas/readiness_check.py').read_text())
    nodes = [n for n in tree.body if
             (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in
              ('assist_observation', 'ReadinessAgent', 'assess')) or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'INSTRUCTION' for t in n.targets))]
    digest = hashlib.sha256(ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False).encode()).hexdigest()
    if digest != fingerprint['readiness_semantics_sha256']:
        raise ValueError('readiness behavior changed since the gate runs')
    return fingerprint['evidence_source_commit']


def verify_readiness(root=ROOT):
    verify_frozen_sources(root)
    records = []
    for seed in (4, 5, 6):
        path = root / f'docs/coordination/2026-10-30-peer-schema-seed{seed}'
        summary = json.loads((path / 'readiness_summary.json').read_text())
        actions = json.loads((path / 'readiness_actions.json').read_text())
        events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
        results = assess(events, actions, 4)
        if (summary.get('seed') != seed or summary.get('rounds') != 4 or not summary.get('assist')
                or not summary.get('passed') or not results['passed']):
            raise ValueError(f'readiness seed {seed} failed')
        cfg = json.loads((path / 'config.json').read_text())
        if cfg.get('model', {}).get('name') != MODEL or not cfg.get('model', {}).get('require_coordination_fields'):
            raise ValueError(f'readiness seed {seed} uses the wrong model or schema')
        # Recalculate frame hash and scores from archived canvas, target and events.
        score = score_run(path)
        if (not score.get('model_metadata_complete') or score.get('observed_models') != [MODEL]
                or score.get('cost_usd') != 0):
            raise ValueError(f'readiness seed {seed} model or cost not verified')
        records.append({'seed': seed, 'correct_cells': score['target_matches'],
                        'final_hash': score['final_hash']})
    return records


def preflight(client, key, cap=CAP):
    if not key:
        raise ValueError('OPENROUTER_API_KEY is required')
    response = client.get('https://openrouter.ai/api/v1/key', headers={'Authorization': 'Bearer ' + key})
    response.raise_for_status()
    quota = response.json().get('data', {}).get('free_model_daily_requests', {})
    remaining = quota.get('remaining')
    if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or remaining < cap:
        raise RuntimeError('free request quota is unknown or below the full attempt cap')
    response = client.get('https://openrouter.ai/api/v1/models')
    response.raise_for_status()
    entry = next((m for m in response.json()['data'] if m['id'] == MODEL), None)
    if entry is None or any(float(entry.get('pricing', {}).get(k, 1)) != 0 for k in ('prompt', 'completion')):
        raise RuntimeError('pinned free model unavailable or not zero-priced')
    return {'remaining_free_requests': remaining, 'model': MODEL}


def source_hashes():
    files = [*sorted((ROOT / 'swarm_canvas').glob('*.py')),
             *sorted((ROOT / 'prompts').glob('*.txt')),
             ROOT / 'targets/sun_boat.txt', ROOT / 'configs/free_smoke_nemotron.yaml']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def launch(output_root=None):
    evidence = verify_readiness()
    with httpx.Client(timeout=20) as client:
        quota = preflight(client, os.environ.get('OPENROUTER_API_KEY'))
    root = Path(output_root or ROOT / 'runs').resolve() / ('larger_pilot_' + uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    path = root / 'pilot.json'
    source = source_hashes()
    plan = {'status': 'running', 'research_evidence': False, 'seeds': list(SEEDS),
            'rounds': ROUNDS, 'max_inference_attempts': CAP, 'interval_seconds': 3.5,
            'model': MODEL, 'assisted': True, 'readiness': evidence, 'preflight': quota,
            'source_sha256': source, 'runs': []}
    def save():
        path.write_text(json.dumps(plan, indent=2) + '\n')
    save()
    with model_request_budget(interval_seconds=3.5, max_requests=CAP, ledger_path=root / "budget.sqlite3") as budget:
        try:
            for seed in SEEDS:
                if source_hashes() != source:
                    raise RuntimeError('source files changed during pilot')
                result, summary = run(seed=seed, rounds=ROUNDS, output_root=root, assist=True, shared_budget=budget)
                plan['runs'].append({'run_dir': str(result.run_dir), 'summary': summary})
                save()
                if not summary['passed'] or not summary['task_scores']['model_metadata_complete'] or summary['task_scores']['observed_models'] != [MODEL]:
                    raise RuntimeError('pilot run failed adherence or model gate')
            plan['status'] = 'completed'
        except Exception as exc:
            plan.update(status='failed', error_type=type(exc).__name__)
            raise
        finally:
            plan['inference_attempts'] = budget.requests
            save()
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true', help='run the bounded free-only pilot')
    args = parser.parse_args()
    if args.launch:
        print(launch())
    else:
        print(json.dumps({'ready_runs': verify_readiness(), 'seeds': SEEDS, 'rounds': ROUNDS,
                          'max_inference_attempts': CAP, 'launch_started': False}, indent=2))
