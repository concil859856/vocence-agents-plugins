# Changelog

## [Unreleased]

## [0.1.2] - 2026-06-19

### Added
- **`VocenceSTT.on_transcript(callback)`** — public method to bind a
  callback for transcript events (INTERIM / FINAL / SPEECH_START /
  SPEECH_END). The shipped 0.1.1 README's worked example had users
  poke `stt._transcript_callback = cb` (a leading-underscore =
  private attribute). The new public method wraps the same slot, so
  BYO-pipeline users no longer have to touch private state. Both
  sync and async callbacks are accepted.

### Changed
- **README — emphasize `stream_synthesize` / `stream_transcribe`** as
  the recommended BYO-pipeline path (yields PCM frames / transcript
  events directly, no `audio_track` plumbing needed). The shipped
  0.1.1 README showed `synthesize(text)` and told users to wire up
  `tts.audio_track` first — but `audio_track` starts as `None` and
  there's no public class to construct one with. The new example
  uses `async for chunk in tts.stream_synthesize(text_stream())`
  which mocks the audio track internally.
- **README — explicit Python 3.11+ note.** Default `python3` on
  Debian / Ubuntu 22.04 is 3.10. Pip's "Could not find a version
  that satisfies the requirement" message is misleading; the actual
  cause (Python version) is buried in an earlier "Ignored the
  following versions" line. The README now calls this out at the
  bottom of the worked example.
- **README — pipeline-wrapped use section.** Brief callout that when
  the plug-ins are dropped into the `videosdk-agents` Pipeline
  class, the framework provides `audio_track` and calls
  `synthesize` / `process_audio` for you (covering the other
  intended use case).

### Fixed
- **`pyproject.toml` URLs** corrected — `Repository` / `Issues`
  pointed at `github.com/concil859856/vocence-plugins` (404). The
  actual repo is `vocence-agents-plugins`. `Documentation` updated
  from `/docs/sdk-agents` to `/docs/sdk-plugins`.

## [0.1.1] - 2026-06-19

### Changed
- **README — full "Using the plug-ins to build a voice agent" worked
  example** added to both the repo-root README and `python/README.md`
  (the latter renders on the PyPI project page). Shipped 0.1.0 only
  had a 4-line Quickstart and a "wire into your pipeline" pointer
  with no concrete agent loop, so anyone landing on PyPI had nothing
  actionable. The new section shows the full agent loop pattern:
  build the components, bind the transcript callback, feed mic
  frames, call `synthesize` (string or async iterator of LLM
  tokens), `interrupt()` on barge-in, `aclose()` at teardown.
  Deliberately framework-agnostic.
- No code changes vs 0.1.0.

## [0.1.0] - 2026-06-19

### Added
- Initial package skeleton (`pyproject.toml`, src layout, README, LICENSE).
- `VocenceTTS` plugin — streaming text-to-speech with the Vocence
  voice library (cloned, designed, and built-in speakers).
  Conforms to the standard TTS abstract interface used by
  real-time agent pipelines. One persistent connection per
  session, lazily opened on first call. Supports both plain
  strings and async-iterator text inputs (with segment-boundary
  markers).
- `VocenceSTT` plugin — streaming speech-to-text. Conforms to the
  standard STT abstract interface. Emits interim + final transcripts
  and optional speech-start / silence events for VAD integration.
  Background reader translates events; main path is just
  audio bytes → send. Language input normalized to ISO-639-1.

### Notes
- Authentication is the shared Vocence `voc_live_…` developer key
  (same one as `vocence-sdk` / CLI). Reads `VOCENCE_API_KEY` from
  the environment by default.
- TTS audio: PCM16LE @ 24 kHz mono. STT audio: PCM16LE @ 16 kHz mono.
