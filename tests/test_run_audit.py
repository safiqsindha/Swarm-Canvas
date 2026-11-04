import json
from pathlib import Path

from swarm_canvas.run_audit import audit


def test_audit_detects_missing_or_mismatched_generation(tmp_path):
    import hashlib
    (tmp_path/'canvas').mkdir()
    frame = {'rows':1, 'cols':1, 'cells':[]}
    digest = hashlib.sha256(json.dumps(frame, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (tmp_path/'canvas/round_01.json').write_text(json.dumps(frame))
    (tmp_path/'config.json').write_text(json.dumps({'status':'completed', 'rounds':1,
        'final_hash':digest, 'swarmchat_errors':0}))
    (tmp_path/'events.jsonl').write_text(json.dumps({'type':'model_call','status':'ok','response_id':'abc'})+'\n')
    trace = [{'event':'end','name':'generate-painter-action', 'metadata':{'http_status':200,'response_id':'abc'}},
             {'event':'export_summary','delivery_verified':False}]
    path = tmp_path/'traces.jsonl'
    path.write_text(''.join(json.dumps(x)+'\n' for x in trace))
    assert audit(tmp_path)['local_checks_passed'] is True
    assert audit(tmp_path)['passed'] is False  # no ledger and preview to reconcile
    trace[0]['metadata']['response_id'] = 'different'
    path.write_text(''.join(json.dumps(x)+'\n' for x in trace))
    assert audit(tmp_path)['local_checks_passed'] is False
    trace[0]['metadata']['response_id'] = 'abc'
    path.write_text(json.dumps(trace[0])+'\n')
    assert audit(tmp_path)['local_checks_passed'] is False


def test_recovered_native_error_does_not_pass_reliability(tmp_path):
    from swarm_canvas.score import score_run
    frame = {'rows':1, 'cols':1, 'cells':[]}
    (tmp_path/'canvas').mkdir()
    (tmp_path/'canvas/round_01.json').write_text(json.dumps(frame))
    (tmp_path/'events.jsonl').write_text('')
    (tmp_path/'config.json').write_text(json.dumps({'status':'completed', 'rounds':1,
        'swarmchat_errors':1, 'agent_type':'random', 'task':{'mode':'free_creation'}}))
    assert score_run(tmp_path)['reliability_ok'] is False
