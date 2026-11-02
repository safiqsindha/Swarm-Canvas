import pytest
from helpers_redesign import Scripted, events_of, recon_cfg

from swarm_canvas.models import _PAINTER_SCHEMA, ModelConfig
from swarm_canvas.runner import run_config
from swarm_canvas.supplier import Supplier, catalog_enabled
from swarm_canvas.validate import validate_action


def test_catalog_enabled_rules():
    assert catalog_enabled({"catalog": ["O"], "swarm_budget": 4})
    assert catalog_enabled(None)
    assert not catalog_enabled({"swarm_budget": 0})
    assert not catalog_enabled({"enabled": False, "swarm_budget": 4})
    for bad in ({"enabled": "no"}, {"swarm_budget": -1}, {"swarm_budget": "4"}, {"swarm_budget": True}):
        with pytest.raises(ValueError):
            catalog_enabled(bad)


def test_disabled_supplier_denies_everything():
    for supplier in (Supplier(["O"], swarm_budget=0), Supplier(["O"], swarm_budget=4, enabled=False)):
        denied = supplier.request("slot-0", "O", 1)
        assert denied["type"] == "deny" and denied["reason"] == "catalog_disabled"
        assert supplier.granted_total == 0 and supplier.deliveries(2) == {}


def test_validate_rejects_requests_when_disabled():
    kwargs = dict(handle="a1", round_num=1, palette=["S"], paint_budget=8, comms_enabled=False,
                  max_messages=2, max_chars=200)
    on = validate_action(action={"requests": ["O"]}, **kwargs)
    assert on.requests == ["O"]
    off = validate_action(action={"requests": ["O"]}, catalog_enabled=False, **kwargs)
    assert off.requests == [] and off.rejections[0]["reason"] == "catalog_disabled"


@pytest.mark.parametrize("supplier", [{"catalog": ["O", "R"], "swarm_budget": 0},
                                      {"catalog": ["O", "R"], "swarm_budget": 4, "enabled": False}])
@pytest.mark.parametrize("kind", ["none", "doc_log"])
def test_prompts_have_no_catalog_text_and_requests_are_ignored(tmp_path, supplier, kind):
    agents = [Scripted([{"requests": ["O"], "paints": [{"column": "A", "row": 1, "color": "S"}]}]),
              Scripted([]), Scripted([]), Scripted([])]
    result = run_config(recon_cfg(tmp_path, rounds=2, kind=kind, supplier=supplier), render=False, agents=agents)
    events = events_of(result.run_dir)
    assert not [e for e in events if e["type"] in {"grant", "request"}]
    assert any(e["type"] == "invalid" and e.get("reason") == "catalog_disabled" for e in events)
    # the legal paint in the same action still applies
    assert any(e["type"] == "paint" and e["cell"] == "A1" for e in events)
    for path in result.run_dir.glob("prompts_rendered/*.txt"):
        assert "catalog" not in path.read_text().lower(), path.name
    assert "O" not in agents[0].seen[0].split("PALETTE:")[1].splitlines()[0].split()


def test_default_prompts_still_mention_catalog(tmp_path):
    agents = [Scripted([]) for _ in range(4)]
    run_config(recon_cfg(tmp_path, rounds=1), render=False, agents=agents)
    assert "CATALOG_LEFT" in agents[0].seen[0]


def test_llm_schema_drops_requests_when_disabled(monkeypatch):
    captured = {}

    def fake_post(url, payload, cfg):
        captured.update(payload)
        return "{}", {}

    monkeypatch.setattr("swarm_canvas.models._post_chat", fake_post)
    from swarm_canvas.models import _openai_compatible

    cfg = ModelConfig(provider="openrouter", name="x:free", catalog_enabled=False)
    _openai_compatible([{"role": "user", "content": "hi"}], cfg)
    assert "requests" not in captured["response_format"]["json_schema"]["schema"]["properties"]
    assert "requests" in _PAINTER_SCHEMA["properties"]  # shared template untouched
    captured.clear()
    _openai_compatible([{"role": "user", "content": "hi"}], ModelConfig(provider="openrouter", name="x:free"))
    assert "requests" in captured["response_format"]["json_schema"]["schema"]["properties"]
