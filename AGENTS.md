# AGENTS.md - Roblox Asset Uploader Project Rules & Guidelines

## Project Architecture & Standards

- **Core Module (`uploader.py`)**:
  - Handles Roblox Assets API integration, EXIF metadata extraction via Pillow, transparent PNG fix via Pixelfix, file hashing & deduplication (`upload_history.json`), run logging (`run_sessions.json`), and CLI argument parsing.
- **Terminal User Interface (`tui.py`)**:
  - Primary user interface powered by **Textual**.
  - Features form inputs, switches, progress bar, real-time logging screen, and session recovery popup dialogs.
- **Global Entry Points (`setup.py`)**:
  - `easy-upload` & `roblox-upload`: Launch the interactive Textual TUI from any folder.
  - `roblox-uploader`: Launch the CLI batch uploader from any folder.

## Key Features & Constraints

1. **Upload Batch Limit (`--max-uploads`)**:
   - Always honor the maximum upload limit set by the user (default e.g. 200). Stop processing when the count is reached and mark session status as `PAUSED`.
2. **Session Resumption (`--resume`)**:
   - Log runs to `run_sessions.json`. On startup, check for unfinished or paused runs and offer to resume from the last saved index.
3. **Pixelfix Preprocessing**:
   - Perform smart transparency checking prior to invoking Pixelfix to avoid unnecessary processing on opaque PNGs.
4. **All Output & Docs in English**:
   - Ensure all UI strings, log entries, docstrings, help messages, and documentation are written in English.

## Testing & Quality Assurance

- Always run the test suite before finalizing any architectural changes or bug fixes:
  ```bash
  py -m unittest discover tests
  ```
- Ensure zero syntax errors by compiling modified files:
  ```bash
  py -m py_compile uploader.py tui.py gui.py setup.py tests/test_uploader.py
  ```
