"""Read-only integrity audit of an exploratory or study attempt."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from swarm_canvas.request_budget import inspect_ledger


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(run_dir: Path, ledger_path: Path | None = None, preview_dir: Path | None = None,
          preview_ledger_path: Path | None = None):
    run_dir = Path(run_dir)
    cfg = json.loads((run_dir / 'config.json').read_text())
    events = _rows(run_dir / 'events.jsonl')
    trace = _rows(run_dir / 'traces.jsonl')
    model_calls = [x for x in events if x.get('type') == 'model_call' and x.get('status') == 'ok']
    failed_events = [x for x in events if x.get('type') in ('api_error', 'agent_error', 'parse_error')
                     or (x.get('type') == 'model_call' and x.get('status') != 'ok')]
    gens = [x for x in trace if x.get('event') == 'end' and x.get('name') == 'generate-painter-action']
    successful_gens = [x for x in gens if (x.get('metadata') or {}).get('http_status') == 200]
    event_ids = [x.get('response_id') for x in model_calls]
    trace_ids = [(x.get('metadata') or {}).get('response_id') for x in successful_gens]
    # Failed/schema-repair HTTP responses are still retained in trace and ledger.
    response_ids_match = (bool(event_ids) and all(event_ids) and all(trace_ids)
                          and collections.Counter(event_ids) == collections.Counter(trace_ids))
    rounds = int(cfg['rounds'])
    frames = [run_dir / 'canvas' / f'round_{i:02d}.json' for i in range(1, rounds + 1)]
    missing_frames = [str(p.name) for p in frames if not p.is_file()]
    invalid_frames, boundary_issues = [], []
    for number, frame_path in enumerate(frames, 1):
        if not frame_path.is_file():
            continue
        try:
            snapshot = json.loads(frame_path.read_text())
            if not isinstance(snapshot.get('cells'), list) or not snapshot.get('rows') or not snapshot.get('cols'):
                raise ValueError('invalid snapshot')
            boundary = run_dir / f'boundary_{number:02d}.json'
            if not boundary.is_file():
                boundary_issues.append(f'missing {boundary.name}')
            else:
                data = json.loads(boundary.read_text())
                if data.get('round') != number or data.get('canvas') != snapshot:
                    boundary_issues.append(f'mismatch {boundary.name}')
        except (OSError, ValueError, TypeError, AttributeError):
            invalid_frames.append(frame_path.name)
    final_hash_valid = False
    if not missing_frames:
        frame = json.loads(frames[-1].read_text())
        digest = hashlib.sha256(json.dumps(frame, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        final_hash_valid = digest == cfg.get('final_hash')
    export_summary = next((x for x in reversed(trace) if x.get('event') == 'export_summary'), None)
    preview = _rows(Path(preview_dir) / 'traces.jsonl') if preview_dir else []
    preview_gens = [x for x in preview if x.get('event') == 'end' and x.get('name') == 'generate-painter-action']
    ledger = inspect_ledger(ledger_path) if ledger_path else None
    preview_ledger = inspect_ledger(preview_ledger_path) if preview_ledger_path else None
    traced_http = sum(bool((x.get('metadata') or {}).get('http_status')) for x in [*gens, *preview_gens])
    if ledger is None:
        ledger_matches = None
    elif preview_ledger is not None:
        run_http = sum(bool((x.get('metadata') or {}).get('http_status')) for x in gens)
        preview_http = traced_http - run_http
        ledger_matches = (ledger['attempts_reserved'] == run_http and ledger['without_recorded_response'] == 0
                          and preview_ledger['attempts_reserved'] == preview_http
                          and preview_ledger['without_recorded_response'] == 0)
    else:
        ledger_matches = ledger['attempts_reserved'] == traced_http and ledger['without_recorded_response'] == 0
    result = {'status': cfg.get('status'), 'rounds_expected': rounds,
              'missing_frames': missing_frames, 'invalid_frames': invalid_frames,
              'boundary_issues': boundary_issues, 'final_hash_valid': final_hash_valid,
              'successful_model_calls': len(model_calls), 'generation_attempts': len(gens),
              'failure_events': len(failed_events),
              'generation_response_ids_match': response_ids_match,
              'trace_export_summary_present': export_summary is not None,
              'local_trace_closed': export_summary is not None,
              'external_delivery_verified': bool((export_summary or {}).get('delivery_verified', False)),
              'swarmchat_errors': cfg.get('swarmchat_errors'),
              'ledger': ledger, 'preview_ledger': preview_ledger, 'traced_http_attempts_including_preview': traced_http,
              'ledger_matches_trace': ledger_matches}
    result['local_checks_passed'] = (result['status'] == 'completed' and not missing_frames and not invalid_frames and final_hash_valid
                        and response_ids_match and export_summary is not None
                        and not failed_events and result['swarmchat_errors'] == 0)
    result['passed'] = (result['local_checks_passed'] and not boundary_issues and ledger is not None
                        and preview_dir is not None and ledger_matches is True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--preview', type=Path)
    parser.add_argument('--preview-ledger', type=Path)
    args = parser.parse_args()
    result = audit(args.run_dir, args.ledger, args.preview, args.preview_ledger)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
