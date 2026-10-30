import json
from pathlib import Path

from swarm_canvas.readiness_check import assess


def test_real_diagnostic_requires_peer_ack_and_territory():
    root = Path(__file__).parents[1] / 'docs/coordination/2026-10-30-gates'
    events = [json.loads(line) for line in (root / 'integrated-required-events.jsonl').read_text().splitlines()]
    actions = json.loads((root / 'integrated-required-gate_actions.json').read_text())
    result = assess(events, actions, 2)
    assert result['model_calls'] == 8
    assert not any('acknowledged peer' in x for x in result['failures'])
    slot = next(e for e in events if e['type'] == 'paint' and e['agent_id'] == 'slot-0')
    slot['cell'] = 'X1'
    assert any('outside assigned' in x for x in assess(events, actions, 2)['failures'])
    for e in events:
        if e['type'] == 'ack' and e['agent_id'] == 'slot-0':
            e['applied'] = False
    assert any('acknowledged peer' in x for x in assess(events, actions, 2)['failures'])


def test_assist_only_uses_visible_territory_and_peer_lines():
    from swarm_canvas.readiness_check import assist_observation
    root = Path(__file__).parents[1] / 'docs/coordination/2026-10-30-readiness-revised'
    text = (root / 'prompts_rendered/round_03_slot-2.txt').read_text()
    hints = assist_observation(text)
    assert hints['latest_peer_line'] == 13
    assert 12 not in hints['peer_lines']
    assert hints['candidate_paints']
    assert all(x['column'] in 'MNOPQR' for x in hints['candidate_paints'])
    assert all(x['column'] != 'M' or x['row'] > 8 for x in hints['candidate_paints'])
