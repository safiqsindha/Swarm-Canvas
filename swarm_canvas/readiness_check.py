"""Bounded development gate for explicitly scaffolded canvas coordination."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from swarm_canvas.agents import LLMAgent
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import _model_config, load_config, run_config

INSTRUCTION = (
    'Read the canvas and target and paint within your assigned columns. '
    'Your permanent slot column assignments are: slot-0 A-F, slot-1 G-L, '
    'slot-2 M-R, slot-3 S-X. Every turn output messages as an array containing '
    'one short string stating your assignment and intended work. When peer '
    'messages are visible, include acks as an array of their real line numbers. '
    'Return paints, messages and acks together in the JSON action object. '
    'Never invent line numbers.'
)


class ReadinessAgent(LLMAgent):
    def __init__(self, *args):
        super().__init__(*args)
        self.actions = []

    def act(self, observation):
        action = super().act(observation + '\n\n' + INSTRUCTION)
        self.actions.append(action)
        return action


def assess(events, actions, rounds):
    """Evaluate predeclared transport and action adherence, not task success."""
    failures = []
    slots = [f'slot-{i}' for i in range(4)]
    messages = {e['line']: e for e in events if e['type'] == 'message' and e.get('applied')}
    calls = [e for e in events if e['type'] == 'model_call']
    for r in range(1, rounds + 1):
        for slot in slots:
            action = actions[slot][r - 1]
            if any(not isinstance(action.get(k), list) for k in ('messages', 'acks', 'paints')):
                failures.append(f'{slot} round {r}: missing or invalid required fields')
            scoped = [e for e in events if e.get('round') == r and e.get('agent_id') == slot]
            if not any(e['type'] == 'message' and e.get('applied') for e in scoped):
                failures.append(f'{slot} round {r}: no applied message')
            paints = [e for e in scoped if e['type'] == 'paint' and e.get('applied')]
            if not paints:
                failures.append(f'{slot} round {r}: no applied paint')
            i = int(slot[-1]); allowed = 'ABCDEFGHIJKLMNOPQRSTUVWX'[i*6:(i+1)*6]
            if any(e['cell'][0] not in allowed for e in paints):
                failures.append(f'{slot} round {r}: painted outside assigned columns')
            exposure = next((e for e in scoped if e['type'] == 'exposure'), {})
            peer_lines = {line for line in exposure.get('lines', []) if line in messages and messages[line]['agent_id'] != slot}
            if peer_lines and not any(e['type'] == 'ack' and e.get('applied') and e.get('line') in peer_lines for e in scoped):
                failures.append(f'{slot} round {r}: no acknowledged peer message')
    if len(calls) != 4 * rounds or any(e.get('status') != 'ok' for e in calls):
        failures.append('model calls missing, repaired, or failed')
    if any(e.get('cost_usd') != 0 for e in calls):
        failures.append('reported cost is nonzero or unavailable')
    bad = [e for e in events if e['type'] in ('parse_error', 'api_error', 'agent_error')]
    if bad:
        failures.append('model, agent, or parsing errors')
    paint_events = [e for e in events if e['type'] == 'paint' and e.get('applied')]
    return {'passed': not failures, 'failures': failures, 'model_calls': len(calls),
            'messages': len(messages), 'applied_paints': len(paint_events),
            'unique_cells': len({e['cell'] for e in paint_events}),
            'applied_acks': sum(e['type'] == 'ack' and bool(e.get('applied')) for e in events)}


def run(seed=3, rounds=4, output_root=None):
    cfg = load_config(ROOT / 'configs/free_smoke_nemotron.yaml')
    cfg.update(seed=seed, rounds=rounds, run_code='readiness_scaffolded', abort_on_model_failure=True)
    cfg['model']['require_coordination_fields'] = True
    if output_root is not None:
        cfg['output_dir'] = str(Path(output_root).resolve())
    agents = [ReadinessAgent(h, _model_config(cfg['model']), '') for h in cfg['agents']['handles']]
    with model_request_budget(interval_seconds=3.5, max_requests=rounds * 4 * 2) as budget:
        result = run_config(cfg, render=False, agents=agents,
                            on_round=lambda p: print(json.dumps({'stage': 'round', **p}), flush=True))
    actions = {f'slot-{i}': a.actions for i, a in enumerate(agents)}
    events = [json.loads(line) for line in (result.run_dir / 'events.jsonl').read_text().splitlines()]
    summary = assess(events, actions, rounds)
    summary.update(run_id=result.run_id, seed=seed, rounds=rounds, request_attempts=budget.requests,
                   task_scores=result.scores, condition='explicit_fixed_ownership',
                   gate_scope='action and communication adherence, not autonomous coordination or benchmark validity')
    (result.run_dir / 'readiness_actions.json').write_text(json.dumps(actions, indent=2) + '\n')
    (result.run_dir / 'readiness_instruction.txt').write_text(INSTRUCTION + '\n')
    (result.run_dir / 'readiness_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return result, summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=3)
    parser.add_argument('--rounds', type=int, default=4)
    args = parser.parse_args()
    if not 2 <= args.rounds <= 4:
        parser.error('readiness check permits 2 to 4 rounds')
    result, summary = run(args.seed, args.rounds)
    print(json.dumps({'run_dir': str(result.run_dir), **summary}), flush=True)
