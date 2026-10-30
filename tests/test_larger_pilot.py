import json
from types import SimpleNamespace

import httpx
import pytest

from swarm_canvas import larger_pilot
from swarm_canvas.request_budget import before_request


def test_preflight_fails_closed_for_unknown_quota_or_paid_model():
    def handler(request):
        if request.url.path.endswith('/key'):
            return httpx.Response(200, json={'data': {'free_model_daily_requests': {'remaining': 287}}})
        return httpx.Response(200, json={'data': [{'id': larger_pilot.MODEL, 'pricing': {'prompt': '0', 'completion': '0'}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match='quota'):
            larger_pilot.preflight(client, 'fake')


def test_failed_pilot_retains_manifest_and_stops_other_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(larger_pilot, 'verify_readiness', lambda: [])
    monkeypatch.setattr(larger_pilot, 'preflight', lambda client, key: {'remaining_free_requests': 500})
    monkeypatch.setattr(larger_pilot, 'source_hashes', lambda: {'source': 'hash'})
    calls = []
    def fake_run(*, seed, rounds, output_root, assist, shared_budget):
        calls.append(seed)
        shared_budget.acquire()
        return SimpleNamespace(run_dir=tmp_path / 'attempt'), {
            'passed': False, 'task_scores': {'model_metadata_complete': True, 'observed_models': [larger_pilot.MODEL]}}
    monkeypatch.setattr(larger_pilot, 'run', fake_run)
    with pytest.raises(RuntimeError, match='failed adherence'):
        larger_pilot.launch(tmp_path)
    assert calls == [7]
    manifest = json.loads(next(tmp_path.glob('larger_pilot_*/pilot.json')).read_text())
    assert manifest['status'] == 'failed' and manifest['inference_attempts'] == 1
    assert len(manifest['runs']) == 1


def test_budget_blocks_extra_requests():
    from swarm_canvas.request_budget import RequestBudget, RequestBudgetExceeded
    budget = RequestBudget(0, 2)
    budget.acquire(); budget.acquire()
    with pytest.raises(RequestBudgetExceeded):
        budget.acquire()


def test_archived_gate_evidence_and_fingerprint_verify():
    results = larger_pilot.verify_readiness()
    assert [r['seed'] for r in results] == [4, 5, 6]
    assert [r['correct_cells'] for r in results] == [124, 120, 89]
