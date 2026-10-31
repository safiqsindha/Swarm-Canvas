"""Two bounded free-model probes of reference visibility over native SwarmChat."""
from __future__ import annotations

import json
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx

from swarm_canvas.agents import LLMAgent
from swarm_canvas.larger_pilot import MODEL, preflight, source_hashes
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import _model_config, load_config, run_config
from swarm_canvas.score import load_plate
from swarm_canvas.tracing import trace_run


class ProbeAgent(LLMAgent):
    def __init__(self, handle, model_cfg, mode, index, reference):
        super().__init__(handle, model_cfg, '')
        self.mode, self.index, self.reference = mode, index, reference
        self.preview_notes = None
        self.turn = 0
        self.suppressed = []

    def act(self, observation):
        self.turn += 1
        if self.mode == 'preview_once' and self.turn == 1:
            observation += '\n\nYour own notes from the reference preview, which is now hidden:\n' + self.preview_notes
        if self.mode == 'leader_visible':
            if self.index == 0:
                observation += ('\n\nYou are the designated leader. Direct the other painters through SwarmChat; '
                                'you do not paint or request colors. Only you receive the reference directly.\n'
                                'REFERENCE GRID (24 columns A-X, rows 1-16):\n' + self.reference)
            else:
                observation += ('\n\nThe designated leader is slot-0. Only the leader sees the reference. '
                                'Coordinate with the leader through SwarmChat while you paint.')
        result = super().act(observation)
        if self.mode == 'leader_visible' and self.index == 0:
            removed = {key: result.pop(key) for key in ('paints', 'requests') if key in result}
            if removed:
                self.suppressed.append({'round': self.turn, 'removed': removed})
        return result


def launch():
    cap = 104  # 2 x 6 x 4 x 2, plus 4 preview agents x 2 attempts.
    key = os.environ.get('OPENROUTER_API_KEY')
    with httpx.Client(timeout=20) as client:
        quota = preflight(client, key, cap)
    cfg = load_config(ROOT / 'configs/open_boat_dev.yaml')
    if cfg['model']['provider'] != 'openrouter' or cfg['model']['name'] != MODEL:
        raise ValueError('expected pinned free OpenRouter model')
    cfg.update(seed=11, rounds=6, interface_feedback={'color_legend': True, 'action_results': True})
    cfg['task'] = {'mode': 'free_creation', 'open_coordination': True,
                   'goal': 'Recreate the shared reference boat scene as accurately as possible.'}
    reference = '\n'.join(load_plate(ROOT / 'targets/sun_boat.txt'))
    root = ROOT / 'runs' / ('reference_visibility_' + uuid4().hex)
    root.mkdir(parents=True)
    sources = source_hashes()
    for path in (Path(__file__).resolve(), ROOT / 'configs/open_boat_dev.yaml'):
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'status': 'running', 'research_evidence': False, 'seed': 11, 'rounds': 6,
                'reference': 'targets/sun_boat.txt', 'preflight': quota, 'max_http_attempts': cap,
                'source_sha256': sources, 'conditions': []}
    def save():
        tmp = root / 'probe.json.tmp'
        tmp.write_text(json.dumps(manifest, indent=2) + '\n')
        os.replace(tmp, root / 'probe.json')
    save()
    with model_request_budget(interval_seconds=3.5, max_requests=cap, ledger_path=root/'budget.sqlite3') as budget:
        try:
            for mode in ('preview_once', 'leader_visible'):
                target_dir = root / mode
                target_dir.mkdir()
                cfg['condition'] = 'reference_' + mode
                cfg['run_code'] = 'reference_' + mode
                cfg['output_dir'] = str(target_dir)
                model = _model_config(cfg['model'])
                agents = [ProbeAgent(handle, replace(model, usage={'calls':0,'input_tokens':0,'output_tokens':0,'retries':0},
                                      calls_log=[], call_records=[]), mode, i, reference)
                          for i, handle in enumerate(cfg['agents']['handles'])]
                if mode == 'preview_once':
                    preview = target_dir / 'preview'
                    preview.mkdir()
                    with trace_run(preview, {'condition': cfg['condition'], 'seed': 11, 'rounds': 0}):
                        for agent in agents:
                            agent.system_prompt = ('You are a painter preparing to reproduce a shared 24 by 16 reference. '
                                'You will see it only now. Write useful notes in the JSON scratchpad field. '
                                'Do not paint or send messages in this preparation step.')
                            prompt = ('REFERENCE GRID, columns A-X, rows 1-16:\n' + reference +
                                      '\nColor codes: S light blue, W dark blue, Y yellow, B brown, '
                                      'w off-white, P pink, G light green, K black. '
                                      'Return a JSON object with a nonempty scratchpad string.')
                            action = LLMAgent.act(agent, prompt)
                            if not isinstance(action.get('scratchpad'), str) or not action['scratchpad'].strip():
                                raise RuntimeError('preview did not return nonempty notes')
                            records = agent.model_cfg.call_records
                            if not records or any(r.get('served_model') != MODEL or r.get('cost_usd') != 0 for r in records):
                                raise RuntimeError('preview model or zero cost not verified')
                            agent.preview_notes = action['scratchpad'][:2000]
                            agent.model_cfg.call_records = []
                            agent.model_cfg.calls_log = []
                result = run_config(cfg, render=False, agents=agents,
                    on_round=lambda p: print(json.dumps({'condition': mode, **p}), flush=True))
                scores = result.scores
                if (not scores.get('reliability_ok') or not scores.get('model_metadata_complete')
                        or scores.get('observed_models') != [MODEL] or scores.get('cost_usd') != 0):
                    raise RuntimeError('model, zero cost, or reliability not verified')
                record = {'condition': mode, 'run_dir': str(result.run_dir), 'scores': scores,
                          'leader_suppressed_actions': agents[0].suppressed if mode == 'leader_visible' else []}
                manifest['conditions'].append(record)
                manifest['http_attempts'] = budget.requests
                save()
            manifest['status'] = 'completed'
        except BaseException as exc:
            manifest.update(status='failed', error_type=type(exc).__name__)
            raise
        finally:
            manifest['http_attempts'] = budget.requests
            save()
    return root / 'probe.json'


if __name__ == '__main__':
    print('PROBE_MANIFEST', launch(), flush=True)
