"""Two bounded free-model probes of reference visibility over native SwarmChat."""
from __future__ import annotations

import json
import hashlib
import os
import threading
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


_audit_lock = threading.Lock()

class ProbeAgent(LLMAgent):
    def __init__(self, handle, model_cfg, mode, index, reference):
        super().__init__(handle, model_cfg, '')
        self.mode, self.index, self.reference = mode, index, reference
        self.preview_notes = None
        self.turn = 0
        self.suppressed = []
        self.peek_pending = False
        self.audit_path = None

    def act(self, observation):
        self.turn += 1
        observation += "\n\nYour own notes from the initial reference preview:\n" + self.preview_notes
        observation += ("\n\nEstimate additional rounds your TEAM needs to finish in "
            "estimated_rounds_remaining (nonnegative integer; 0 means complete). "
            "You may request a free look at the reference by setting peek_reference: true. "
            "A look does not use your painting turn: you will see the reference immediately "
            "and then choose your actions. Otherwise act normally.")
        first = super().act(observation)
        if any(first.get(k) for k in ('_api_error', '_parse_error', '_agent_error')):
            return first
        estimate = first.pop('estimated_rounds_remaining', None)
        peek = first.pop('peek_reference', False)
        valid_estimate = isinstance(estimate, int) and not isinstance(estimate, bool) and estimate >= 0
        requested = peek is True
        result = first
        if requested:
            second = observation + "\n\nYou chose a free look. REFERENCE GRID, columns A-X, rows 1-16:\n" + self.reference + "\nNow choose your painting and messages for this same round."
            result = super().act(second)
            if isinstance(result, dict):
                result.pop('peek_reference', None)
                result.pop('estimated_rounds_remaining', None)
        with _audit_lock:
            with self.audit_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'agent': self.index, 'round': self.turn,
                    'estimate': estimate if valid_estimate else None,
                    'invalid_estimate': estimate is not None and not valid_estimate,
                    'peek_requested': requested, 'peek_field_invalid': not isinstance(peek, bool)}) + "\n")
                f.flush()
        return result


def launch(seed=11):
    cap = 392  # 24 rounds; two generations per turn plus previews, up to two attempts each.
    key = os.environ.get('OPENROUTER_API_KEY')
    with httpx.Client(timeout=20) as client:
        quota = preflight(client, key, cap)
    cfg = load_config(ROOT / 'configs/open_boat_dev.yaml')
    if cfg['model']['provider'] != 'openrouter' or cfg['model']['name'] != MODEL:
        raise ValueError('expected pinned free OpenRouter model')
    cfg.update(seed=seed, rounds=6, abort_on_model_failure=False, interface_feedback={'color_legend': True, 'action_results': True})
    cfg['task'] = {'mode': 'free_creation', 'open_coordination': True,
                   'goal': 'Recreate the shared reference boat scene as accurately as possible.'}
    reference = '\n'.join(load_plate(ROOT / 'targets/sun_boat.txt'))
    root = ROOT / 'runs' / ('reference_visibility_' + uuid4().hex)
    root.mkdir(parents=True)
    sources = source_hashes()
    for path in (Path(__file__).resolve(), ROOT / 'configs/open_boat_dev.yaml'):
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'status': 'running', 'research_evidence': False, 'seed': seed, 'rounds_by_condition': {'free_peek_24':24},
                'reference': 'targets/sun_boat.txt', 'preflight': quota, 'max_http_attempts': cap,
                'source_sha256': sources, 'conditions': []}
    def save():
        tmp = root / 'probe.json.tmp'
        tmp.write_text(json.dumps(manifest, indent=2) + '\n')
        os.replace(tmp, root / 'probe.json')
    save()
    with model_request_budget(interval_seconds=3.5, max_requests=cap, ledger_path=root/'budget.sqlite3') as budget:
        try:
            for label, rounds in (('free_peek_24', 24),):
                mode = 'preview_once'
                cfg['rounds'] = rounds
                target_dir = root / label
                target_dir.mkdir()
                cfg['condition'] = 'reference_' + label
                cfg['run_code'] = 'reference_' + label
                cfg['output_dir'] = str(target_dir)
                model = _model_config(cfg['model'])
                agents = [ProbeAgent(handle, replace(model, usage={'calls':0,'input_tokens':0,'output_tokens':0,'retries':0},
                                      calls_log=[], call_records=[]), mode, i, reference)
                          for i, handle in enumerate(cfg['agents']['handles'])]
                for agent in agents:
                    agent.audit_path = target_dir / 'choices.jsonl'
                if mode == 'preview_once':
                    preview = target_dir / 'preview'
                    preview.mkdir()
                    with trace_run(preview, {'condition': cfg['condition'], 'seed': seed, 'rounds': 0}):
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
                    on_round=lambda p: print(json.dumps({'condition': label, **p}), flush=True))
                scores = result.scores
                if (not scores.get('model_metadata_complete')
                        or scores.get('observed_models') != [MODEL] or scores.get('cost_usd') != 0):
                    raise RuntimeError('model, zero cost, or reliability not verified')
                record = {'condition': label, 'run_dir': str(result.run_dir), 'scores': scores,
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
