#!/usr/bin/env python3
"""Restricted pull-only updater for Pixar V2, one Lenovo charging automation
and the Pixar dashboard configuration.

Pixar JavaScript and its images are the only files copied to the HA config.
One fixed automation may be installed through the Home Assistant config editor
API, after separate allowlist validation. The pixar-board-v2 dashboard may be
saved through the Lovelace API when auto_dashboard_sync is enabled. Never edits
.storage or HA YAML files.
"""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = "franckdavion/Home-assistant-pixar"
API = f"https://api.github.com/repos/{REPO}"
TARGET = Path("/homeassistant/www/pixar-board")
DATA = Path("/data")
MAX_FILE = 5_000_000
MAX_TOTAL = 40_000_000
IMAGE_RE = re.compile(r"^pixar/(equipements|rooms-v5)/[a-z0-9-]+\.(?:svg|webp)$")
# Page Tesla 3D : moteur Three.js copié localement et modèle allégé (liste fermée).
TESLA_FILES = {
    "pixar/vendor/three/three.module.min.js",
    "pixar/vendor/three/GLTFLoader.js",
    "pixar/vendor/three/BufferGeometryUtils.js",
    "pixar/tesla/tesla-model-3-lite.glb",
}
MAX_MODEL = 8_000_000
JS_PATH = "pixar/pixar-board-v2.js"
MANIFEST_PATH = "manifest.sha256"
AUTOMATION_PATH = "automations/lenovo-recharge-shelly-40-80.yaml"
DASHBOARD_PATH = "dashboard-updates/pixar-board-v2.yaml"

def say(message):
    print(f"[pixar-sync] {message}", flush=True)

def api_json(path, token):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "HomeAssistant-Pixar-Sync/0.1",
    })
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read(MAX_MODEL * 2).decode("utf-8"))

def blob_bytes(sha, token, limit=MAX_FILE):
    if not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
        raise ValueError("Invalid Git blob SHA")
    doc = api_json("/git/blobs/" + sha, token)
    if doc.get("encoding") != "base64":
        raise ValueError("GitHub did not return base64")
    raw = base64.b64decode(doc["content"], validate=False)
    if len(raw) > limit:
        raise ValueError("GitHub file exceeds safety limit")
    return raw

def planned_files(tree):
    found = {}
    for item in tree.get("tree", []):
        path = item.get("path", "")
        if item.get("type") != "blob":
            continue
        if path in (JS_PATH, MANIFEST_PATH, AUTOMATION_PATH, DASHBOARD_PATH) or path in TESLA_FILES or IMAGE_RE.fullmatch(path):
            found[path] = item.get("sha", "")
    if tree.get("truncated"):
        raise ValueError("GitHub repository tree is incomplete")
    if JS_PATH not in found or MANIFEST_PATH not in found or AUTOMATION_PATH not in found:
        raise ValueError("Pixar source, Lenovo automation, or integrity manifest missing")
    if sum(k.startswith("pixar/equipements/") for k in found) < 2:
        raise ValueError("Missing equipment images")
    if sum(k.startswith("pixar/rooms-v5/") for k in found) < 2:
        raise ValueError("Missing room images")
    if len(found) > 111:
        raise ValueError("Unexpected number of files")
    return found

def sha256(blob):
    return hashlib.sha256(blob).hexdigest()

def checked_sources(token):
    tree = api_json("/git/trees/main?recursive=1", token)
    entries = planned_files(tree)
    manifest = blob_bytes(entries[MANIFEST_PATH], token).decode("utf-8")
    expected = {}
    for line in manifest.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("Invalid integrity manifest")
        expected[match.group(2)] = match.group(1)
    sources = {}
    total = 0
    for name, gitsha in sorted(entries.items()):
        if name == MANIFEST_PATH:
            continue
        if name not in expected:
            raise ValueError("File missing from manifest: " + name)
        payload = blob_bytes(gitsha, token, MAX_MODEL if name.endswith(".glb") else MAX_FILE)
        if sha256(payload) != expected[name]:
            raise ValueError("Integrity mismatch: " + name)
        total += len(payload)
        if total > MAX_TOTAL:
            raise ValueError("Update exceeds total size limit")
        sources[name] = payload
    return sources

def safe_target(path):
    if TARGET.is_symlink() or TARGET.parent.is_symlink():
        raise ValueError("Symbolic link in target folder")
    if not TARGET.is_dir():
        raise ValueError("Existing Pixar folder not found")
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Symbolic link in an update destination")
    if not path.parent.exists():
        # Seuls les dossiers de la page Tesla peuvent être créés, dans le dossier Pixar existant.
        allowed = {TARGET / "tesla", TARGET / "vendor", TARGET / "vendor" / "three"}
        if path.parent not in allowed:
            raise ValueError("Expected destination image folder missing: " + str(path.parent))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise ValueError("Symbolic link in an update destination")
    if not path.parent.is_dir():
        raise ValueError("Destination is not a directory")
    if path.is_dir():
        raise ValueError("Destination is a directory")

def path_for(name):
    if name == JS_PATH:
        return TARGET / "pixar-board-v2.js"
    if name in TESLA_FILES:
        return TARGET / name.removeprefix("pixar/")
    if not IMAGE_RE.fullmatch(name):
        raise ValueError("Unauthorized update path")
    return TARGET / name.removeprefix("pixar/")

def validate_js(js):
    with tempfile.NamedTemporaryFile(suffix=".js") as temp:
        temp.write(js)
        temp.flush()
        result = subprocess.run(["node", "--check", temp.name],
                                capture_output=True, text=True, timeout=40)
    if result.returncode != 0:
        raise ValueError("JavaScript syntax check failed")

def deploy(sources):
    if JS_PATH not in sources:
        raise ValueError("Missing Pixar JavaScript")
    validate_js(sources[JS_PATH])
    changes = []
    for name, new in sources.items():
        path = path_for(name)
        safe_target(path)
        if name == JS_PATH and not path.is_file():
            raise ValueError("pixar-board-v2.js not present in Home Assistant")
        if path.is_file() and sha256(path.read_bytes()) == sha256(new):
            continue
        changes.append((name, path, new))
    if not changes:
        say("Nothing to change: Pixar is already up to date")
        return 0

    backup_root = DATA / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_root / (stamp + "-" + str(os.getpid()))
    backup.mkdir()
    original = {}
    try:
        for name, path, _ in changes:
            if path.exists():
                blob = path.read_bytes()
                original[name] = blob
                dest = backup / name.removeprefix("pixar/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
            else:
                original[name] = None
        (backup / "files.json").write_text(json.dumps(
            {"changed": [name for name, _, _ in changes],
             "new_files": [name for name, data in original.items() if data is None]},
            indent=2), encoding="utf-8")
        written = []
        try:
            for name, path, new in changes:
                fd, tmp = tempfile.mkstemp(prefix=".pixar-sync-", dir=str(path.parent))
                try:
                    with os.fdopen(fd, "wb") as out:
                        out.write(new)
                    os.chmod(tmp, 0o644)
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                written.append((name, path))
        except Exception:
            for name, path in reversed(written):
                data = original[name]
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            raise
        say(f"Installed {len(changes)} files with backup: {backup}")
        all_backups = sorted(p for p in backup_root.iterdir() if p.is_dir())
        for old in all_backups[:-5]:
            shutil.rmtree(old)
        return len(changes)
    except Exception:
        say(f"Update failed; check backup: {backup}")
        raise

def run_once(options):
    token = options.get("github_token", "").strip()
    if not token:
        say("No GitHub token configured. Add a read-only token in app settings.")
        return
    say("Checking private GitHub Pixar repository")
    sources = checked_sources(token)
    automation_source = sources.pop(AUTOMATION_PATH)
    dashboard_source = sources.pop(DASHBOARD_PATH, None)
    deploy(sources)
    if options.get("auto_automation_sync") is True:
        from automation_sync import run as sync_lenovo_automation
        sync_lenovo_automation(automation_source, sha256(automation_source))
    if options.get("auto_dashboard_sync") is True and dashboard_source is not None:
        sync_dashboard(dashboard_source)
    if options.get("auto_resource_version") is True:
        js_hash = sha256(sources[JS_PATH])
        # Only the exact Pixar V2 resource can be modified, via HA API.
        # Old resource metadata is archived before any change.
        result = subprocess.run(
            ["node", "/resource_version.js", js_hash],
            capture_output=True, text=True, timeout=30,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                say(line[:250])
        if result.returncode != 0:
            raise ValueError("Resource version update unavailable: " +
                             result.stderr.strip()[:300])

def sync_dashboard(source):
    """Convert the GitHub dashboard YAML to JSON, then let dashboard_sync.js save it."""
    import yaml
    if len(source) > MAX_FILE:
        raise ValueError("Dashboard file exceeds safety limit")
    try:
        config = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ValueError("Invalid dashboard YAML; dashboard unchanged") from exc
    if not isinstance(config, dict):
        raise ValueError("Dashboard YAML must be a mapping; dashboard unchanged")
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as temp:
        json.dump(config, temp, ensure_ascii=False)
        temp.flush()
        result = subprocess.run(
            ["node", "/dashboard_sync.js", sha256(source), temp.name],
            capture_output=True, text=True, timeout=40,
        )
    for line in result.stdout.strip().splitlines():
        say(line[:250])
    if result.returncode != 0:
        raise ValueError("Dashboard sync stopped: " + result.stderr.strip()[:300])

def main():
    say("Pixar private GitHub synchronizer started (Pixar + allowlisted Lenovo automation + Pixar dashboard)")
    if "--self-test" in sys.argv:
        print("Updater module imports correctly")
        return
    previous_status = None
    while True:
        try:
            options = json.loads((DATA / "options.json").read_text("utf-8"))
            enabled = options.get("enabled") is True
            if not enabled:
                if previous_status != "disabled":
                    say("Synchronization disabled. No Home Assistant files will be modified.")
                previous_status = "disabled"
            else:
                previous_status = "enabled"
                try:
                    run_once(options)
                except (urllib.error.URLError, OSError, ValueError, KeyError,
                        TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                    say("Sync aborted safely: " + type(error).__name__ + ": " + str(error)[:250])
            period = int(options.get("interval_minutes", 15))
            time.sleep(max(5, min(1440, period)) * 60 if enabled else 30)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            say("Configuration error; check app settings.")
            time.sleep(30)

if __name__ == "__main__":
    main()
