import pytest
from swarm_canvas.models import ModelConfig, validate_model_policy, _openai_compatible

def test_paid_model_is_explicit_and_restricted():
    model = 'deepseek/deepseek-v4.1-flash-1017'
    with pytest.raises(ValueError): validate_model_policy(ModelConfig(provider='openrouter', name=model))
    validate_model_policy(ModelConfig(provider='openrouter', name=model, paid_experiment=True))
    with pytest.raises(ValueError): validate_model_policy(ModelConfig(provider='openrouter', name='other/model', paid_experiment=True))
    with pytest.raises(ValueError): validate_model_policy(ModelConfig(provider='openrouter', name=model, paid_experiment='true'))

def test_paid_price_cap_does_not_change_free_default(monkeypatch):
    captured = []
    def capture(url, payload, cfg):
        captured.append(payload)
        return '{}', {}
    monkeypatch.setattr('swarm_canvas.models._post_chat', capture)
    for name, paid in [('deepseek/deepseek-v4.1-flash-1017', True), ('test/model:free', False)]:
        _openai_compatible([{'role':'user','content':'test'}], ModelConfig(provider='openrouter', name=name, paid_experiment=paid))
    assert captured[0]['provider']['max_price'] == {'prompt':0.3, 'completion':1.2}
    assert captured[1]['provider']['max_price'] == {'prompt':0, 'completion':0, 'request':0}
