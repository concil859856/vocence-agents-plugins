# Changelog

## [Unreleased]

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
