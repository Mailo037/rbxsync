# Roblox Creator Store Uploader & TUI

A robust, automated toolchain and interactive **Terminal User Interface (TUI)** for uploading assets (Images, Decals, Audio, Models, Videos) to the Roblox Creator Store. Built with **Textual** (OpenTUI ecosystem), it features automatic preprocessing via Pixelfix, EXIF metadata extraction, session logging with resume capability, upload limits, and intelligent deduplication for mass uploads.

---

## Features

* **Terminal User Interface (TUI)**: Interactive, mouse-friendly terminal interface powered by Textual with form controls, live statistics, real-time logging, and queue controls.
* **Encrypted Settings Storage**: Sensitive credentials (API Keys, User/Group IDs, preferences) are automatically encrypted on disk using Windows DPAPI (`%APPDATA%\easy-asset-upload\settings.enc`).
* **Persistent `%APPDATA%` Storage**: All application state (`upload_history.json`, `run_sessions.json`, `settings.enc`, cached Pixelfix binaries) is stored in `%APPDATA%\easy-asset-upload` so data persists seamlessly across folders and updates.
* **Automatic Updates**: Periodically checks git origin for new updates and automatically pulls and syncs the codebase on startup.
* **Upload Batch Limits**: Limit the number of uploads per run (e.g. max 200 assets) and automatically pause upon reaching the limit.
* **Session Logging & Resume**: Logs active runs into `%APPDATA%\easy-asset-upload\run_sessions.json`. On startup, detects unfinished runs and prompts *"Unfinished run detected! Do you want to resume?"*.
* **Mass Upload Support**: Process single files, entire directories, or JSON manifests for precise metadata control.
* **Automatic Preprocessing (Pixelfix)**: Transparent PNGs are processed to prevent pixel bleeding. Transparency is dynamically checked to save processing time.
* **Metadata Extraction**: Extracts internal file metadata comments (EXIF/PNG chunks) via Pillow to automatically populate asset descriptions.
* **Deduplication**: Hashes files and checks history to prevent uploading duplicate assets.
* **Auto-Watcher**: Optional watcher script to monitor directories and automatically upload new assets.

---

## Setup

### 1. Install Dependencies

Install the required Python packages:

```bash
pip install textual rich requests python-dotenv watchdog Pillow
```

### 2. Configuration (.env)

Create a `.env` file in the root directory to store your credentials:

```env
ROBLOX_API_KEY=your_api_key_here
USER_ID=12345678
GROUP_ID=
```

### 3. API Key Permissions

1. Navigate to [create.roblox.com/dashboard/credentials](https://create.roblox.com/dashboard/credentials)
2. Create a new API Key with `asset:read` and `asset:write` permissions under the **Assets API**.

## Global Command Line Commands

You can run the application directly from **any folder or terminal window** using any of these global commands:

```bash
# Launch interactive TUI from anywhere:
easy-upload
# or
roblox-upload

# Launch CLI uploader from anywhere:
roblox-uploader --user-id 12345 --max-uploads 200 ./path/to/assets
```

---

## Usage: Terminal User Interface (TUI)

Launch the interactive Terminal UI:

```bash
easy-upload
# or
roblox-upload
# or
py -m tui
```

### TUI Capabilities
- **Resume Prompt**: Automatically prompts to resume unfinished or paused runs upon startup.
- **Form Controls**: Easily enter API Key, User/Group ID, Asset Type, Target Path, and Max Upload Limits.
- **Toggles**: Enable/disable Pixelfix, Deduplication, Dry Runs, or Creator Store Distribution.
- **Live Monitoring**: Displays real-time progress bar, uploaded/failed counters, and scrolling color log.

---

## Usage: Command Line Interface (CLI)

The CLI tool (`uploader.py`) is ideal for automation and headless environments.

### Examples

#### Basic File Upload
```bash
python uploader.py --user-id 12345 --asset-type Decal icon.png
```

#### Directory Upload with a 200 Upload Limit
```bash
python uploader.py --user-id 12345 --asset-type Decal --max-uploads 200 ./watch_dir/
```

#### Resume Latest Unfinished Run
```bash
python uploader.py --resume
```

#### Dry Run Test
```bash
python uploader.py --user-id 12345 --dry-run --max-uploads 10 ./watch_dir/
```

---

## CLI Arguments Reference (`uploader.py`)

| Argument | Description |
| :--- | :--- |
| `input` | File or folder paths to upload |
| `--key` | Roblox API Key (defaults to `ROBLOX_API_KEY` env var) |
| `--user-id` | Upload as User ID (defaults to `USER_ID` env var) |
| `--group-id` | Upload as Group ID (defaults to `GROUP_ID` env var) |
| `--asset-type` | Asset type (Decal, Image, Audio, Model, Video) |
| `--max-uploads` | Limit the maximum number of assets uploaded in this session (e.g. 200) |
| `--resume` | Resume the latest paused or unfinished run session |
| `--manifest` | Path to a JSON manifest with individual asset metadata |
| `--name` | Display name (for single file uploads) |
| `--description` | Default description for uploaded assets |
| `--no-pixelfix` | Disable automatic Pixelfix preprocessing |
| `--no-dedup` | Upload even if the file hash exists in history |
| `--distribute` | Automatically configure asset on the Creator Store |
| `--start-index` | Skip files until reaching this index |
| `--delay` | Pause between uploads in seconds (Default: 1.2s) |
| `--dry-run` | Simulate processing without sending requests to Roblox |
| `--results` | Output JSON file path for final run results |