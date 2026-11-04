import json
import sys
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from experiments import paired_study


def test_preflight_requires_bounded_key_and_pricing():
    def respond(request):
        if request.url.path.endswith('/key'):
            return httpx.Response(200,json={'data':{'limit_remaining':9}})
        return httpx.Response(200,json={'data':[{'id':paired_study.MODEL,'pricing':{'prompt':'0.0000001','completion':'0.0000005'}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError,match='at most'):
            paired_study.preflight(client,'key')


def test_failed_attempt_blocks_restart_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(paired_study,'sources',lambda:{'source':'hash'})
    monkeypatch.setattr(paired_study,'frozen_commit',lambda:'commit')
    batch=tmp_path/'batch'; batch.mkdir()
    manifest={'git_commit':'commit','source_hashes':{'source':'hash'},'python':sys.version,'dependencies':paired_study.versions(),
              'schedule':[list(x) for x in paired_study.SCHEDULE], 'previews':{},
              'attempts':[{'arm':'baseline','seed':11,'status':'failed'}]}
    (batch/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError,match='manual inspection'):
        paired_study.execute(batch)


def test_six_run_schedule_reuses_preview_notes_and_restart_is_idempotent(tmp_path,monkeypatch):
    monkeypatch.setattr(paired_study,'sources',lambda:{'source':'hash'})
    monkeypatch.setattr(paired_study,'frozen_commit',lambda:'commit')
    monkeypatch.setattr(paired_study,'preflight',lambda *args:{'remaining':1})
    previews=[]; attempts=[]
    def fake_preview(seed,directory):
        previews.append(seed);directory.mkdir()
        (directory/'notes.json').write_text(json.dumps({'seed':seed,'notes':[str(seed)]*4}))
    def fake_attempt(seed,arm,directory,notes,preview_dir):
        attempts.append((arm,seed,notes));directory.mkdir()
        return {'ok':True}
    monkeypatch.setattr(paired_study,'preview',fake_preview)
    monkeypatch.setattr(paired_study,'attempt',fake_attempt)
    batch=tmp_path/'batch'
    paired_study.execute(batch)
    assert previews == [11,12,13]
    assert [(arm,seed) for arm,seed,_ in attempts] == paired_study.SCHEDULE
    assert all(notes == [str(seed)]*4 for _,seed,notes in attempts)
    paired_study.execute(batch)
    assert len(attempts)==6 and len(previews)==3


def test_matched_preview_and_full_reminder_run(tmp_path,monkeypatch):
    from swarm_canvas.runner import _model_config
    monkeypatch.setenv('SWARM_CANVAS_TRACING','local')
    monkeypatch.setattr(paired_study,'INTERVAL',0)
    def respond(request):
        body=json.loads(request.content)
        user=body['messages'][-1]['content']
        if 'REFERENCE GRID, columns A-X' in user and 'Return a JSON object with a nonempty scratchpad' in user:
            content={'scratchpad':'remember the boat'}
        else:
            content={'messages':['Canvas complete.'], 'paints':[]}
        return httpx.Response(200,json={'id':'gen-'+uuid4().hex,'model':paired_study.MODEL,'provider':'mock',
            'choices':[{'message':{'content':json.dumps(content)},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'cost':0.000001}})
    monkeypatch.setattr(paired_study,'_model_config',lambda cfg:replace(_model_config(cfg),transport=httpx.MockTransport(respond)))
    preview=tmp_path/'preview'
    notes=paired_study.preview(11,preview)
    assert notes == ['remember the boat']*4
    baseline=tmp_path/'baseline'
    baseline_result=paired_study.attempt(11,'baseline',baseline,notes,preview)
    assert baseline_result['audit']['passed']
    assert not (baseline/'intervention.jsonl').exists()
    attempt=tmp_path/'attempt'
    result=paired_study.attempt(11,'reminder',attempt,notes,preview)
    assert result['audit']['passed']
    assert result['scorecard']['claims'][0]['round']==1
    records=[json.loads(x) for x in (attempt/'intervention.jsonl').read_text().splitlines()]
    assert [x['type'] for x in records].count('reminder_trigger')==1
    assert [x['type'] for x in records].count('reminder_delivery')==4
    assert all(x['round']==2 for x in records if x['type']=='reminder_delivery')
