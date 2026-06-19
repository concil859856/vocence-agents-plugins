"""Vocence voice plug-ins.

Drop-in components that bring **Vocence custom voices** and
**Vocence streaming speech recognition** into your real-time voice
agent pipeline. Authenticated with the standard Vocence
``voc_live_…`` developer key — the same one you use across the rest
of the Vocence platform.

The headline component is :class:`VocenceTTS` — streaming
text-to-speech with the Vocence voice library: cloned voices,
designed voices, and the built-in speaker catalog. :class:`VocenceSTT`
streams audio in and transcripts out.

Example
-------

>>> from vocence_plugins import VocenceTTS, VocenceSTT
>>>
>>> tts = VocenceTTS(api_key="voc_live_...", voice="design-aria")
>>> stt = VocenceSTT(api_key="voc_live_...", language="English")

Plug them into the agent framework of your choice — both classes
conform to the standard TTS / STT abstract interfaces.

See https://www.vocence.ai/docs/sdk-agents for the full guide.
"""
from __future__ import annotations

__version__ = "0.1.1"

from .tts import VocenceTTS
from .stt import VocenceSTT

__all__ = [
    "VocenceTTS",
    "VocenceSTT",
]
