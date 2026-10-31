import json

import pytest
from test_rules_and_run import _cfg, Scripted

from swarm_canvas.attempt_audit import inspect_attempt
from swarm_canvas.runner import run_config


def test_open_condition_has_all_switches_off_and_no_reference(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), rounds=1,
               task={'mode': 'free_creation', 'goal': 'Paint a boat', 'open_coordination': True})
    r = run_config(cfg, render=False)
    manifest = json.loads((r.run_dir / 'config.json').read_text())
    assert not any(manifest['assistance'].values())
    assert not (r.run_dir / 'assistance_reference.json').exists()
    prompt = (r.run_dir / 'prompts_rendered/round_01_slot-0.txt').read_text()
    assert 'Suggested target-derived paints' not in prompt and 'TARGET (visible' not in prompt


def test_independent_suggestions_and_requirements_are_visible_and_logged(tmp_path):
    cfg = _cfg(kind='swarmchat', output_dir=str(tmp_path), rounds=1,
               task={'mode': 'free_creation', 'goal': 'Paint a boat', 'open_coordination': True},
               assistance={'suggested_paints': True, 'assigned_territories': True,
                           'require_messages': True, 'require_peer_acks': False})
    r = run_config(cfg, render=False, agents=[Scripted([{}]) for _ in range(4)])
    manifest = json.loads((r.run_dir / 'config.json').read_text())
    prompt = (r.run_dir / 'prompts_rendered/round_01_slot-0.txt').read_text()
    assert manifest['assistance']['suggested_paints'] and not manifest['assistance']['reference_image']
    assert 'Suggested target-derived paints' in prompt and 'assigned territory' in prompt
    assert 'TARGET (visible' not in prompt and 'Include at least one nonempty message' in prompt
    events = [json.loads(line) for line in (r.run_dir / 'events.jsonl').read_text().splitlines()]
    assert sum(e['type'] == 'assistance_violation' and e['reason'] == 'required_message_missing' for e in events) == 4
    assert r.scores['target_accuracy'] is None


def test_checkpoint_survives_interruption_and_detects_tampering(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), rounds=2)
    def abort(_):
        raise RuntimeError('deliberate interruption')
    with pytest.raises(RuntimeError):
        run_config(cfg, render=False, on_round=abort)
    p = next(tmp_path.iterdir())
    info = inspect_attempt(p)
    assert info['status'] == 'failed' and info['last_completed_round'] == 1 and info['checkpoint_valid']
    (p / 'canvas/round_01.json').write_text('{}')
    assert not inspect_attempt(p)['checkpoint_valid']


def test_invalid_assistance_fails_before_run(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), assistance={'require_peer_acks': True})
    with pytest.raises(ValueError, match='SwarmChat'):
        run_config(cfg, render=False)
    assert not list(tmp_path.iterdir())


def test_reference_switch_exposes_reference_without_forcing_other_scaffolds(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), rounds=1,
               task={'mode': 'free_creation', 'goal': 'Paint a boat', 'open_coordination': True},
               assistance={'reference_image': True})
    r = run_config(cfg, render=False)
    manifest = json.loads((r.run_dir / 'config.json').read_text())
    prompt = (r.run_dir / 'prompts_rendered/round_01_slot-0.txt').read_text()
    assert 'TARGET (visible' in prompt and 'Suggested target-derived paints' not in prompt
    assert manifest['assistance']['reference_image'] and not manifest['assistance']['assigned_territories']
    assert len(manifest['assistance']['reference_sha256']) == 64
    assert r.scores['target_accuracy'] is None


def test_batch_stops_and_saves_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from swarm_canvas import open_boat_check
    monkeypatch.setattr(open_boat_check, 'preflight', lambda *a: {'remaining_free_requests': 1000})
    calls = []
    def fake_run(cfg, **kwargs):
        calls.append(cfg['seed'])
        return SimpleNamespace(run_dir=tmp_path / 'attempt', scores={'model_metadata_complete': False})
    monkeypatch.setattr(open_boat_check, 'run_config', fake_run)
    with pytest.raises(RuntimeError, match='not verified'):
        open_boat_check.run_batch((101, 102), 1, tmp_path)
    assert calls == [101]
    manifest = json.loads(next(tmp_path.glob('open_boat_batch_*/batch.json')).read_text())
    assert manifest['status'] == 'failed' and len(manifest['runs']) == 1
    assert manifest['http_attempts'] == 0 and manifest['max_http_attempts'] == 16


def test_peer_ack_requirement_reports_invalid_ack_without_changing_action(tmp_path):
    cfg = _cfg(kind='swarmchat', output_dir=str(tmp_path), rounds=2,
               assistance={'require_peer_acks': True})
    agents = [Scripted([{'messages': ['hello']}, {'acks': [9999]}]) for _ in range(4)]
    result = run_config(cfg, render=False, agents=agents)
    events = [json.loads(line) for line in (result.run_dir / 'events.jsonl').read_text().splitlines()]
    violations = [e for e in events if e['type'] == 'assistance_violation' and e['reason'] == 'required_peer_ack_missing']
    assert len(violations) == 4 and all(e['round'] == 2 for e in violations)
    assert not any(e['type'] == 'ack' and e.get('applied') for e in events)


def test_audit_conservatively_counts_truncated_tail_and_rejects_midfile_corruption(tmp_path):
    (tmp_path / 'config.json').write_text(json.dumps({'status': 'running'}))
    start = json.dumps({'name': 'generate-painter-action', 'event': 'start', 'id': '1'})
    (tmp_path / 'traces.jsonl').write_text(start + '\n' + '{"name":')
    audit = inspect_attempt(tmp_path)
    assert audit['generation_starts_upper_bound'] == 2
    assert audit['truncated_trace_tail'] and audit['incomplete_generation_spans'] == 1
    (tmp_path / 'traces.jsonl').write_text('not-json\n' + start + '\n')
    with pytest.raises(ValueError, match='corruption'):
        inspect_attempt(tmp_path)


def test_batch_recovery_counts_each_attempt_and_never_assumes_resume(tmp_path):
    from swarm_canvas.attempt_audit import plan_batch_recovery
    (tmp_path / 'batch.json').write_text(json.dumps({'status': 'running', 'seeds': [1, 2],
        'max_http_attempts': 10, 'runs': []}))
    for seed in (1, 2):
        d = tmp_path / f'open_boat_s{seed}_test'; d.mkdir()
        (d / 'config.json').write_text(json.dumps({'status': 'running', 'seed': seed}))
        (d / 'traces.jsonl').write_text(json.dumps({'name': 'generate-painter-action', 'event': 'start', 'id': f'id{seed}'}) + '\n')
    result = plan_batch_recovery(tmp_path)
    assert result['completed_seeds'] == [] and result['restart_seeds_from_round_one'] == [1, 2]
    assert result['attempts_upper_bound'] == 2 and result['remaining_attempts_lower_bound'] == 8
    assert result['original_process_stopped'] == 'unverified'
    (tmp_path / 'open_boat_s2_test/traces.jsonl').unlink()
    with pytest.raises(ValueError, match='without every trace'):
        plan_batch_recovery(tmp_path)
