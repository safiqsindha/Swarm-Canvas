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
