"""Conservative reference-reconstruction scorecard for exploratory or study runs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from swarm_canvas.completion_claims import is_explicit_completion_claim
from swarm_canvas.engine import cell_name
from swarm_canvas.score import _final_snapshot, load_plate


def score(run_dir: Path, target_path: Path):
    run_dir = Path(run_dir)
    config = json.loads((run_dir/'config.json').read_text())
    if config.get('status') != 'completed':
        raise ValueError('Only completed attempts have a final score; report failures separately')
    target = load_plate(Path(target_path))
    final = _final_snapshot(run_dir)
    if len(target) != final['rows'] or any(len(row) != final['cols'] for row in target):
        raise ValueError('Target and canvas dimensions differ')
    expected = {cell_name(col,row):color for row, line in enumerate(target) for col,color in enumerate(line)}
    painted = {x['cell']:x['color'] for x in final['cells']}
    foreground = {key: color for key,color in expected.items() if color not in ('S','W')}
    events = [json.loads(line) for line in (run_dir/'events.jsonl').read_text().splitlines() if line.strip()]
    claims = []
    for event in events:
        if event.get('type') != 'message' or not event.get('applied') or not is_explicit_completion_claim(event.get('text')):
            continue
        number = int(event['round'])
        previous = run_dir/'canvas'/f'round_{number-1:02d}.json'
        if number == 1:
            prior = {}
        elif previous.is_file():
            prior = {x['cell']:x['color'] for x in json.loads(previous.read_text())['cells']}
        else:
            raise ValueError(f'Missing observation frame for round {number}')
        claims.append({'round':number, 'sender':event.get('agent_id'), 'text':event.get('text'),
                       'message_id':event.get('remote_id'), 'blank_cells':len(expected)-len(prior),
                       'incorrect_cells':sum(prior.get(key) != value for key,value in expected.items())})
    sequential, round_start_redundant, paints = {}, 0, 0
    start_state = {}
    current_round = None
    sequential_redundant = 0
    paints_after_claim = 0
    for event in events:
        if event.get('type') != 'paint' or not event.get('applied'):
            continue
        number = int(event['round'])
        if current_round != number:
            if current_round is not None and number < current_round:
                raise ValueError('Paint events are not ordered by round')
            current_round, start_state = number, dict(sequential)
        cell, color = event['cell'], event['color']
        sequential_redundant += sequential.get(cell) == color
        round_start_redundant += start_state.get(cell) == color
        sequential[cell] = color
        paints += 1
        if claims and number > claims[0]['round']:
            paints_after_claim += 1
    return {'run':config.get('run'), 'target':str(target_path),
            'target_sha256':hashlib.sha256(Path(target_path).read_bytes()).hexdigest(),
            'total_cells':len(expected),
            'painted_cells':len(painted), 'blank_cells':len(expected)-len(painted),
            'exact_matches':sum(painted.get(k)==v for k,v in expected.items()),
            'foreground_matches':sum(painted.get(k)==v for k,v in foreground.items()),
            'foreground_cells':len(foreground), 'claims':claims,
            'applied_paints':paints, 'sequential_same_color_paints':sequential_redundant,
            'round_start_same_color_applied_paints':round_start_redundant,
            'paints_in_rounds_after_first_claim':paints_after_claim if claims else None,
            'claim_detector':'conservative lexical trigger; manual review required',
            'scope':'reference reconstruction; not a visual-quality rating'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path); parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(json.dumps(score(args.run_dir,args.target),indent=2))
