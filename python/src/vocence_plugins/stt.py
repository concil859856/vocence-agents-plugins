"""VocenceSTT — streaming speech-to-text with Vocence recognition.

Conforms to the standard STT abstract interface used by real-time
agent pipelines, so it slots in alongside any compatible
``Pipeline(stt=...)``. The plug-in handles connection lifecycle,
audio framing, and event translation — callers just see audio in
and standard transcript events out.

Audio input: PCM16LE @ 16 kHz, mono. One persistent connection is
lazily opened on the first audio frame and torn down on
``aclose()``. A background reader task translates incoming events
into the framework's standard transcript event shape.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

import aiohttp

from videosdk.agents import (  # type: ignore[import-not-found]
    STT,
    STTResponse,
    SpeechData,
    SpeechEventType,
)

from ._lang import to_iso_639_1

logger = logging.getLogger(__name__)


_DEFAULT_BASE_URL = os.environ.get("VOCENCE_BASE_URL", "https://api.vocence.ai")
_DEFAULT_SAMPLE_RATE = 16_000
_DEFAULT_TIMEOUT_SEC = 30.0


def _ws_url_from_base(base_url: str) -> str:
    """Translate ``https://api.vocence.ai`` → ``wss://api.vocence.ai/v1/stt/stream``."""
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{parsed.path}/v1/stt/stream"


class VocenceSTT(STT):
    """Streaming STT plugin backed by the Vocence recognition service.

    Parameters
    ----------
    api_key:
        Vocence developer key (``voc_live_…``). Falls back to the
        ``VOCENCE_API_KEY`` env var. Required.
    language:
        Spoken language. Accepts ISO-639-1 codes (``"en"``), full
        names (``"English"``), or ``"auto"`` for auto-detect.
        Default ``"auto"``. Normalized to ISO upfront to avoid
        silent degradation to auto-detect for unrecognized forms.
    sample_rate:
        Audio sample rate. Default 16 kHz (mono PCM16LE). Only
        16 kHz is accepted today; argument is kept for
        forward-compatibility.
    enable_partials:
        Stream interim hypotheses as recognition refines. Default
        ``True`` — needed for any responsive UI; disable only for
        batch / archival use cases that just want finals.
    vad_events:
        Emit speech-start / silence events from the internal VAD so
        the orchestrator can drive its interrupt / speech_started
        hooks off these. Default ``True``. Independent of any
        external VAD plugin you wire alongside.
    base_url:
        Override the default ``https://api.vocence.ai``.
    forward_interim_transcripts:
        Whether to surface interim text to the user UI (passed
        through to the standard STT base initializer).
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        language: str = "auto",
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        enable_partials: bool = True,
        vad_events: bool = True,
        base_url: str = _DEFAULT_BASE_URL,
        forward_interim_transcripts: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(forward_interim_transcripts=forward_interim_transcripts)
        self.api_key = api_key or os.environ.get("VOCENCE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Vocence API key required — pass api_key= or set VOCENCE_API_KEY"
            )
        self.language = language
        self.sample_rate = sample_rate
        self.enable_partials = enable_partials
        self.vad_events = vad_events
        self.base_url = base_url
        self._ws_url = _ws_url_from_base(base_url)

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader_task: asyncio.Task | None = None
        self._connect_lock = asyncio.Lock()
        self._closed = False

    # ----- public binding hooks -------------------------------------------

    def on_transcript(
        self,
        callback: "Callable[[Any], Awaitable[None]] | Callable[[Any], None]",
    ) -> None:
        """Bind a callback invoked with each transcript event.

        The callback receives an ``STTResponse`` from the framework's
        STT base class: ``event.event_type`` is one of ``INTERIM``,
        ``FINAL``, ``SPEECH_START``, ``SPEECH_END``; ``event.data.text``
        carries the recognized text (empty for VAD events).

        Both sync and async callbacks are accepted. Internally this
        sets the same private callback slot the framework's pipeline
        uses (``_transcript_callback``) — exposing it publicly so
        BYO-pipeline users have a non-underscore API to bind against.
        """
        self._transcript_callback = callback

    # ----- abstract overrides ---------------------------------------------

    async def process_audio(
        self,
        audio_frames: bytes,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Send one PCM16LE frame to the pod. Lazy-opens the WS on
        first call. The framework calls this once per audio frame
        (typically 20-40 ms), so the hot path is just a bytes send.

        ``language`` is accepted for API symmetry but ignored once
        the connection is established — the pod's ``start`` frame
        binds the language for the session. Construct a new
        ``VocenceSTT`` for a different language.
        """
        if self._closed:
            return
        if self._ws is None:
            await self._ensure_connection()
        ws = self._ws
        if ws is None or ws.closed:
            return
        try:
            await ws.send_bytes(audio_frames)
        except Exception as exc:  # noqa: BLE001
            logger.warning("VocenceSTT send_bytes failed: %s", exc)
            await self._teardown_ws()

    async def flush(self) -> None:
        """Ask the pod to finalize its current partial as soon as
        possible. Useful at end-of-utterance when the orchestrator
        knows the turn is over but the pod hasn't auto-emitted a
        final yet."""
        ws = self._ws
        if ws is None or ws.closed:
            return
        try:
            await ws.send_str(json.dumps({"type": "commit"}))
        except Exception as exc:  # noqa: BLE001
            logger.debug("VocenceSTT commit failed: %s", exc)

    async def aclose(self) -> None:
        """Close the WebSocket + HTTP session. Idempotent."""
        self._closed = True
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        await self._teardown_ws()

    # ----- internals ------------------------------------------------------

    async def _ensure_connection(self) -> None:
        """Open the WS, send ``start``, wait for ``ready``, kick the reader."""
        async with self._connect_lock:
            if self._ws is not None and not self._ws.closed:
                return
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT_SEC),
                )
            headers = {"Authorization": f"Bearer {self.api_key}"}
            self._ws = await self._session.ws_connect(self._ws_url, headers=headers)
            start_payload = {
                "type": "start",
                "language": to_iso_639_1(self.language),
                "sample_rate": self.sample_rate,
                "encoding": "pcm_s16le",
                "enable_partials": self.enable_partials,
                "vad_events": self.vad_events,
            }
            await self._ws.send_str(json.dumps(start_payload))
            ready = await self._ws.receive(timeout=_DEFAULT_TIMEOUT_SEC)
            if ready.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError(
                    f"VocenceSTT: expected ready frame, got {ready.type}"
                )
            data = json.loads(ready.data)
            mtype = (data.get("type") or "").lower()
            if mtype == "error":
                raise RuntimeError(
                    f"VocenceSTT connect rejected: "
                    f"{data.get('code')}: {data.get('message')}"
                )
            if mtype != "ready":
                raise RuntimeError(
                    f"VocenceSTT: unexpected first frame {mtype!r}"
                )
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="vocence_stt_reader"
            )

    async def _read_loop(self) -> None:
        """Background task: translate pod events → STTResponse callbacks."""
        ws = self._ws
        if ws is None:
            return
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        return
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                response = self._translate_event(data)
                if response is None:
                    continue
                cb = self._transcript_callback
                if cb is None:
                    continue
                try:
                    await cb(response)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("VocenceSTT callback raised: %s", exc)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("VocenceSTT reader loop crashed: %s", exc)
            self.emit("error", str(exc))

    def _translate_event(self, data: dict) -> STTResponse | None:
        """Map one pod event to the the framework's STTResponse shape.

        Returns ``None`` for events we drop (errors are logged via
        EventEmitter instead of being passed to the orchestrator).
        """
        mtype = (data.get("type") or "").lower()
        if mtype == "partial":
            text = (data.get("text") or "").strip()
            if not text:
                return None
            return STTResponse(
                event_type=SpeechEventType.INTERIM,
                data=SpeechData(text=text, language=self.language),
            )
        if mtype == "final":
            text = (data.get("text") or "").strip()
            if not text:
                return None
            return STTResponse(
                event_type=SpeechEventType.FINAL,
                data=SpeechData(
                    text=text,
                    language=data.get("language_detected") or self.language,
                ),
            )
        if mtype == "vad_speech":
            return STTResponse(
                event_type=SpeechEventType.START,
                data=SpeechData(text=""),
            )
        if mtype == "vad_silence":
            return STTResponse(
                event_type=SpeechEventType.END,
                data=SpeechData(text=""),
            )
        if mtype == "error":
            logger.warning(
                "VocenceSTT pod error: %s: %s",
                data.get("code"), data.get("message"),
            )
            self.emit("error", str(data.get("message") or data.get("code")))
            return None
        # ready / pong / unknown — drop silently
        return None

    async def _teardown_ws(self) -> None:
        ws = self._ws
        if ws is not None and not ws.closed:
            with _suppress():
                await ws.send_str(json.dumps({"type": "close"}))
            with _suppress():
                await ws.close(code=1000)
        self._ws = None
        if self._session is not None and not self._session.closed:
            with _suppress():
                await self._session.close()
        self._session = None


class _suppress:
    """Inline contextlib.suppress(Exception) — keeps the module's
    explicit import surface small."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, Exception)
