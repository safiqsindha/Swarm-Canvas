"""Interleaved, resumable schedule for the two 24-round peek conditions.

Run with OPENROUTER_API_KEY set. Restart with --resume PATH after quota resets.
An interrupted active attempt requires manual inspection; it is never replayed.
"""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from experiments import free_peek_probe, voluntary_peek_probe
from swarm_canvas.larger_pilot import preflight
from swarm_canvas.paths import ROOT

SCHEDULE = [('costs_turn', 11), ('free_look', 11), ('free_look', 12),
            ('costs_turn', 12), ('costs_turn', 13), ('free_look', 13)]
CAPS = {'costs_turn': 200, 'free_look': 392}


def execute(path=None):
    path = Path(path).resolve() if path else ROOT / 'runs' / ('peek_comparison_' + uuid4().hex + '.json')
    if path.exists():
        plan = json.loads(path.read_text())
        if plan.get('schedule') != [list(x) for x in SCHEDULE]:
            raise ValueError('saved comparison schedule differs')
        if any(x['status'] == 'running' for x in plan['attempts']):
            raise RuntimeError('interrupted attempt requires manual inspection')
    else:
        plan = {'schedule': SCHEDULE, 'attempts': [], 'status': 'running',
                'rounds': 24, 'painters': 4, 'exploratory': True}
    def save():
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(plan, indent=2) + '\n')
        os.replace(tmp, path)
    save()
    for condition, seed in SCHEDULE:
        if any(x['condition'] == condition and x['seed'] == seed for x in plan['attempts']):
            continue
        try:
            with httpx.Client(timeout=20) as client:
                preflight(client, os.getenv('OPENROUTER_API_KEY'), CAPS[condition])
        except RuntimeError as exc:
            if 'free request quota' not in str(exc):
                raise
            plan['status'] = 'waiting_for_free_quota'
            save()
            print('WAITING_FOR_FREE_QUOTA', path, condition, seed, flush=True)
            return path
        attempt = {'condition': condition, 'seed': seed, 'status': 'running'}
        plan['attempts'].append(attempt)
        save()
        before = set((ROOT / 'runs').glob('reference_visibility_*'))
        try:
            module = voluntary_peek_probe if condition == 'costs_turn' else free_peek_probe
            attempt['manifest'] = str(module.launch(seed=seed))
            attempt['status'] = 'completed'
        except Exception as exc:
            attempt.update(status='failed', error_type=type(exc).__name__,
                           created_runs=sorted(str(p) for p in set((ROOT / 'runs').glob('reference_visibility_*')) - before))
        save()
    plan['status'] = 'finished'
    save()
    print('COMPARISON_FINISHED', path, flush=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path)
    execute(parser.parse_args().resume)
