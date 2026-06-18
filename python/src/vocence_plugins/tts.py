"""VocenceTTS — streaming text-to-speech with the Vocence voice library.

Conforms to the standard TTS abstract interface used by real-time
agent pipelines, so it slots in alongside any compatible
``Pipeline(tts=...)``. The plug-in handles all of the network
plumbing — connection lifecycle, audio framing, and reconnection —
so callers just see text in and audio out.

Audio output: PCM16LE @ 24 kHz, mono. One persistent connection is
reused across many ``synthesize()`` calls in the same session;
lazily opened on the first call and torn down on ``aclose()``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Optional, Union
from urllib.parse import urlparse

import aiohttp

from videosdk.agents import TTS, FlushMarker  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


_DEFAULT_BASE_URL = os.environ.get("VOCENCE_BASE_URL", "https://api.vocence.ai")
_DEFAULT_SAMPLE_RATE = 24_000
_DEFAULT_CHANNELS = 1
_DEFAULT_TIMEOUT_SEC = 30.0
# Per-speak text cap. Mirrors the dev-API limit so the server doesn't
# reject mid-stream. Plugin users sending longer text should split
# their input — the framework's sentence chunker already handles this when
# wired in front of the plugin.
_MAX_TEXT_CHARS_PER_SPEAK = 4000


def _ws_url_from_base(base_url: str, voice_id: str) -> str:
    """Translate ``https://api.vocence.ai`` → ``wss://api.vocence.ai/...``."""
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{parsed.path}/v1/voices/{voice_id}/stream"


class VocenceTTS(TTS):
    """Streaming TTS plugin backed by the Vocence voice service.

    Parameters
    ----------
    api_key:
        Vocence developer key (``voc_live_…``). Falls back to the
        ``VOCENCE_API_KEY`` env var. Required.
    voice:
        Voice slug (built-in like ``"design-aria"``) or the numeric id
        of a saved designed / cloned voice. Required at construction
        because the WS endpoint is voice-scoped.
    language:
        Optional language hint passed on every ``speak`` frame.
    base_url:
        Override the default ``https://api.vocence.ai`` (set for
        staging / self-hosted deployments).
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        voice: Union[str, int],
        language: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        **kwargs: Any,
    ) -> None:
        super().__init__(sample_rate=sample_rate, num_channels=_DEFAULT_CHANNELS)
        self.api_key = api_key or os.environ.get("VOCENCE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Vocence API key required — pass api_key= or set VOCENCE_API_KEY"
            )
        self.voice = str(voice)
        self.language = language
        self.base_url = base_url
        self._ws_url = _ws_url_from_base(base_url, self.voice)

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._connect_lock = asyncio.Lock()
        # Per-speak state: cleared at the start of each synthesize() call.
        # The receiver loop runs INLINE with the speak request so we can
        # cancel cleanly on interrupt without a separate task.
        self._interrupted = False
        self._first_chunk_sent = False

    # ----- abstract overrides ---------------------------------------------

    async def synthesize(
        self,
        text: AsyncIterator[Union[str, FlushMarker]] | str,
        voice_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Send text → push PCM frames to ``self.audio_track``.

        ``text`` may be a plain string OR an async iterator of strings
        (with optional ``FlushMarker`` segment boundaries). The async
        iterator path lets the pipeline pump LLM tokens directly here
        instead of waiting for the full reply. We don't yet support
        the WebSocket re-flush semantics that some upstream sentence
        chunkers rely on, so we concatenate iterator chunks up to a
        flush / end-of-stream marker and send them as one ``speak``
        frame each. This produces good audio with one network
        round-trip per sentence.

        ``voice_id`` is accepted for API symmetry but ignored — the
        endpoint is voice-scoped at the WS URL, so changing voice
        mid-session would require a fresh connection. Construct a new
        ``VocenceTTS`` for a different voice.
        """
        self._interrupted = False
        self._first_chunk_sent = False
        await self._ensure_connection()
        if isinstance(text, str):
            await self._speak_once(text)
            return
        # Async iterator path — collect into segments separated by FlushMarker
        # (or end-of-iterator), send each segment as one speak.
        buf: list[str] = []
        async for chunk in text:
            if self._interrupted:
                return
            if isinstance(chunk, FlushMarker):
                segment = "".join(buf).strip()
                buf = []
                if segment:
                    await self._speak_once(segment)
                    if self._interrupted:
                        return
                continue
            if chunk:
                buf.append(chunk)
        tail = "".join(buf).strip()
        if tail and not self._interrupted:
            await self._speak_once(tail)

    async def interrupt(self) -> None:
        """Stop the in-flight ``synthesize()`` ASAP. Doesn't close the
        WebSocket — the connection stays warm for the next call."""
        self._interrupted = True
        ws = self._ws
        if ws is not None and not ws.closed:
            # Best-effort: cancel any in-flight read. The receiver loop
            # checks self._interrupted between chunks and bails out.
            # No control frame to send — the pod will move on once we
            # send a fresh ``speak`` next time.
            pass

    async def aclose(self) -> None:
        """Tear down the WebSocket + HTTP session. Idempotent."""
        ws = self._ws
        if ws is not None and not ws.closed:
            with _suppress():
                await ws.send_str(json.dumps({"type": "stop"}))
            with _suppress():
                await ws.close(code=1000)
        self._ws = None
        if self._session is not None and not self._session.closed:
            with _suppress():
                await self._session.close()
        self._session = None

    def reset_first_audio_tracking(self) -> None:
        self._first_chunk_sent = False

    # ----- internals ------------------------------------------------------

    async def _ensure_connection(self) -> None:
        """Open the WS if not already open; reopen if it died."""
        async with self._connect_lock:
            if self._ws is not None and not self._ws.closed:
                return
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT_SEC),
                )
            headers = {"Authorization": f"Bearer {self.api_key}"}
            self._ws = await self._session.ws_connect(self._ws_url, headers=headers)
            # First message from the server is ``ready``. Wait for it so
            # subsequent ``speak`` frames aren't sent into a half-open
            # connection. Surface any auth / not-found error here.
            msg = await self._ws.receive(timeout=_DEFAULT_TIMEOUT_SEC)
            if msg.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError(
                    f"VocenceTTS: expected text ready frame, got {msg.type}"
                )
            data = json.loads(msg.data)
            mtype = (data.get("type") or "").lower()
            if mtype == "error":
                raise RuntimeError(
                    f"VocenceTTS connect rejected: "
                    f"{data.get('code')}: {data.get('message')}"
                )
            if mtype != "ready":
                raise RuntimeError(
                    f"VocenceTTS: unexpected first frame {mtype!r}"
                )

    async def _speak_once(self, text: str) -> None:
        """Send one ``speak`` and drain audio frames until ``end``."""
        if not text:
            return
        if len(text) > _MAX_TEXT_CHARS_PER_SPEAK:
            # Truncate rather than fail: a sentence chunker in front
            # of us should keep segments well under the cap.
            logger.warning(
                "VocenceTTS: truncating %d-char segment to %d (cap)",
                len(text), _MAX_TEXT_CHARS_PER_SPEAK,
            )
            text = text[:_MAX_TEXT_CHARS_PER_SPEAK]
        ws = self._ws
        if ws is None:
            return
        payload: dict[str, Any] = {"type": "speak", "text": text}
        if self.language:
            payload["language"] = self.language
        await ws.send_str(json.dumps(payload))
        await self._drain_until_end(ws)

    async def _drain_until_end(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Read frames until ``{"type":"end"}`` or interruption."""
        while True:
            if self._interrupted:
                return
            try:
                msg = await ws.receive(timeout=_DEFAULT_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                logger.warning("VocenceTTS: receive timed out")
                return
            if msg.type == aiohttp.WSMsgType.BINARY:
                if not msg.data:
                    continue
                # First-byte callback for TTFB metrics — the pipeline
                # uses this to fire its ``first_audio_byte`` event.
                if not self._first_chunk_sent:
                    self._first_chunk_sent = True
                    if self._first_audio_callback is not None:
                        with _suppress():
                            await self._first_audio_callback()
                if self.audio_track is not None:
                    with _suppress():
                        await self.audio_track.add_new_bytes(msg.data)
                continue
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                mtype = (data.get("type") or "").lower()
                if mtype == "end":
                    return
                if mtype == "meta":
                    # Sample rate / encoding info — we know our pod
                    # output is PCM16LE @ 24 kHz mono so don't need to
                    # do anything with this on the plugin side. The
                    # the audio_track already expects this format
                    # because we set ``sample_rate=24000`` on the base
                    # class at __init__.
                    continue
                if mtype == "error":
                    logger.warning(
                        "VocenceTTS pod error: %s: %s",
                        data.get("code"), data.get("message"),
                    )
                    return
                continue
            if msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.ERROR,
            ):
                self._ws = None
                return


class _suppress:
    """Tiny ``contextlib.suppress(Exception)`` clone — kept inline to
    keep the module's import surface small."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, Exception)
