#!/usr/bin/env python3
"""
Instagram Auto-Poster HTTP Backend Server
Runs as a persistent systemd service. Handles posting logic for the Plasma widget.
"""

import os
import sys
import json
import random
import threading
import time
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

APP_DIR = Path(__file__).parent.resolve()
ENV_FILE = APP_DIR / ".env"
POSTER_SCRIPT = str(APP_DIR / "poster.py")
VENV_PYTHON = str(APP_DIR / "insta-env" / "bin" / "python")
LOG_FILE = APP_DIR / "server.log"

# Track active post thread
active_post_thread = None
is_posting = False


def load_env():
    """Load .env file into dict."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip()
    return env


def get_config():
    """Get current settings from .env."""
    env = load_env()
    return {
        "IG_USERNAME": env.get("IG_USERNAME", ""),
        "IMAGE_FOLDER": env.get("IMAGE_FOLDER", str(APP_DIR / "images_to_post")),
        "DELAY_AFTER_BOOT_MINUTES": int(env.get("DELAY_AFTER_BOOT_MINUTES", "2")),
        "MIN_INTERVAL_HOURS": int(env.get("MIN_INTERVAL_HOURS", "5")),
        "MAX_INTERVAL_HOURS": int(env.get("MAX_INTERVAL_HOURS", "7")),
        "NEXT_POST_IN_SECONDS": getattr(load_env(), "_next_post", 0),
    }


def save_config(settings):
    """Update .env file with new settings."""
    env = load_env()
    env.update({k: str(v) for k, v in settings.items()})
    
    # Preserve order and comments
    lines = []
    written = set()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                key = s.split("=", 1)[0].strip()
                if key in env:
                    lines.append(f"{key}={env[key]}")
                    written.add(key)
            else:
                lines.append(line)
    
    for key, val in env.items():
        if key not in written:
            lines.append(f"{key}={val}")
    
    ENV_FILE.write_text("\n".join(lines) + "\n")
    return True


def get_posted_log():
    """Return loaded posted_images.json."""
    log_path = APP_DIR / "posted_images.json"
    if log_path.exists():
        try:
            return json.loads(log_path.read_text())
        except Exception:
            pass
    return {"posted": {}, "last_post_time": None}


def count_queue_images():
    """Count unposted images in IMAGE_FOLDER."""
    folder = Path(get_config()["IMAGE_FOLDER"])
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    if not folder.exists():
        return 0
    return sum(1 for f in folder.iterdir() 
               if f.is_file() and f.suffix.lower() in exts 
               and str(f.resolve()) not in get_posted_log()["posted"])


def run_poster(force=False):
    """Run poster.py as subprocess."""
    global is_posting, active_post_thread
    
    cmd = [VENV_PYTHON, POSTER_SCRIPT]
    if force:
        cmd.append("--force")
    
    process = None
    try:
        import subprocess
        process = subprocess.Popen(cmd, cwd=str(APP_DIR))
        active_post_thread = process
        is_posting = True
        
        process.wait(timeout=300)
        exit_code = process.returncode
        return exit_code == 0
    except Exception as e:
        return False
    finally:
        is_posting = False
        active_post_thread = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.route("/")
def index():
    return jsonify({"service": "Instagram Auto-Poster Backend", "status": "running"})


@app.route("/post_now", methods=["POST"])
def post_now():
    """Trigger an immediate post."""
    global is_posting
    
    if is_posting:
        return jsonify({"success": False, "error": "Already posting..."}), 409
    
    thread = threading.Thread(target=lambda: run_poster(force=True))
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "message": "Post started"})


@app.route("/status", methods=["GET"])
def status():
    """Get current status: queue count, posted count, schedule info."""
    posted = get_posted_log()
    posted_count = len(posted.get("posted", {}))
    queued = count_queue_images()
    next_schedule = "unknown"
    
    last_time = posted.get("last_post_time")
    if last_time:
        try:
            dt = datetime.fromisoformat(last_time)
            elapsed = (datetime.now() - dt).total_seconds() / 3600
            min_h = int(load_env().get("MIN_INTERVAL_HOURS", 5))
            max_h = int(load_env().get("MAX_INTERVAL_HOURS", 7))
            target = random.uniform(min_h, max_h)
            remaining = max(0, target - elapsed)
            next_schedule = f"{remaining:.1f}h"
        except Exception:
            pass
    
    return jsonify({
        "posting": is_posting,
        "queued_images": queued,
        "posted_count": posted_count,
        "next_post_in": next_schedule,
    })


@app.route("/history", methods=["GET"])
def history():
    """Return last 5 posts (reverse chronological)."""
    log = get_posted_log()
    entries = []
    for path, data in log.get("posted", {}).items():
        try:
            t = datetime.fromisoformat(data["posted_at"])
            entries.append((t, path, data))
        except (KeyError, ValueError):
            continue
    entries.sort(key=lambda x: x[0], reverse=True)
    
    # Return top 5 with image thumbnails
    result = []
    for t, path, data in entries[:5]:
        moved_to = data.get("moved_to", "")
        if moved_to and Path(moved_to).exists():
            img_name = Path(moved_to).name
        else:
            img_name = data.get("image_name", "Unknown")
        
        result.append({
            "image_name": img_name,
            "caption": data.get("caption", ""),
            "posted_at": data.get("posted_at", ""),
            "time_formatted": datetime.fromisoformat(data["posted_at"]).strftime("%b %d, %I:%M %p"),
        })
    
    return jsonify(result)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    """Get or update settings."""
    if request.method == "GET":
        return jsonify(get_config())
    elif request.method == "POST":
        data = request.get_json() or {}
        valid_keys = {
            "IG_USERNAME", "IG_PASSWORD", 
            "IMAGE_FOLDER",
            "DELAY_AFTER_BOOT_MINUTES", "MIN_INTERVAL_HOURS", "MAX_INTERVAL_HOURS"
        }
        updates = {k: v for k, v in data.items() if k in valid_keys}
        if not updates:
            return jsonify({"success": False, "error": "No valid keys provided"}), 400
        save_config(updates)
        return jsonify({"success": True})


@app.route("/health", methods=["GET"])
def health_check():
    """Ping endpoint for systemd/service monitoring."""
    return jsonify({"healthy": True}), 200


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print(f"[Server] Instagram Auto-Poster Backend starting...")
    print(f"[Server] Listening on http://127.0.0.1:29157")
    app.run(host="127.0.0.1", port=29157, debug=False)
