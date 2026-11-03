# Watchyard 0.5.1 — retained alert links

Includes the alert replay, download and Saved clips features from 0.5. Replay
links now look up retained alerts directly when they are outside the dashboard's
latest 80 events. An expired alert gives a clear message pointing to Saved clips.
The metadata lookup requires the same authentication as video playback.

77 automated tests pass, including retained-alert lookup beyond recent Activity.
The 0.5 recorder, playback, download, storage and live permission checks are
documented in release-0.5.md. See replay-and-clips.md for operation and limits.
