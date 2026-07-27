# RBXSync 🚀

**RBXSync** is a high-performance, modern Roblox Creator Store batch asset uploader and synchronizer featuring an interactive **Textual TUI**, encrypted credential storage, transparency cleanup via **Pixelfix**, and automated deduplication.

[![Release](https://img.shields.io/github/v/release/Mailo037/rbxsync?color=brightgreen)](https://github.com/Mailo037/rbxsync/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 💾 Quickstart (Standalone Executable)

1. **Download `rbxsync.exe`** from the [Latest Release](https://github.com/Mailo037/rbxsync/releases/latest/download/rbxsync.exe).
2. **Run `rbxsync.exe`**. On its first launch, it automatically registers itself to your Windows User PATH!
3. Open any terminal (Command Prompt or PowerShell) and simply type:
   ```bash
   rbxsync
   ```

---

## 🌟 Key Features

* **Terminal User Interface (TUI)**: Full interactive terminal interface built with Textual, complete with form inputs, live statistics, real-time logging screen, and session controls.
* **Encrypted Credential Storage**: Protects your Roblox API Key, User/Group IDs, and upload preferences on disk using Windows DPAPI (`%APPDATA%\easy-asset-upload\settings.enc`).
* **Automatic PATH Integration**: Standalone `rbxsync.exe` automatically registers itself into your Windows system PATH on first execution so the `rbxsync` command works everywhere.
* **Batch Upload Limits (`--max-uploads`)**: Set a custom maximum upload limit per run (e.g. 200) and automatically pause cleanly.
* **Session Resume (`--resume`)**: Unfinished or paused runs are saved to `%APPDATA%\easy-asset-upload\run_sessions.json`. On startup, RBXSync prompts to resume from the last processed asset index.
* **Smart Transparency Preprocessing (Pixelfix)**: Dynamic alpha channel detection preprocesses transparent PNGs to prevent pixel bleeding.
* **EXIF & PNG Metadata Extraction**: Automatically populates asset descriptions using embedded file comments.
* **File Deduplication**: Hashes files with SHA-256 and tracks history to prevent duplicate uploads.

---

## 💻 CLI Usage

If you prefer command-line batch runs without the TUI interface:

```bash
# Upload assets from a folder with a 200 upload limit
rbxsync-cli --user-id 12345678 --max-uploads 200 ./my_assets

# Resume an unfinished session
rbxsync-cli --resume

# View help and version
rbxsync -help
rbxsync -version
```

---

## 🛠️ Installation from Source

```bash
git clone https://github.com/Mailo037/rbxsync.git
cd rbxsync
pip install -e .
```

---

## 🧪 Testing

Run the automated unittest suite:
```bash
python -m unittest discover tests
```