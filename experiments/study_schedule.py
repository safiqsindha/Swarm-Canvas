"""Prepare a six-run plan; this command never makes model requests."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from swarm_canvas.paths import ROOT

SCHEDULE = [('baseline',11), ('reminder',11), ('reminder',12), ('baseline',12),
            ('baseline',13), ('reminder',13)]

def build_plan(root: Path = ROOT):
    required = [root/'docs/roadmap/2026-10-31-study-protocol.md',
                root/'swarm_canvas/completion_claims.py', root/'targets/sun_boat.txt',
                root/'swarm_canvas/reminder_gate.py', root/'swarm_canvas/run_audit.py',
                root/'swarm_canvas/study_scorecard.py', root/'experiments/study_condition.py',
                root/'configs/open_boat_dev.yaml']
    return {'status':'implemented_not_preregistered', 'model':'deepseek/deepseek-v4.1-flash-1017',
            'rounds':24, 'agents':4, 'paint_budget_per_agent':8,
            'schedule':[{'arm':arm,'seed':seed} for arm,seed in SCHEDULE],
            'preview_policy':'one shared set of four generated notes per seed',
            'protocol_hashes':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in required},
            'blockers':['immutable timestamped source and protocol snapshot', 'dedicated capped OpenRouter key',
                        'durable batch destination', 'scorecard and checkpoint review']}

if __name__ == '__main__':
    print(json.dumps(build_plan(), indent=2))
