#!/usr/bin/env python3
"""
Roblox Asset Uploader - ASSET_CORE Terminal TUI v3.0
Modern Terminal User Interface (TUI) powered by Textual.
"""

import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict

from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Grid
from textual.widgets import (
    Header, Footer, Button, Input, Select, Switch, Label, Static, ProgressBar, RichLog
)
from textual.screen import ModalScreen

from uploader import (
    process_and_upload,
    collect_images,
    load_manifest,
    get_latest_unfinished_session,
    create_run_session,
    update_run_session,
    check_and_auto_update,
    ensure_executable_in_path,
    load_encrypted_settings,
    save_encrypted_settings,
    APP_DATA_DIR,
    HAS_PILLOW,
    RATE_LIMIT_DELAY
)

PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()


class ResumeSessionModal(ModalScreen[bool]):
    """Modal dialog asking user if they want to resume an unfinished upload session."""

    def __init__(self, session_data: Dict):
        super().__init__()
        self.session_data = session_data

    def compose(self) -> ComposeResult:
        run_id = self.session_data.get("run_id", "Unknown")
        target = self.session_data.get("target_path", "Unknown")
        last_idx = self.session_data.get("last_index", 1)
        total = self.session_data.get("total_queued", 0)
        uploaded = self.session_data.get("uploaded_count", 0)

        with Container(id="resume_modal_dialog"):
            yield Label("⚠️ Unfinished Upload Run Detected!", id="modal_title")
            yield Static(
                f"[b]Run ID:[/b] {run_id}\n"
                f"[b]Target Path:[/b] {target}\n"
                f"[b]Progress:[/b] Index {last_idx} / {total} (Uploaded: {uploaded})\n\n"
                f"Would you like to resume this run where you left off?",
                id="modal_text"
            )
            with Horizontal(id="modal_buttons"):
                yield Button("Resume Run", variant="success", id="btn_resume")
                yield Button("Start New Run", variant="error", id="btn_new")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_resume":
            self.dismiss(True)
        else:
            self.dismiss(False)


class AssetUploaderApp(App):
    """RBXSync Terminal TUI Application."""

    TITLE = "RBXSync Terminal TUI"
    SUB_TITLE = "Roblox Creator Store Batch Asset Synchronizer"
    CSS = """
    Screen {
        background: $surface-darken-3;
    }

    #main_layout {
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr 1fr;
        height: 1fr;
        margin: 1;
    }

    #config_panel {
        background: $panel;
        border: solid $primary-background;
        padding: 1 2;
        height: 100%;
        overflow-y: auto;
    }

    #right_panel {
        layout: vertical;
        height: 100%;
        margin-left: 1;
    }

    #stats_panel {
        background: $panel;
        border: solid $primary;
        padding: 1;
        height: auto;
        margin-bottom: 1;
    }

    #log_panel {
        background: $surface;
        border: solid $accent;
        height: 1fr;
    }

    .form_label {
        color: $text-muted;
        text-style: bold;
        margin-bottom: 0;
        margin-top: 1;
    }

    Input {
        margin-bottom: 1;
    }

    Select {
        margin-bottom: 1;
    }

    Switch {
        margin-right: 2;
    }

    .switch_container {
        height: auto;
        align: left middle;
        margin-bottom: 1;
    }

    #btn_start {
        width: 100%;
        margin-top: 1;
    }

    #btn_stop {
        width: 100%;
        margin-top: 1;
    }

    #resume_modal_dialog {
        padding: 2 4;
        background: $panel;
        border: thick $accent;
        width: 60;
        height: auto;
        align: center middle;
    }

    #modal_title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #modal_text {
        margin-bottom: 2;
    }

    #modal_buttons {
        align: center middle;
        height: auto;
    }

    #modal_buttons Button {
        margin: 0 1;
    }

    ProgressBar {
        margin: 1 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.upload_thread: Optional[threading.Thread] = None
        self.stop_requested = False
        self.active_run_id: Optional[str] = None
        self.resumed_session: Optional[Dict] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="main_layout"):
            # Left Panel: Configuration Form
            with Container(id="config_panel"):
                yield Label("🔑 Roblox API Key", classes="form_label")
                yield Input(
                    placeholder="Enter Roblox API Key",
                    password=True,
                    value=os.getenv("ROBLOX_API_KEY", ""),
                    id="input_api_key"
                )

                yield Label("👤 Creator Type & ID", classes="form_label")
                yield Select(
                    [("User ID", "user"), ("Group ID", "group")],
                    value="user" if os.getenv("USER_ID") or not os.getenv("GROUP_ID") else "group",
                    id="select_creator_type"
                )
                yield Input(
                    placeholder="Enter User or Group ID",
                    value=os.getenv("USER_ID") or os.getenv("GROUP_ID", ""),
                    id="input_creator_id"
                )

                yield Label("📦 Asset Type", classes="form_label")
                yield Select(
                    [
                        ("Decal", "Decal"),
                        ("Image", "Image"),
                        ("Audio", "Audio"),
                        ("Model", "Model"),
                        ("Video", "Video"),
                    ],
                    value="Decal",
                    id="select_asset_type"
                )

                yield Label("📁 Target File or Folder", classes="form_label")
                yield Input(
                    placeholder="Path to asset file or folder",
                    value="watch_dir",
                    id="input_target_path"
                )

                yield Label("🛑 Max Upload Limit (0 = Unlimited, e.g. 200)", classes="form_label")
                yield Input(
                    placeholder="Max uploads (e.g. 200)",
                    value="200",
                    id="input_max_uploads"
                )

                yield Label("⚙️ Options", classes="form_label")
                with Horizontal(classes="switch_container"):
                    yield Switch(value=False, id="switch_dry_run")
                    yield Label(" Dry Run (Test without uploading)")

                with Horizontal(classes="switch_container"):
                    yield Switch(value=False, id="switch_no_pixelfix")
                    yield Label(" Disable Pixelfix")

                with Horizontal(classes="switch_container"):
                    yield Switch(value=False, id="switch_no_dedup")
                    yield Label(" Disable Deduplication")

                with Horizontal(classes="switch_container"):
                    yield Switch(value=False, id="switch_distribute")
                    yield Label(" Distribute to Creator Store (Free)")

                yield Button("🚀 INITIATE UPLOAD RUN", variant="primary", id="btn_start")
                yield Button("⏸️ PAUSE / STOP RUN", variant="error", id="btn_stop", disabled=True)

            # Right Panel: Statistics & Live Log
            with Vertical(id="right_panel"):
                with Container(id="stats_panel"):
                    yield Static("[b]Status:[/b] Ready", id="stat_status")
                    yield Static("[b]Queue Progress:[/b] 0 / 0", id="stat_queue")
                    yield Static("[b]Uploaded:[/b] 0 | [b]Failed:[/b] 0 | [b]Limit:[/b] 200", id="stat_counts")
                    yield ProgressBar(total=100, show_percentage=True, id="progress_bar")

                with Container(id="log_panel"):
                    yield RichLog(highlight=True, markup=True, id="console_log")

        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#console_log", RichLog)
        log.write("[bold cyan]====================================================[/bold cyan]")
        log.write("[bold cyan] ASSET_CORE TERMINAL TUI v3.0 INITIALIZED [/bold cyan]")
        log.write("[bold cyan]====================================================[/bold cyan]")
        log.write(f"AppData Directory: [green]{APP_DATA_DIR}[/green]")
        log.write(f"Metadata Extraction: [green]AVAILABLE[/green]" if HAS_PILLOW else "Metadata Extraction: [yellow]OFF (Install Pillow)[/yellow]")
        log.write("[green]Encrypted Settings Loaded (%APPDATA%\\settings.enc)[/green]")

        # Populate form fields with encrypted settings if available
        saved = load_encrypted_settings()
        if saved.get("roblox_api_key"):
            self.query_one("#input_api_key", Input).value = saved["roblox_api_key"]
        if saved.get("creator_id"):
            self.query_one("#input_creator_id", Input).value = saved["creator_id"]
        if saved.get("creator_type"):
            self.query_one("#select_creator_type", Select).value = saved["creator_type"]
        if saved.get("asset_type"):
            self.query_one("#select_asset_type", Select).value = saved["asset_type"]
        if saved.get("max_uploads") is not None:
            self.query_one("#input_max_uploads", Input).value = str(saved["max_uploads"])

        # Check for unfinished sessions to prompt resume
        unfinished = get_latest_unfinished_session()
        if unfinished:
            self.resumed_session = unfinished
            self.push_screen(ResumeSessionModal(unfinished), self.handle_resume_choice)

    def handle_resume_choice(self, resume: bool) -> None:
        log = self.query_one("#console_log", RichLog)
        if resume and self.resumed_session:
            s = self.resumed_session
            log.write(f"[bold yellow]▶ Resuming previous run '{s['run_id']}' from index {s['last_index']}...[/bold yellow]")
            if s.get("target_path"):
                self.query_one("#input_target_path", Input).value = s["target_path"]
            if s.get("asset_type"):
                self.query_one("#select_asset_type", Select).value = s["asset_type"]
            if s.get("creator_type"):
                self.query_one("#select_creator_type", Select).value = s["creator_type"]
            if s.get("creator_id"):
                self.query_one("#input_creator_id", Input).value = s["creator_id"]
            if s.get("max_uploads") is not None:
                self.query_one("#input_max_uploads", Input).value = str(s["max_uploads"])
            
            # Auto start resumed run
            self.start_upload_process(resume_index=s.get("last_index", 1))
        else:
            log.write("[info]Starting fresh session.[/info]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_start":
            self.start_upload_process()
        elif event.button.id == "btn_stop":
            self.stop_upload_process()

    def start_upload_process(self, resume_index: int = 1) -> None:
        api_key = self.query_one("#input_api_key", Input).value.strip()
        creator_type = str(self.query_one("#select_creator_type", Select).value)
        creator_id = self.query_one("#input_creator_id", Input).value.strip()
        asset_type = str(self.query_one("#select_asset_type", Select).value)
        target_path_str = self.query_one("#input_target_path", Input).value.strip()
        max_uploads_str = self.query_one("#input_max_uploads", Input).value.strip()

        dry_run = self.query_one("#switch_dry_run", Switch).value
        no_pixelfix = self.query_one("#switch_no_pixelfix", Switch).value
        no_dedup = self.query_one("#switch_no_dedup", Switch).value
        distribute = self.query_one("#switch_distribute", Switch).value

        log = self.query_one("#console_log", RichLog)

        if not api_key:
            log.write("[bold red][ERROR] Roblox API Key is required![/bold red]")
            return
        if not creator_id:
            log.write("[bold red][ERROR] Creator ID is required![/bold red]")
            return
        if not target_path_str:
            log.write("[bold red][ERROR] Target file or directory path is required![/bold red]")
            return

        try:
            max_uploads = int(max_uploads_str) if max_uploads_str and int(max_uploads_str) > 0 else None
        except ValueError:
            log.write("[bold red][ERROR] Max uploads must be an integer (e.g. 200)[/bold red]")
            return

        # Save settings encrypted
        save_encrypted_settings({
            "roblox_api_key": api_key,
            "creator_type": creator_type,
            "creator_id": creator_id,
            "asset_type": asset_type,
            "max_uploads": max_uploads,
            "dry_run": dry_run,
            "no_pixelfix": no_pixelfix,
            "no_dedup": no_dedup,
            "distribute": distribute,
        })

        target_path = Path(target_path_str)
        if not target_path.exists():
            log.write(f"[bold red][ERROR] Path does not exist: {target_path_str}[/bold red]")
            return

        self.query_one("#btn_start", Button).disabled = True
        self.query_one("#btn_stop", Button).disabled = False
        self.stop_requested = False

        self.upload_thread = threading.Thread(
            target=self.run_upload_worker,
            args=(
                api_key, creator_type, creator_id, asset_type, target_path,
                max_uploads, dry_run, no_pixelfix, no_dedup, distribute, resume_index
            ),
            daemon=True
        )
        self.upload_thread.start()

    def stop_upload_process(self) -> None:
        log = self.query_one("#console_log", RichLog)
        log.write("[yellow][INFO] Stop / Pause requested. Finishing current item...[/yellow]")
        self.stop_requested = True
        self.query_one("#btn_stop", Button).disabled = True

    def run_upload_worker(
        self,
        api_key: str,
        creator_type: str,
        creator_id: str,
        asset_type: str,
        target_path: Path,
        max_uploads: Optional[int],
        dry_run: bool,
        no_pixelfix: bool,
        no_dedup: bool,
        distribute: bool,
        start_index: int
    ) -> None:
        log = self.query_one("#console_log", RichLog)
        progress_bar = self.query_one("#progress_bar", ProgressBar)

        if target_path.is_file() and target_path.suffix.lower() == ".json":
            entries = load_manifest(target_path)
            tasks = [{"path": Path(e["file"]), "name": e.get("name"), "description": e.get("description", "")} for e in entries]
        else:
            images = collect_images([str(target_path)])
            tasks = [{"path": img, "name": None, "description": "Uploaded by ASSET_CORE"} for img in images]

        total_queued = len(tasks)
        if total_queued == 0:
            self.call_from_thread(log.write, "[bold red][ERROR] No supported asset files found![/bold red]")
            self.call_from_thread(self.finish_upload_worker, "FAILED")
            return

        run_id = create_run_session(
            target_path=str(target_path),
            asset_type=asset_type,
            creator_type=creator_type,
            creator_id=creator_id,
            max_uploads=max_uploads,
            total_queued=total_queued,
            start_index=start_index
        )
        self.active_run_id = run_id

        self.call_from_thread(log.write, f"[bold green]Session Started: {run_id}[/bold green]")
        self.call_from_thread(log.write, f"Queued {total_queued} asset(s) | Limit: {max_uploads or 'Unlimited'}")

        self.call_from_thread(progress_bar.update, total=total_queued, progress=start_index - 1)

        uploaded_count = 0
        failed_count = 0
        consecutive_errors = 0
        current_index = start_index

        for i, task in enumerate(tasks, 1):
            if i < start_index:
                continue

            if self.stop_requested:
                self.call_from_thread(log.write, "[yellow][PAUSED] Upload run manually paused by user.[/yellow]")
                break

            if max_uploads and uploaded_count >= max_uploads:
                self.call_from_thread(
                    log.write,
                    f"[bold green]🛑 UPLOAD LIMIT REACHED ({uploaded_count}/{max_uploads} uploaded). Halting run.[/bold green]"
                )
                break

            current_index = i
            img_path = task["path"]
            filename = img_path.name

            self.call_from_thread(
                self.query_one("#stat_status", Static).update,
                f"[b]Status:[/b] Uploading [{i}/{total_queued}] {filename}"
            )
            self.call_from_thread(
                self.query_one("#stat_queue", Static).update,
                f"[b]Queue Progress:[/b] {i} / {total_queued}"
            )
            self.call_from_thread(progress_bar.update, progress=i)

            self.call_from_thread(log.write, f"[{i}/{total_queued}] Processing '{filename}'...")

            try:
                record = process_and_upload(
                    image_path=img_path,
                    api_key=api_key,
                    creator_type=creator_type,
                    creator_id=creator_id,
                    display_name=task["name"],
                    description=task["description"],
                    skip_pixelfix=no_pixelfix,
                    skip_dedup=no_dedup,
                    distribute=distribute,
                    dry_run=dry_run,
                    asset_type=asset_type
                )
                if record:
                    uploaded_count += 1
                    asset_id = record.get("assetId", "DryRun" if dry_run else "Unknown")
                    self.call_from_thread(log.write, f"  [green]✔ Success -> Asset ID: {asset_id}[/green]")
                consecutive_errors = 0
            except Exception as e:
                failed_count += 1
                consecutive_errors += 1
                self.call_from_thread(log.write, f"  [bold red]✘ Failed -> {e}[/bold red]")

                if consecutive_errors >= 3:
                    self.call_from_thread(
                        log.write,
                        "[bold red][CRITICAL] 3 consecutive failures detected. Auto-pausing session to save progress.[/bold red]"
                    )
                    break

            self.call_from_thread(
                self.query_one("#stat_counts", Static).update,
                f"[b]Uploaded:[/b] {uploaded_count} | [b]Failed:[/b] {failed_count} | [b]Limit:[/b] {max_uploads or 'Unlimited'}"
            )

            update_run_session(run_id, current_index, uploaded_count, failed_count, "RUNNING")

            if i < total_queued and (not max_uploads or uploaded_count < max_uploads) and not self.stop_requested:
                time.sleep(RATE_LIMIT_DELAY)

        final_status = "COMPLETED" if (current_index >= total_queued and not self.stop_requested and consecutive_errors < 3) else "PAUSED"
        update_run_session(run_id, current_index, uploaded_count, failed_count, final_status)

        self.call_from_thread(self.finish_upload_worker, final_status)

    def finish_upload_worker(self, final_status: str) -> None:
        log = self.query_one("#console_log", RichLog)
        log.write(f"[bold cyan]====================================================[/bold cyan]")
        log.write(f"[bold cyan] RUN FINISHED - STATUS: {final_status} [/bold cyan]")
        log.write(f"[bold cyan]====================================================[/bold cyan]")

        self.query_one("#stat_status", Static).update(f"[b]Status:[/b] {final_status}")
        self.query_one("#btn_start", Button).disabled = False
        self.query_one("#btn_stop", Button).disabled = True


VERSION = "3.0.0"

def main():
    ensure_executable_in_path()
    check_and_auto_update()

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("-v", "--version", "-version"):
            print(f"ASSET_CORE Terminal TUI v{VERSION}")
            sys.exit(0)
        elif arg in ("-h", "--help", "-help"):
            print(f"""
RBXSync Terminal TUI v{VERSION}
Roblox Creator Store Batch Asset Synchronizer

Usage:
  rbxsync                  Launch the interactive Textual TUI
  rbxsync -help            Display this help information
  rbxsync -version         Display version information

CLI Batch Commands:
  rbxsync-cli --user-id <ID> --max-uploads <LIMIT> <PATH>
  rbxsync-cli --resume
""")
            sys.exit(0)

    app = AssetUploaderApp()
    app.run()


if __name__ == "__main__":
    main()
