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
