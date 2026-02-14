# Single Camera Recording (Intrinsic Calibration)

Record from the focused camera only to `calibration/intrinsic/cam_N.mp4`.

## Context

Intrinsic calibration requires a video of a single camera viewing a calibration board. The user enters focus mode for one camera, records, and the output goes to a known path that Caliscope can consume.

No frametimes needed for intrinsic calibration, but FrameRecorder writes them anyway (harmless).

## Key Insight

In focus mode, `pause_all_except()` blocks other producers. The global `is_recording` flag is safe because only the focused camera's producer is active and pushing frames to its recording queue.

## Sentinel Bug Fix

Current `stop_recording()` sends sentinels to ALL recording queues:

```python
for queues in self._producer_queues.values():
    queues.recording.put(None)
```

After single-camera recording, leftover sentinels in non-recording queues would break a subsequent full recording (recorder would see sentinel immediately and stop).

**Fix:** Store `_recording_paths` during `start_recording()`, sentinel only those in `stop_recording()`:

```python
# In start_recording():
self._recording_paths = list(recording_queues.keys())

# In stop_recording():
for path in self._recording_paths:
    self._producer_queues[path].recording.put(None)
self._recording_paths = []
```

**Drain excluded queues:** When `cam_ids` specifies a subset of cameras, drain recording queues for non-recording paths before setting `is_recording`. Prevents stale frames from leaking into a subsequent full recording.

## Session API

No new parameters. `cam_ids` already carries the filter — its keys define which cameras record:

```python
def start_recording(self, output_dir: Path, cam_ids: dict[str, int] | None = None) -> None:
    # ... existing cam_ids defaulting logic ...

    # Only create recording queues for cameras in cam_ids
    recording_queues = {
        path: queues.recording
        for path, queues in self._producer_queues.items()
        if path in cam_ids
    }

    # Drain excluded queues to prevent stale frames
    for path, queues in self._producer_queues.items():
        if path not in cam_ids:
            while not queues.recording.empty():
                try:
                    queues.recording.get_nowait()
                except Empty:
                    break

    self._recording_paths = list(recording_queues.keys())
```

## Signal Flow

```
"Record" clicked in FocusView
  -> view.record_requested (Signal)
  -> Coordinator wires to presenter.start_recording(output_dir)
  -> presenter builds cam_ids={device_path: source_id}
  -> session.start_recording(dir, cam_ids=cam_ids)
  -> presenter emits recording_started
  -> view.set_recording(True)

"Stop" clicked
  -> view.stop_requested (Signal)
  -> presenter.stop_recording()
  -> session.stop_recording()
  -> sentinel to recorded queues only
  -> recorder drains + finalizes
  -> presenter emits recording_stopped
  -> view.set_recording(False)
```

## Deactivation Guard

If recording is active when the presenter deactivates (e.g. window close), stop recording first:

```python
def deactivate(self) -> None:
    if not self._active:
        return
    if self._session.is_recording:
        self.stop_recording()
    self._timer.stop()
    self._session.resume_all()
    self._active = False
```

## Files Modified

| File | Change |
|------|--------|
| `pipeline/session.py` | Filter `recording_queues` by `cam_ids` keys, drain excluded queues, store `_recording_paths`, fix sentinel targeting |
| `ui/presenters/single_source.py` | Add `source_id` param, recording signals + methods, deactivation guard. Cross-ref: `# See also: MultiSourcePresenter.start_recording` |
| `ui/views/focus_view.py` | Add Record/Stop buttons, `record_requested`/`stop_requested` signals, `set_recording(bool)` reusing `set_config_enabled()` |
| `ui/coordinator.py` | Pass `source_id` to presenter, wire recording signals, output_dir = `project_path / "calibration" / "intrinsic"` |

## UI During Recording

- **Disabled:** Record, Apply, resolution/framerate combos, Back to Grid (via `set_config_enabled(False)`)
- **Enabled:** Stop, Control panel (adjust exposure mid-recording is useful)

## Code Duplication Note

Both `SingleSourcePresenter` and `MultiSourcePresenter` have parallel `start_recording()`/`stop_recording()` methods and `recording_started`/`recording_stopped` signals. This is intentional — the implementations differ in how `cam_ids` is constructed. Not worth a mixin for two consumers. Extract if a third recording context appears.

## Verification

1. Focus view -> Record -> wave board -> Stop -> `calibration/intrinsic/cam_N.mp4` exists and plays
2. Return to grid -> grid recording still works (sentinel fix verified)
