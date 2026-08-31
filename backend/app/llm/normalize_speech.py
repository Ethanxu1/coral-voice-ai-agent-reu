"""Child-speech normalization for regex intent matching.

Kids are disfluent, use contractions, and phrase commands creatively. This
module lightens the load on the regex matcher by mapping common kid phrasing
to canonical verbs before the regex runs, while leaving the original text
available for the LLM fallback so it still sees natural language.
"""

from __future__ import annotations

import re


# Leading filler words that don't affect intent (with optional trailing punctuation).
_LEADING_FILLERS_RE = re.compile(
    r"^(?:(?:um|uh|like|well|so|okay|ok)\b[,;:!.]?\s+)+",
    re.IGNORECASE,
)

# Contractions and informal shortenings commonly produced by child speech.
_CONTRACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwanna\b", re.IGNORECASE), "want to"),
    (re.compile(r"\bgonna\b", re.IGNORECASE), "going to"),
    (re.compile(r"\blemme\b", re.IGNORECASE), "let me"),
    (re.compile(r"\bgimme\b", re.IGNORECASE), "give me"),
    (re.compile(r"\bkinda\b", re.IGNORECASE), "kind of"),
    (re.compile(r"\bsorta\b", re.IGNORECASE), "sort of"),
]

# Phrase-level synonyms → canonical motion verbs.
# Order matters: longer, more specific phrases are replaced first.
_MOTION_SYNONYMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(make|put)\s+it\s+(go\s+)?up\b", re.IGNORECASE), "raise"),
    (re.compile(r"\b(make|put)\s+it\s+(go\s+)?down\b", re.IGNORECASE), "lower"),
    (re.compile(r"\bput\s+(?:your\s+|my\s+|the\s+)?(left|right|both)?\s*(?:arm|arms)\s+up\b", re.IGNORECASE), r"raise \1 arm"),
    (re.compile(r"\bput\s+(?:your\s+|my\s+|the\s+)?(left|right|both)?\s*(?:arm|arms)\s+down\b", re.IGNORECASE), r"lower \1 arm"),
    (re.compile(r"\blift\s+(it\s+)?up\b", re.IGNORECASE), "raise"),
    (re.compile(r"\bput\s+(it\s+)?down\b", re.IGNORECASE), "lower"),
    (re.compile(r"\bmove\s+it\s+out\b", re.IGNORECASE), "extend"),
    (re.compile(r"\bmove\s+it\s+up\b", re.IGNORECASE), "raise"),
    (re.compile(r"\bmove\s+it\s+down\b", re.IGNORECASE), "lower"),
    (re.compile(r"\bturn\s+it\s+(left|right)\b", re.IGNORECASE), r"turn \1"),
    (re.compile(r"\blook\s+it\s+(left|right)\b", re.IGNORECASE), r"look \1"),
    # "put your head up/down" → tilt head up/down
    (re.compile(r"\bput\s+(?:your\s+|my\s+|the\s+)?head\s+(up|down)\b", re.IGNORECASE), r"tilt head \1"),
    # "put your head left/right" → turn head left/right
    (re.compile(r"\bput\s+(?:your\s+|my\s+|the\s+)?head\s+(left|right)\b", re.IGNORECASE), r"turn head \1"),
]

# Collapse repeated words (e.g. "the the the" → "the").
_REPEATED_WORDS_RE = re.compile(r"\b(\w+)(\s+\1)+\b", re.IGNORECASE)


def normalize_for_regex(text: str) -> str:
    """Return a normalized version of *text* for regex intent matching.

    The original casing and wording are not preserved; the output is lowercased
    and stripped of leading fillers. The LLM fallback should receive the
    original text, not this normalized form.
    """
    normalized = text.lower()

    # Strip leading fillers.
    normalized = _LEADING_FILLERS_RE.sub("", normalized)

    # Expand contractions.
    for pattern, replacement in _CONTRACTIONS:
        normalized = pattern.sub(replacement, normalized)

    # Replace creative phrasing with canonical verbs.
    for pattern, replacement in _MOTION_SYNONYMS:
        normalized = pattern.sub(replacement, normalized)

    # Collapse repeated words.
    normalized = _REPEATED_WORDS_RE.sub(r"\1", normalized)

    # Normalize whitespace.
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized
