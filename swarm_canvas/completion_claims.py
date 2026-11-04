"""Conservative preregistration trigger, not a general semantic classifier."""
from __future__ import annotations

import re

# Only explicit whole-artifact statements trigger. Broad ambiguous wording is left for review.
_WHOLE = r'(?:canvas|painting|picture|scene)'
_STATE = r'(?:complete|completed|finished|done)'
_CLAIM = re.compile(r'\b(?:the\s+|our\s+)?' + _WHOLE + r'\s+(?:is\s+)?' + _STATE + r'\b|'
                    r'\b(?:finished|completed)\s+(?:the\s+|our\s+)?(?:entire\s+|whole\s+)' + _WHOLE + r'\b', re.I)
_NEGATED = re.compile(r"\b(?:not|isn't|isnt|wasn't|wasnt|never|incomplete|unfinished|almost|nearly|not yet)\b", re.I)
_HYPOTHETICAL = re.compile(r'\b(?:if|when|once|whether|might|may|could|would|should|hope|wish|think|claim|said|says|previous)\b', re.I)


def is_explicit_completion_claim(text: str) -> bool:
    """Reject questions, negations, hedges, and reports of someone else's claim."""
    if not isinstance(text, str):
        return False
    for sentence in re.split(r'(?<=[.!?])\s+|[\n;]', text):
        if ('?' not in sentence and not _NEGATED.search(sentence)
                and not _HYPOTHETICAL.search(sentence) and _CLAIM.search(sentence)):
            return True
    return False
