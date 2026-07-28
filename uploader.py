#!/usr/bin/env python3
import os
import sys
import json
import time
import hashlib
import platform
import subprocess
import argparse
import urllib.request
import urllib.error
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Set
import mimetypes
from dotenv import load_dotenv

def get_app_data_dir() -> Path:
    if platform.system() == "Windows":
        app_data = Path(os.environ.get("APPDATA", Path.home())) / "easy-asset-upload"
    else:
        app_data = Path.home() / ".config" / "easy-asset-upload"
    app_data.mkdir(parents=True, exist_ok=True)
    return app_data

APP_DATA_DIR = get_app_data_dir()
PROJECT_ROOT = Path(__file__).parent

def ensure_executable_in_path():
    """Ensures executable / scripts folder is in Windows User PATH automatically."""
    if platform.system() != "Windows":
        return
    try:
        import winreg
        exe_dir = str(Path(sys.executable).parent.resolve())
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS)
        user_path, path_type = winreg.QueryValueEx(key, "Path")
        if exe_dir.lower() not in user_path.lower():
            new_path = user_path + ";" + exe_dir
            winreg.SetValueEx(key, "Path", 0, path_type, new_path)
            print(f"[PATH] Added '{exe_dir}' to User PATH! You can now run 'rbxsync' from any command prompt.")
        winreg.CloseKey(key)
    except Exception:
        pass

# Load dotenv from AppData, project root, and CWD
load_dotenv(APP_DATA_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

# -- Optional rich output ------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markup import escape
    from rich import print as rprint
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    def escape(text): return str(text)
    class Console:
        def print(self, *a, **kw): print(*a)
        def log(self, *a, **kw): print("[LOG]", *a)
    console = Console()
    def rprint(*a, **kw): print(*a)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request as urlreq

# -- Optional Pillow for Metadata Extraction & Transparency Check ----------------
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# Migrate legacy project-root files to AppData
def migrate_legacy_data():
    legacy_files = {
        PROJECT_ROOT / "upload_history.json": APP_DATA_DIR / "upload_history.json",
        PROJECT_ROOT / "run_sessions.json": APP_DATA_DIR / "run_sessions.json",
        PROJECT_ROOT / ".env": APP_DATA_DIR / ".env",
    }
    for src, dst in legacy_files.items():
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass

    legacy_pixelfix = PROJECT_ROOT / "tools" / "pixelfix-win-x64.exe"
    dst_pixelfix = APP_DATA_DIR / "tools" / "pixelfix-win-x64.exe"
    if legacy_pixelfix.exists() and not dst_pixelfix.exists():
        try:
            dst_pixelfix.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_pixelfix, dst_pixelfix)
        except Exception:
            pass

migrate_legacy_data()

# -- Constants -----------------------------------------------------------------
PIXELFIX_URL = "https://github.com/Corecii/Transparent-Pixel-Fix/releases/download/1.0.0/pixelfix-win-x64.exe"
PIXELFIX_BIN = APP_DATA_DIR / "tools" / "pixelfix-win-x64.exe"
ROBLOX_ASSETS_API = "https://apis.roblox.com/assets/v1/assets"
ROBLOX_OPS_API    = "https://apis.roblox.com/assets/v1/operations/{op_id}"
HISTORY_FILE      = APP_DATA_DIR / "upload_history.json"
RUN_SESSIONS_FILE = APP_DATA_DIR / "run_sessions.json"
UPDATE_CHECK_FILE = APP_DATA_DIR / "update_check.json"
SETTINGS_FILE     = APP_DATA_DIR / "settings.enc"
SUPPORTED_EXT     = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".mp3", ".ogg", ".wav", ".fbx", ".obj"}
RATE_LIMIT_DELAY  = 1.2   # seconds between uploads (stay under Roblox limits)
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL     = 2.0   # seconds between operation polls
PIXELFIX_TIMEOUT  = 15.0  # seconds before abandoning pixelfix on a single file

# -- Encrypted Settings Storage (Windows DPAPI / Machine Key) -------------------
if platform.system() == "Windows":
    import ctypes
    import ctypes.wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def _encrypt_bytes(data: bytes) -> bytes:
        in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob), "EasyAssetSettings", None, None, None, 0, ctypes.byref(out_blob)):
            buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return buf
        raise RuntimeError("Windows DPAPI encryption failed")

    def _decrypt_bytes(data: bytes) -> bytes:
        in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return buf
        raise RuntimeError("Windows DPAPI decryption failed")
else:
    def _get_key_bytes() -> bytes:
        key_file = APP_DATA_DIR / ".key"
        if not key_file.exists():
            key_file.write_bytes(os.urandom(32))
        return key_file.read_bytes()

    def _encrypt_bytes(data: bytes) -> bytes:
        key = _get_key_bytes()
        return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])

    def _decrypt_bytes(data: bytes) -> bytes:
        return _encrypt_bytes(data)

def load_encrypted_settings() -> Dict:
    if not SETTINGS_FILE.exists():
        env_key = os.getenv("ROBLOX_API_KEY", "")
        env_user = os.getenv("USER_ID", "")
        env_group = os.getenv("GROUP_ID", "")
        return {
            "roblox_api_key": env_key,
            "user_id": env_user,
            "group_id": env_group,
            "creator_type": "user" if env_user or not env_group else "group",
            "creator_id": env_user or env_group,
            "asset_type": "Decal",
            "target_path": "watch_dir",
            "start_index": 1,
            "max_uploads": 200,
            "dry_run": False,
            "no_pixelfix": False,
            "no_dedup": False,
            "distribute": False,
        }
    try:
        raw_enc = SETTINGS_FILE.read_bytes()
        raw_dec = _decrypt_bytes(raw_enc)
        return json.loads(raw_dec.decode("utf-8"))
    except Exception:
        return {}

def save_encrypted_settings(settings: Dict):
    try:
        raw_json = json.dumps(settings, indent=2).encode("utf-8")
        raw_enc = _encrypt_bytes(raw_json)
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_bytes(raw_enc)
    except Exception as e:
        print(f"[WARN] Failed to save encrypted settings: {e}")

def get_setting(key: str, default=None):
    s = load_encrypted_settings()
    return s.get(key, default)

def set_setting(key: str, value):
    s = load_encrypted_settings()
    s[key] = value
    save_encrypted_settings(s)

# -- Auto Updater ---------------------------------------------------------------
def check_and_auto_update(force: bool = False) -> bool:
    """
    Periodically checks if a newer version is available from git origin and auto-updates.
    Rate limited to once every 3 hours unless force=True.
    """
    now = time.time()
    interval = 10800  # 3 hours

    if not force and UPDATE_CHECK_FILE.exists():
        try:
            with open(UPDATE_CHECK_FILE, "r") as f:
                data = json.load(f)
                if now - data.get("last_check", 0) < interval:
                    return False
        except Exception:
            pass

    try:
        UPDATE_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(UPDATE_CHECK_FILE, "w") as f:
            json.dump({"last_check": now}, f)
    except Exception:
        pass

    git_dir = PROJECT_ROOT / ".git"
    if not git_dir.exists():
        return False

    try:
        res = subprocess.run(
            ["git", "fetch"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=8
        )
        if res.returncode != 0:
            return False

        local_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        ).stdout.strip()

        remote_commit = subprocess.run(
            ["git", "rev-parse", "@{u}"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        ).stdout.strip()

        if local_commit and remote_commit and local_commit != remote_commit:
            print("\n[AUTO-UPDATE] 🚀 New version detected! Performing automatic update...")
            pull_res = subprocess.run(
                ["git", "pull"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=15
            )
            if pull_res.returncode == 0:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", "."],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True
                )
                print("[AUTO-UPDATE] ✔ Successfully updated to the latest version!\n")
                return True
            else:
                print(f"[AUTO-UPDATE] [WARN] Update pull failed: {pull_res.stderr.strip()}")
    except Exception:
        pass

    return False

# -- Run Session Logging --------------------------------------------------------
def load_run_sessions() -> Dict[str, Dict]:
    if RUN_SESSIONS_FILE.exists():
        try:
            with open(RUN_SESSIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_run_sessions(sessions: Dict[str, Dict]):
    RUN_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=2)

def create_run_session(
    target_path: str,
    asset_type: str,
    creator_type: str,
    creator_id: str,
    max_uploads: Optional[int],
    total_queued: int,
    start_index: int = 1
) -> str:
    sessions = load_run_sessions()
    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    session = {
        "run_id": run_id,
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_path": str(target_path),
        "asset_type": asset_type,
        "creator_type": creator_type,
        "creator_id": str(creator_id),
        "max_uploads": max_uploads,
        "total_queued": total_queued,
        "last_index": start_index,
        "uploaded_count": 0,
        "failed_count": 0,
        "status": "RUNNING",
    }
    sessions[run_id] = session
    save_run_sessions(sessions)
    return run_id

def update_run_session(
    run_id: str,
    last_index: int,
    uploaded_count: int,
    failed_count: int,
    status: str
):
    sessions = load_run_sessions()
    if run_id in sessions:
        session = sessions[run_id]
        session["updated_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        session["last_index"] = last_index
        session["uploaded_count"] = uploaded_count
        session["failed_count"] = failed_count
        session["status"] = status
        save_run_sessions(sessions)

def get_latest_unfinished_session() -> Optional[Dict]:
    sessions = load_run_sessions()
    unfinished = [
        s for s in sessions.values()
        if s.get("status") in ("PAUSED", "INTERRUPTED", "RUNNING")
        and s.get("last_index", 1) <= s.get("total_queued", 0)
    ]
    if not unfinished:
        return None
    # Return most recently updated unfinished run
    unfinished.sort(key=lambda x: x.get("updated_time", ""), reverse=True)
    return unfinished[0]

# -- History (deduplication) ---------------------------------------------------
def load_history() -> Dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}

def save_history(history: Dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# -- Image Analysis ------------------------------------------------------------
def get_image_comment(image_path: Path) -> Optional[str]:
    """Attempts to extract metadata comments or descriptions from the image."""
    if not HAS_PILLOW or image_path.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
        return None
        
    try:
        with Image.open(image_path) as img:
            if hasattr(img, 'text') and img.text:
                for key in ['Comment', 'Description', 'Title', 'UserComment']:
                    if key in img.text:
                        return str(img.text[key]).strip()
            
            if 'Comment' in img.info:
                return str(img.info['Comment']).strip()
            if 'Description' in img.info:
                return str(img.info['Description']).strip()

            exif = img.getexif()
            if exif:
                for tag_id in [37510, 270]:
                    val = exif.get(tag_id)
                    if val:
                        if isinstance(val, bytes):
                            val = val.decode('utf-8', errors='ignore')
                        val_str = str(val).replace('ASCII\x00\x00\x00', '').replace('\x00', '').strip()
                        if val_str:
                            return val_str
    except Exception as e:
        print(f"  [WARN] Could not read metadata from {image_path.name}: {e}")
        
    return None

def needs_pixelfix(image_path: Path) -> bool:
    """Checks if the image actually has transparent pixels to avoid useless processing."""
    if not HAS_PILLOW or image_path.suffix.lower() != '.png':
        # If we don't have pillow, assume it needs it to be safe
        return True 
        
    try:
        with Image.open(image_path) as img:
            # Check if it has an alpha channel or transparency info
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                if img.mode == 'RGBA':
                    extrema = img.getextrema()
                    # extrema for RGBA is ((Rmin, Rmax), (Gmin, Gmax), (Bmin, Bmax), (Amin, Amax))
                    if extrema[3][0] < 255: 
                        return True # Alpha channel has values below 255 (transparent pixels exist)
                elif img.mode == 'LA':
                    extrema = img.getextrema()
                    if extrema[1][0] < 255:
                        return True
                elif img.mode == 'P' and 'transparency' in img.info:
                    return True
            return False # No transparency found
    except Exception:
        # On error, default to true just in case
        return True

# -- Pixelfix ------------------------------------------------------------------
def download_pixelfix():
    """Download Pixelfix binary if not present (Windows only)."""
    if platform.system() != "Windows":
        return False
    if PIXELFIX_BIN.exists():
        return True
    
    print("Downloading Pixelfix...")
    PIXELFIX_BIN.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(PIXELFIX_URL, PIXELFIX_BIN)
        print("[OK] Pixelfix downloaded successfully.")
        return True
    except Exception as e:
        print(f"[ERROR] Could not download Pixelfix: {e}")
        return False

def run_pixelfix(image_path: Path, output_path: Optional[Path] = None) -> Path:
    if platform.system() != "Windows":
        print(f"  [SKIP] Pixelfix is Windows-only. Skipping for {image_path.name}")
        return image_path

    if not PIXELFIX_BIN.exists():
        if not download_pixelfix():
            print(f"  [WARN] Pixelfix unavailable. Uploading original.")
            return image_path

    # Smart Check: Does it even need Pixelfix?
    if not needs_pixelfix(image_path):
        print(f"  [SKIP] No transparent pixels detected in {image_path.name}. Skipping Pixelfix.")
        return image_path

    if output_path is None:
        output_path = image_path.parent / "pixelfix_out" / image_path.name
    
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(image_path, output_path)
    except Exception as e:
        print(f"  [ERROR] Could not copy file for Pixelfix: {e}")
        return image_path

    # Run Pixelfix with a timeout AND AUTOMATIC ENTER KEYPRESS (\n) so it NEVER hangs
    try:
        result = subprocess.run(
            [str(PIXELFIX_BIN), str(output_path)],
            input="\n",           # <--- Simulates "Press any key"
            capture_output=True, 
            text=True,
            timeout=PIXELFIX_TIMEOUT
        )
        
        if result.returncode != 0 or not output_path.exists():
            print(f"  [WARN] Pixelfix failed on {image_path.name}. Uploading original file instead.")
            if output_path.exists():
                output_path.unlink()
            return image_path

    except subprocess.TimeoutExpired:
        print(f"  [WARN] Pixelfix timed out after {PIXELFIX_TIMEOUT}s on {image_path.name}. Uploading original.")
        # Attempt to clean up the locked/corrupted copy
        try:
            if output_path.exists():
                output_path.unlink()
        except:
            pass
        return image_path

    return output_path

# -- Roblox API ----------------------------------------------------------------
def make_headers(api_key: str) -> Dict:
    return {"x-api-key": api_key}

def upload_asset(
    api_key: str,
    image_path: Path,
    display_name: str,
    description: str,
    creator_type: str,   # "user" or "group"
    creator_id: str,
    asset_type: str = "Decal",
) -> Dict:
    mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    
    if mime == "application/octet-stream" and image_path.suffix.lower() in {".fbx", ".obj"}:
        mime = "model/" + image_path.suffix.lower()[1:]

    request_body = {
        "assetType": asset_type,
        "displayName": display_name,
        "description": description,
        "creationContext": {
            "creator": {
                f"{creator_type}Id": str(creator_id)
            }
        }
    }

    if HAS_REQUESTS:
        with open(image_path, "rb") as f:
            resp = requests.post(
                ROBLOX_ASSETS_API,
                headers=make_headers(api_key),
                data={"request": json.dumps(request_body)},
                files={"fileContent": (image_path.name, f, mime)},
            )
        resp.raise_for_status()
        return resp.json()
    else:
        import io, email.generator
        boundary = "----RobloxUploaderBoundary"
        body_parts = []
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="request"\r\n'
            f"Content-Type: application/json\r\n\r\n"
            f"{json.dumps(request_body)}\r\n"
        )
        with open(image_path, "rb") as f:
            img_data = f.read()
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="fileContent"; filename="{image_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        )
        body_bytes = "".join(body_parts).encode() + img_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            ROBLOX_ASSETS_API,
            data=body_bytes,
            headers={
                "x-api-key": api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

def poll_operation(api_key: str, operation_path: str) -> Optional[Dict]:
    url = f"https://apis.roblox.com/assets/v1/{operation_path}"
    for attempt in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL)
        if HAS_REQUESTS:
            resp = requests.get(url, headers=make_headers(api_key))
            resp.raise_for_status()
            data = resp.json()
        else:
            req = urllib.request.Request(url, headers=make_headers(api_key))
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read())

        if data.get("done"):
            if "error" in data:
                raise RuntimeError(f"Operation failed: {data['error']}")
            return data.get("response", data)

    raise TimeoutError(f"Operation did not complete after {MAX_POLL_ATTEMPTS} attempts.")

def set_creator_store_free(api_key: str, asset_id: str):
    url = f"https://apis.roblox.com/assets/v1/assets/{asset_id}"
    payload = {"previews": []}
    if HAS_REQUESTS:
        resp = requests.patch(
            url,
            headers={**make_headers(api_key), "Content-Type": "application/json"},
            json=payload
        )
        if resp.status_code not in (200, 204):
            print(f"[INFO] Creator Store needs manual setup (HTTP {resp.status_code})")

# -- Manifest loading ----------------------------------------------------------
def load_manifest(manifest_path: Path) -> List[Dict]:
    with open(manifest_path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("assets", [])

# -- Core upload logic ---------------------------------------------------------
MAX_RETRIES = 5
RETRY_DELAY = 2.0  # seconds base retry delay

def process_and_upload(
    image_path: Path,
    api_key: str,
    creator_type: str,
    creator_id: str,
    display_name: Optional[str],
    description: str,
    skip_pixelfix: bool,
    skip_dedup: bool,
    distribute: bool,
    dry_run: bool,
    asset_type: str = "Decal",
    max_retries: int = MAX_RETRIES,
    retry_delay: float = RETRY_DELAY,
    log_callback: Optional[callable] = None,
) -> Optional[Dict]:

    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        elif RICH:
            try:
                console.print(msg)
            except Exception:
                try:
                    safe_msg = msg.encode("ascii", errors="ignore").decode("ascii")
                    print(safe_msg)
                except Exception:
                    pass
        else:
            try:
                print(msg)
            except Exception:
                try:
                    safe_msg = msg.encode("ascii", errors="ignore").decode("ascii")
                    print(safe_msg)
                except Exception:
                    pass

    history = load_history()

    if not skip_dedup:
        h = file_hash(image_path)
        if h in history:
            prev = history[h]
            _log(f"  [SKIP] {image_path.name} (already uploaded as assetId={prev['assetId']})")
            return prev

    name = display_name or image_path.stem.replace("_", " ").replace("-", " ").title()

    extracted_comment = get_image_comment(image_path)
    if extracted_comment:
        description = extracted_comment
        _log(f"  [INFO] Found metadata comment: '{description}'")

    processed = image_path
    if not skip_pixelfix and image_path.suffix.lower() == ".png":
        _log(f"  -> Processing image...")
        processed = run_pixelfix(image_path)

    try:
        if dry_run:
            _log(f"  [DRY RUN] Would upload '{name}' from {processed}")
            return {"dryRun": True, "file": str(image_path), "name": name}

        last_exception = None
        for attempt in range(1, max_retries + 1):
            try:
                _log(f"  -> Uploading '{name}' as {asset_type} (attempt {attempt}/{max_retries})...")
                op = upload_asset(api_key, processed, name, description, creator_type, creator_id, asset_type)

                op_path = op.get("path") or op.get("operationId")
                if op_path:
                    _log(f"  -> Polling operation...")
                    result = poll_operation(api_key, op_path)
                else:
                    result = op

                asset_id = (
                    result.get("assetId")
                    or result.get("assetVersionId") 
                    or result.get("id")
                )
                if not asset_id:
                    _log(f"  [WARN] No assetId in response")

                if distribute and asset_id:
                    _log("  -> Configuring Creator Store...")
                    set_creator_store_free(api_key, str(asset_id))

                record = {
                    "assetId": asset_id,
                    "name": name,
                    "file": str(image_path),
                    "uploadedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "fullResponse": result,
                }
                if not skip_dedup:
                    h = file_hash(image_path)
                    history[h] = record
                    save_history(history)

                _log(f"  [OK] Done -> assetId={asset_id}")
                return record

            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    delay = retry_delay * (1.5 ** (attempt - 1))
                    _log(f"  [bold yellow]⚠️ Network/HTTP error: {e}. Retrying item ({attempt}/{max_retries}) in {delay:.1f}s...[/bold yellow]")
                    time.sleep(delay)
                else:
                    _log(f"  [bold red]✘ All {max_retries} retry attempts failed for '{image_path.name}': {e}[/bold red]")
                    raise last_exception

    finally:
        if processed != image_path and processed.exists():
            try:
                processed.unlink()
                parent_dir = processed.parent
                if parent_dir.exists() and not any(parent_dir.iterdir()):
                    parent_dir.rmdir()
            except Exception:
                pass

# -- CLI -----------------------------------------------------------------------
VERSION = "3.1.0"

def build_parser() -> argparse.ArgumentParser:
    saved = load_encrypted_settings()
    p = argparse.ArgumentParser(
        prog="roblox_uploader",
        description="Upload assets to the Roblox Creator Store with Pixelfix preprocessing.",
    )
    p.add_argument("-v", "--version", "-version", action="version", version=f"%(prog)s v{VERSION}")
    
    auth = p.add_argument_group("Authentication")
    auth.add_argument("--key", metavar="API_KEY", default=os.environ.get("ROBLOX_API_KEY") or saved.get("roblox_api_key"))
    creator = auth.add_mutually_exclusive_group()
    creator.add_argument("--user-id", metavar="ID", default=os.environ.get("USER_ID") or (saved.get("creator_id") if saved.get("creator_type") == "user" else None))
    creator.add_argument("--group-id", metavar="ID", default=os.environ.get("GROUP_ID") or (saved.get("creator_id") if saved.get("creator_type") == "group" else None))

    inp = p.add_argument_group("Input")
    inp.add_argument("input", nargs="*")
    inp.add_argument("--manifest", metavar="FILE")

    meta = p.add_argument_group("Metadata")
    meta.add_argument("--asset-type", default=saved.get("asset_type", "Decal"))
    meta.add_argument("--name", metavar="NAME")
    meta.add_argument("--description", metavar="TEXT", default="Uploaded by roblox_uploader")

    beh = p.add_argument_group("Behaviour")
    beh.add_argument("--no-pixelfix", action="store_true")
    beh.add_argument("--no-dedup", action="store_true")
    beh.add_argument("--distribute", action="store_true")
    beh.add_argument("--dry-run", action="store_true")
    beh.add_argument("--delay", type=float, default=RATE_LIMIT_DELAY)
    beh.add_argument("--start-index", type=int, default=1, help="Start processing at this specific image index")
    beh.add_argument("--max-uploads", type=int, default=saved.get("max_uploads", 200), help="Maximum number of uploads per run (e.g. 200)")
    beh.add_argument("--resume", action="store_true", help="Resume from the latest unfinished session")

    out = p.add_argument_group("Output")
    out.add_argument("--results", metavar="FILE")

    return p

def collect_images(inputs: List[str]) -> List[Path]:
    images = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            for ext in SUPPORTED_EXT:
                images.extend(sorted(p.glob(f"**/*{ext}")))
                images.extend(sorted(p.glob(f"**/*{ext.upper()}")))
        elif p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
            images.append(p)
        else:
            print(f"[WARN] Skipping unsupported input: {inp}")
            
    seen = set()
    result = []
    for p in images:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            result.append(p)
    return result

def main():
    # Check for automatic updates
    check_and_auto_update()

    # Preprocess single-dash -help and -version flags for convenience
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.lower() in ("-help", "-h"):
            sys.argv[i] = "--help"
        elif arg.lower() in ("-version", "-v"):
            sys.argv[i] = "--version"

    parser = build_parser()
    args = parser.parse_args()

    if args.key:
        set_setting("roblox_api_key", args.key)
    if args.user_id:
        set_setting("creator_type", "user")
        set_setting("creator_id", args.user_id)
    elif args.group_id:
        set_setting("creator_type", "group")
        set_setting("creator_id", args.group_id)

    if args.resume:
        session = get_latest_unfinished_session()
        if session:
            print(f"[RESUME] Found unfinished run '{session['run_id']}' starting at index {session['last_index']}")
            args.start_index = session["last_index"]
            if not args.input and session.get("target_path"):
                args.input = [session["target_path"]]
            if session.get("asset_type"):
                args.asset_type = session["asset_type"]
            if session.get("max_uploads") and not args.max_uploads:
                args.max_uploads = session["max_uploads"]
            if session.get("creator_type") == "user" and not args.user_id:
                args.user_id = session.get("creator_id")
            elif session.get("creator_type") == "group" and not args.group_id:
                args.group_id = session.get("creator_id")

    if not args.key:
        parser.error("--key or ROBLOX_API_KEY env var required.")
    if not args.user_id and not args.group_id:
        parser.error("Either --user-id or --group-id is required.")
    if not args.input and not args.manifest:
        parser.error("Provide at least one input file/folder or --manifest.")

    creator_type = "user" if args.user_id else "group"
    creator_id   = args.user_id or args.group_id

    print("\n============================================================")
    print("ROBLOX CREATOR STORE UPLOADER")
    print("============================================================")
    print(f"Creator: {creator_type} {creator_id} | Type: {args.asset_type}")
    print(f"Pixelfix: {'OFF' if args.no_pixelfix else 'ON'} | Dry run: {'YES' if args.dry_run else 'NO'}")
    print(f"Metadata Extract: {'[ON]' if HAS_PILLOW else '[OFF] (pip install Pillow for metadata support)'}")
    if args.max_uploads:
        print(f"Upload Limit: Max {args.max_uploads} asset(s)")
    if args.start_index > 1:
        print(f"Resuming Queue: Starting from index {args.start_index}")
    print("============================================================\n")

    tasks: List[Dict] = []

    if args.manifest:
        entries = load_manifest(Path(args.manifest))
        for e in entries:
            path = Path(e["file"])
            tasks.append({
                "path": path,
                "name": e.get("name"),
                "description": e.get("description", args.description),
            })
    else:
        images = collect_images(args.input)
        if not images:
            print("[ERROR] No supported files found.")
            sys.exit(1)
        for img in images:
            tasks.append({
                "path": img,
                "name": args.name if len(images) == 1 else None,
                "description": args.description,
            })

    print(f"{len(tasks)} file(s) queued.\n")

    target_desc = str(args.input[0]) if args.input else (args.manifest or "Unknown")
    run_id = create_run_session(
        target_path=target_desc,
        asset_type=args.asset_type,
        creator_type=creator_type,
        creator_id=creator_id,
        max_uploads=args.max_uploads,
        total_queued=len(tasks),
        start_index=args.start_index
    )

    if not args.no_pixelfix and platform.system() == "Windows":
        download_pixelfix()

    results = []
    failed  = []
    consecutive_errors = 0
    current_index = args.start_index
    uploaded_in_session = 0
    run_status = "COMPLETED"

    # Wrapper to catch KeyboardInterrupt (Ctrl+C) for graceful exit
    try:
        for i, task in enumerate(tasks, 1):
            if i < args.start_index:
                continue # Skip files until we hit the start index

            if args.max_uploads and uploaded_in_session >= args.max_uploads:
                print(f"\n[LIMIT REACHED] Upload limit of {args.max_uploads} uploads reached for this session.")
                run_status = "PAUSED"
                break

            current_index = i
            path = task["path"]
            print(f"[{i}/{len(tasks)}] {path.name}")

            try:
                record = process_and_upload(
                    image_path   = path,
                    api_key      = args.key,
                    creator_type = creator_type,
                    creator_id   = creator_id,
                    display_name = task["name"],
                    description  = task["description"],
                    skip_pixelfix= args.no_pixelfix,
                    skip_dedup   = args.no_dedup,
                    distribute   = args.distribute,
                    dry_run      = args.dry_run,
                    asset_type   = args.asset_type,
                )
                if record:
                    results.append(record)
                    uploaded_in_session += 1
                
                # Reset error counter on success
                consecutive_errors = 0 
                
            except Exception as e:
                print(f"  [ERROR] {e}")
                failed.append({"file": str(path), "error": str(e), "index": i})
                consecutive_errors += 1

                print(f"\n[CRITICAL] Network/HTTP error: 5 retries failed for '{path.name}'. Auto-pausing session to save progress.")
                print(f"Please check your internet connection or Roblox API status. You can resume anytime using --resume.")
                run_status = "PAUSED"
                break

            update_run_session(run_id, current_index, len(results), len(failed), "RUNNING")

            if i < len(tasks) and (not args.max_uploads or uploaded_in_session < args.max_uploads):
                time.sleep(args.delay)

    except KeyboardInterrupt:
        print(f"\n\n[INFO] Upload manually paused by user (Ctrl+C).")
        run_status = "PAUSED"

    if current_index >= len(tasks) and consecutive_errors < 3 and run_status != "PAUSED":
        run_status = "COMPLETED"
    else:
        run_status = "PAUSED"

    update_run_session(run_id, current_index, len(results), len(failed), run_status)

    print(f"\n{'='*60}")
    print("UPLOAD SUMMARY")
    print(f"{'='*60}")
    
    for r in results:
        status = "[DRY RUN]" if r.get("dryRun") else "[OK]"
        asset_id = str(r.get("assetId", "-"))
        filename = Path(r.get("file", "?")).name
        print(f"{status} | {asset_id:<15} | {filename}")
        
    for f in failed:
        filename = Path(f["file"]).name
        print(f"[FAILED] | {'-':<15} | {filename} ({f['error'][:40]})")
        
    print(f"{'='*60}")
    print(f"Done: {len(results)} uploaded, {len(failed)} failed.")

    if run_status == "PAUSED" or current_index < len(tasks):
        next_index = current_index if (consecutive_errors >= 3 or run_status == "PAUSED") else current_index + 1
        print(f"\n[RESUME INFO] Session '{run_id}' paused/incomplete at index {current_index}.")
        print(f"To resume where you left off, run:")
        print(f"  py uploader.py --resume")

    if args.results:
        out = {"uploaded": results, "failed": failed}
        with open(args.results, "w") as f:
            json.dump(out, f, indent=2)
        print(f"Results written to -> {args.results}")

    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()