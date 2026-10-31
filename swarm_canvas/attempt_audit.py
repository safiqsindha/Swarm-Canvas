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
              'incomplete_generation_spans': None}
    if config.get('checkpoint_frame'):
        frame = (path / config['checkpoint_frame']).resolve()
        if frame.parent != path / 'canvas':
            raise ValueError('checkpoint frame outside canvas directory')
        result['checkpoint_valid'] = frame.is_file() and hashlib.sha256(frame.read_bytes()).hexdigest() == config.get('checkpoint_sha256')
    trace_path = path / 'traces.jsonl'
    if trace_path.exists():
        started, ended = set(), set()
        for line in trace_path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # a process may have died while writing its last line
            if event.get('name') == 'generate-painter-action':
                if event.get('event') == 'start': started.add(event['id'])
                if event.get('event') == 'end': ended.add(event['id'])
        result['generation_starts_upper_bound'] = len(started)
        result['incomplete_generation_spans'] = len(started - ended)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir')
    print(json.dumps(inspect_attempt(parser.parse_args().run_dir), indent=2))
