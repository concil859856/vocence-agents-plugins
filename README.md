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

The plug-ins expose **two surfaces**: a high-level streaming API (`stream_synthesize` / `stream_transcribe`) that yields bytes or transcript events directly — recommended for BYO pipelines — and a lower-level `synthesize` / `process_audio` API that integrates with framework-managed audio tracks (used when you wire the plug-ins into the `videosdk-agents` Pipeline class).

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
    # 2. TTS — text in, 24 kHz PCM frames out, no audio_track needed.
    # ---------------------------------------------------------------
    # ``stream_synthesize`` takes an async iterator of text and yields
    # raw bytes. No need to wire up an audio_track — the framework's
    # mock track captures frames internally and pipes them straight
    # to you. Hand each chunk to your speaker / WebSocket / recorder.
    async def reply_stream():
        # Plain string: wrap in a single-yield generator.
        yield "Hi there — how can I help you today?"
    async for pcm_chunk in tts.stream_synthesize(reply_stream()):
        # 24 kHz mono PCM16LE. Hand to your audio sink:
        play_or_forward(pcm_chunk)

    # For live LLM streaming (first audio plays before LLM finishes),
    # the iterator can yield tokens as they arrive:
    async def token_stream():
        async for token in your_llm.stream("Tell me a joke"):
            yield token
    async for pcm_chunk in tts.stream_synthesize(token_stream()):
        play_or_forward(pcm_chunk)

    # ---------------------------------------------------------------
    # 3. STT — bind a callback, then push captured mic frames in.
    # ---------------------------------------------------------------
    # Events arrive as the standard STTResponse envelope:
    #   event.event_type ∈ {INTERIM, FINAL, SPEECH_START, SPEECH_END}
    #   event.data.text  → recognized text (empty for VAD events)
    # In a real pipeline this callback drives turn-taking: on FINAL,
    # run the LLM and synthesize the reply.
    async def on_transcript(event):
        if event.event_type.name == "FINAL":
            user_text = event.data.text
            print("user said:", user_text)
            # Hand off to your LLM + TTS loop here.

    stt.on_transcript(on_transcript)

    # Feed PCM16LE @ 16 kHz mono frames from your mic. Typical frame
    # cadence is 20–40 ms; the hot path is just an awaited byte send.
    # Replace this stub with your real capture (sounddevice, PyAudio,
    # browser WebSocket forward, etc.).
    async for frame in capture_mic_at_16k_mono_pcm16le():
        await stt.process_audio(frame)
        # Explicit end-of-utterance signal? Ask the pod to commit
        # immediately instead of waiting for its silence timer:
        if user_pressed_enter():
            await stt.flush()

    # Alternative: ``stream_transcribe`` returns transcript events as
    # an async iterator instead of via callback — pick whichever shape
    # fits your loop better.
    #
    # async for event in stt.stream_transcribe(mic_frame_stream()):
    #     if event.event_type.name == "FINAL":
    #         ...

    # ---------------------------------------------------------------
    # 4. Barge-in — cancel an in-flight TTS reply when the user speaks.
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

### Pipeline-wrapped use (`videosdk-agents`)

When you wire the plug-ins into the `videosdk-agents` `Pipeline` class instead of orchestrating yourself, that framework provides the `audio_track` automatically and calls `synthesize(text)` / `process_audio(frame)` for you. You still build the components the same way; you just don't need `stream_synthesize` / `stream_transcribe` / `on_transcript`. See the [videosdk-agents docs](https://pypi.org/project/videosdk-agents/) for the pipeline assembly.

### Python version

The plug-ins require **Python ≥ 3.11** (inherited from `videosdk-agents`, which uses 3.11-only syntax). On Debian / Ubuntu 22.04 the default `python3` is 3.10 — install 3.11+ first (e.g. `apt install python3.11`) and create your venv from it.

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
