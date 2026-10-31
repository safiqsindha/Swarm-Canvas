"""Actual HTTP attempts share a cap; failures cannot become fake inactivity."""

import json
from pathlib import Path

import httpx
import pytest
from test_rules_and_run import Scripted, _cfg

from swarm_canvas.models import ModelCallError, ModelConfig, call_model
from swarm_canvas.request_budget import RequestBudget, RequestBudgetExceeded, model_request_budget
from swarm_canvas.runner import run_config


def test_http_cap_also_counts_schema_fallbacks():
    seen = []

    def reject_schema(request):
        seen.append(request)
        return httpx.Response(400, json={"error": "unsupported schema"})

    cfg = ModelConfig(
        provider="openrouter",
        name="test/model:free",
        transport=httpx.MockTransport(reject_schema),
    )
    with model_request_budget(interval_seconds=0, max_requests=1) as budget:
        with pytest.raises(ModelCallError):
            call_model([{"role": "user", "content": "test"}], cfg)
        assert budget.requests == 1
    assert len(seen) == 1


def test_budget_is_shared_between_painters_and_restored_after_failure():
    def respond(request):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}], "usage": {"cost": 0}},
        )

    configs = [
        ModelConfig(
            provider="openrouter",
            name="test/model:free",
            transport=httpx.MockTransport(respond),
        )
        for _ in range(2)
    ]
    with model_request_budget(interval_seconds=0, max_requests=2) as budget:
        for cfg in configs:
            assert call_model([{"role": "user", "content": "test"}], cfg) == "{}"
        with pytest.raises(ModelCallError):
            call_model([{"role": "user", "content": "test"}], configs[0])
        assert budget.requests == 2
    assert call_model([{"role": "user", "content": "test"}], configs[0]) == "{}"


def test_request_pacing_uses_one_shared_clock(monkeypatch):
    import swarm_canvas.request_budget as module

    clock = [0.0]
    waits = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(module.time, "sleep", sleep)
    budget = RequestBudget(3.5, 2)
    budget.acquire()
    budget.acquire()
    assert waits == [3.5]
    assert budget.requests == 2


def test_fail_fast_run_is_marked_failed_and_stops_after_one_round(tmp_path):
    cfg = _cfg(output_dir=str(tmp_path), rounds=3)
    cfg["abort_on_model_failure"] = True
    agents = [Scripted([{"_api_error": True, "_error_type": "test"}, {}])] + [
        Scripted([{}, {}]) for _ in range(3)
    ]
    progress = []
    with pytest.raises(RuntimeError, match="development attempt aborted"):
        run_config(cfg, agents=agents, render=False, on_round=progress.append)
    assert all(len(agent.seen) == 1 for agent in agents)
    assert progress == []
    manifest = next(tmp_path.glob("*/config.json"))
    assert json.loads(manifest.read_text())["status"] == "failed"


def test_paired_check_preflights_free_quota_before_model_calls(tmp_path, monkeypatch):
    import swarm_canvas.paired_check as module

    original = httpx.Client

    def respond(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(
                200, json={"data": {"free_model_daily_requests": {"remaining": 5}}}
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "nvidia/nemotron-3.5-super-vl:free",
                        "pricing": {"prompt": "0", "completion": "0"},
                    }
                ]
            },
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(
        module,
        "run_config",
        lambda *args, **kwargs: pytest.fail(
            "must not call models with insufficient quota"
        ),
    )
    with pytest.raises(RuntimeError, match="Insufficient free request quota"):
        module.run_paired_check(output_root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_pair_plan_is_saved_before_calls_and_excludes_inline_credentials(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import swarm_canvas.paired_check as module

    original_client = httpx.Client
    original_load = module.load_config

    def respond(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(
                200, json={"data": {"free_model_daily_requests": {"remaining": 1000}}}
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "nvidia/nemotron-3.5-super-vl:free",
                        "pricing": {"prompt": "0", "completion": "0"},
                    }
                ]
            },
        )

    def load_with_inline_key(path):
        cfg = original_load(path)
        cfg["model"]["api_key"] = "inline-test-value"
        return cfg

    calls = []

    def fake_run(cfg, **kwargs):
        manifest = Path(cfg["output_dir"]) / "pair.json"
        saved = json.loads(manifest.read_text())
        assert saved["status"] == "running" and saved["research_evidence"] is False
        assert saved["source_sha256"]
        assert "inline-test-value" not in manifest.read_text()
        calls.append(cfg)
        return SimpleNamespace(
            run_dir=manifest.parent / cfg["run_code"],
            scores={
                "reliability_ok": True,
                "model_metadata_complete": True,
                "observed_models": ["nvidia/nemotron-3.5-super-vl:free"],
                "cost_usd": 0,
            },
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    monkeypatch.setattr(module, "load_config", load_with_inline_key)
    monkeypatch.setattr(module, "run_config", fake_run)
    result = module.run_paired_check(
        output_root=tmp_path, rounds=1, max_requests=8, interval_seconds=0
    )
    assert result["status"] == "completed"
    assert {c["condition"] for c in calls} == {"c1_nochat", "c2b_swarmchat"}
    assert all(c["model"]["reasoning_enabled"] is False for c in calls)


def test_durable_budget_survives_process_death_before_response(tmp_path):
    import sqlite3
    import subprocess
    import sys
    from swarm_canvas.request_budget import BudgetLedgerError

    ledger = tmp_path / 'budget.sqlite3'
    code = '''
import os, sys, httpx
from swarm_canvas.models import ModelConfig, call_model
from swarm_canvas.request_budget import model_request_budget
cfg = ModelConfig(provider='openrouter', name='test/model:free',
                  transport=httpx.MockTransport(lambda request: os._exit(77)))
with model_request_budget(interval_seconds=0, max_requests=2, ledger_path=sys.argv[1]):
    call_model([{'role': 'user', 'content': 'test'}], cfg)
'''
    process = subprocess.run([sys.executable, '-c', code, str(ledger)], cwd=Path(__file__).parents[1])
    assert process.returncode == 77
    with sqlite3.connect(ledger) as db:
        assert db.execute('SELECT status, http_status FROM attempts').fetchall() == [('reserved', None)]
    with model_request_budget(interval_seconds=0, max_requests=2, ledger_path=ledger, resume=True) as budget:
        assert budget.requests == 1
        cfg = ModelConfig(provider='openrouter', name='test/model:free',
                          transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'choices':[{'message':{'content':'{}'}}]})))
        assert call_model([{'role':'user','content':'test'}], cfg) == '{}'
        with pytest.raises(ModelCallError):
            call_model([{'role':'user','content':'test'}], cfg)
        assert budget.requests == 2
        with pytest.raises(BudgetLedgerError, match='already in use'):
            from swarm_canvas.request_budget import DurableLedger
            DurableLedger(ledger, interval_seconds=0, max_requests=2, resume=True)
    with sqlite3.connect(ledger) as db:
        assert db.execute('SELECT status FROM attempts ORDER BY id').fetchall() == [('reserved',), ('response_received',)]
    assert ledger.stat().st_mode & 0o077 == 0
    with pytest.raises(BudgetLedgerError, match='do not match'):
        with model_request_budget(interval_seconds=0, max_requests=3, ledger_path=ledger, resume=True):
            pass


def test_durable_budget_refuses_missing_or_existing_ledger(tmp_path):
    from swarm_canvas.request_budget import BudgetLedgerError
    ledger = tmp_path / 'budget.sqlite3'
    with pytest.raises(BudgetLedgerError, match='missing'):
        with model_request_budget(interval_seconds=0, max_requests=2, ledger_path=ledger, resume=True):
            pass
    with model_request_budget(interval_seconds=0, max_requests=2, ledger_path=ledger):
        pass
    with pytest.raises(BudgetLedgerError, match='already exists'):
        with model_request_budget(interval_seconds=0, max_requests=2, ledger_path=ledger):
            pass


def test_durable_budget_concurrent_reservations_are_unique(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import sqlite3
    path = tmp_path / 'budget.sqlite3'
    with model_request_budget(interval_seconds=0, max_requests=40, ledger_path=path) as budget:
        with ThreadPoolExecutor(max_workers=12) as pool:
            ids = list(pool.map(lambda _: budget.acquire(), range(40)))
        assert len(set(ids)) == 40 and budget.requests == 40
        with pytest.raises(RequestBudgetExceeded, match='budget exhausted'):
            budget.acquire()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 40


def test_durable_reservation_links_to_generation_without_credentials(tmp_path):
    from swarm_canvas.tracing import trace_run
    ledger = tmp_path / 'budget.sqlite3'
    secret = 'sk-or-v1-test-credential-placeholder'
    cfg = ModelConfig(provider='openrouter', name='test/model:free', api_key=secret,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'choices':[{'message':{'content':'{}'}}]})))
    with trace_run(tmp_path, {'condition':'test', 'seed':1, 'rounds':1}):
        with model_request_budget(interval_seconds=0, max_requests=1, ledger_path=ledger):
            call_model([{'role':'user','content':'hi'}], cfg)
    records = [json.loads(line) for line in (tmp_path / 'traces.jsonl').read_text().splitlines()]
    reserved = next(x for x in records if x['event'] == 'budget_reserved')
    response = next(x for x in records if x['event'] == 'budget_response')
    assert reserved['attempt_id'] == response['attempt_id'] == 1
    assert reserved['observation_id'] == response['observation_id']
    assert secret not in (tmp_path / 'traces.jsonl').read_text()
    assert secret.encode() not in ledger.read_bytes()


def test_inspect_ledger_counts_unknown_without_releasing_it(tmp_path):
    from swarm_canvas.request_budget import inspect_ledger
    ledger = tmp_path / 'budget.sqlite3'
    with model_request_budget(interval_seconds=0, max_requests=3, ledger_path=ledger) as budget:
        budget.acquire()
        assert inspect_ledger(ledger) == {'max_requests': 3, 'interval_seconds': 0,
            'attempts_reserved': 1, 'responses_received': 0,
            'without_recorded_response': 1, 'remaining_attempts': 2}
    assert inspect_ledger(ledger)['remaining_attempts'] == 2
