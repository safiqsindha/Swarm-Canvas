import pytest
from swarm_canvas.completion_claims import is_explicit_completion_claim

@pytest.mark.parametrize('text', ['The canvas is complete.', 'Canvas complete.', 'Our scene is done!', 'We finished the entire painting.'])
def test_affirmative_whole_canvas_claims_trigger(text):
    assert is_explicit_completion_claim(text)

@pytest.mark.parametrize('text', ['The canvas is not complete.', 'Is the canvas complete?',
    'The boat is complete.', 'The canvas is almost complete.', 'The canvas will be complete.',
    'The canvas seems complete.', 'The previous message said the canvas is complete.',
    'If the canvas is complete, stop.', 'Row 3 is done.'])
def test_uncertain_negated_partial_and_future_do_not_trigger(text):
    assert not is_explicit_completion_claim(text)
