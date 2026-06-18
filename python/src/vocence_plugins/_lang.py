"""Language-name → ISO-639-1 mapping for the Vocence STT pod.

The pod's wire protocol expects an ISO code (or ``"auto"``); full
names like ``"English"`` silently degrade to auto-detect, which then
mis-classifies short utterances. Mirrors the helper used inside the
Vocence backend so plugin users get the same behavior the hosted
service does.
"""
from __future__ import annotations

from typing import Optional

_NAME_TO_ISO = {
    "English": "en",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko",
    "German": "de",
    "French": "fr",
    "Russian": "ru",
    "Portuguese": "pt",
    "Spanish": "es",
    "Italian": "it",
}


def to_iso_639_1(language: Optional[str]) -> str:
    """Resolve any input form to the ISO-639-1 code the STT pod wants.

    Accepts agent-config full names (``"English"``), already-ISO codes
    (``"en"``), and the sentinel ``"auto"`` / ``None``. Falls back to
    ``"auto"`` for unknown input so the pod is never sent a string it
    doesn't understand.
    """
    if not language:
        return "auto"
    s = language.strip()
    if s.lower() == "auto":
        return "auto"
    if s in _NAME_TO_ISO:
        return _NAME_TO_ISO[s]
    if len(s) == 2 and s.isalpha():
        return s.lower()
    return "auto"
