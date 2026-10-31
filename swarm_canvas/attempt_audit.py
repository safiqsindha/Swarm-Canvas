"""Inspect durable run state without claiming a process is alive or resuming it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def inspect_attempt(path):
    path = Path(path).resolve()
    config = json.loads((path / 'config.json').read_text())
    result = {'status': config.get('status'), 'last_completed_round': config.get('last_completed_round'),
              'checkpoint_valid': None, 'generation_starts_upper_bound': None,
              'incomplete_generation_spans': None, 'boundary_valid': None}
    if config.get('checkpoint_frame'):
        frame = (path / config['checkpoint_frame']).resolve()
        if frame.parent != path / 'canvas':
            raise ValueError('checkpoint frame outside canvas directory')
        result['checkpoint_valid'] = frame.is_file() and hashlib.sha256(frame.read_bytes()).hexdigest() == config.get('checkpoint_sha256')
    if config.get('boundary_state'):
        from swarm_canvas.boundary_state import validate_boundary
        result['boundary_valid'] = validate_boundary(path, config)
    trace_path = path / 'traces.jsonl'
    if trace_path.exists():
        started, ended = set(), set()
        lines = trace_path.read_text().splitlines()
        truncated_tail = False
        for index, line in enumerate(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if index != len(lines) - 1:
                    raise ValueError('trace contains corruption before its final line')
                truncated_tail = True
                break
            if event.get('name') == 'generate-painter-action':
                if event.get('event') == 'start': started.add(event['id'])
                if event.get('event') == 'end': ended.add(event['id'])
        result['generation_starts_upper_bound'] = len(started) + int(truncated_tail)
        result['truncated_trace_tail'] = truncated_tail
        result['incomplete_generation_spans'] = len(started - ended)
    return result


def plan_batch_recovery(batch_dir):
    """Plan a fresh attempt without mutating or combining interrupted runs.

    The caller must separately establish that the original process has stopped.
    """
    batch_dir = Path(batch_dir).resolve()
    batch = json.loads((batch_dir / 'batch.json').read_text())
    if batch.get('status') == 'completed':
        raise ValueError('batch already completed')
    cap = batch.get('max_http_attempts')
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise ValueError('batch is missing a valid request cap')
    consumed = 0
    attempts = []
    for cfg in sorted(batch_dir.glob('open_boat_*/config.json')):
        info = inspect_attempt(cfg.parent)
        if info['generation_starts_upper_bound'] is None:
            raise ValueError('cannot establish request bound without every trace')
        consumed += info['generation_starts_upper_bound']
        meta = json.loads(cfg.read_text())
        attempts.append({'run_dir': str(cfg.parent), 'seed': meta.get('seed'), **info})
    from swarm_canvas.score import _final_snapshot
    completed = set()
    observed = {Path(item['run_dir']).resolve(): item for item in attempts}
    for record in batch.get('runs', []):
        run_path = Path(record.get('run_dir', '')).resolve()
        if run_path not in observed or run_path.parent != batch_dir:
            raise ValueError('completed run is outside the batch or missing')
        meta = json.loads((run_path / 'config.json').read_text())
        if (meta.get('status') != 'completed' or meta.get('seed') != record.get('seed')
                or not record.get('scores', {}).get('reliability_ok')
                or not meta.get('final_hash')
                or record.get('scores', {}).get('final_hash') != meta.get('final_hash')):
            raise ValueError('completed run metadata is inconsistent')
        _final_snapshot(run_path)
        completed.add(record['seed'])
    seeds = batch.get('seeds')
    if not isinstance(seeds, list) or not seeds:
        raise ValueError('batch is missing seed order')
    if consumed > cap:
        raise ValueError('recorded request upper bound exceeds batch cap')
    return {'status': 'plan_only', 'original_status': batch.get('status'),
            'completed_seeds': [s for s in seeds if s in completed],
            'restart_seeds_from_round_one': [s for s in seeds if s not in completed],
            'attempts_upper_bound': consumed, 'remaining_attempts_lower_bound': cap - consumed,
            'original_process_stopped': 'unverified', 'attempts': attempts,
            'note': 'No requests were made; retain all attempts. A restart is a new attempt, not continuation of the old SwarmChat session.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--batch', action='store_true', help='plan a conservative restart for a batch')
    args = parser.parse_args()
    print(json.dumps(plan_batch_recovery(args.path) if args.batch else inspect_attempt(args.path), indent=2))
