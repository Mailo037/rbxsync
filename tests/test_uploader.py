#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Roblox Asset Uploader & TUI
Run with: python -m unittest discover tests
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import uploader
import tui


class TestUploaderCore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_dir_path = Path(self.test_dir)
        
        # Override history and session files for isolated testing
        self.orig_history = uploader.HISTORY_FILE
        self.orig_sessions = uploader.RUN_SESSIONS_FILE
        
        uploader.HISTORY_FILE = self.test_dir_path / "test_history.json"
        uploader.RUN_SESSIONS_FILE = self.test_dir_path / "test_sessions.json"

        # Create dummy image asset file
        self.dummy_asset = self.test_dir_path / "test_icon.png"
        self.dummy_asset.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")

    def tearDown(self):
        uploader.HISTORY_FILE = self.orig_history
        uploader.RUN_SESSIONS_FILE = self.orig_sessions
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_app_data_dir_resolution(self):
        app_data = uploader.get_app_data_dir()
        self.assertTrue(app_data.exists())
        self.assertTrue(app_data.is_dir())

    def test_check_and_auto_update(self):
        # Verify check_and_auto_update executes safely without throwing errors
        updated = uploader.check_and_auto_update(force=False)
        self.assertIsInstance(updated, bool)

    def test_encrypted_settings(self):
        orig_settings = uploader.SETTINGS_FILE
        uploader.SETTINGS_FILE = self.test_dir_path / "test_settings.enc"
        try:
            sample_settings = {
                "roblox_api_key": "secret_api_key_abc123",
                "creator_type": "user",
                "creator_id": "998877",
                "asset_type": "Decal",
                "target_path": "my_assets_folder",
                "start_index": 5,
                "max_uploads": 150,
                "dry_run": True,
                "no_pixelfix": True,
                "no_dedup": False,
                "distribute": True,
            }
            uploader.save_encrypted_settings(sample_settings)
            
            # Verify file exists on disk and is encrypted (does not contain plaintext API key)
            raw_bytes = uploader.SETTINGS_FILE.read_bytes()
            self.assertNotIn(b"secret_api_key_abc123", raw_bytes)
            
            # Verify decrypt matches original settings
            loaded = uploader.load_encrypted_settings()
            self.assertEqual(loaded.get("roblox_api_key"), "secret_api_key_abc123")
            self.assertEqual(loaded.get("target_path"), "my_assets_folder")
            self.assertEqual(loaded.get("start_index"), 5)
            self.assertEqual(loaded.get("max_uploads"), 150)
            self.assertTrue(loaded.get("dry_run"))
            self.assertTrue(loaded.get("no_pixelfix"))
            self.assertFalse(loaded.get("no_dedup"))
            self.assertTrue(loaded.get("distribute"))
        finally:
            uploader.SETTINGS_FILE = orig_settings

    def test_file_hash(self):
        h1 = uploader.file_hash(self.dummy_asset)
        self.assertIsInstance(h1, str)
        self.assertEqual(len(h1), 64)  # SHA-256 hex string

    def test_history_load_and_save(self):
        history = uploader.load_history()
        self.assertEqual(history, {})

        test_data = {"hash123": {"assetId": "9999", "name": "Test"}}
        uploader.save_history(test_data)
        
        loaded = uploader.load_history()
        self.assertEqual(loaded, test_data)

    def test_run_session_lifecycle(self):
        # 1. Create run session
        run_id = uploader.create_run_session(
            target_path=str(self.dummy_asset),
            asset_type="Decal",
            creator_type="user",
            creator_id="12345",
            max_uploads=200,
            total_queued=10,
            start_index=1
        )
        self.assertTrue(run_id.startswith("run_"))

        # 2. Verify active session can be retrieved
        session = uploader.get_latest_unfinished_session()
        self.assertIsNotNone(session)
        self.assertEqual(session["run_id"], run_id)
        self.assertEqual(session["status"], "RUNNING")

        # 3. Update run session
        uploader.update_run_session(run_id, last_index=5, uploaded_count=4, failed_count=0, status="PAUSED")
        
        updated = uploader.get_latest_unfinished_session()
        self.assertEqual(updated["last_index"], 5)
        self.assertEqual(updated["uploaded_count"], 4)
        self.assertEqual(updated["status"], "PAUSED")

        # 4. Complete session
        uploader.update_run_session(run_id, last_index=10, uploaded_count=10, failed_count=0, status="COMPLETED")
        completed_check = uploader.get_latest_unfinished_session()
        self.assertIsNone(completed_check)

    def test_process_and_upload_dry_run(self):
        record = uploader.process_and_upload(
            image_path=self.dummy_asset,
            api_key="test_key",
            creator_type="user",
            creator_id="12345",
            display_name="Test Asset",
            description="Test Description",
            skip_pixelfix=True,
            skip_dedup=True,
            distribute=False,
            dry_run=True,
            asset_type="Decal"
        )
        self.assertIsNotNone(record)
        self.assertTrue(record.get("dryRun"))
        self.assertEqual(record.get("name"), "Test Asset")

    def test_cli_parser_flags(self):
        parser = uploader.build_parser()
        
        # Test default parsing
        args = parser.parse_args(["--key", "mykey", "--user-id", "123", "--max-uploads", "50", "--resume", "file.png"])
        self.assertEqual(args.key, "mykey")
        self.assertEqual(args.user_id, "123")
        self.assertEqual(args.max_uploads, 50)
        self.assertTrue(args.resume)
        self.assertEqual(args.input, ["file.png"])

    def test_pixelfix_cleanup(self):
        # Create a mock pixelfix_out file
        pixelfix_dir = self.dummy_asset.parent / "pixelfix_out"
        pixelfix_dir.mkdir(parents=True, exist_ok=True)
        pixelfix_file = pixelfix_dir / self.dummy_asset.name
        pixelfix_file.write_bytes(b"dummy pixelfix content")

        with patch("uploader.run_pixelfix", return_value=pixelfix_file):
            record = uploader.process_and_upload(
                image_path=self.dummy_asset,
                api_key="test_key",
                creator_type="user",
                creator_id="12345",
                display_name="Clean Test",
                description="Test",
                skip_pixelfix=False,
                skip_dedup=True,
                distribute=False,
                dry_run=True,
                asset_type="Decal"
            )
            self.assertIsNotNone(record)
            # Verify the pixelfix_out temp file was cleaned up automatically
            self.assertFalse(pixelfix_file.exists())
            self.assertFalse(pixelfix_dir.exists())


class TestTUICore(unittest.TestCase):
    def test_tui_app_css_validation(self):
        css = tui.AssetUploaderApp.CSS
        self.assertIn(".switch_container", css)
        self.assertIn("align: left middle;", css)

    def test_tui_version_flag(self):
        with patch.object(sys, "argv", ["easy-upload", "-version"]):
            with patch("builtins.print") as mock_print:
                with self.assertRaises(SystemExit) as cm:
                    tui.main()
                self.assertEqual(cm.exception.code, 0)
                mock_print.assert_called_with(f"ASSET_CORE Terminal TUI v{tui.VERSION}")

    def test_tui_help_flag(self):
        with patch.object(sys, "argv", ["easy-upload", "-help"]):
            with patch("builtins.print") as mock_print:
                with self.assertRaises(SystemExit) as cm:
                    tui.main()
                self.assertEqual(cm.exception.code, 0)

    def test_copy_text_to_clipboard(self):
        # Verify copy_text_to_clipboard runs without exception
        res = tui.copy_text_to_clipboard("12345678")
        self.assertIsInstance(res, bool)

    def test_upload_history_modal_instantiation(self):
        modal = tui.UploadHistoryModal()
        self.assertIsNotNone(modal)
        self.assertIsInstance(modal.history_data, dict)


if __name__ == "__main__":
    unittest.main()
