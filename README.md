# vocence-plugins

Vocence voice plug-ins for real-time agent pipelines — drop in **Vocence custom voices** for TTS and **Vocence streaming speech recognition** for STT.

- **`VocenceTTS`** — streaming text-to-speech with the Vocence voice library (cloned, designed, and built-in speakers). One persistent connection per session, sub-second TTFB on warm connections, PCM16LE @ 24 kHz output.
- **`VocenceSTT`** — streaming speech-to-text with interim + final transcripts, optional speech / silence events for VAD integration, and language auto-detect.

> Status: 0.1.0 — public alpha.

## Install

```bash
pip install vocence-plugins
```

The plug-ins conform to the standard TTS / STT abstract interfaces, so they slot into any compatible voice-agent framework.

## API key

Get one at https://www.vocence.ai/account/developer. Requires the Premium plan.

```bash
export VOCENCE_API_KEY=voc_live_...
```

Or pass it directly: `VocenceTTS(api_key="voc_live_...", voice="...")`.

## Quickstart

```python
from vocence_plugins import VocenceTTS, VocenceSTT

tts = VocenceTTS(voice="design-aria", language="English")
stt = VocenceSTT(language="English")

# Wire into your agent pipeline as the TTS / STT components.
```

The plug-ins handle the WebSocket lifecycle, reconnection, and audio framing — your code just sees text in and audio out (TTS), or audio in and transcript events out (STT).

## Using the plug-ins to build a voice agent

A real-time voice agent is a loop: capture mic audio → recognize speech → run an LLM → speak the reply → repeat, with barge-in support so the user can interrupt mid-reply. `VocenceSTT` covers the recognition side, `VocenceTTS` covers synthesis; you bring (or reuse a framework for) the mic capture, the LLM call, and the audio playback.

```python
import asyncio
from vocence_plugins import VocenceTTS, VocenceSTT


async def main() -> None:
    # ---------------------------------------------------------------
    # 1. Build the components. Both pick up VOCENCE_API_KEY from env.
    # ---------------------------------------------------------------
    tts = VocenceTTS(voice="design-aria", language="English")
    stt = VocenceSTT(language="English")

    # ---------------------------------------------------------------
    # 2. STT side — push captured mic frames in, get transcripts out.
    # ---------------------------------------------------------------
    # Bind a transcript callback. Events arrive in the standard
    # {event_type, data: {text, language, ...}} envelope. event_type
    # is INTERIM (live caption), FINAL (committed utterance), or one
    # of the VAD events (SPEECH_START / SPEECH_END) when vad_events
    # is on. In a real pipeline this callback drives turn-taking:
    # on FINAL → run the LLM → speak the reply.
    async def on_transcript(event):
        if event.event_type.name == "FINAL":
            user_text = event.data.text
            print("user said:", user_text)
            # Hand off to whatever LLM you're running. The reply is
            # then synthesized by the TTS half below.
            reply = await your_llm.complete(user_text)
            await tts.synthesize(reply)

    stt._transcript_callback = on_transcript

    # Feed PCM16LE @ 16 kHz mono frames from your mic. Typical frame
    # cadence is 20–40 ms; the hot path is just an awaited byte send.
    # Replace this stub with your real capture loop (sounddevice,
    # PyAudio, browser WebSocket forward, etc.).
    async for frame in capture_mic_at_16k_mono_pcm16le():
        await stt.process_audio(frame)
        # End-of-utterance signal? Ask the pod to commit immediately
        # instead of waiting for its silence timer:
        if user_pressed_enter():
            await stt.flush()

    # ---------------------------------------------------------------
    # 3. TTS side — push text in, get 24 kHz PCM frames out.
    # ---------------------------------------------------------------
    # synthesize() pushes PCM frames to tts.audio_track as they
    # arrive from the pod. Wire your speaker output (or a WebSocket
    # forward, or a recorder) into tts.audio_track BEFORE calling
    # synthesize. Most pipeline frameworks expose
    # audio_track.add_sink(callable) — see your framework's docs.

    # Plain string:
    await tts.synthesize("Hi there — how can I help you today?")

    # Or an async iterator of token chunks for live LLM streaming,
    # so the first audio plays before the LLM has finished generating:
    async def token_stream():
        for token in ["Sure, ", "let me ", "check that ", "for you."]:
            yield token
    await tts.synthesize(token_stream())

    # ---------------------------------------------------------------
    # 4. Barge-in — cancel an in-flight reply when the user speaks.
    # ---------------------------------------------------------------
    # Call this from your VAD / interrupt detector the moment the
    # user starts talking over the agent. The WebSocket stays warm
    # for the next turn.
    await tts.interrupt()

    # ---------------------------------------------------------------
    # 5. Teardown at session end.
    # ---------------------------------------------------------------
    await tts.aclose()
    await stt.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

The full orchestration — capturing the mic, running VAD locally, deciding when to call `flush()`, holding chat history, dispatching tool calls — belongs to your pipeline. `VocenceTTS` and `VocenceSTT` slot in as the speech components and stay out of the way of everything else.

| Component | Direction | Format |
|---|---|---|
| `VocenceTTS` | out (pod → your sink) | PCM16LE, 24 kHz, mono |
| `VocenceSTT` | in (your mic → pod) | PCM16LE, 16 kHz, mono |

## Plugin reference

### `VocenceTTS(*, api_key=None, voice, language=None, base_url=...)`

Streaming TTS over the Vocence voice service. One WebSocket reused across many `synthesize()` calls in the same session, closed on `aclose()`.

| Arg | Default | Notes |
|---|---|---|
| `api_key` | `VOCENCE_API_KEY` env | Required (`voc_live_…`). |
| `voice` | — | Required. Either a built-in slug (`"design-aria"`, `"design-jasper"`, …) or the numeric id of a saved designed / cloned voice. |
| `language` | `None` | Optional hint sent on every speak. |
| `base_url` | `https://api.vocence.ai` | Override for staging / self-hosted. |

Audio output: PCM16LE @ 24 kHz, mono.

### `VocenceSTT(*, api_key=None, language="auto", sample_rate=16000, enable_partials=True, vad_events=True, base_url=...)`

Streaming STT. Lazy-opens a WebSocket on the first audio frame, runs a background reader that translates events into the framework's standard transcript event shape (interim, final, speech-start, speech-end).

| Arg | Default | Notes |
|---|---|---|
| `api_key` | `VOCENCE_API_KEY` env | Required. |
| `language` | `"auto"` | ISO-639-1 (`"en"`), full name (`"English"`), or `"auto"`. Normalized to ISO before send. |
| `sample_rate` | 16000 | PCM16LE mono input. |
| `enable_partials` | `True` | Stream interim hypotheses as the model refines. |
| `vad_events` | `True` | Emit speech-start / silence events from the internal VAD. |

## Compared to the Vocence Python SDK

| Use case | Use |
|---|---|
| Talk to a Vocence-hosted voice agent (REST + WebSocket to our service) | [`vocence`](https://pypi.org/project/vocence/) |
| Build your own agent pipeline with Vocence voices + recognition | This package |

The two don't overlap — different products for different use cases. Both authenticate with the same `voc_live_…` key.

## License

Apache-2.0.
