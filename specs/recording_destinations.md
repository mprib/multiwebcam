# Recording Destinations & Open Folder

## Problem

Grid view recordings always go to `recordings/`. Users need to choose between:
- **Extrinsic calibration** recordings (`calibration/extrinsic/`)
- **Named recordings** (`recordings/<name>/`)

There's also no way to quickly open the project folder to inspect output files.

## User Decisions (from interview)

- Default recording name: auto-generate (e.g. `recording_001`), user can override
- Existing destination with files: warn and confirm before overwriting
- Destination controls: always visible, disabled during recording

## Design

### Recording Intent Dataclass

New file: `src/multiwebcam/ui/recording_intent.py`

```python
@dataclass(frozen=True)
class GridRecordingIntent:
    is_extrinsic: bool
    recording_name: str  # Only meaningful when is_extrinsic is False
```

The view constructs this from widget state and emits it with the record signal. The coordinator resolves it to a `Path`.

### Default Name Generator

New file: `src/multiwebcam/recording/naming.py`

```python
def next_recording_name(recordings_dir: Path) -> str:
    """Return 'recording_NNN' where NNN is one past the highest existing."""
```

Pure function. Scans `recordings/` for existing `recording_NNN` folders. Returns `recording_001` if none exist. Must handle non-existent `recordings_dir` gracefully (return `recording_001`).

### GridView Changes

File: `src/multiwebcam/ui/views/grid_view.py`

**New widgets** (destination row, inserted between grid and existing action row):

```
[Extrinsic Calibration checkbox] [Recording name: label+input] [-> path summary] ... [Open Folder link]
```

- Horizontal separator line between grid and destination row
- When "Extrinsic Calibration" checked: name label+input hide, summary shows `-> calibration/extrinsic/`
- When unchecked: name input visible with auto-generated default, summary shows `-> recordings/<name>/`
- "Open Folder" styled as flat link button, right-aligned
- All destination controls disabled during recording/stopping

**Signal changes:**

- `record_requested` changes from `Signal()` to `Signal(object)` — emits `GridRecordingIntent`
- New: `open_folder_requested = Signal()`

**New methods:**

- `set_default_recording_name(name: str)` — sets the line edit text without triggering signals
- `confirm_overwrite(display_name: str) -> bool` — shows `QMessageBox.question()`, returns True if user confirms

**Updated methods:**

- `set_recording(is_recording)` — also disables/enables extrinsic checkbox and name input
- `set_stopping()` — also disables destination controls
- Internal `_on_record_clicked()` — reads checkbox + line edit, constructs `GridRecordingIntent`, emits `record_requested(intent)`

### Coordinator Changes

File: `src/multiwebcam/ui/coordinator.py`

**In `create_grid_view()`:**

1. After creating view, call `view.set_default_recording_name(next_recording_name(recordings_dir))`
2. Replace `_on_record()` closure:
   ```python
   def _on_record(intent: GridRecordingIntent):
       if intent.is_extrinsic:
           output_dir = self._project_path / "calibration" / "extrinsic"
       else:
           name = _sanitize_recording_name(intent.recording_name)
           output_dir = self._project_path / "recordings" / name

       # Overwrite check
       if output_dir.exists() and any(output_dir.iterdir()):
           if not view.confirm_overwrite(str(output_dir.relative_to(self._project_path))):
               return

       cam_ids = {
           info.device_path: info.source_id
           for info in self._sources.values()
           if info.device_path and not info.error and not info.profile.ignore
       }
       if cam_ids:
           p.start_recording(output_dir, cam_ids=cam_ids)
   ```
3. Connect `view.open_folder_requested` to handler:
   ```python
   def _on_open_folder():
       from PySide6.QtCore import QUrl
       from PySide6.QtGui import QDesktopServices
       QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._project_path)))
   ```
4. After `recording_stopped`, update default name:
   ```python
   def _on_recording_stopped():
       view.set_recording(False)
       recordings_dir = self._project_path / "recordings"
       view.set_default_recording_name(next_recording_name(recordings_dir))
   ```

**Helper in coordinator:**

```python
import re

def _sanitize_recording_name(raw: str) -> str:
    """Sanitize user input to a safe filesystem name."""
    name = raw.strip()
    name = re.sub(r'[^\w\-]', '_', name)  # Only alphanumeric, underscore, hyphen
    return name or "untitled"
```

### What Does NOT Change

- **CapturePresenter** — `start_recording(output_dir, cam_ids)` interface already correct
- **CaptureSession** — pure Python model, unchanged
- **FrameRecorder** — receives output_dir, unchanged
- **FocusView** — always records to `calibration/intrinsic/`, unchanged

## File Summary

| File | Action |
|------|--------|
| `src/multiwebcam/ui/recording_intent.py` | NEW — `GridRecordingIntent` frozen dataclass |
| `src/multiwebcam/recording/naming.py` | NEW — `next_recording_name()` pure function |
| `src/multiwebcam/ui/views/grid_view.py` | MODIFY — add destination row, change record signal |
| `src/multiwebcam/ui/coordinator.py` | MODIFY — path resolution, overwrite check, open folder |

## Verification

1. Run widget visualization: `xvfb-run --auto-servernum python scripts/widget_visualization/wv_grid_recording_controls.py`
2. Manual test with cameras:
   - Record with default name -> files appear in `recordings/recording_001/`
   - Record with custom name -> files appear in `recordings/<custom>/`
   - Check "Extrinsic Calibration" and record -> files in `calibration/extrinsic/`
   - Record to existing destination -> overwrite confirmation dialog appears
   - Click "Open Folder" -> system file manager opens project directory
   - Controls disabled during recording, re-enabled after stop
   - Default name increments after each recording
