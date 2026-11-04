"""Exploratory reference-preview run using native SwarmChat and capped DeepSeek calls."""
import hashlib
import json
import os
from pathlib import Path
from dataclasses import replace
from uuid import uuid4

from experiments.retained_notes_probe import ProbeAgent
from swarm_canvas.agents import LLMAgent
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.runner import _model_config, load_config, run_config
from swarm_canvas.score import load_plate
from swarm_canvas.tracing import trace_run

MODEL = 'deepseek/deepseek-v4.1-flash-1017'

def _execute(root):
    if not os.environ.get('OPENROUTER_API_KEY'):
        raise RuntimeError('OPENROUTER_API_KEY required')
    root.mkdir(parents=True)
    cfg = load_config(ROOT / 'configs/open_boat_dev.yaml')
    cfg.update(seed=11, rounds=24, condition='deepseek_reference_exploratory',
               run_code='deepseek_reference', output_dir=str(root),
               interface_feedback={'color_legend': True, 'action_results': True}, abort_on_model_failure=True)
    cfg['task'] = {'mode': 'free_creation', 'open_coordination': True,
                   'goal': 'Recreate the shared reference boat scene as accurately as possible.'}
    cfg['model'].update(name=MODEL, paid_experiment=True)
    reference = '\n'.join(load_plate(ROOT / 'targets/sun_boat.txt'))
    model = _model_config(cfg['model'])
    agents = [ProbeAgent(h, replace(model, usage={'calls':0,'input_tokens':0,'output_tokens':0,'retries':0},
                        calls_log=[], call_records=[]), 'preview_once', i, reference)
              for i,h in enumerate(cfg['agents']['handles'])]
    src = [*sorted((ROOT/'swarm_canvas').glob('*.py')), *sorted((ROOT/'prompts').glob('*.txt')),
           ROOT/'configs/open_boat_dev.yaml', ROOT/'targets/sun_boat.txt', ROOT/'experiments/deepseek_full_run.py',
           ROOT/'experiments/retained_notes_probe.py']
    (root/'sources.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in src},indent=2))
    with model_request_budget(interval_seconds=4.2, max_requests=200, ledger_path=root/'budget.sqlite3') as budget:
        preview = root/'preview'; preview.mkdir()
        preview_cost = 0.0
        with trace_run(preview, {'condition':cfg['condition'], 'seed':11, 'rounds':0,
                                 'model_policy':'openrouter_paid_experiment'}):
            for agent in agents:
                agent.system_prompt = ('You are a painter preparing to reproduce a shared 24 by 16 reference. '
                    'You will see it only now. Write useful notes in the JSON scratchpad field. '
                    'Do not paint or send messages in this preparation step.')
                action = LLMAgent.act(agent, 'REFERENCE GRID, columns A-X, rows 1-16:\n'+reference+
                    '\nColor codes: S light blue, W dark blue, Y yellow, B brown, w off-white, P pink, '
                    'G light green, K black. Return a JSON object with a nonempty scratchpad string.')
                if not isinstance(action.get('scratchpad'),str) or not action['scratchpad'].strip():
                    raise RuntimeError('preview did not return nonempty notes')
                if not agent.model_cfg.call_records or any(r.get('served_model') != MODEL or r.get('cost_usd') is None for r in agent.model_cfg.call_records):
                    raise RuntimeError('preview model or cost not verified')
                preview_cost += sum(r['cost_usd'] for r in agent.model_cfg.call_records)
                agent.preview_notes = action['scratchpad'][:2000]
                agent.model_cfg.call_records = []; agent.model_cfg.calls_log = []
        (root/'preview_cost.json').write_text(json.dumps({'cost_usd':preview_cost}))
        result = run_config(cfg, render=False, agents=agents,
                            on_round=lambda info: print(json.dumps(info),flush=True))
        traces = [json.loads(x) for x in (result.run_dir/'traces.jsonl').read_text().splitlines()]
        n = sum(x.get('event') == 'end' and x.get('name') == 'generate-painter-action' for x in traces)
        model_calls = sum(len(a.model_cfg.call_records) for a in agents)
        summary = {'run_dir':str(result.run_dir), 'http_attempts':budget.requests,
                   'preview_cost_usd':preview_cost, 'scores':result.scores,
                   'generation_trace_count':n, 'run_call_records':model_calls,
                   'trace_complete':n==model_calls}
        (root/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
        print('RESULT',json.dumps(summary),flush=True)
        if n != model_calls:
            raise RuntimeError('Incomplete model generation trace')

def main():
    root = Path(os.environ.get('SWARM_RUN_PARENT', str(ROOT/'runs'))) / ('deepseek_full_' + uuid4().hex)
    durable_parent = os.environ.get('SWARM_DURABLE_PARENT')
    try:
        _execute(root)
    finally:
        # Runs only after native clients and the SQLite ledger have been closed.
        # SIGKILL or machine failure cannot execute a finally block.
        if durable_parent and root.exists():
            from experiments.durable_staging import promote
            print('PROMOTED', promote(root, Path(durable_parent)), flush=True)


if __name__ == '__main__':
    main()
