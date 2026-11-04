"""Prepare or run the matched six-run reconstruction study.

An interrupted running attempt is never automatically replayed. The caller must
inspect it and create a separately identified replacement under the protocol.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
from experiments.study_condition import StudyAgent, finish_round
from experiments.study_schedule import SCHEDULE
from swarm_canvas.agents import LLMAgent
from swarm_canvas.paths import ROOT
from swarm_canvas.reminder_gate import ReminderGate
from swarm_canvas.request_budget import model_request_budget
from swarm_canvas.run_audit import audit
from swarm_canvas.runner import _model_config, load_config, run_config
from swarm_canvas.score import load_plate
from swarm_canvas.study_scorecard import score
from swarm_canvas.tracing import trace_run

MODEL = 'deepseek/deepseek-v4.1-flash-1017'
INTERVAL = 4.2
PER_ATTEMPT_CAP = 200
PREVIEW_CAP = 24
MAX_REMAINING_USD = 50.0


def sources():
    paths = [*sorted((ROOT/'swarm_canvas').glob('*.py')), *sorted((ROOT/'prompts').glob('*.txt')),
             *sorted((ROOT/'experiments').glob('*.py')), ROOT/'configs/open_boat_dev.yaml',
             ROOT/'targets/sun_boat.txt', ROOT/'requirements.txt',
             ROOT/'docs/roadmap/2026-10-31-study-protocol.md']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def versions():
    return {name:importlib.metadata.version(name) for name in ('swarmchat','httpx','pyyaml','langfuse')}


def frozen_commit():
    """Require every experiment input to be committed with no local edits."""
    paths = list(sources())
    head = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()
    tracked = subprocess.run(['git','ls-files','--',*paths],cwd=ROOT,check=True,capture_output=True,text=True)
    if set(tracked.stdout.splitlines()) != set(paths):
        raise RuntimeError('Experiment source and protocol must all be tracked in a frozen commit')
    changed = subprocess.run(['git','diff','--quiet','HEAD','--',*paths],cwd=ROOT)
    if changed.returncode != 0:
        raise RuntimeError('Experiment source or protocol differs from the frozen commit')
    return head


def atomic_json(path: Path, value):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as out:
        json.dump(value, out, indent=2); out.write('\n'); out.flush(); os.fsync(out.fileno())
    os.replace(tmp, path)


def preflight(client, key):
    if not key:
        raise ValueError('OPENROUTER_API_KEY is required')
    response = client.get('https://openrouter.ai/api/v1/key', headers={'Authorization':'Bearer '+key})
    response.raise_for_status()
    data = response.json()['data']
    remaining = data.get('limit_remaining')
    if isinstance(remaining, bool) or not isinstance(remaining, (int,float)) or not 0 < remaining <= MAX_REMAINING_USD:
        raise RuntimeError('The OpenRouter key needs a positive remaining spending limit of at most $50')
    if data.get('limit_reset') is not None:
        raise RuntimeError('The OpenRouter key spending limit must not automatically reset during the batch')
    response = client.get('https://openrouter.ai/api/v1/models')
    response.raise_for_status()
    model = next((m for m in response.json().get('data', []) if m.get('id') == MODEL), None)
    if not model:
        raise RuntimeError('Pinned model unavailable')
    pricing = model.get('pricing') or {}
    try:
        prompt, completion = float(pricing['prompt'])*1_000_000, float(pricing['completion'])*1_000_000
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('Current model pricing unavailable') from None
    if not 0 <= prompt <= .3 or not 0 <= completion <= 1.2:
        raise RuntimeError('Current model price exceeds the protocol ceiling')
    return {'model':MODEL, 'prompt_per_million':prompt, 'completion_per_million':completion,
            'key_limit_remaining_usd':remaining}


def config(root, seed, condition):
    cfg = load_config(ROOT/'configs/open_boat_dev.yaml')
    cfg.update(seed=seed, rounds=24, condition=condition, run_code=condition,
               output_dir=str(root), interface_feedback={'color_legend':True,'action_results':True},
               abort_on_model_failure=True)
    cfg['task'] = {'mode':'free_creation','open_coordination':True,
        'goal':'Recreate the shared reference boat scene as accurately as possible, including filling every cell.'}
    cfg['model'].update(name=MODEL, paid_experiment=True)
    return cfg


def preview(seed, directory):
    directory.mkdir()
    cfg = config(directory, seed, 'paired_preview')
    model = _model_config(cfg['model'])
    reference = '\n'.join(load_plate(ROOT/'targets/sun_boat.txt'))
    notes = []
    with model_request_budget(interval_seconds=INTERVAL,max_requests=PREVIEW_CAP,ledger_path=directory/'budget.sqlite3'):
        with trace_run(directory, {'condition':'paired_preview','seed':seed,'rounds':0,
                                   'model_policy':'openrouter_paid_experiment'}):
            for handle in cfg['agents']['handles']:
                agent = LLMAgent(handle, replace(model,usage={'calls':0,'input_tokens':0,'output_tokens':0,'retries':0},
                                 calls_log=[],call_records=[]),
                    'You are a painter preparing to reproduce a shared 24 by 16 reference. '
                    'You will see it only now. Write useful notes in the JSON scratchpad field. '
                    'Do not paint or send messages in this preparation step.')
                action = agent.act('REFERENCE GRID, columns A-X, rows 1-16:\n'+reference+
                    '\nColor codes: S light blue, W dark blue, Y yellow, B brown, w off-white, P pink, '
                    'G light green, K black. Return a JSON object with a nonempty scratchpad string.')
                value = action.get('scratchpad')
                records = agent.model_cfg.call_records
                if not isinstance(value,str) or not value.strip() or not records or any(
                    r.get('served_model') != MODEL or r.get('cost_usd') is None for r in records):
                    raise RuntimeError('Preview failed or model/cost metadata missing')
                notes.append(value[:2000])
    atomic_json(directory/'notes.json', {'seed':seed,'notes':notes})
    return notes


def attempt(seed, arm, directory, notes, preview_dir):
    directory.mkdir()
    cfg = config(directory, seed, 'paired_'+arm)
    model = _model_config(cfg['model'])
    reference = '\n'.join(load_plate(ROOT/'targets/sun_boat.txt'))
    gate = ReminderGate(rounds=24) if arm == 'reminder' else None
    audit_path = directory/'intervention.jsonl'
    agents = [StudyAgent(h, replace(model,usage={'calls':0,'input_tokens':0,'output_tokens':0,'retries':0},
                          calls_log=[],call_records=[]), 'preview_once', i, reference,
                          gate=gate,audit_path=audit_path) for i,h in enumerate(cfg['agents']['handles'])]
    for agent, note in zip(agents, notes, strict=True):
        agent.preview_notes = note
    def on_round(info):
        if gate is not None:
            finish_round(gate, directory/info['run'], info['round'], audit_path)
        print(json.dumps({'arm':arm,'seed':seed,**info}),flush=True)
    with model_request_budget(interval_seconds=INTERVAL,max_requests=PER_ATTEMPT_CAP,ledger_path=directory/'budget.sqlite3'):
        result = run_config(cfg, render=False, agents=agents, on_round=on_round)
    report = audit(result.run_dir,directory/'budget.sqlite3',preview_dir,preview_dir/'budget.sqlite3')
    metrics = score(result.run_dir,ROOT/'targets/sun_boat.txt')
    atomic_json(directory/'audit.json',report)
    atomic_json(directory/'study_scorecard.json',metrics)
    if not report['passed']:
        raise RuntimeError('Attempt integrity audit failed')
    return {'run_dir':str(result.run_dir), 'audit':report, 'scorecard':metrics, 'harness_scores':result.scores}


def _execute_locked(batch: Path):
    batch = batch.resolve()
    manifest_path = batch/'manifest.json'
    commit = frozen_commit()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('status') == 'stopped':
            raise RuntimeError('Stopped batch requires manual inspection')
        if manifest.get('git_commit') != commit or manifest['source_hashes'] != sources() or manifest['python'] != sys.version or manifest.get('dependencies') != versions():
            raise RuntimeError('Source, Python or dependency versions changed; cannot continue this batch')
        if manifest.get('schedule') != [list(x) for x in SCHEDULE]:
            raise RuntimeError('Saved schedule differs from the frozen protocol')
        if any(a['status'] != 'completed' for a in manifest['attempts']):
            raise RuntimeError('A failed or interrupted attempt requires manual inspection')
        if any(p['status'] != 'completed' for p in manifest['previews'].values()):
            raise RuntimeError('A failed or interrupted preview requires manual inspection')
    else:
        batch.mkdir(parents=True,exist_ok=False)
        manifest = {'status':'prepared','git_commit':commit,'source_hashes':sources(),'python':sys.version,'dependencies':versions(),
                    'schedule':[list(x) for x in SCHEDULE], 'previews':{}, 'attempts':[]}
        atomic_json(manifest_path,manifest)
    with httpx.Client(timeout=30) as client:
        manifest['preflight'] = preflight(client,os.environ.get('OPENROUTER_API_KEY'))
    manifest['status']='running'; atomic_json(manifest_path,manifest)
    for arm,seed in SCHEDULE:
        if sources()!=manifest['source_hashes'] or versions()!=manifest['dependencies']:
            manifest.update(status='stopped',error_type='SourceOrDependencyChanged')
            atomic_json(manifest_path,manifest)
            raise RuntimeError('Source or dependencies changed during batch')
        key=str(seed)
        if key not in manifest['previews']:
            p=batch/f'preview_{seed}'
            manifest['previews'][key]={'status':'running','path':str(p)};atomic_json(manifest_path,manifest)
            try:
                preview(seed,p)
                manifest['previews'][key].update(status='completed',
                    notes_sha256=hashlib.sha256((p/'notes.json').read_bytes()).hexdigest())
            except BaseException as exc:
                manifest['previews'][key].update(status='failed',error_type=type(exc).__name__)
                manifest['status']='stopped';atomic_json(manifest_path,manifest);raise
            atomic_json(manifest_path,manifest)
        item=manifest['previews'][key]
        if item['status'] != 'completed': raise RuntimeError('Preview incomplete; inspect before continuation')
        if hashlib.sha256((Path(item['path'])/'notes.json').read_bytes()).hexdigest() != item.get('notes_sha256'):
            manifest.update(status='stopped',error_type='PreviewNotesChanged')
            atomic_json(manifest_path,manifest)
            raise RuntimeError('Shared preview notes changed after generation')
        if any(a['arm']==arm and a['seed']==seed for a in manifest['attempts']): continue
        with httpx.Client(timeout=30) as client:
            preflight(client,os.environ.get('OPENROUTER_API_KEY'))
        notes=json.loads((Path(item['path'])/'notes.json').read_text())['notes']
        directory=batch/f'{arm}_{seed}_{uuid4().hex}'
        record={'arm':arm,'seed':seed,'status':'running','path':str(directory)}
        manifest['attempts'].append(record);atomic_json(manifest_path,manifest)
        try:
            result=attempt(seed,arm,directory,notes,Path(item['path']))
            record.update(status='completed',result=result)
        except BaseException as exc:
            record.update(status='failed',error_type=type(exc).__name__)
            manifest['status']='stopped';atomic_json(manifest_path,manifest);raise
        atomic_json(manifest_path,manifest)
    manifest['status']='completed';atomic_json(manifest_path,manifest)
    return manifest_path


def execute(batch: Path):
    batch = batch.resolve()
    if not batch.parent.is_dir():
        raise ValueError('Batch parent directory must already exist')
    lock_path = batch.parent / ('.' + batch.name + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another process is operating on this batch') from None
        return _execute_locked(batch)
    finally:
        os.close(fd)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch',type=Path)
    parser.add_argument('--launch',action='store_true')
    args=parser.parse_args()
    if not args.launch: raise SystemExit('Add --launch after preparing the protocol and budget')
    print(execute(args.batch))
