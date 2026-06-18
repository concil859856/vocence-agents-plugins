# Changelog

## [Unreleased]

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
